import sqlite3

import pytest
import yaml

from ifcat.adapters import build_default_registry
from ifcat.dbro import ReadOnlyDb
from ifcat.evidence import RunRecorder
from ifcat.meta import load_form
from ifcat.primitives import Primitives
from ifcat.result import Status
from ifcat.runner import ScenarioRunner
from ifcat.scenario import (ScenarioError, load_scenario, parse_scenario, render_markdown, resolve,
                            validate_scenario)
from ifcat.statemodel import BillModel, ResultTable

BASE = {
    "id": "base", "title": "基线", "module": "DP",
    "roles": {"maker": "制单员"},
    "data": {"amount": "100", "k": "K1"},
    "steps": [
        {"id": "a", "do": "fill", "as": "maker", "args": {"form": "F", "values": {"x": "${data.amount}"}}},
        {"id": "b", "do": "expect_db_status", "args": {"flow": "DEMO", "key": "${data.k}", "state": "approved"}},
    ],
}


def _write(tmp_path, name, raw):
    p = tmp_path / f"{name}.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return p


def test_resolve_keeps_type_and_errors_on_missing():
    ctx = {"data": {"n": 5, "s": "a"}}
    assert resolve("${data.n}", ctx) == 5
    assert resolve("x-${data.s}", ctx) == "x-a"
    with pytest.raises(ScenarioError):
        resolve("${data.zzz}", ctx)


def test_unknown_action_and_duplicate_ids_rejected():
    with pytest.raises(ScenarioError):
        parse_scenario({**BASE, "steps": [{"do": "teleport"}]})
    with pytest.raises(ScenarioError):
        parse_scenario({**BASE, "steps": [{"id": "a", "do": "save", "args": {"form": "F"}}] * 2})


def test_increment_inserts_sets_and_removes(tmp_path):
    _write(tmp_path, "base", BASE)
    inc = _write(tmp_path, "inc", {
        "id": "inc", "title": "增量", "module": "DP", "extends": "base", "requirement": "REQ-1",
        "set": {"data.amount": "200"},
        "add_steps_after": {"a": [{"id": "n1", "do": "expect_field",
                                   "args": {"form": "F", "label": "x", "expected": "200"}}]},
    })
    sc = load_scenario(inc)
    assert [s.id for s in sc.steps] == ["a", "n1", "b"]
    assert sc.data["amount"] == "200" and sc.requirement == "REQ-1"
    # 基线本身不被改动
    assert load_scenario(tmp_path / "base.yaml").data["amount"] == "100"

    bad = _write(tmp_path, "bad", {"id": "bad", "title": "t", "module": "DP", "extends": "base",
                                   "remove_steps": ["nope"]})
    with pytest.raises(ScenarioError):
        load_scenario(bad)
    cyc = _write(tmp_path, "cyc", {"id": "cyc", "title": "t", "module": "DP", "extends": "cyc"})
    with pytest.raises(ScenarioError):
        load_scenario(cyc)


def _form():
    return load_form({"formID": "F", "formName": "x", "components": [
        {"type": "FormTextInput", "key": "x", "label": "名称", "required": True}]})


def test_validate_flags_no_checkpoint_and_unknown_field():
    sc = parse_scenario({"id": "s", "title": "t", "module": "DP",
                         "steps": [{"id": "a", "do": "fill", "args": {"form": "F", "values": {"不存在": 1}}}]})
    msgs = [i.message for i in validate_scenario(sc, {"F": _form()})]
    assert any("没有任何业务检查点" in m for m in msgs)
    assert any("没有字段" in m for m in msgs)


def test_render_markdown_marks_checkpoints():
    md = render_markdown(parse_scenario(BASE))
    assert "【检查点】" in md and "制单员" in md


@pytest.fixture
def runner_env(tmp_path):
    c = sqlite3.connect(":memory:")
    c.execute("create table ZJ_HEAD(F_ID text, F_ZT text)")
    c.execute("insert into ZJ_HEAD values('K1','3')")
    model = BillModel("DEMO", "演示", "ZJ_HEAD", "F_ZT", "F_ID", results={}, states={"approved": "3"})
    rec = RunRecorder(tmp_path, "p", "e", "s")
    prim = Primitives(page=None, forms={"F": _form()}, registry=build_default_registry(), recorder=rec,
                      db=ReadOnlyDb(connection=c), bills={"DEMO": model})
    return prim


def test_runner_db_only_scenario_passes_and_switches_roles(runner_env):
    sc = parse_scenario({"id": "s", "title": "t", "module": "DP", "data": {"k": "K1"},
                         "steps": [{"id": "b", "do": "expect_db_status",
                                    "args": {"flow": "DEMO", "key": "${data.k}", "state": "approved"}}]})
    assert ScenarioRunner(runner_env).run(sc) is Status.PASSED


def test_runner_stops_at_first_unpassed_and_blocks_without_role_switch(runner_env):
    sc = parse_scenario(BASE)
    r = ScenarioRunner(runner_env)
    assert r.run(sc) is Status.BLOCKED
    assert len(runner_env.rec.steps) == 1  # 第二步没有执行


def test_runner_uncalibrated_action_blocks(runner_env):
    sc = parse_scenario({"id": "s", "title": "t", "module": "DP", "steps": [
        {"id": "a", "do": "save", "args": {"form": "F"}},
        {"id": "b", "do": "expect_db_status", "args": {"flow": "DEMO", "key": "K1", "state": "approved"}}]})
    assert ScenarioRunner(runner_env).run(sc) is Status.BLOCKED


def test_extension_loader_registers_new_and_reports_bad(tmp_path):
    from ifcat.extloader import load_extensions
    (tmp_path / "ok.py").write_text(
        "from ifcat.adapters import Adapter\nclass A(Adapter):\n    type_name='NewComp'\n", encoding="utf-8")
    (tmp_path / "clash.py").write_text(
        "from ifcat.adapters import Adapter\nclass B(Adapter):\n    type_name='FormTextInput'\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("raise RuntimeError('x')\n", encoding="utf-8")
    reg = build_default_registry()
    res = load_extensions(reg, tmp_path)
    assert res["loaded"] == ["ok.py:NewComp"] and "NewComp" in reg.types()
    assert len(res["errors"]) == 2


def test_release_manifest_matches_core():
    from ifcat import guard
    guard.verify_integrity()
