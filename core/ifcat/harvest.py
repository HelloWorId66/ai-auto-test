"""ifc harvest：把各工作区里临时补的扩展（适配器、动作、数据库方言）汇总成一份归纳清单。

做功能的人在工作区里临时补扩展完成当次工作；归纳、抽象由维护者定期做。本命令给维护者用：
列出每个扩展在哪个工作区、哪个文件、被多少场景引用、运行过多少次、通过多少次，
以及多个工作区都补了的同名扩展（最值得优先并入框架）。只读，不改任何工作区。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from . import actions, dbro
from .adapters import build_default_registry
from .batch import load_candidates
from .extloader import load_extensions
from .workspace import load_workspace

_KIND_TEXT = {"adapter": "控件适配器", "action": "动作", "dialect": "数据库方言"}


@dataclass
class Item:
    kind: str
    name: str
    source: str
    scenarios: int = 0
    runs: int = 0
    passed: int = 0
    last_used: str = ""


@dataclass
class WorkspaceHarvest:
    root: Path
    project: str
    items: List[Item] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _run_stats(results_dir: Path) -> Dict[Tuple[str, str], Tuple[int, int, str]]:
    """（类型, 名称）-> （运行次数, 通过次数, 最近一次时间），来自每次运行落盘的 result.json。"""
    stats: Dict[Tuple[str, str], Tuple[int, int, str]] = {}
    runs = results_dir / "runs"
    for f in sorted(runs.glob("*/*/*/*/result.json")) if runs.is_dir() else []:
        try:
            meta = json.loads(f.read_text(encoding="utf-8")).get("meta", {})
        except (OSError, ValueError):
            continue
        for used in meta.get("extensions_used") or []:
            key = (str(used.get("kind")), str(used.get("name")))
            n, ok, last = stats.get(key, (0, 0, ""))
            stats[key] = (n + 1, ok + (meta.get("final_status") == "passed"), max(last, str(meta.get("finished") or "")))
    return stats


def harvest_workspace(path: str | Path) -> WorkspaceHarvest:
    ws = load_workspace(str(path))
    registry = build_default_registry()
    out = WorkspaceHarvest(ws.root, ws.project, errors=load_extensions(registry, ws.extensions_dir)["errors"])
    items = [Item("adapter", name, src) for name, src in sorted(registry.extension_types().items())]
    items += [Item("action", name, spec.source) for name, spec in sorted(actions.extension_actions().items())]
    items += [Item("dialect", kind, "") for kind in dbro.extension_dialects()]
    cands = [c for c in load_candidates(ws, ws.scenario_files()) if c.scenario is not None]
    stats = _run_stats(ws.results_dir)
    for it in items:
        if it.kind == "action":
            it.scenarios = sum(1 for c in cands if any(s.do == it.name for s in c.scenario.steps))
        it.runs, it.passed, it.last_used = stats.get((it.kind, it.name), (0, 0, ""))
    out.items = items
    return out


def render_markdown(found: List[WorkspaceHarvest], now: datetime | None = None) -> str:
    out = [f"# 扩展归纳清单（{(now or datetime.now()):%Y-%m-%d %H:%M}）", "",
           "各工作区里尚未并入框架的临时扩展。运行次数多、通过率高、多个工作区重复出现的，优先并入框架。", ""]
    seen: Dict[Tuple[str, str], List[str]] = {}
    for h in found:
        for it in h.items:
            seen.setdefault((it.kind, it.name), []).append(h.project)
    repeated = {k: v for k, v in seen.items() if len(v) > 1}
    if repeated:
        out += ["## 多个工作区重复出现", ""]
        out += [f"- {_KIND_TEXT[kind]} `{name}`：{'、'.join(projects)}" for (kind, name), projects in sorted(repeated.items())]
        out.append("")
    for h in found:
        out += [f"## 工作区 {h.project}", "", f"目录：`{h.root}`", ""]
        if not h.items:
            out += ["没有扩展。", ""]
        else:
            out += ["| 类型 | 名称 | 文件 | 引用场景 | 运行次数 | 通过次数 | 最近使用 |", "|---|---|---|---|---|---|---|"]
            for it in h.items:
                refs = str(it.scenarios) if it.kind == "action" else "—"
                out.append(f"| {_KIND_TEXT[it.kind]} | `{it.name}` | {it.source or '—'} | {refs} | {it.runs} | {it.passed} | {it.last_used or '—'} |")
            out.append("")
        if h.errors:
            out += ["加载失败的扩展文件：", ""] + [f"- {e}" for e in h.errors] + [""]
    return "\n".join(out)
