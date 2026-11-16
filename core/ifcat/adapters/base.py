from __future__ import annotations

from typing import Any, ClassVar, Optional


class Adapter:
    """一种 PanUI 组件的操作适配器。

    type_name 必须等于表单 JSON 里的组件 type 字符串。
    root 是定位器给出的「该字段所在容器」的 Playwright Locator。
    """

    type_name: ClassVar[str] = ""
    def set(self, page: Any, root: Any, value: Any) -> None:
        raise NotImplementedError

    def get(self, page: Any, root: Any) -> Any:
        raise NotImplementedError

    def is_readonly(self, page: Any, root: Any) -> Optional[bool]:
        """无法判断时返回 None，由调用方决定，不要猜。"""
        return None
