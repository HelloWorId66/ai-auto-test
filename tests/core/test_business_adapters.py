"""用按 05 文档描述搭的模拟页面测试适配器逻辑。
模拟页面只能证明代码按文档的假设工作，不能证明真实页面如此，真实页面要靠标定。
"""
import pytest

pw = pytest.importorskip("playwright.sync_api")

from ifcat.adapters import build_default_registry
from ifcat.evidence import RunRecorder
from ifcat.meta import load_form
from ifcat.primitives import Primitives
from ifcat.result import Status

HTML = """
<html><body>
<div class="common-parallel-input F1-U-form-container">
  <div class="ant-select"><div class="ant-select-selector" style="min-width:120px;min-height:24px" onclick="
     document.getElementById('pu').style.display='block'">
    <span class="ant-select-selection-item" id="puval"></span></div></div>
</div>
<div id="pu" class="paymentUnit-select" style="display:none">
  <ul><li onclick="document.getElementById('puval').textContent='集团财务公司';document.getElementById('pu').style.display='none'">集团财务公司</li>
      <li>客户甲</li><li>客户乙</li></ul>
</div>

<div class="F1-C-form-container">
  <div class="ant-select"><div class="ant-select-selector" style="min-width:120px;min-height:24px" onclick="document.getElementById('cu').style.display='block'">
    <span class="ant-select-selection-item" id="cuval"></span></div></div>
</div>
<div id="cu" class="currencyConpent" style="display:none">
  <div class="it" onclick="pick('CNY-人民币')">CNY-人民币</div>
  <div class="it" onclick="pick('USD-美元')">USD-美元</div>
  <div class="it" onclick="pick('USD-美元2')">USD-美元2</div>
</div>
<script>function pick(t){document.getElementById('cuval').textContent=t;document.getElementById('cu').style.display='none'}</script>

<div class="InterestRate F1-R-form-container">
  <input id="F1-R-form-input" class="ant-input"
   onblur="if(this.value&&!this.value.includes('.'))this.value=this.value+'.00'"><span class="suffix-unit">%</span>
</div>
</body></html>
"""

def _form():
    def f(key, label, typ):
        return {"key": key, "type": typ, "props": {"showLabelText": label, "dataSetID": "T", "dataSetColID": "F_" + key}}
    return load_form({"formID": "F1", "formName": "x", "components": [{"key": "R", "type": "FormBoxContainer", "children": [
        f("U", "存款方", "PaymentUnit"), f("C", "币种", "Currency"), f("R", "实际年利率", "InterestRateInput"),
        f("Z", "金额", "AmountComp")]}]})


@pytest.fixture
def prim(tmp_path):
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"没有可用的 chromium：{exc}")
        page = browser.new_page()
        page.set_content(HTML)
        yield Primitives(page, {"F1": _form()}, build_default_registry(), RunRecorder(tmp_path, "p", "e", "s"))
        browser.close()


def test_payment_unit_pick_by_text(prim):
    assert prim.fill("F1", {"存款方": "集团财务公司"}).ok
    assert prim.expect_field("F1", "存款方", "集团财务公司").ok


def test_currency_code_prefix_match_and_ambiguity_blocks(prim):
    assert prim.fill("F1", {"币种": "CNY"}).ok
    assert prim.expect_field("F1", "币种", "CNY-人民币").ok
    # 「美元」同时命中 USD-美元 和 USD-美元2 的后缀规则不成立，但 USD 前缀命中两项，必须阻塞
    r = prim.fill("F1", {"币种": "USD"})
    assert r.status is Status.BLOCKED and "2 个选项" in r.message


def test_interest_rate_read_after_blur(prim):
    assert prim.fill("F1", {"实际年利率": "3"}).ok
    assert prim.expect_field("F1", "实际年利率", "3.00").ok


def test_unsupported_type_blocks_instead_of_guessing(prim):
    r = prim.fill("F1", {"金额": "100"})
    assert r.status is Status.BLOCKED
