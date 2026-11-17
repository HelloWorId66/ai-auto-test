"""ifc init：生成工作区骨架。

重复执行是安全的：已存在的文件不覆盖。智能体规程随 ifc-autotest 技能分发，不再复制进工作区。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

from . import CORE_VERSION
from .workspace import WORKSPACE_FILE

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = FRAMEWORK_ROOT / "templates" / "workspace"
# 旧版本曾把规程复制到工作区的这个位置；现在规程只随技能分发，这份副本会过期
OLD_SKILL_COPY = Path(".claude") / "skills" / "ifc-autotest"

_DIRS = ["scenarios", "reviews", "results", "extensions", "bills", "probes",
         "knowledge/modules", "knowledge/requirements", "knowledge/exploration", "knowledge/forms", "config/local"]


class InitError(Exception):
    pass


def _fill(text: str, project: str) -> str:
    return text.replace("{project}", project).replace("{framework_version}", CORE_VERSION)


def _write_new(path: Path, text: str, created: List[str], root: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    created.append(str(path.relative_to(root)))


def _template(name: str) -> str:
    src = TEMPLATES / name
    if not src.is_file():
        raise InitError(f"缺少模板 {src}，技能或框架目录不完整，请重新安装")
    return src.read_text(encoding="utf-8")


def old_skill_copy(target: str | Path) -> Path | None:
    p = Path(target).expanduser().resolve() / OLD_SKILL_COPY
    return p if p.is_dir() else None


def init_workspace(target: str | Path, project: str, refresh: bool = False) -> List[str]:
    """refresh：只给已有工作区补上缺少的说明文件，不动任何已有文件。"""
    root = Path(target).expanduser().resolve()
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", project or ""):
        raise InitError("项目名只能用字母、数字、下划线、连字符，如 acme、pilot")
    created: List[str] = []
    if refresh:
        if not (root / WORKSPACE_FILE).is_file():
            raise InitError(f"{root} 不是工作区，不能 --refresh")
    else:
        if (root / WORKSPACE_FILE).is_file():
            raise InitError(f"{root} 已经是工作区；只想补上缺少的说明文件请加 --refresh")
        root.mkdir(parents=True, exist_ok=True)
        for d in _DIRS:
            (root / d).mkdir(parents=True, exist_ok=True)
        (root / "results" / ".gitkeep").touch()
        _write_new(root / WORKSPACE_FILE, _fill(_template("workspace.yaml"), project), created, root)
        _write_new(root / "README.md", _fill(_template("README.md"), project), created, root)
        _write_new(root / ".gitignore", _template("gitignore"), created, root)
        _write_new(root / "config" / "local" / "dev.yaml.example", _fill(_template("env.yaml.example"), project), created, root)
        _write_new(root / "probes" / "标定探针示例.yaml", _template("probes.example.yaml"), created, root)
    _write_new(root / "AGENTS.md", _fill(_template("AGENTS.md"), project), created, root)
    _write_new(root / "CLAUDE.md", "@AGENTS.md\n", created, root)
    return created
