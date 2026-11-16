"""网格（PanGrid / osp-grid）操作。

依据 docs/exploration/06-网格与单元格编辑器.md，全部选择器来自源码，未在真实页面验证：
- 容器类 ${formID}-${网格key}-form-pan-grid；行 .osp-row；单元格 .osp-cell[col-id=列key]
- 新增行点工具栏「增加分录」类按钮（按钮文字因表单而异，由场景的 add_button 给出）
- 单元格编辑器码 1/3/5/6/21 复用通用适配器，7（字典帮助）已在真实页面验证，30（自定义表单帮助）没有证据，一律阻塞
新增行的位置（首/尾）未确认，所以填完后一定读回比较，位置不对会被发现而不是悄悄通过。
"""
from __future__ import annotations

from typing import Any, Dict, List

from . import waits
from .adapters.base import Adapter
from .adapters.business import _click_unique_text
from .adapters.generic import ComboBoxAdapter, DateAdapter, NumberInputAdapter, TextInputAdapter
from .meta import FormMeta, GridColumnMeta, GridMeta
from .result import BlockedError

class DictHelpCellAdapter(Adapter):
    """编辑器码 7：字典帮助。点开单元格里的下拉，弹出「编号 名称」表格，按名称（或编号）点一行。
    依据 dev 环境授信申请页「授信品种」列的真实观察（2026-11-16）。"""

    type_name = "GridCell:7"

    def set(self, page: Any, root: Any, value: Any) -> None:
        root.locator(".ant-select-selector").first.click()
        popup = page.locator(".ant-select-dropdown:visible")
        waits.poll(lambda: popup.count() >= 1, 8.0, "字典帮助弹层出现")
        _click_unique_text(popup.last, str(value), "字典帮助")
        waits.poll(lambda: page.locator(".ant-select-dropdown:visible").count() == 0, 8.0, "字典帮助弹层关闭")
        page.keyboard.press("Tab")  # 离开单元格，让值提交到行里

    def get(self, page: Any, root: Any) -> Any:
        item = root.locator(".ant-select-selection-item").first
        if item.count():
            return (item.get_attribute("title") or item.inner_text()).strip()
        return root.inner_text().strip()


_CELL_ADAPTERS = {
    "1": TextInputAdapter(), "22": TextInputAdapter(), "101": TextInputAdapter(),
    "3": NumberInputAdapter(), "5": DateAdapter(), "6": ComboBoxAdapter(), "21": ComboBoxAdapter(), "7": DictHelpCellAdapter(),
}
UNSUPPORTED = {"30": "自定义表单帮助会弹出另一张表单，未确认"}


def cell_type_name(col: GridColumnMeta) -> str:
    return f"GridCell:{col.editor_type}"


def find_grid_meta(form: FormMeta, grid_key: str) -> GridMeta:
    for g in form.grids:
        if g.key == grid_key:
            return g
    raise BlockedError(f"表单 {form.form_id} 里没有网格 {grid_key}")


def find_column(grid: GridMeta, name: str) -> GridColumnMeta:
    plain = lambda t: str(t).strip().lstrip("*").strip()  # 必填列的表头带 * 前缀，业务上叫的是不带 * 的名字
    hits = [c for c in grid.columns if c.header == name or c.key == name or plain(c.header) == plain(name)]
    if not hits:
        raise BlockedError(f"网格 {grid.key} 里没有列「{name}」")
    if len(hits) > 1:
        raise BlockedError(f"网格 {grid.key} 里有 {len(hits)} 列叫「{name}」，请用列 key 指定")
    return hits[0]


def grid_root(page: Any, form: FormMeta, grid: GridMeta) -> Any:
    root = page.locator(f".{form.form_id}-{grid.key}-form-pan-grid")
    if root.count() != 1:
        raise BlockedError(f"页面上找到 {root.count()} 个网格容器 {form.form_id}-{grid.key}，期望 1 个")
    return root


def cell(root: Any, row_index: int, col: GridColumnMeta) -> Any:
    return root.locator(f".osp-row[row-index='{row_index}'] .osp-cell[col-id='{col.key}']")


def row_count(root: Any) -> int:
    return root.locator(".osp-center-cols-container .osp-row, .osp-row").count()


def add_row(page: Any, root: Any, add_button: str) -> int:
    """点增加按钮并等待行数加一，返回新增前的行数。"""
    before = row_count(root)
    page.get_by_text(add_button, exact=True).first.click()
    waits.poll(lambda: row_count(root) == before + 1, 8.0, f"点击「{add_button}」后行数没有增加")
    return before


def set_cell(page: Any, root: Any, row_index: int, col: GridColumnMeta, value: Any, gate: Any = None) -> None:
    code = col.editor_type
    if code in UNSUPPORTED:
        raise BlockedError(f"列「{col.header}」编辑器码 {code}：{UNSUPPORTED[code]}")
    adapter = _CELL_ADAPTERS.get(code)
    if adapter is None:
        raise BlockedError(f"列「{col.header}」编辑器码 {code} 没有适配器")
    if gate is not None:
        problem = gate.problem(cell_type_name(col))
        if problem:
            raise BlockedError(problem)
    if not col.editable:
        raise BlockedError(f"列「{col.header}」在表单里不可编辑")
    c = cell(root, row_index, col)
    if c.count() != 1:
        raise BlockedError(f"第 {row_index + 1} 行找不到列「{col.header}」的单元格（可能被虚拟化隐藏）")
    c.click()
    adapter.set(page, c, value)


def read_cell(root: Any, row_index: int, col: GridColumnMeta) -> str:
    c = cell(root, row_index, col)
    if c.count() != 1:
        raise BlockedError(f"第 {row_index + 1} 行找不到列「{col.header}」的单元格")
    item = c.locator(".ant-select-selection-item").first
    if item.count():  # 下拉类编辑器：输入框是搜索框，值在选中项里
        return (item.get_attribute("title") or item.inner_text()).strip()
    box = c.locator("input").first
    if box.count():
        return box.input_value()
    return c.locator(".osp-cell-value").first.inner_text().strip()


def read_rows(root: Any, grid: GridMeta, columns: List[str]) -> List[Dict[str, str]]:
    cols = [find_column(grid, n) for n in columns]
    return [{c.header: read_cell(root, i, c) for c in cols} for i in range(row_count(root))]
