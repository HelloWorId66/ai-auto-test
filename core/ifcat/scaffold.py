"""ifc init：生成工作区骨架，并把智能体规程（SKILL）放进工作区。

重复执行是安全的：已存在的文件不覆盖；只有框架拥有的智能体规程文件（.claude/skills/ifc-autotest/）每次同步最新版。
本机路径（框架位置）只写进不入库的 workspace.local.yaml。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List

import yaml

from .workspace import LOCAL_FILE, WORKSPACE_FILE

FRAMEWORK_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = FRAMEWORK_ROOT / "templates" / "workspace"
SKILL_SRC = FRAMEWORK_ROOT / "skills" / "ifc-autotest"
METHOD_SRC = FRAMEWORK_ROOT / "docs" / "组件识别方法论.md"
SKILL_DST = Path(".claude") / "skills" / "ifc-autotest"

_DIRS = ["scenarios", "reviews", "results", "extensions", "bills", "probes",
         "knowledge/modules", "knowledge/requirements", "knowledge/exploration", "knowledge/forms", "config/local"]


class InitError(Exception):
    pass


def _fill(text: str, project: str) -> str:
    return text.replace("{project}", project)


def _write_new(path: Path, text: str, created: List[str], root: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    created.append(str(path.relative_to(root)))


def sync_skill(root: Path) -> List[str]:
    """把框架里的智能体规程同步进工作区，返回写入的文件。"""
    out: List[str] = []
    dst = root / SKILL_DST
    dst.mkdir(parents=True, exist_ok=True)
    for src, name in ((SKILL_SRC / "SKILL.md", "SKILL.md"), (METHOD_SRC, METHOD_SRC.name)):
        if not src.is_file():
            raise InitError(f"框架里缺少 {src.name}，框架目录不完整")
        target = dst / name
        text = src.read_text(encoding="utf-8")
        if not target.is_file() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8")
            out.append(str((SKILL_DST / name)))
    return out


def init_workspace(target: str | Path, project: str, refresh: bool = False) -> List[str]:
    root = Path(target).expanduser().resolve()
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", project or ""):
        raise InitError("项目名只能用字母、数字、下划线、连字符，如 acme、pilot")
    if refresh:
        if not (root / WORKSPACE_FILE).is_file():
            raise InitError(f"{root} 不是工作区，不能 --refresh")
        created: List[str] = []
        _write_new(root / "AGENTS.md", _fill((TEMPLATES / "AGENTS.md").read_text(encoding="utf-8"), project), created, root)
        _write_new(root / "CLAUDE.md", "@AGENTS.md\n", created, root)
        return created + sync_skill(root)
    if (root / WORKSPACE_FILE).is_file():
        raise InitError(f"{root} 已经是工作区；只想更新智能体规程请加 --refresh")
    root.mkdir(parents=True, exist_ok=True)
    created: List[str] = []
    for d in _DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "results" / ".gitkeep").touch()
    _write_new(root / WORKSPACE_FILE, _fill((TEMPLATES / "workspace.yaml").read_text(encoding="utf-8"), project), created, root)
    _write_new(root / "README.md", _fill((TEMPLATES / "README.md").read_text(encoding="utf-8"), project), created, root)
    agents = _fill((TEMPLATES / "AGENTS.md").read_text(encoding="utf-8"), project)
    _write_new(root / "AGENTS.md", agents, created, root)
    _write_new(root / "CLAUDE.md", "@AGENTS.md\n", created, root)
    _write_new(root / ".gitignore", (TEMPLATES / "gitignore").read_text(encoding="utf-8"), created, root)
    _write_new(root / "config" / "local" / "dev.yaml.example",
               _fill((TEMPLATES / "env.yaml.example").read_text(encoding="utf-8"), project), created, root)
    _write_new(root / LOCAL_FILE, yaml.safe_dump({"framework": str(FRAMEWORK_ROOT)}, allow_unicode=True), created, root)
    created += sync_skill(root)
    return created
