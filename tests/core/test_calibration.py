from datetime import datetime, timedelta

import pytest

from ifcat import CORE_VERSION
from ifcat.adapters import build_default_registry
from ifcat.calibration import (CalibrationGate, CalibrationKey, CalibrationRecord, CalibrationStore, Probe,
                               preflight, run_calibration)
from ifcat.evidence import RunRecorder
from ifcat.meta import load_form
from ifcat.primitives import Primitives
from ifcat.result import Status

KEY = CalibrationKey("6.2.7", "projA", "sit")
NOW = datetime(2026, 11, 13, 12, 0, 0)


def _rec(t, passed=True, days_ago=1, core=CORE_VERSION, detail=""):
    return CalibrationRecord(t, passed, (NOW - timedelta(days=days_ago)).isoformat(), core, detail)


def _gate(tmp_path, *recs):
    store = CalibrationStore(tmp_path, KEY)
    for r in recs:
        store.put(r)
    return CalibrationGate(store, max_age_days=30, now=lambda: NOW)


def test_gate_each_reason(tmp_path):
    g = _gate(tmp_path, _rec("FormTextInput"), _rec("FormDateField", passed=False, detail="没找到"),
              _rec("FormComboBox", core="0.0.1"), _rec("HelpComboBox", days_ago=31))
    assert g.problem("FormTextInput") is None
    assert "没有标定记录" in g.problem("PaymentUnit")
    assert "标定失败" in g.problem("FormDateField") and "没找到" in g.problem("FormDateField")
    assert "重新标定" in g.problem("FormComboBox")
    assert "已过期" in g.problem("HelpComboBox")


def test_records_are_separate_per_product_version_project_env(tmp_path):
    s1 = CalibrationStore(tmp_path, KEY)
    s1.put(_rec("FormTextInput"))
    path = s1.save()
    assert path.is_file()
    assert CalibrationStore(tmp_path, KEY).get("FormTextInput").passed
    for other in (CalibrationKey("6.3.0", "projA", "sit"), CalibrationKey("6.2.7", "projB", "sit"),
                  CalibrationKey("6.2.7", "projA", "uat")):
        assert CalibrationStore(tmp_path, other).get("FormTextInput") is None


def _form():
    def f(key, label, typ):
        return {"key": key, "type": typ, "props": {"showLabelText": label, "dataSetID": "T", "dataSetColID": "F_" + key}}
    return load_form({"formID": "F", "formName": "x", "components": [{"key": "R", "type": "FormBoxContainer", "children": [
        f("A", "名称", "FormTextInput"), f("B", "金额", "FormCheckBox"), f("C", "日期", "FormDateField")]}]})


def test_preflight_reports_missing_adapter_and_uncalibrated(tmp_path):
    g = _gate(tmp_path, _rec("FormTextInput"))
    rep = preflight([_form()], build_default_registry(), g)
    assert not rep.ok and rep.no_adapter == ["FormCheckBox"] and "FormDateField" in rep.problems
    # 只检查场景实际用到的字段时，不相关的组件不拦截
    rep2 = preflight([_form()], build_default_registry(), g, only_labels={"F": ["名称"]})
    assert rep2.ok


pw = pytest.importorskip("playwright.sync_api")
HTML = '<div><span>名称</span><div><input class="FormTextInput"></div></div>'


@pytest.fixture
def page():
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"没有可用的 chromium：{exc}")
        pg = b.new_page()
        pg.set_content(HTML)
        yield pg
        b.close()


def test_run_calibration_records_pass_and_fail_and_gate_enforced(tmp_path, page):
    prim = Primitives(page, {"F": _form()}, build_default_registry(), RunRecorder(tmp_path, "p", "e", "cal"))
    store = CalibrationStore(tmp_path, KEY)
    opened = []
    probes = [Probe("FormTextInput", "F", "名称", "abc"),
              Probe("FormDateField", "F", "日期", "2026-01-01")]  # 页面上没有日期控件，必须标定失败
    recs = {r.type_name: r for r in run_calibration(prim, probes, store, opened.append, now=lambda: NOW)}
    assert opened == ["F", "F"]
    assert recs["FormTextInput"].passed and not recs["FormDateField"].passed and recs["FormDateField"].detail

    gate = CalibrationGate(CalibrationStore(tmp_path, KEY), now=lambda: NOW)
    assert gate.problem("FormTextInput") is None and gate.problem("FormDateField")

    gated = Primitives(page, {"F": _form()}, build_default_registry(), RunRecorder(tmp_path, "p", "e", "run"), gate=gate)
    assert gated.fill("F", {"名称": "x"}).ok
    r = gated.fill("F", {"日期": "2026-01-01"})
    assert r.status is Status.BLOCKED and "标定失败" in r.message
