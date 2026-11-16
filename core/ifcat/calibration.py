"""选择器标定记录与运行前自检。

适配器的选择器来自源码阅读，是否适用取决于具体环境和产品版本。
标定结果因此按「产品版本、项目、环境、界面语言」分别记录，并绑定核心库版本；
场景运行前用 CalibrationGate 检查用到的组件类型，没有有效标定就不放行。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import yaml

from . import CORE_VERSION
from .adapters import AdapterRegistry
from .meta import FormMeta
from .result import Status, StepResult

DEFAULT_MAX_AGE_DAYS = 30  # 超过这个天数视为过期，需要重标；可在项目配置里调整
_UNSAFE = re.compile(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]+")


def _slug(text: str) -> str:
    return _UNSAFE.sub("_", text).strip("_") or "x"


@dataclass(frozen=True)
class CalibrationKey:
    product_version: str
    project: str
    env_name: str
    # 界面语言不同，按钮和选项文字不同，同一套适配器在另一种语言下未必可用，所以标定按语言分开记
    locale: str = ""

    def path(self, results_root: str | Path) -> Path:
        name = _slug(self.product_version) + (f"__{_slug(self.locale)}" if self.locale else "")
        return Path(results_root) / "calibration" / _slug(self.project) / _slug(self.env_name) / f"{name}.json"


@dataclass
class CalibrationRecord:
    type_name: str
    passed: bool
    checked_at: str
    core_version: str
    detail: str = ""


class CalibrationStore:
    def __init__(self, results_root: str | Path, key: CalibrationKey):
        self.key = key
        self._path = key.path(results_root)
        self._records: Dict[str, CalibrationRecord] = {}
        if self._path.is_file():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for r in raw.get("records", []):
                self._records[r["type_name"]] = CalibrationRecord(**r)

    def get(self, type_name: str) -> Optional[CalibrationRecord]:
        return self._records.get(type_name)

    def put(self, rec: CalibrationRecord) -> None:
        self._records[rec.type_name] = rec

    def save(self) -> Path:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"key": asdict(self.key), "records": [asdict(r) for r in self._records.values()]}
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._path

    def all(self) -> List[CalibrationRecord]:
        return sorted(self._records.values(), key=lambda r: r.type_name)


class CalibrationGate:
    def __init__(self, store: CalibrationStore, max_age_days: int = DEFAULT_MAX_AGE_DAYS,
                 core_version: str = CORE_VERSION, now: Callable[[], datetime] = datetime.now):
        self.store = store
        self.max_age = timedelta(days=max_age_days)
        self.core_version = core_version
        self._now = now

    def problem(self, type_name: str) -> Optional[str]:
        """返回不能放行的原因；可以放行返回 None。"""
        rec = self.store.get(type_name)
        k = self.store.key
        where = f"产品版本 {k.product_version}、项目 {k.project}、环境 {k.env_name}" + (f"、语言 {k.locale}" if k.locale else "")
        if rec is None:
            return f"组件 {type_name} 在 {where} 上没有标定记录，请先运行标定"
        if not rec.passed:
            return f"组件 {type_name} 在 {where} 上标定失败（{rec.detail}），不能使用"
        if rec.core_version != self.core_version:
            return f"组件 {type_name} 的标定针对核心库 {rec.core_version}，当前是 {self.core_version}，请重新标定"
        age = self._now() - datetime.fromisoformat(rec.checked_at)
        if age > self.max_age:
            return f"组件 {type_name} 的标定已过期（{age.days} 天前），请重新标定"
        return None


@dataclass
class PreflightReport:
    types_used: List[str]
    no_adapter: List[str] = field(default_factory=list)
    problems: Dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.no_adapter and not self.problems

    def message(self) -> str:
        parts = []
        if self.no_adapter:
            parts.append("没有适配器：" + "、".join(self.no_adapter))
        parts.extend(self.problems.values())
        return "；".join(parts)


def preflight(forms: Iterable[FormMeta], registry: AdapterRegistry, gate: CalibrationGate,
              only_labels: Optional[Dict[str, Iterable[str]]] = None) -> PreflightReport:
    """检查表单里用到的组件类型是否都有适配器和有效标定。

    only_labels：{form_id: 场景实际要用的字段标签}。给出时只检查这些字段的类型，
    不给就检查整张表单的所有字段（偏保守）。
    """
    used: set[str] = set()
    for form in forms:
        wanted = None if only_labels is None else set(only_labels.get(form.form_id, ()))
        for f in form.fields:
            if wanted is None or f.label in wanted:
                used.add(f.type)
    report = PreflightReport(types_used=sorted(used))
    known = set(registry.types())
    for t in report.types_used:
        if t not in known:
            report.no_adapter.append(t)
            continue
        p = gate.problem(t)
        if p:
            report.problems[t] = p
    return report


@dataclass
class Probe:
    """一条标定探针：在真实页面上对某类组件填一个值再读回，验证适配器可用。"""
    type_name: str
    form_id: str
    label: str
    value: Any
    expect: Any = None
    within: Optional[str] = None
    occurrence: Optional[int] = None
    # 网格单元格探针：type 写成 GridCell:<编辑器码>，label 是列名，需给出 grid 和 add_button
    grid: Optional[str] = None
    add_button: str = ""
    existing: bool = False  # true：不新增行，改系统已带出的第一行
    # read：只读字段没法填，只验证能定位并读出值（detail 里标明「仅验证读取」）
    read_only: bool = False


def load_probes(path: str | Path) -> List[Probe]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [Probe(type_name=p["type"], form_id=p["form"], label=p["label"], value=p.get("value"),
                  expect=p.get("expect"), within=p.get("within"), occurrence=int(p["occurrence"]) if "occurrence" in p else None,
                  grid=p.get("grid"), add_button=p.get("add_button", ""), existing=bool(p.get("existing", False)),
                  read_only=bool(p.get("read_only", False)), )
            for p in raw.get("probes", [])]


def run_calibration(prim: Any, probes: Iterable[Probe], store: CalibrationStore,
                    open_form: Callable[[str], Any],
                    now: Callable[[], datetime] = datetime.now) -> List[CalibrationRecord]:
    """逐个探针标定。open_form 由调用方提供，负责把页面带到指定表单。

    同一组件类型只要有一个探针失败就记为失败；探针里的失败原因保留在 detail。
    """
    by_type: Dict[str, CalibrationRecord] = {}
    for p in probes:
        try:
            open_form(p.form_id)
            if p.read_only:
                prim.read_field(p.form_id, p.label, p.within, p.occurrence)
                checked = StepResult.passed("仅验证读取")
                filled = checked
            elif p.grid:  # fill_grid 自带读回比较
                checked = prim.fill_grid(p.form_id, p.grid, [{p.label: p.value}], p.add_button, existing=p.existing)
                filled = checked
            else:
                filled = prim.fill(p.form_id, {p.label: p.value}, within=p.within, occurrence=p.occurrence)
            if p.grid or p.read_only:
                pass
            elif filled.status is Status.PASSED:
                expect = p.value if p.expect is None else p.expect
                checked = prim.expect_field(p.form_id, p.label, expect, within=p.within, occurrence=p.occurrence)
            else:
                checked = filled
            ok, detail = checked.status is Status.PASSED, checked.message
        except Exception as exc:
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        prev = by_type.get(p.type_name)
        if prev is not None and not prev.passed:
            continue  # 已失败，保留首个失败原因
        by_type[p.type_name] = CalibrationRecord(
            p.type_name, ok, now().isoformat(timespec="seconds"), CORE_VERSION, "" if ok else detail
        )
    for rec in by_type.values():
        store.put(rec)
    store.save()
    return list(by_type.values())
