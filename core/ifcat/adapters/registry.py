from __future__ import annotations

from typing import Dict, List, Optional, Type

from ..result import BlockedError
from .base import Adapter


class RegistryError(Exception):
    pass


class AdapterRegistry:
    """核心适配器先注册并锁定；扩展层只能新增类型，不能覆盖核心已有类型。"""

    def __init__(self) -> None:
        self._core: Dict[str, Adapter] = {}
        self._ext: Dict[str, Adapter] = {}
        self._ext_source: Dict[str, str] = {}
        self._locked = False

    def register_core(self, cls: Type[Adapter]) -> None:
        if self._locked:
            raise RegistryError("核心适配器已锁定，不能再注册")
        name = cls.type_name
        if not name:
            raise RegistryError(f"{cls.__name__} 没有 type_name")
        if name in self._core:
            raise RegistryError(f"核心适配器重复注册：{name}")
        self._core[name] = cls()

    def lock_core(self) -> None:
        self._locked = True

    def register_extension(self, cls: Type[Adapter], source: str = "") -> None:
        name = cls.type_name
        if not name:
            raise RegistryError(f"{cls.__name__} 没有 type_name")
        if name in self._core:
            raise RegistryError(f"扩展层不能覆盖核心适配器：{name}（要改核心请走提案）")
        if name in self._ext:
            raise RegistryError(f"扩展适配器重复注册：{name}")
        self._ext[name] = cls()
        self._ext_source[name] = source

    def extension_source(self, type_name: str) -> Optional[str]:
        """是扩展适配器时返回它所在的扩展文件名（可能为空串），核心适配器返回 None。"""
        return self._ext_source.get(type_name)

    def extension_types(self) -> Dict[str, str]:
        return dict(self._ext_source)

    def get(self, type_name: str) -> Adapter:
        if type_name in self._core:
            return self._core[type_name]
        if type_name in self._ext:
            return self._ext[type_name]
        raise BlockedError(f"没有适配器：{type_name}。请在扩展层新增，不要猜选择器")

    def types(self) -> List[str]:
        return sorted(set(self._core) | set(self._ext))

    def core_types(self) -> List[str]:
        return sorted(self._core)
