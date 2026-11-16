import pytest

pw = pytest.importorskip("playwright.sync_api")

from ifcat.adapters import build_default_registry
from ifcat.evidence import RunRecorder
from ifcat.meta import load_form
from ifcat.primitives import Primitives
from ifcat.result import Status

HTML = """
<html><body>
<div class="row"><span>*名称</span><div><input class="font-style-wrapper FormTextInput" id="a"></div></div>
<div class="row"><span>名称</span><div><input class="font-style-wrapper FormTextInput" id="b"></div></div>
<div class="row"><span>金额</span><div class="osp-number-input"><input id="n"></div></div>
<div class="row"><span>隐藏</span><div style="display:none"><input class="FormTextInput"></div></div>
</body></html>
"""

def _form():
    def f(key, label, typ, col):
        return {"key": key, "type": typ, "props": {"showLabelText": label, "dataSetID": "T", "dataSetColID": col}}
    return load_form({"formID": "F", "formName": "x", "components": [{"key": "R", "type": "FormBoxContainer", "children": [
        f("A", "名称", "FormTextInput", "F_A"), f("B", "名称", "FormTextInput", "F_B"),
        f("N", "金额", "FormNumberInput", "F_N"), f("M", "不存在", "FormTextInput", "F_M")]}]})


@pytest.fixture
def prim(tmp_path):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"没有可用的 chromium：{exc}")
        page = browser.new_page()
        page.set_content(HTML)
        yield Primitives(page, {"F": _form()}, build_default_registry(), RunRecorder(tmp_path, "p", "e", "s"))
        browser.close()


def test_duplicate_labels_resolved_by_order_and_star_prefix_ignored(prim):
    assert prim.fill("F", {"名称": "第一个"}, occurrence=0).ok
    assert prim.fill("F", {"名称": "第二个"}, occurrence=1).ok
    assert prim.page.input_value("#a") == "第一个"
    assert prim.page.input_value("#b") == "第二个"
    assert prim.expect_field("F", "名称", "第二个", occurrence=1).ok
    r = prim.expect_field("F", "名称", "第一个", occurrence=1)
    assert r.status is Status.FAILED


def test_number_compared_as_decimal(prim):
    assert prim.fill("F", {"金额": "1000.5"}).ok
    assert prim.expect_field("F", "金额", "1,000.50").ok


def test_missing_label_in_page_blocks_not_guesses(prim):
    r = prim.fill("F", {"不存在": "x"})
    assert r.status is Status.BLOCKED and "找不到字段" in r.message
