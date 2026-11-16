"""工作区、业务审核、命令行：用自带的演示工作区，不依赖任何真实项目内容。"""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

from ifcat.cli import main
from ifcat.review import check_review, record_approval
from ifcat.scenario import load_scenario
from ifcat.workspace import WorkspaceError, load_workspace

FORM = {
    "formID": "DEMO_FORM", "formName": "演示", "version": "React",
    "components": [{"key": "Root", "type": "FormBoxContainer", "props": {}, "children": [
        {"key": "A", "type": "FormTextInput", "props": {"showLabelText": "名称", "dataSetID": "T1", "dataSetColID": "F_NAME"}},
    ]}],
    "dataModels": [], "actionComps": [], "tableSource": [{"tableName": "主表", "tableID": "!T1"}],
}

SCENARIO = {
    "id": "DEMO-演示场景", "title": "演示", "module": "DEMO",
    "roles": {"maker": "经办"},
    "data": {"name": "甲"},
    "steps": [
        {"id": "s1", "as": "maker", "do": "open", "说明": "打开演示表单", "args": {"form": "DEMO_FORM"}},
        {"id": "s2", "as": "maker", "do": "fill", "说明": "填名称", "args": {"form": "DEMO_FORM", "values": {"名称": "${data.name}"}}},
        {"id": "c1", "as": "maker", "do": "expect_field", "说明": "名称是甲", "args": {"form": "DEMO_FORM", "label": "名称", "expected": "甲"}},
    ],
}


@pytest.fixture
def ws_root(tmp_path):
    root = tmp_path / "ws"
    (root / "scenarios" / "DEMO").mkdir(parents=True)
    (root / "forms").mkdir()
    (root / "forms" / "DEMO_FORM.json").write_text(json.dumps(FORM, ensure_ascii=False), encoding="utf-8")
    (root / "workspace.yaml").write_text("project: demo\nform_dirs: [forms]\n", encoding="utf-8")
    (root / "scenarios" / "DEMO" / "演示.yaml").write_text(yaml.safe_dump(SCENARIO, allow_unicode=True), encoding="utf-8")
    return root


def _args(root, *a):
    return ["--workspace", str(root), "--skip-integrity", *a]


def test_workspace_found_by_env_var_and_cwd(ws_root, monkeypatch):
    monkeypatch.setenv("IFCAT_WORKSPACE", str(ws_root))
    assert load_workspace().project == "demo"
    monkeypatch.delenv("IFCAT_WORKSPACE")
    assert load_workspace(start=ws_root / "scenarios" / "DEMO").root == ws_root.resolve()
    with pytest.raises(WorkspaceError):
        load_workspace(start=ws_root.parent.parent)


def test_local_file_overrides_workspace_file(ws_root):
    other = ws_root / "other_forms"
    other.mkdir()
    (ws_root / "workspace.local.yaml").write_text(f"form_dirs: [{other}]\n", encoding="utf-8")
    assert load_workspace(str(ws_root)).form_dirs == [ws_root / "knowledge" / "forms", other]


def test_new_scenario_is_unreviewed_and_approval_binds_to_content(ws_root):
    ws = load_workspace(str(ws_root))
    p = ws.resolve_scenario("演示")
    assert check_review(load_scenario(p), p).status == "unreviewed"
    record_approval(load_scenario(p), p, "  ")  # 不写姓名也可以，记为对话确认
    assert check_review(load_scenario(p), p).by == "业务人员对话确认"
    record_approval(load_scenario(p), p, "张三")
    st = check_review(load_scenario(p), p)
    assert st.approved and st.by == "张三"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["data"]["name"] = "乙"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert check_review(load_scenario(p), p).status == "changed"


def test_review_goes_stale_when_base_scenario_changes(ws_root):
    base = ws_root / "scenarios" / "DEMO" / "演示.yaml"
    child = ws_root / "scenarios" / "DEMO" / "演示-增量.yaml"
    child.write_text(yaml.safe_dump({
        "id": "DEMO-增量", "title": "增量", "module": "DEMO", "extends": "演示",
        "data": {"name": "丙"}, "steps": [],
    }, allow_unicode=True), encoding="utf-8")
    sc = load_scenario(child)
    record_approval(sc, child, "张三")
    assert check_review(load_scenario(child), child).approved
    raw = yaml.safe_load(base.read_text(encoding="utf-8"))
    raw["steps"][2]["args"]["expected"] = "乙"
    base.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert check_review(load_scenario(child), child).status == "changed"


def test_cli_list_render_validate_approve(ws_root, capsys):
    assert main(_args(ws_root, "list")) == 0
    assert "未审核" in capsys.readouterr().out
    assert main(_args(ws_root, "render", "演示")) == 0
    assert (ws_root / "reviews" / "DEMO-演示场景.html").is_file()
    assert main(_args(ws_root, "validate", "演示")) == 0
    assert "校验通过" in capsys.readouterr().out
    assert main(_args(ws_root, "approve", "演示", "--by", "张三")) == 0
    assert main(_args(ws_root, "list")) == 0
    assert "已审核（张三" in capsys.readouterr().out


def test_cli_run_refuses_unreviewed_and_changed(ws_root, capsys):
    assert main(_args(ws_root, "run", "演示", "--env", "dev")) == 3
    assert "未审核" in capsys.readouterr().err
    assert main(_args(ws_root, "approve", "演示", "--by", "张三")) == 0
    p = ws_root / "scenarios" / "DEMO" / "演示.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["data"]["name"] = "乙"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert main(_args(ws_root, "run", "演示", "--env", "dev")) == 3
    assert "重新审核" in capsys.readouterr().err


def test_cli_approve_rejects_invalid_scenario(ws_root):
    p = ws_root / "scenarios" / "DEMO" / "演示.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw["steps"][1]["args"]["values"] = {"不存在的字段": "x"}
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    assert main(_args(ws_root, "approve", "演示", "--by", "张三")) == 1
    assert not (ws_root / "scenarios" / "DEMO" / "演示.review.yaml").exists()


def test_ui_lists_scenarios_and_only_approved_runnable(ws_root, monkeypatch):
    p = Path(__file__).resolve().parents[2] / "ui" / "server.py"
    spec = importlib.util.spec_from_file_location("ui_server", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.WS = load_workspace(str(ws_root))
    html = m.page()
    assert "运行" in html and "未审核" in html
    assert "value='scenario:DEMO/演示.yaml'" not in html
    assert m.scope_args("all") == ["--all"] and m.scope_args("module:DEMO") == ["--module", "DEMO"]
    assert m.scope_args("scenario:DEMO/演示.yaml") is None and m.scope_args("module:../x") is None
    sp = m.WS.resolve_scenario("演示")
    record_approval(load_scenario(sp), sp, "张三")
    assert "value='scenario:DEMO/演示.yaml'" in m.page()
    assert m.scope_args("scenario:DEMO/演示.yaml") == ["DEMO/演示.yaml"]


# --- 审核页与批量运行、报告 ---
def test_review_html_is_business_readable(ws_root):
    from ifcat.reviewpage import render_review_html
    p = ws_root / "scenarios" / "DEMO" / "演示.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    raw.update(goal="保证演示流程可用", source=["演示需求"], unconfirmed=["余额规则待确认"], labels={"名称": "客户名称"})
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    sc = load_scenario(p)
    out = render_review_html(sc, check_review(sc, p))
    assert "保证演示流程可用" in out and "余额规则待确认" in out and "检查点" in out and "未审核" in out
    assert "客户名称" in out  # 技术名通过 labels 显示为业务名称
    assert "<script" not in out


def _cfg(tmp_path):
    from ifcat.config import load_config
    f = tmp_path / "env.yaml"
    f.write_text("project: demo\nenv_name: dev\nbase_url: http://x\naccounts:\n  maker: {username: u, password: p}\n", encoding="utf-8")
    return load_config(f)


def _add_scenarios(ws_root, ids):
    for sid, mod in ids:
        raw = dict(SCENARIO, id=sid, title=f"场景{sid}", module=mod)
        (ws_root / "scenarios" / mod).mkdir(exist_ok=True)
        (ws_root / "scenarios" / mod / f"{sid}.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


def _fake_batch_env(monkeypatch, outcomes):
    """用假的会话和假的单场景运行，按 outcomes 给出每个场景的结果（或抛异常）。"""
    from ifcat import batch
    from ifcat.evidence import RunRecorder
    from ifcat.result import StepResult

    class FakeSession:
        def __init__(self, *a, **k): pass
        def start(self): pass
        def close(self): pass

    def fake_run_one(ws, cfg, sc, state, sess, db, registry, bills, gate, batch_dir):
        out = outcomes[sc.id]
        if out == "boom":
            raise RuntimeError("浏览器崩了")
        rec = RunRecorder(ws.results_dir, cfg.project, cfg.env_name, sc.id, batch_dir=batch_dir)
        rec.record_step("填 X", StepResult.passed("ok"))
        if out != "passed":
            rec.record_step("验 Y", StepResult.failed("期望 7，实际 8") if out == "failed" else StepResult.blocked("找不到组件"))
        rec.annotate_steps_since(0, text="步骤说明", role_name="经办", checkpoint=False)
        rec.finish(out)
        return out, rec

    monkeypatch.setattr(batch, "_run_one", fake_run_one)
    import ifcat.session
    monkeypatch.setattr(ifcat.session, "Session", FakeSession)


def test_batch_runs_only_approved_isolates_failures_and_never_overwrites(ws_root, tmp_path, monkeypatch):
    from ifcat.batch import run_batch, select
    _add_scenarios(ws_root, [("A1", "DP"), ("A2", "DP"), ("A3", "DP"), ("B1", "LM"), ("B2", "LM")])
    ws = load_workspace(str(ws_root))
    for sid in ("A1", "A2", "A3", "B1"):  # B2 故意不审核
        p = ws.resolve_scenario(sid)
        record_approval(load_scenario(p), p, "张三")
    _fake_batch_env(monkeypatch, {"A1": "passed", "A2": "failed", "A3": "boom", "B1": "blocked", "B2": "passed"})
    cfg = _cfg(tmp_path)
    scope, cands = select(ws, None, ["dp", "LM"], False)
    assert scope == "DP+LM" and len(cands) == 5
    b1 = run_batch(ws, cfg, scope, cands, None, {}, log=lambda m: None)
    st = {s["id"]: s["status"] for s in b1["scenarios"]}
    assert st == {"A1": "passed", "A2": "failed", "A3": "blocked", "B1": "blocked", "B2": "skipped"}
    assert b1["complete"] and not b1["draft"]
    d1 = ws.results_dir / "runs" / "demo" / "dev" / b1["batch_id"]
    assert (d1 / "report.html").is_file() and (d1 / "batch.json").is_file()
    assert "第 2 步" in next(s for s in b1["scenarios"] if s["id"] == "A2")["problem"]
    assert "浏览器崩了" in next(s for s in b1["scenarios"] if s["id"] == "A3")["problem"]
    rep = (d1 / "report.html").read_text(encoding="utf-8")
    assert "未运行" in rep and "检查未通过" in rep and "自动化未能完成" in rep
    a1 = next(s for s in b1["scenarios"] if s["id"] == "A1")
    assert (d1 / a1["dir"] / "report.html").is_file()

    # 第二次：A2 恢复、A1 新增失败；第一批不被覆盖
    _fake_batch_env(monkeypatch, {"A1": "failed", "A2": "passed", "A3": "passed", "B1": "passed", "B2": "passed"})
    b2 = run_batch(ws, cfg, scope, cands, None, {}, log=lambda m: None)
    assert b2["batch_id"] != b1["batch_id"] and (d1 / "batch.json").is_file()
    rep2 = (ws.results_dir / "runs" / "demo" / "dev" / b2["batch_id"] / "report.html").read_text(encoding="utf-8")
    assert "新增失败 <b>1</b>" in rep2 and "已恢复 <b>3</b>" in rep2
    idx = (ws.results_dir / "index.html").read_text(encoding="utf-8")
    assert b1["batch_id"] in idx and b2["batch_id"] in idx


def test_batch_draft_marks_unreviewed_and_bad_file_does_not_stop_batch(ws_root, tmp_path, monkeypatch):
    from ifcat.batch import run_batch, select
    _add_scenarios(ws_root, [("A1", "DP")])
    (ws_root / "scenarios" / "DP" / "坏文件.yaml").write_text("id: [\n", encoding="utf-8")
    ws = load_workspace(str(ws_root))
    _fake_batch_env(monkeypatch, {"A1": "passed"})
    scope, cands = select(ws, None, None, True)
    b = run_batch(ws, _cfg(tmp_path), scope, cands, None, {}, draft=True, log=lambda m: None)
    st = {s["id"]: s["status"] for s in b["scenarios"]}
    assert st["A1"] == "passed" and st["坏文件"] == "blocked" and b["draft"]
    assert "调试" in (ws.results_dir / "runs" / "demo" / "dev" / b["batch_id"] / "report.html").read_text(encoding="utf-8")


def test_cli_run_batch_without_approved_scenarios_runs_nothing(ws_root, capsys):
    _add_scenarios(ws_root, [("A1", "DP")])
    cfgdir = ws_root / "config" / "local"
    cfgdir.mkdir(parents=True)
    (cfgdir / "dev.yaml").write_text("project: demo\nenv_name: dev\nbase_url: http://x\naccounts:\n  maker: {username: u, password: p}\n",
                                     encoding="utf-8")
    assert main(_args(ws_root, "run", "--module", "DP", "--env", "dev")) == 3  # 全部未审核：不启动浏览器，退出码 3
    assert "未运行 1" in capsys.readouterr().out
    assert list((ws_root / "results" / "runs" / "demo" / "dev").glob("*/report.html"))


def test_form_snapshots_import_list_and_validate_without_product_source(ws_root, tmp_path, capsys):
    src = tmp_path / "product_forms"
    src.mkdir()
    (src / "DEMO_FORM.json").write_text(json.dumps(FORM, ensure_ascii=False), encoding="utf-8")
    (ws_root / "forms" / "DEMO_FORM.json").unlink()  # 工作区里没有任何本机表单目录，只靠快照
    (ws_root / "workspace.yaml").write_text("project: demo\n", encoding="utf-8")
    assert main(_args(ws_root, "forms", "import", "DEMO_FORM", "--from", str(src))) == 2  # 缺产品版本
    assert main(_args(ws_root, "forms", "import", "DEMO_FORM", "--from", str(src), "--product-version", "6.2.7")) == 0
    assert main(_args(ws_root, "forms", "list")) == 0
    assert "DEMO_FORM" in capsys.readouterr().out
    index = (ws_root / "knowledge" / "forms" / "_index.yaml").read_text(encoding="utf-8")
    assert str(tmp_path) not in index  # 索引里不能出现本机路径
    assert main(_args(ws_root, "validate", "演示")) == 0
    (src / "BAD.json").write_text("{坏的", encoding="utf-8")
    assert main(_args(ws_root, "forms", "import", "BAD", "--from", str(src), "--product-version", "6.2.7")) == 2
    assert not (ws_root / "knowledge" / "forms" / "BAD.json").exists()
