"""框架层的保证：失败分类、不漏场景、编号唯一、工作区临时扩展（动作/方言）、归纳清单、语言与版本绑定。"""
import json
import sqlite3
from datetime import datetime

import pytest
import yaml

from ifcat import CORE_VERSION, actions
from ifcat.adapters import build_default_registry
from ifcat.batch import select
from ifcat.calibration import CalibrationGate, CalibrationKey, CalibrationStore
from ifcat.cli import main
from ifcat.config import DbConfig
from ifcat.dbro import ReadOnlyDb, ReadOnlyViolation, register_extension_dialect
from ifcat.evidence import RunRecorder
from ifcat.extloader import load_extensions
from ifcat.primitives import Primitives
from ifcat.result import Status, StepResult
from ifcat.reviewpage import render_review_html
from ifcat.review import ReviewState
from ifcat.runner import ScenarioRunner
from ifcat.scaffold import init_workspace
from ifcat.scenario import (ScenarioError, describe_date_macro, load_scenario, new_unique, parse_scenario, resolve,
                            resolve_data, validate_scenario)
from ifcat.waits import WaitTimeout
from ifcat.workspace import WorkspaceError, load_workspace

EXT = '''
from ifcat.ext import StepResult, action


@action("note_value", required=["value"], text="记下一个值")
def note_value(ctx, value, **_):
    ctx.captured["note"] = value
    return StepResult.passed("已记下")


@action("expect_note", required=["expected"], text="检查记下的值", checkpoint=True)
def expect_note(ctx, expected, **_):
    got = ctx.captured.get("note")
    return StepResult.passed("一致") if got == expected else StepResult.failed(f"期望 {expected}，实际 {got}")


@action("bad_return")
def bad_return(ctx, **_):
    return "不是步骤结果"
'''

SCENARIO = {
    "id": "DEMO-扩展动作", "title": "用工作区扩展动作", "module": "DEMO", "data": {"v": "甲"},
    "steps": [
        {"id": "s1", "do": "note_value", "args": {"value": "${data.v}"}},
        {"id": "c1", "do": "expect_note", "args": {"expected": "甲"}},
    ],
}


class FakePage:
    def screenshot(self, path, full_page=False):
        with open(path, "wb") as f:
            f.write(b"png")


@pytest.fixture
def ws_root(tmp_path):
    root = tmp_path / "ws"
    init_workspace(root, "demo")
    (root / "scenarios" / "DEMO").mkdir(parents=True)
    (root / "extensions" / "temp_actions.py").write_text(EXT, encoding="utf-8")
    (root / "scenarios" / "DEMO" / "扩展动作.yaml").write_text(yaml.safe_dump(SCENARIO, allow_unicode=True), encoding="utf-8")
    return root


def _args(root, *a):
    return ["--workspace", str(root), "--skip-integrity", *a]


def _prim(tmp_path, page=None):
    return Primitives(page, {}, build_default_registry(), RunRecorder(tmp_path / "res", "p", "e", "s"))


# --- 失败分类 ---
def test_step_that_cannot_finish_is_blocked_and_leaves_a_screenshot(tmp_path):
    prim = _prim(tmp_path, FakePage())

    def timeout():
        raise WaitTimeout("等待超时（8s）：下拉弹层出现")

    r = prim._step("填 X", timeout)
    assert r.status is Status.BLOCKED and "WaitTimeout" in r.message
    assert r.evidence and (prim.rec.dir / r.evidence[0]).is_file()
    # 检查点比对不一致仍然是 failed：只有它代表系统行为与预期不符
    assert prim._step("验 X", lambda: StepResult.failed("期望 1，实际 2")).status is Status.FAILED


# --- 不漏场景、编号唯一 ---
def test_module_run_keeps_unparseable_scenario(ws_root):
    (ws_root / "scenarios" / "DEMO" / "坏的.yaml").write_text("id: x\ntitle: t\nmodule: DEMO\nsteps:\n  - {do: 不存在的动作}\n",
                                                             encoding="utf-8")
    load_extensions(build_default_registry(), ws_root / "extensions")
    _, cands = select(load_workspace(str(ws_root)), None, ["demo"], False)
    assert sorted(c.path.name for c in cands) == ["坏的.yaml", "扩展动作.yaml"]
    assert [c.path.name for c in cands if c.scenario is None] == ["坏的.yaml"]


def test_duplicate_scenario_id_fails_validate_and_approve(ws_root, capsys):
    twin = {**SCENARIO, "title": "同编号的另一个"}
    (ws_root / "scenarios" / "DEMO" / "重复.yaml").write_text(yaml.safe_dump(twin, allow_unicode=True), encoding="utf-8")
    assert main(_args(ws_root, "validate", "--module", "DEMO")) == 1
    assert "重复" in capsys.readouterr().out
    assert main(_args(ws_root, "approve", "扩展动作")) == 1
    assert not (ws_root / "scenarios" / "DEMO" / "扩展动作.review.yaml").exists()


# --- 工作区临时扩展：动作 ---
def test_extension_action_is_usable_like_builtin(ws_root, tmp_path, capsys):
    assert main(_args(ws_root, "validate", "扩展动作")) == 0
    assert main(_args(ws_root, "render", "扩展动作")) == 0
    capsys.readouterr()
    sc = load_scenario(ws_root / "scenarios" / "DEMO" / "扩展动作.yaml")
    prim = _prim(tmp_path)
    assert ScenarioRunner(prim).run(sc) is Status.PASSED
    assert [s["checkpoint"] for s in prim.rec.steps] == [False, True]
    used = prim.rec.meta["extensions_used"]
    assert {"kind": "action", "name": "note_value", "source": "temp_actions.py"} in used and len(used) == 2
    html = render_review_html(sc, ReviewState("unreviewed"))
    assert "记下一个值" in html and "检查点" in html and "甲" in html


def test_extension_action_failed_checkpoint_and_bad_return(ws_root, tmp_path):
    load_extensions(build_default_registry(), ws_root / "extensions")
    wrong = parse_scenario({**SCENARIO, "steps": [SCENARIO["steps"][0],
                                                  {"id": "c1", "do": "expect_note", "args": {"expected": "乙"}}]})
    assert ScenarioRunner(_prim(tmp_path / "a")).run(wrong) is Status.FAILED
    bad = parse_scenario({**SCENARIO, "steps": [{"id": "s1", "do": "bad_return"}]})
    prim = _prim(tmp_path / "b")
    assert ScenarioRunner(prim).run(bad) is Status.BLOCKED and "必须返回 StepResult" in prim.rec.steps[0]["message"]
    missing = parse_scenario({**SCENARIO, "steps": [{"id": "s1", "do": "note_value"}, SCENARIO["steps"][1]]})
    assert any("缺少参数" in i.message for i in validate_scenario(missing, {}))


def test_extension_action_cannot_override_builtin_and_unknown_still_rejected(tmp_path):
    (tmp_path / "clash.py").write_text(
        "from ifcat.ext import action, StepResult\n@action('save')\ndef save(ctx, **_):\n    return StepResult.passed('x')\n",
        encoding="utf-8")
    res = load_extensions(build_default_registry(), tmp_path)
    assert res["loaded"] == [] and "不能覆盖内置动作" in res["errors"][0]
    assert actions.extension_actions() == {}
    with pytest.raises(ScenarioError, match="extensions"):
        parse_scenario({**SCENARIO, "steps": [{"do": "note_value", "args": {"value": 1}}]})


# --- 工作区临时扩展：数据库方言 ---
def test_extension_dialect_registers_but_cannot_replace_builtin(tmp_path):
    with pytest.raises(ReadOnlyViolation):
        register_extension_dialect("oracle", lambda cfg: None)
    (tmp_path / "db.py").write_text(
        "import sqlite3\nfrom ifcat.ext import register_dialect\nregister_dialect('demo_db', lambda cfg: sqlite3.connect(':memory:'))\n",
        encoding="utf-8")
    assert load_extensions(build_default_registry(), tmp_path)["errors"] == []
    with ReadOnlyDb(DbConfig("demo_db", "x", "u", "p")) as db:
        assert db.query("select 1 as n") == [{"n": 1}]
    load_extensions(build_default_registry(), tmp_path / "nothing")
    with pytest.raises(ReadOnlyViolation):
        ReadOnlyDb(DbConfig("demo_db", "x", "u", "p"))


# --- 归纳清单 ---
def test_harvest_lists_extensions_with_usage(ws_root, capsys):
    run = ws_root / "results" / "runs" / "demo" / "dev" / "20260101-000000_x" / "s"
    run.mkdir(parents=True)
    meta = {"final_status": "passed", "finished": "20260101-000100",
            "extensions_used": [{"kind": "action", "name": "note_value", "source": "temp_actions.py"}]}
    (run / "result.json").write_text(json.dumps({"meta": meta, "steps": []}), encoding="utf-8")
    out_file = ws_root / "harvest.md"
    assert main(["--skip-integrity", "harvest", str(ws_root), str(ws_root), "--out", str(out_file)]) == 0
    text = out_file.read_text(encoding="utf-8")
    assert "| 动作 | `note_value` | temp_actions.py | 1 | 1 | 1 | 20260101-000100 |" in text
    assert "| 动作 | `bad_return` | temp_actions.py | 0 | 0 | 0 | — |" in text
    assert "多个工作区重复出现" in text  # 同一个工作区给了两次，等同于两个工作区都补了同名扩展
    assert main(["--skip-integrity", "harvest"]) == 2


# --- 不重复编号 ---
def test_unique_variable_is_stable_within_a_run_and_described_for_review(tmp_path):
    u = new_unique(datetime(2026, 11, 16, 9, 30, 5))
    assert len(u) == 14 and u.startswith("261116093005") and u.isdigit()
    assert resolve_data({"name": "测试-${unique}", "d": "${today}", "k": "${captured.x}"}, "77")["name"] == "测试-77"
    assert resolve_data({"k": "${captured.x}"}, "77") == {"k": "${captured.x}"}
    assert resolve("${unique}", {"unique": "77"}) == "77"
    assert "不重复编号" in describe_date_macro("测试-${unique}")
    (tmp_path / "ext").mkdir()
    (tmp_path / "ext" / "a.py").write_text(EXT, encoding="utf-8")
    load_extensions(build_default_registry(), tmp_path / "ext")
    sc = parse_scenario({"id": "u", "title": "t", "module": "DEMO", "data": {"v": "N-${unique}"}, "steps": [
        {"id": "s1", "do": "note_value", "args": {"value": "${data.v}"}},
        {"id": "c1", "do": "expect_note", "args": {"expected": "N-${unique}"}}]})
    prim = _prim(tmp_path)
    runner = ScenarioRunner(prim)
    assert runner.run(sc) is Status.PASSED
    assert runner.captured["note"] == "N-" + prim.rec.meta["unique"]


# --- 基线跨模块 ---
def test_base_scenario_can_live_in_another_module(tmp_path):
    lm, dp = tmp_path / "scenarios" / "LM" / "授信", tmp_path / "scenarios" / "DP" / "存入"
    lm.mkdir(parents=True)
    dp.mkdir(parents=True)
    base = {"id": "LM-基线", "title": "基线", "module": "LM",
            "steps": [{"id": "a", "do": "expect_db_status", "args": {"flow": "F", "key": "K", "state": "approved"}}]}
    (lm / "基线.yaml").write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    inc = dp / "增量.yaml"
    inc.write_text(yaml.safe_dump({"id": "DP-增量", "title": "增量", "module": "DP", "extends": "LM-基线"},
                                  allow_unicode=True), encoding="utf-8")
    assert [s.id for s in load_scenario(inc).steps] == ["a"]


# --- 标定按语言分开、工作区声明框架最低版本 ---
def test_calibration_is_kept_per_locale(tmp_path):
    zh, en = CalibrationKey("6.2.7", "p", "dev", "zh-CN"), CalibrationKey("6.2.7", "p", "dev", "en-US")
    assert zh.path(tmp_path) != en.path(tmp_path)
    assert "语言 en-US" in CalibrationGate(CalibrationStore(tmp_path, en)).problem("FormTextInput")


def test_workspace_declares_minimum_framework_version(ws_root):
    f = ws_root / "workspace.yaml"
    assert yaml.safe_load(f.read_text(encoding="utf-8"))["framework_min_version"] == CORE_VERSION
    load_workspace(str(ws_root))
    f.write_text(f.read_text(encoding="utf-8").replace(CORE_VERSION, "99.0.0"), encoding="utf-8")
    with pytest.raises(WorkspaceError, match="请先更新框架"):
        load_workspace(str(ws_root))

def test_review_page_renders_incomplete_step():
    sc = parse_scenario({
        "id": "XX-草稿", "title": "草稿", "module": "XX", "goal": "g", "roles": {"maker": "制单员"},
        "steps": [{"id": "c1", "as": "maker", "do": "expect_field", "args": {"form": "F1", "label": "状态"}}],
    })
    assert "参数不完整" in render_review_html(sc, ReviewState("unreviewed"))
