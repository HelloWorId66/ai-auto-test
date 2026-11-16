"""本地扩展层加载：扫描扩展目录里的 .py，把其中的 Adapter 子类注册为扩展适配器。

扩展只能新增类型；与核心同名会被注册表拒绝。单个扩展文件出错不影响其他文件，
错误随结果返回，由运行入口显示，不静默吞掉。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Dict, List

from .adapters import Adapter, AdapterRegistry


def load_extensions(registry: AdapterRegistry, ext_dir: str | Path) -> Dict[str, List[str]]:
    loaded: List[str] = []
    errors: List[str] = []
    d = Path(ext_dir)
    if not d.is_dir():
        return {"loaded": loaded, "errors": errors}
    for path in sorted(d.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"ifc_ext_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            classes = [c for c in vars(mod).values()
                       if isinstance(c, type) and issubclass(c, Adapter) and c is not Adapter
                       and c.__module__ == mod.__name__]
            for cls in classes:
                registry.register_extension(cls)
                loaded.append(f"{path.name}:{cls.type_name}")
        except Exception as exc:
            errors.append(f"{path.name}: {type(exc).__name__}: {exc}")
    return {"loaded": loaded, "errors": errors}
