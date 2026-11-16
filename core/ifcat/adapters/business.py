"""IFC 业务组件适配器（osp-react-department-webcomps）。

选择器依据 docs/exploration/05-IFC业务组件.md，全部来自源码阅读，未在真实页面验证。
弹层内部结构（@panui/fi 的 PacketClassify、ParallelCode）未读，因此选项一律按「弹层内文本」匹配，
不依赖弹层内部类名；匹配不到或多于一个都阻塞，不猜。
"""
from __future__ import annotations

import re
from typing import Any, ClassVar, Optional

from .. import waits
from ..result import BlockedError
from .base import Adapter


def _click_table_row(popup: Any, text: str, what: str) -> bool:
    """弹层是表格（真实页面：@panui 的 custom-selector）时按行匹配：任一单元格文字等于 text 即命中。
    表格是大数据虚拟滚动，只渲染可见行，找不到就向下滚动再找。"""
    rows = popup.locator("tr.ant-table-row")
    try:
        waits.poll(lambda: rows.count() > 0, 4.0, f"{what}弹层表格加载")
    except Exception:
        return False  # 不是表格型弹层
    body = popup.locator(".ant-table-body").first
    for _ in range(60):
        hit = rows.filter(has=popup.page.get_by_text(text, exact=True))
        if hit.count() > 1:
            raise BlockedError(f"{what}弹层里有 {hit.count()} 行匹配「{text}」，请给出更完整的文本")
        if hit.count() == 1:
            hit.first.click()
            return True
        before = body.evaluate("e => e.scrollTop")
        body.evaluate("e => { e.scrollTop += e.clientHeight; }")
        popup.page.wait_for_timeout(250)
        if body.evaluate("e => e.scrollTop") == before:
            break
    raise BlockedError(f"{what}弹层里没有选项「{text}」")


def _click_unique_text(popup: Any, value: str, what: str) -> None:
    text = str(value).strip()
    if _click_table_row(popup, text, what):
        return
    exact = popup.get_by_text(text, exact=True)
    n = exact.count()
    if n == 0:
        # 币种项显示为「代码-名称」，允许只给代码或只给名称
        fuzzy = popup.locator(f'xpath=.//*[not(*)][starts-with(normalize-space(.), "{text}-") or '
                              f'substring(normalize-space(.), string-length(normalize-space(.)) - string-length("{text}")) = "-{text}"]')
        n, exact = fuzzy.count(), fuzzy
    if n == 0:
        raise BlockedError(f"{what}弹层里没有选项「{text}」")
    if n > 1:
        raise BlockedError(f"{what}弹层里有 {n} 个选项匹配「{text}」，请给出更完整的文本")
    exact.first.click()


class PopupPickAdapter(Adapter):
    """点击打开弹层 -> 在弹层里按文本点选项。"""

    trigger_css: ClassVar[str] = ".ant-select-selector"
    popup_css: ClassVar[str] = ""
    what: ClassVar[str] = ""

    def set(self, page: Any, root: Any, value: Any) -> None:
        root.locator(self.trigger_css).first.click()
        popup = page.locator(f":is({self.popup_css}):visible")
        waits.poll(lambda: popup.count() >= 1, 8.0, f"{self.what}弹层出现")
        _click_unique_text(popup.last, str(value), self.what)
        waits.poll(lambda: page.locator(f":is({self.popup_css}):visible").count() == 0, 8.0, f"{self.what}弹层关闭")

    def get(self, page: Any, root: Any) -> Any:
        item = root.locator(".ant-select-selection-item").first
        if not item.count():
            return ""
        return item.get_attribute("title") or item.inner_text().strip()

    def is_readonly(self, page: Any, root: Any) -> Optional[bool]:
        cls = root.get_attribute("class") or ""
        return "select-disabled-box" in cls or root.locator(".ant-select-disabled").count() > 0


class PaymentUnitAdapter(PopupPickAdapter):
    type_name = "PaymentUnit"
    popup_css = ".panui-custom-selector-dropdown, .paymentUnit-select"
    what = "付款单位"


class _PanuiHelpAdapter(PopupPickAdapter):
    popup_css = ".panui-custom-selector-dropdown, .panui-parallel-code"


class AccountOpenOrganAdapter(_PanuiHelpAdapter):
    type_name = "AccountOpenOrgan"
    what = "开户机构"


class PaymentAccountAdapter(_PanuiHelpAdapter):
    type_name = "PaymentAccount"
    what = "付款账号"


class CountryAreaAdapter(_PanuiHelpAdapter):
    type_name = "CountryArea"
    what = "国家地区"


class CurrencyAdapter(PopupPickAdapter):
    """币种下拉。有的表单是单选（点选项即关闭），有的是多选（勾选项后点弹层里的「确定」才关闭，如授信币种）。
    多选时 value 可以是一个币种或币种列表；读回值是已选币种，多个用空格隔开。"""

    type_name = "Currency"
    popup_css = ".currencyConpent"
    what = "币种"

    def set(self, page: Any, root: Any, value: Any) -> None:
        root.locator(self.trigger_css).first.click()
        popup = page.locator(f":is({self.popup_css}):visible")
        waits.poll(lambda: popup.count() >= 1, 8.0, f"{self.what}弹层出现")
        values = value if isinstance(value, (list, tuple)) else [value]
        for v in values:
            _click_unique_text(popup.last, str(v), self.what)
        # 多选弹层不会自动关闭，要点「确定」
        ok = popup.last.get_by_role("button", name="确定", exact=True) if popup.count() else None
        if ok is not None and popup.count() and ok.count():
            ok.first.click()
        waits.poll(lambda: page.locator(f":is({self.popup_css}):visible").count() == 0, 8.0, f"{self.what}弹层关闭")

    def get(self, page: Any, root: Any) -> Any:
        items = root.locator(".ant-select-selection-item")
        out = []
        for i in range(items.count()):
            it = items.nth(i)
            text = (it.get_attribute("title") or it.inner_text()).strip()
            if not re.fullmatch(r"\+\s*\d+", text):  # 「+0」是多选省略标记，不是币种
                out.append(text)
        return " ".join(x for x in out if x)


class AmountCompAdapter(PopupPickAdapter):
    """币种加金额的组合组件。value 可以是 {"currency": "USD", "amount": "1000"}，也可以是 "USD 1000"。
    读回值格式是「币种 金额」，金额取输入框里的文字（可能带千分位）。"""

    type_name = "AmountComp"
    popup_css = ".panui-custom-selector-dropdown, .currencyConpent"
    what = "币种"
    trigger_css = ".currency-input .ant-select-selector"

    @staticmethod
    def _split(value: Any) -> tuple:
        if isinstance(value, dict):
            return value.get("currency"), value.get("amount")
        parts = str(value).split()
        if len(parts) == 2:
            return parts[0], parts[1]
        raise BlockedError('金额字段的值要写成 "币种 金额"（如 "USD 1000"）或 {currency, amount}')

    def set(self, page: Any, root: Any, value: Any) -> None:
        currency, amount = self._split(value)
        # 币种已经是目标值时不重选：真实系统里重选币种会触发联动，清空周期、利率并重置金额（编辑已保存单据时实测）
        cur_now = root.locator(".currency-input .ant-select-selection-item").first
        cur_text = (cur_now.get_attribute("title") or cur_now.inner_text().strip()) if cur_now.count() else ""
        if currency and cur_text != str(currency).strip():
            super().set(page, root, currency)
        if amount is not None:
            box = root.locator("input.ant-input:not([disabled])").last
            # 金额框里已有值时（编辑已保存单据），直接 fill 会被组件还原成旧值；点进去全选后逐键输入才生效
            box.click()
            box.press("ControlOrMeta+a")
            page.keyboard.type(str(amount), delay=40)
            box.press("Tab")
            waits.wait_input_debounce(page)

    def get(self, page: Any, root: Any) -> Any:
        cur = root.locator(".currency-input .ant-select-selection-item").first
        cur_text = (cur.get_attribute("title") or cur.inner_text().strip()) if cur.count() else ""
        amt = root.locator("input.ant-input").last
        return f"{cur_text} {amt.input_value()}".strip()


class InterestRateAdapter(Adapter):
    """利率是 antd Input，不是数字框。小数补零发生在失焦，读值必须在失焦之后。"""

    type_name = "InterestRateInput"

    def set(self, page: Any, root: Any, value: Any) -> None:
        box = root.locator("input").first
        if not box.count():
            raise BlockedError("利率字段没有输入框，可能是只读展示态")
        box.fill(str(value))
        box.press("Tab")

    def get(self, page: Any, root: Any) -> Any:
        box = root.locator("input").first
        if box.count():
            return box.input_value()
        shown = root.locator(".display-state-box")
        return shown.inner_text().strip() if shown.count() else ""

    def is_readonly(self, page: Any, root: Any) -> Optional[bool]:
        box = root.locator("input").first
        return True if not box.count() else bool(box.is_disabled())
