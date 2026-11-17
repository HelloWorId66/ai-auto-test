"""核心库完整性校验与扩展层隔离。

- 发布时生成 MANIFEST.json（每个核心文件的 sha256 和版本）。
- 运行前校验：文件被改动、缺失或多出，都拒绝运行。
- 扩展层只能新增适配器，不能覆盖核心已注册的同名类型。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List

from . import CORE_VERSION

MANIFEST_NAME = "MANIFEST.json"
_PKG_DIR = Path(__file__).resolve().parent


class IntegrityError(Exception):
    pass


def _iter_core_files(pkg_dir: Path) -> List[Path]:
    return sorted(
        p
        for p in pkg_dir.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(pkg_dir: Path = _PKG_DIR) -> Dict[str, object]:
    return {
        "version": CORE_VERSION,
        "files": {str(p.relative_to(pkg_dir)).replace("\\", "/"): _digest(p) for p in _iter_core_files(pkg_dir)},
    }


def write_manifest(pkg_dir: Path = _PKG_DIR) -> Path:
    """仅供维护者发版时调用。"""
    out = pkg_dir / MANIFEST_NAME
    out.write_text(json.dumps(build_manifest(pkg_dir), indent=2, sort_keys=True), encoding="utf-8")
    return out


def verify_integrity(pkg_dir: Path = _PKG_DIR) -> None:
    mf = pkg_dir / MANIFEST_NAME
    if not mf.is_file():
        raise IntegrityError("缺少 MANIFEST.json，核心库未经发布，拒绝运行")
    expected = json.loads(mf.read_text(encoding="utf-8"))
    if expected.get("version") != CORE_VERSION:
        raise IntegrityError(f"版本不一致：清单 {expected.get('version')}，代码 {CORE_VERSION}")
    actual = build_manifest(pkg_dir)["files"]
    exp_files: Dict[str, str] = expected.get("files", {})
    problems: List[str] = []
    for name, h in exp_files.items():
        if name not in actual:
            problems.append(f"缺失：{name}")
        elif actual[name] != h:
            problems.append(f"被改动：{name}")
    for name in actual:
        if name not in exp_files:
            problems.append(f"多出：{name}")
    if problems:
        raise IntegrityError("；".join(problems) + "。引擎文件不能改：缺控件或动作请在工作区 extensions/ 里补；"
                             "不是有意改动的话，请重新安装技能")
