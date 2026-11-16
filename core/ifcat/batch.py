"""批量运行：一次运行一个批次，批次可以是单个场景、一个或几个模块、或全部场景。

- 只运行已审核的场景；未审核或审核后被改动的场景记为「未运行」，不算失败，也不会被悄悄跳过（报告里列出）。
- 一个场景失败、阻塞，甚至抛出意外异常，都不影响后面的场景。
- 每个场景用全新的浏览器上下文，场景之间不串会话。
- 每完成一个场景就写一次批次报告，中途中断也能看到已完成的部分。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .calibration import CalibrationGate, CalibrationKey, CalibrationStore, preflight
from .config import EnvConfig
from .dbro import ReadOnlyDb
from .evidence import RunRecorder
from .meta import FormMeta, find_form_file, load_form_file
from .primitives import Primitives
from .report import first_problem, write_batch, write_index, write_scenario_report
from .review import ReviewState, check_review
from .runner import ScenarioRunner
from .scenario import Scenario, ScenarioError, load_scenario
from .workspace import Workspace

_UNSAFE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


@dataclass
class Candidate:
    path: Path
    scenario: Optional[Scenario]
    state: Optional[ReviewState]
    error: str = ""


def forms_for(sc: Scenario, dirs: List[Path]) -> Dict[str, FormMeta]:
    ids = {s.args["form"] for s in sc.steps if isinstance(s.args.get("form"), str) and not s.args["form"].startswith("${")}
    return {i: load_form_file(find_form_file(i, dirs)) for i in sorted(ids)}


def load_candidates(ws: Workspace, paths: List[Path]) -> List[Candidate]:
    out: List[Candidate] = []
    for p in paths:
        try:
            sc = load_scenario(p)
            out.append(Candidate(p, sc, check_review(sc, p)))
        except Exception as exc:  # 一个场景文件坏了不能拖垮整批
            out.append(Candidate(p, None, None, f"{type(exc).__name__}: {exc}"))
    return out


def module_of(ws: Workspace, c: Candidate) -> str:
    """场景所属模块。文件解析不了时读不到 module 字段，按 scenarios/<模块>/ 的目录名归属，
    这样按模块运行时坏文件仍会出现在报告里，而不是被悄悄漏掉。"""
    if c.scenario is not None:
        return c.scenario.module
    try:
        parts = c.path.resolve().relative_to(ws.scenarios_dir.resolve()).parts
    except ValueError:
        return "未知"
    return parts[0] if len(parts) > 1 else "未知"


def duplicate_ids(cands: List[Candidate]) -> Dict[str, List[Path]]:
    """场景编号必须在工作区内唯一：报告对比、基线查找、历史点阵都按编号对应。返回重复的编号及其文件。"""
    seen: Dict[str, List[Path]] = {}
    for c in cands:
        if c.scenario is not None:
            seen.setdefault(c.scenario.id, []).append(c.path)
    return {k: v for k, v in seen.items() if len(v) > 1}


def select(ws: Workspace, target: Optional[str], modules: Optional[List[str]], everything: bool) -> Tuple[str, List[Candidate]]:
    """返回（范围名称，候选场景）。模块按场景里的 module 字段匹配，大小写不敏感。"""
    if target:
        p = ws.resolve_scenario(target)
        return p.stem, load_candidates(ws, [p])
    cands = load_candidates(ws, ws.scenario_files())
    if modules:
        want = {m.strip().upper() for m in modules if m.strip()}
        cands = [c for c in cands if module_of(ws, c).upper() in want]
        return "+".join(sorted(want)), cands
    if everything:
        return "全部", cands
    raise ScenarioError("请指定场景，或用 --module <模块> / --all")


def _new_batch_dir(ws: Workspace, cfg: EnvConfig, scope: str) -> Tuple[Path, str]:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"{ts}_{_UNSAFE.sub('_', scope).strip('_')[:40] or 'x'}"
    root = ws.results_dir / "runs" / _UNSAFE.sub("_", cfg.project) / _UNSAFE.sub("_", cfg.env_name)
    root.mkdir(parents=True, exist_ok=True)
    name, n = base, 1
    while (root / name).exists():
        n += 1
        name = f"{base}-{n}"
    (root / name).mkdir()
    return root / name, name


def run_batch(ws: Workspace, cfg: EnvConfig, scope: str, cands: List[Candidate], registry: Any, bills: Dict[str, Any],
              draft: bool = False, headed: bool = False, log: Callable[[str], None] = print) -> Dict[str, Any]:
    from .session import Session

    batch_dir, batch_id = _new_batch_dir(ws, cfg, scope)
    t0 = time.monotonic()
    batch: Dict[str, Any] = {
        "batch_id": batch_id, "project": cfg.project, "env": cfg.env_name, "product_version": cfg.product_version,
        "locale": cfg.locale, "scope": scope, "started": batch_id[:15], "finished": "", "duration_s": 0,
        "draft": False, "complete": False, "scenarios": [],
    }

    def flush(complete: bool = False) -> None:
        batch["duration_s"] = round(time.monotonic() - t0, 1)
        batch["complete"] = complete
        if complete:
            batch["finished"] = datetime.now().strftime("%Y%m%d-%H%M%S")
        write_batch(batch_dir, batch)
        write_index(ws.results_dir)

    flush()
    store = CalibrationStore(ws.results_dir, CalibrationKey(cfg.product_version, cfg.project, cfg.env_name, cfg.locale))
    gate = CalibrationGate(store)
    sess: Optional[Session] = None
    db = ReadOnlyDb(cfg.db) if cfg.db else None
    try:
        for c in cands:
            rel = str(c.path.relative_to(ws.scenarios_dir)) if c.path.is_relative_to(ws.scenarios_dir) else str(c.path)
            if c.scenario is None:
                batch["scenarios"].append({"id": c.path.stem, "title": c.path.stem, "module": module_of(ws, c), "file": rel,
                                           "status": "blocked", "reviewed": False, "review": "", "dir": "",
                                           "problem": f"场景文件无法解析：{c.error}"})
                flush()
                continue
            sc, state = c.scenario, c.state
            entry: Dict[str, Any] = {"id": sc.id, "title": sc.title, "module": sc.module, "file": rel,
                                     "reviewed": state.approved, "review": state.describe(), "dir": ""}
            if not state.approved and not draft:
                entry.update(status="skipped", problem=state.describe() + "，未运行")
                batch["scenarios"].append(entry)
                log(f"{sc.id}: 未运行（{state.describe()}）")
                flush()
                continue
            if not state.approved:
                batch["draft"] = True
            try:
                if sess is None:
                    sess = Session(cfg, headless=not headed)
                    sess.start()
                status, rec = _run_one(ws, cfg, sc, state, sess, db, registry, bills, gate, batch_dir)
                entry.update(status=status, dir=rec.dir.name, duration_s=rec.meta.get("duration_s"))
                steps = rec.steps
                entry["problem"] = first_problem(steps)
                entry["captured"] = rec.meta.get("captured", {})
                entry["extensions"] = rec.meta.get("extensions_used", [])
                write_scenario_report(rec.dir, entry)
            except Exception as exc:  # 环境或自动化自身的意外错误，不能拖垮整批
                entry.update(status="blocked", problem=f"运行出错：{type(exc).__name__}: {exc}")
                if sess is not None:
                    try:
                        shot = batch_dir / f"{_UNSAFE.sub('_', sc.id)}-运行出错.png"
                        sess.page.screenshot(path=str(shot))
                        entry["problem"] += f"（出错时的页面截图：{shot.name}；页面空白或 502 时，先查环境是否可访问、本机代理是否拦截）"
                    except Exception:
                        pass
                    try:
                        sess.close()
                    except Exception:
                        pass
                    sess = None
            batch["scenarios"].append(entry)
            log(f"{sc.id}: {entry['status']}")
            flush()
    finally:
        if sess is not None:
            sess.close()
        if db:
            db.close()
    flush(complete=True)
    return batch


def _run_one(ws: Workspace, cfg: EnvConfig, sc: Scenario, state: ReviewState, sess: Any, db: Any, registry: Any,
             bills: Dict[str, Any], gate: CalibrationGate, batch_dir: Path) -> Tuple[str, RunRecorder]:
    rec = RunRecorder(ws.results_dir, cfg.project, cfg.env_name, sc.id, batch_dir=batch_dir)
    rec.meta["reviewed"] = state.approved
    rec.meta["review"] = state.describe()
    try:
        forms = forms_for(sc, ws.form_dirs)
    except Exception as exc:
        from .result import StepResult
        rec.record_step("加载表单定义", StepResult.blocked(f"{type(exc).__name__}: {exc}"))
        rec.finish("blocked")
        return "blocked", rec
    used: Dict[str, set] = {}
    for s in sc.steps:
        if s.do == "fill":
            used.setdefault(s.args["form"], set()).update(s.args["values"].keys())
        elif s.do in ("expect_field", "capture_field"):
            used.setdefault(s.args["form"], set()).add(s.args["label"])
    report = preflight(forms.values(), registry, gate, used)
    if not report.ok:
        rec.meta["preflight"] = report.message()
    page = sess.fresh_context()
    prim = Primitives(page, forms, registry, rec, db, bills, gate, nav=sess, ui_text=cfg.env_params.get("ui_text"))
    first_role = next((s.role for s in sc.steps if s.role), next(iter(cfg.accounts)))
    sess.login(first_role)
    runner = ScenarioRunner(prim, sess.switch_role)
    runner._role = first_role
    status = runner.run(sc)
    rec.finish(status.value)
    return status.value, rec
