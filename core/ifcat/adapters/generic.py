"""通用控件适配器（来自 osp-react-designer-webcomps）。

选择器依据 docs/exploration/01-组件全集.md，未在真实页面验证，使用前必须有对应环境的标定记录（calibration.py）。
"""
from __future__ import annotations

from typing import Any, Optional

from .. import waits
from ..result import BlockedError
from .base import Adapter


def _input(root: Any) -> Any:
    return root.locator("input, textarea").first


class TextInputAdapter(Adapter):
    type_name = "FormTextInput"

    def set(self, page: Any, root: Any, value: Any) -> None:
        box = _input(root)
        box.fill(str(value))
        box.press("Tab")
        waits.wait_input_debounce(page)

    def get(self, page: Any, root: Any) -> Any:
        box = _input(root)
        if box.count():
            return box.input_value()
        return root.inner_text().strip()

    def is_readonly(self, page: Any, root: Any) -> Optional[bool]:
        box = _input(root)
        if not box.count():
            return True
        return bool(box.is_disabled() or box.get_attribute("readonly") is not None)


class TextAreaAdapter(TextInputAdapter):
    type_name = "FormTextArea"


class NumberInputAdapter(TextInputAdapter):
    type_name = "FormNumberInput"


class DateAdapter(Adapter):
    type_name = "FormDateField"

    def set(self, page: Any, root: Any, value: Any) -> None:
        box = _input(root)
        if not box.count():
            raise BlockedError("日期字段没有可输入的框，可能是只读展示态")
        box.click()
        box.fill(str(value))
        box.press("Enter")
        waits.wait_input_debounce(page)

    def get(self, page: Any, root: Any) -> Any:
        box = _input(root)
        if box.count():
            return box.input_value()
        return root.inner_text().strip()

    def is_readonly(self, page: Any, root: Any) -> Optional[bool]:
        # 只读时值为空会渲染成 span.no-value-comp（01 §2.4），没有 input
        return not _input(root).count() or bool(_input(root).is_disabled())


class _SelectAdapter(Adapter):
    def set(self, page: Any, root: Any, value: Any) -> None:
        root.locator(".ant-select-selector").first.click()
        dropdown = waits.wait_open_dropdown(page)
        search = root.locator(".ant-select-selection-search-input").first
        if search.count() and search.is_editable():
            search.fill(str(value))
        waits.wait_dropdown_items_stable(dropdown)
        text = str(value)
        item = dropdown.locator(f'.ant-select-item[title="{text}"]')
        if item.count() == 0:
            item = dropdown.locator(".ant-select-item", has_text=text)
        if item.count() == 0:
            raise BlockedError(f"下拉里没有选项「{text}」")
        if item.count() > 1:
            raise BlockedError(f"下拉里有 {item.count()} 个选项匹配「{text}」，请给出更完整的选项文本")
        item.first.click()

    def get(self, page: Any, root: Any) -> Any:
        item = root.locator(".ant-select-selection-item").first
        if not item.count():
            return ""
        return item.get_attribute("title") or item.inner_text().strip()

    def is_readonly(self, page: Any, root: Any) -> Optional[bool]:
        return "ant-select-disabled" in (root.locator(".ant-select").first.get_attribute("class") or "")


class ComboBoxAdapter(_SelectAdapter):
    type_name = "FormComboBox"


class HelpComboBoxAdapter(_SelectAdapter):
    type_name = "HelpComboBox"
