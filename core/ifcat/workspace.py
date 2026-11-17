"""工作区：一个项目（客户/环境组）自己的配置、场景、状态模型、探针、扩展和运行结果。

框架（本包）与工作区分开：新增业务、新增场景只在工作区里做，不改框架，框架才能保持稳定。
工作区根目录有 workspace.yaml（可入库，不含机器路径和口令）；本机特有的内容（表单定义目录等）
写在 workspace.local.yaml（不入库），内容覆盖 workspace.yaml。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from . import CORE_VERSION

WORKSPACE_FILE = "workspace.yaml"
LOCAL_FILE = "workspace.local.yaml"
ENV_VAR = "IFCAT_WORKSPACE"
DESIGN_FILE = "用例设计.yaml"  # 和场景文件放在同一个功能目录里，但它不是场景，不被引擎执行
FORMS_SNAPSHOT_DIR = "knowledge/forms"  # 表单定义快照，随工作区入库，运行期只读这里，不依赖产品源码


class WorkspaceError(Exception):
    pass


@dataclass
class Workspace:
    root: Path
    project: str
    form_dirs: List[Path] = field(default_factory=list)
    bills: List[Path] = field(default_factory=list)
    probes: List[Path] = field(default_factory=list)
    default_env: str = ""

    @property
    def scenarios_dir(self) -> Path:
        return self.root / "scenarios"

    @property
    def extensions_dir(self) -> Path:
        return self.root / "extensions"

    @property
    def results_dir(self) -> Path:
        return self.root / "results"

    @property
    def forms_dir(self) -> Path:
        return self.root / FORMS_SNAPSHOT_DIR

    @property
    def reviews_dir(self) -> Path:
        return self.root / "reviews"

    def env_config(self, env: str) -> Path:
        p = self.root / "config" / "local" / f"{env}.yaml"
        if not p.is_file():
            raise WorkspaceError(f"找不到环境配置：{p}（复制同目录的 dev.yaml.example 后填写）")
        return p

    def envs(self) -> List[str]:
        d = self.root / "config" / "local"
        return sorted(p.stem for p in d.glob("*.yaml")) if d.is_dir() else []

    def resolve_scenario(self, target: str) -> Path:
        """接受绝对路径、相对工作区的路径，或场景 id/文件名（在 scenarios 下按名字找，重名报错）。"""
        for cand in (Path(target), self.root / target, self.scenarios_dir / target):
            if cand.is_file():
                return cand
        names = {target, f"{target}.yaml"}
        hits = [p for p in self.scenario_files() if p.name in names or p.stem == target]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise WorkspaceError(f"场景 {target} 有多个同名文件：{[str(h) for h in hits]}")
        raise WorkspaceError(f"找不到场景：{target}")

    def scenario_files(self) -> List[Path]:
        return sorted(p for p in self.scenarios_dir.rglob("*.yaml")
                      if not p.name.endswith(".review.yaml") and p.name != DESIGN_FILE)


def _expand(raw: Any, base: Path) -> List[Path]:
    out = []
    for item in raw or []:
        p = Path(os.path.expandvars(os.path.expanduser(str(item))))
        out.append(p if p.is_absolute() else base / p)
    return out


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise WorkspaceError(f"不是有效的 YAML：{path}") from exc
    if not isinstance(data, dict):
        raise WorkspaceError(f"顶层必须是键值结构：{path}")
    return data


def find_root(explicit: Optional[str] = None, start: Optional[Path] = None) -> Path:
    raw = explicit or os.environ.get(ENV_VAR)
    if raw:
        root = Path(raw).expanduser().resolve()
        if not (root / WORKSPACE_FILE).is_file():
            raise WorkspaceError(f"{root} 不是工作区（缺少 {WORKSPACE_FILE}）")
        return root
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / WORKSPACE_FILE).is_file():
            return d
    raise WorkspaceError(f"没有找到工作区：用 --workspace 指定，或设置环境变量 {ENV_VAR}，或在工作区目录内运行")


def _version(text: str) -> Tuple[int, ...]:
    try:
        return tuple(int(p) for p in text.strip().split("."))
    except ValueError as exc:
        raise WorkspaceError(f"版本号写法不对：{text!r}（应为 0.2.0 这样的数字）") from exc


def load_workspace(explicit: Optional[str] = None, start: Optional[Path] = None) -> Workspace:
    root = find_root(explicit, start)
    raw = _read(root / WORKSPACE_FILE)
    local = root / LOCAL_FILE
    if local.is_file():
        raw.update({k: v for k, v in _read(local).items() if v not in (None, [], "")})
    if not raw.get("project"):
        raise WorkspaceError(f"{WORKSPACE_FILE} 缺少 project")
    need = str(raw.get("framework_min_version") or "")
    if need and _version(need) > _version(CORE_VERSION):
        raise WorkspaceError(f"工作区要求框架版本不低于 {need}，本机框架是 {CORE_VERSION}，请先更新框架")
    return Workspace(
        root=root,
        project=str(raw["project"]),
        form_dirs=[root / FORMS_SNAPSHOT_DIR, *_expand(raw.get("form_dirs"), root)],
        bills=_expand(raw.get("bills"), root),
        probes=_expand(raw.get("probes"), root),
        default_env=str(raw.get("default_env") or ""),
    )
