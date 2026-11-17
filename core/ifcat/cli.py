"""命令行入口。

框架不含任何项目内容；所有项目相关的东西都从工作区读（--workspace、环境变量 IFCAT_WORKSPACE，或在工作区内运行）。

  list [--module M]                  列出场景及审核状态
  validate <场景>|--module M|--all    离线校验（不连环境）
  render <场景>|--module M|--all      生成给业务人员审核的 HTML 页面（写入工作区 reviews/）
  approve <场景>            记录业务审核通过（只能在业务人员明确同意后执行）
  run <场景>|--module M|--all --env   运行一个批次，生成 HTML 报告；只运行已审核的场景，--draft 仅供调试
  calibrate --env 环境                用真实页面标定组件适配器
  harvest <工作区>...                 汇总各工作区临时补的扩展，供维护者定期归纳（只读）

模块可以写多个，逗号分隔，如 --module DP,LM。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

from . import CORE_VERSION, guard
from .adapters import build_default_registry
from .batch import Candidate, duplicate_ids, forms_for, load_candidates, run_batch, select
from .calibration import CalibrationKey, CalibrationStore, load_probes, run_calibration
from .config import load_config
from .dbro import ReadOnlyDb
from .evidence import RunRecorder
from .extloader import load_extensions
from .meta import find_form_file, load_form_file
from .meta.formmeta import FormMetaError
from .primitives import Primitives
from .review import record_approval
from .reviewpage import render_feature_html, review_page_name
from .scenario import ScenarioError, validate_scenario
from .statemodel import BillModel, load_bill_models
from .workspace import Workspace, WorkspaceError, load_workspace


def _bills(ws: Workspace) -> Dict[str, BillModel]:
    out: Dict[str, BillModel] = {}
    for f in ws.bills:
        out.update(load_bill_models(f))
    return out


def _env_name(a: argparse.Namespace, ws: Workspace) -> str:
    env = a.env or ws.default_env
    if not env:
        raise WorkspaceError("需要 --env 指定环境（或在 workspace.yaml 里设置 default_env）")
    return env


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ifc", description="IFC AI 自动化测试框架")
    ap.add_argument("command", choices=["list", "validate", "render", "approve", "run", "calibrate", "forms", "init", "doctor", "harvest"])
    ap.add_argument("target", nargs="?", help="场景（文件、相对路径或名字）")
    ap.add_argument("rest", nargs="*", help="forms import 时的表单 ID；harvest 时的其他工作区目录")
    ap.add_argument("--out", help="harvest 的输出文件（不给则打印）")
    ap.add_argument("--from", dest="src", help="forms import 的来源：产品表单定义目录")
    ap.add_argument("--product-version", help="forms import 的产品版本，如 6.2.7")
    ap.add_argument("--module", help="模块代号，如 DP；多个用逗号分隔")
    ap.add_argument("--all", action="store_true", help="全部场景")
    ap.add_argument("--workspace", help="工作区目录；也可用环境变量 IFCAT_WORKSPACE")
    ap.add_argument("--env", help="环境名，对应工作区 config/local/<环境>.yaml")
    ap.add_argument("--by", help="审核人（approve 用）")
    ap.add_argument("--draft", action="store_true", help="允许运行未审核的场景（仅调试，结果标记为未审核）")
    ap.add_argument("--project", help="init 时的项目名")
    ap.add_argument("--refresh", action="store_true", help="init 时只给已有工作区补上缺少的说明文件")
    ap.add_argument("--login", action="store_true", help="doctor 时实际登录一次，验证账号口令")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--skip-integrity", action="store_true", help="跳过核心库完整性校验（仅开发期）")
    a = ap.parse_args(argv)

    if not a.skip_integrity:
        try:
            guard.verify_integrity()
        except guard.IntegrityError as exc:
            print(f"核心库完整性校验失败：{exc}", file=sys.stderr)
            return 2
    try:
        return _dispatch(a)
    except (WorkspaceError, FormMetaError, ScenarioError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _select(a: argparse.Namespace, ws: Workspace):
    modules = a.module.split(",") if a.module else None
    return select(ws, a.target, modules, a.all)


def _init(a: argparse.Namespace) -> int:
    from .scaffold import InitError, init_workspace, old_skill_copy

    if not a.target or not (a.project or a.refresh):
        print("用法：ifc init <工作区目录> --project <项目名>；给已有工作区补说明文件：ifc init <工作区目录> --refresh", file=sys.stderr)
        return 2
    try:
        project = a.project
        if a.refresh and not project:
            project = load_workspace(a.target).project
        done = init_workspace(a.target, project, refresh=a.refresh)
    except InitError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(("已补上：" if a.refresh else "已创建：") + ("、".join(done) if done else "（没有变化）"))
    old = old_skill_copy(a.target)
    if old:
        print(f"提示：{old} 是旧版本留下的规程副本，已不再更新。规程现在随 ifc-autotest 技能分发，这个目录可以删除。")
    if not a.refresh:
        print("下一步：复制 config/local/dev.yaml.example 为 dev.yaml 并填写，然后运行 ifc doctor --login")
    return 0


def _dispatch(a: argparse.Namespace) -> int:
    if a.command == "init":
        return _init(a)
    if a.command == "doctor":
        from .doctor import run_doctor

        return run_doctor(a.workspace, a.env, a.login)
    if a.command == "harvest":
        return _harvest(a)
    ws = load_workspace(a.workspace)
    # 场景里可能用到工作区扩展动作，必须先加载扩展再解析场景
    registry = build_default_registry()
    for e in load_extensions(registry, ws.extensions_dir)["errors"]:
        print(f"扩展加载失败：{e}", file=sys.stderr)

    if a.command == "list":
        modules = a.module.split(",") if a.module else None
        _, cands = select(ws, None, modules, True)
        for c in cands:
            rel = c.path.relative_to(ws.scenarios_dir)
            print(f"{rel}\t{c.state.describe() if c.state else '无法解析：' + c.error}")
        for sid, files in _duplicates(ws).items():
            print(f"场景编号重复：{sid}（{'、'.join(f.name for f in files)}）", file=sys.stderr)
        return 0

    if a.command == "forms":
        return _forms(a, ws)

    bills = _bills(ws)

    if a.command == "calibrate":
        return _calibrate(a, ws, registry, bills)

    if not (a.target or a.module or a.all):
        print("需要指定场景，或用 --module / --all", file=sys.stderr)
        return 2
    scope, cands = _select(a, ws)
    if not cands:
        print("没有匹配的场景", file=sys.stderr)
        return 2
    broken = [c for c in cands if c.scenario is None]
    if a.target and broken:
        print(f"场景无法解析：{broken[0].error}", file=sys.stderr)
        return 2

    if a.command == "render":
        return _render(a, ws, cands)

    if a.command == "validate":
        return _validate(ws, cands, registry, bills)

    if a.command == "approve":
        if not a.target:
            print("approve 只能针对单个场景", file=sys.stderr)
            return 2
        c = cands[0]
        errors = _issues(ws, c, registry, bills)
        if errors:
            print("场景校验有错误，不能审核通过：", *errors, sep="\n", file=sys.stderr)
            return 1
        print(f"已记录审核：{record_approval(c.scenario, c.path, a.by or '')}")
        return 0

    return _run(a, ws, scope, cands, registry, bills)


def _forms(a: argparse.Namespace, ws: Workspace) -> int:
    from .formsnap import SnapshotError, import_forms, list_snapshots

    if a.target == "list":
        for fid, m in list_snapshots(ws).items():
            print(f"{fid}\t产品版本 {m['product_version']}\t{m['source']}\t{m['imported_at']}")
        return 0
    if a.target == "import":
        if not (a.src and a.rest):
            print("用法：ifc forms import <表单ID>... --from <表单定义目录> --product-version <版本>", file=sys.stderr)
            return 2
        try:
            done = import_forms(ws, Path(a.src).expanduser(), a.rest, a.product_version or "", "本地产品表单定义目录导入")
        except SnapshotError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"已导入 {len(done)} 个表单定义到 {ws.forms_dir}：{', '.join(done)}")
        return 0
    print("forms 子命令：import、list", file=sys.stderr)
    return 2


def _render(a: argparse.Namespace, ws: Workspace, cands: List[Candidate]) -> int:
    """同一功能的场景放在一个审核页里；没有功能分组的场景各自一页。"""
    pool = cands
    if a.target:  # 指定了单个场景：把它所在功能的兄弟场景也带上，业务人员要看到完整覆盖面
        t = cands[0].scenario
        if t is not None and t.feature:
            _, everything = select(ws, None, None, True)
            pool = [c for c in everything if c.scenario and c.scenario.module == t.module and c.scenario.feature == t.feature]
    groups: Dict[tuple, List[Candidate]] = {}
    for c in pool:
        if c.scenario is None:
            print(f"跳过 {c.path.name}：{c.error}", file=sys.stderr)
            continue
        groups.setdefault(review_page_name(c.scenario), []).append(c)
    ws.reviews_dir.mkdir(parents=True, exist_ok=True)
    for fname, cs in groups.items():
        out = ws.reviews_dir / fname
        out.write_text(render_feature_html([(c.scenario, c.state) for c in cs]), encoding="utf-8")
        print(f"已生成审核页：{out}")
    return 0


def _duplicates(ws: Workspace) -> Dict[str, List[Path]]:
    return duplicate_ids(load_candidates(ws, ws.scenario_files()))


def _duplicate_message(sid: str, files: List[Path]) -> str:
    return f"场景编号 {sid} 在工作区里重复（{'、'.join(f.name for f in files)}），编号必须唯一"


def _issues(ws: Workspace, c: Candidate, registry, bills) -> List[str]:
    forms = forms_for(c.scenario, ws.form_dirs)
    errors = [f"{i.step}: {i.message}" for i in validate_scenario(c.scenario, forms, registry, bills or None)
              if i.level == "error"]
    dups = _duplicates(ws)
    if c.scenario.id in dups:
        errors.append("-: " + _duplicate_message(c.scenario.id, dups[c.scenario.id]))
    return errors


def _harvest(a: argparse.Namespace) -> int:
    from .harvest import harvest_workspace, render_markdown

    targets = [t for t in [a.target, *a.rest] if t] or ([a.workspace] if a.workspace else [])
    if not targets:
        print("用法：ifc harvest <工作区目录>... [--out <文件>]", file=sys.stderr)
        return 2
    text = render_markdown([harvest_workspace(t) for t in targets])
    if a.out:
        Path(a.out).expanduser().write_text(text, encoding="utf-8")
        print(f"已生成归纳清单：{a.out}")
    else:
        print(text)
    return 0


def _validate(ws: Workspace, cands: List[Candidate], registry, bills) -> int:
    bad = 0
    dups = _duplicates(ws)
    for c in cands:
        if c.scenario is None:
            print(f"[error] {c.path.name}: 无法解析：{c.error}")
            bad += 1
            continue
        forms = forms_for(c.scenario, ws.form_dirs)
        issues = validate_scenario(c.scenario, forms, registry, bills or None)
        for i in issues:
            print(f"[{i.level}] {c.scenario.id} {i.step}: {i.message}")
        errs = [i for i in issues if i.level == "error"]
        if c.scenario.id in dups:
            print(f"[error] {c.scenario.id} -: {_duplicate_message(c.scenario.id, dups[c.scenario.id])}")
        bad += bool(errs) or c.scenario.id in dups
    print("校验通过" if not bad else f"校验未通过：{bad} 个场景有错误")
    return 1 if bad else 0


def _run(a, ws: Workspace, scope: str, cands: List[Candidate], registry, bills) -> int:
    if a.target and not a.draft and not cands[0].state.approved:
        print(f"场景「{cands[0].scenario.id}」{cands[0].state.describe()}，不能正式运行。请先把 `ifc render` 生成的审核页交业务人员审核，"
              "通过后再 `ifc approve`；仅调试可加 --draft。", file=sys.stderr)
        return 3
    cfg = load_config(ws.env_config(_env_name(a, ws)))
    batch = run_batch(ws, cfg, scope, cands, registry, bills, draft=a.draft, headed=a.headed)
    sc = batch["scenarios"]
    counts = {k: sum(1 for s in sc if s["status"] == k) for k in ("passed", "failed", "blocked", "invalid", "skipped")}
    tag = "（含未审核场景，仅调试，不能作为回归结论）" if batch["draft"] else ""
    print(f"批次 {batch['batch_id']}：共 {len(sc)} 个，通过 {counts['passed']}，检查未通过 {counts['failed']}，"
          f"自动化未能完成 {counts['blocked']}，没有检查点 {counts['invalid']}，未运行 {counts['skipped']}{tag}")
    print(f"报告：{ws.results_dir / 'runs' / cfg.project / cfg.env_name / batch['batch_id'] / 'report.html'}")
    if counts["passed"] + counts["failed"] + counts["blocked"] + counts["invalid"] == 0:
        return 3
    return 0 if counts["passed"] == len(sc) - counts["skipped"] else 1


def _calibrate(a, ws: Workspace, registry, bills) -> int:
    cfg = load_config(ws.env_config(_env_name(a, ws)))
    from .session import Session

    probe_files = [Path(a.target)] if a.target else ws.probes
    if not probe_files:
        print("工作区没有配置标定探针（workspace.yaml 的 probes），也没有指定探针文件", file=sys.stderr)
        return 2
    probes = [p for f in probe_files for p in load_probes(f)]
    forms = {p.form_id: load_form_file(find_form_file(p.form_id, ws.form_dirs)) for p in probes}
    store = CalibrationStore(ws.results_dir, CalibrationKey(cfg.product_version, cfg.project, cfg.env_name, cfg.locale))
    sess = Session(cfg, headless=not a.headed)
    db = ReadOnlyDb(cfg.db) if cfg.db else None
    try:
        page = sess.start()
        sess.login(next(iter(cfg.accounts)))
        rec = RunRecorder(ws.results_dir, cfg.project, cfg.env_name, "calibration")
        prim = Primitives(page, forms, registry, rec, db, bills, nav=sess)
        total = failed = 0
        for r in run_calibration(prim, probes, store, sess.open_form):
            print(f"{r.type_name}: {'通过' if r.passed else '失败 ' + r.detail}")
            total += 1
            failed += not r.passed
        rec.finish("calibration")
        print(f"标定完成：通过 {total - failed}，失败 {failed}（产品版本 {cfg.product_version}，语言 {cfg.locale}，框架 {CORE_VERSION}）")
        print(f"标定记录：{store.key.path(ws.results_dir)}")
        return 1 if failed else 0
    finally:
        sess.close()
        if db:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
