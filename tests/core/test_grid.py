import pytest

pw = pytest.importorskip("playwright.sync_api")

from ifcat.adapters import build_default_registry
from ifcat.evidence import RunRecorder
from ifcat.meta import GridColumnMeta, GridMeta, load_form
from ifcat.primitives import Primitives
from ifcat.result import Status

# 模拟页面只证明代码按文档假设工作，不代表真实 osp-grid 的行为
HTML = """<style>.osp-cell{min-width:100px;min-height:20px;border:1px solid}</style>
<div class="F-G1-form-pan-grid"><button id="add" onclick="addRow()">增加分录</button><div id="body"></div></div>
<script>
let n = 0;
function addRow() {
  const r = document.createElement('div'); r.className = 'osp-row'; r.setAttribute('row-index', n++);
  r.innerHTML = '<div class="osp-cell" col-id="C1"><span class="osp-cell-value"></span></div>';
  const c = r.firstChild;
  c.onclick = () => { if (!c.querySelector('input')) { c.innerHTML = '<input>';
    c.querySelector('input').onblur = e => { c.innerHTML = '<span class="osp-cell-value">' + e.target.value + '</span>'; }; c.querySelector('input').focus(); } };
  document.getElementById('body').appendChild(r);
}
</script>
"""


@pytest.fixture
def prim(tmp_path):
    form = load_form({"formID": "F", "formName": "x", "components": []})
    form.grids.append(GridMeta("G1", "DS", "CM", [GridColumnMeta("C1", "品种", "F_C1", "1", "", True, True)]))
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.set_content(HTML)
        rec = RunRecorder(tmp_path, "p", "e", "s")
        yield Primitives(page, {"F": form}, build_default_registry(), rec)
        b.close()


def test_fill_and_expect_grid(prim):
    r = prim.fill_grid("F", "G1", [{"品种": "流动资金"}, {"品种": "项目贷款"}], add_button="增加分录")
    assert r.status is Status.PASSED, r.message
    assert prim.expect_grid("F", "G1", [{"品种": "流动资金"}, {"品种": "项目贷款"}]).ok
    assert prim.expect_grid("F", "G1", [{"品种": "流动资金"}]).status is Status.FAILED
    assert prim.expect_grid("F", "G1", [{"品种": "x"}, {"品种": "项目贷款"}]).status is Status.FAILED


def test_grid_blocks_without_add_button_or_unknown_column(prim):
    assert prim.fill_grid("F", "G1", [{"品种": "a"}]).status is Status.BLOCKED
    assert prim.fill_grid("F", "G1", [{"不存在": "a"}], add_button="增加分录").status is Status.BLOCKED
