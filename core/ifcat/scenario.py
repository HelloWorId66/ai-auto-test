"""场景即数据。

业务场景是一份结构化 YAML：业务语言的说明 + 机器可执行的动作。运行器直接解释执行，
不生成任何脚本代码，所以不存在「需要审代码」的环节。业务人员审的是由它渲染出的文字版。

增量需求用 extends 表达：继承基线场景，在指定步骤后插入新步骤或改数据，
这样「先跑受影响的主线，再加新字段的检查点」不需要复制整份场景。
"""
from __future__ import annotations

import copy
import re
from datetime import date, timedelta
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .adapters import AdapterRegistry
from .meta import FormMeta

# 动作名 -> 必填参数
STEP_SPECS: Dict[str, List[str]] = {
    "open": ["form"],
    "fill": ["form", "values"],
    "fill_grid": ["form", "grid", "rows"],
    "save": ["form"],
    "submit": ["form"],
    "approve": ["bill"],
    "reject": ["bill"],
    "edit": ["form"],
    "open_todo": ["bill", "form"],
    "submit_with_warning": ["form", "warning", "then"],
    "approve_blocked": ["bill", "message"],
    "expect_visible": ["form", "label", "visible"],
    "pick_record": ["form", "find"],
    "expect_query": ["form", "conditions"],
    "expect_not_listed": ["form", "find"],
    "capture_field": ["form", "label", "name"],
    "capture_db": ["flow", "key", "column", "name"],
    "expect_flow_completed": ["bill"],
    "expect_field": ["form", "label", "expected"],
    "expect_grid": ["form", "grid", "rows"],
    "expect_db_status": ["flow", "key", "state"],
    "expect_db_result": ["flow", "result", "where"],
    "expect_db_record": ["flow", "key", "table"],
}
# 算业务检查点的动作
CHECKPOINT_STEPS = {"expect_flow_completed", "expect_field", "expect_visible", "submit_with_warning", "approve_blocked", "expect_grid", "expect_db_status", "expect_db_result", "expect_db_record", "expect_query", "expect_not_listed"}

_VAR = re.compile(r"\$\{([A-Za-z0-9_.+:\-\u4e00-\u9fff]+)\}")
_DATE = re.compile(r"today(?:([+-])(\d+)([dm]?))?(:compact)?")


class ScenarioError(Exception):
    pass


@dataclass
class Step:
    id: str
    do: str
    text: str
    args: Dict[str, Any] = field(default_factory=dict)
    role: Optional[str] = None


@dataclass
class Scenario:
    id: str
    title: str
    module: str
    steps: List[Step]
    data: Dict[str, Any] = field(default_factory=dict)
    roles: Dict[str, str] = field(default_factory=dict)  # 角色代号 -> 业务名称
    preconditions: List[str] = field(default_factory=list)
    requirement: str = ""  # 对应的需求编号，增量场景填写
    extends: str = ""
    goal: str = ""  # 这个场景要保证的业务目的，一两句话
    source: List[str] = field(default_factory=list)  # 依据：需求、设计、禅道用例、实际界面观察等
    unconfirmed: List[str] = field(default_factory=list)  # 还没有证据的内容，审核页会标红请业务确认
    labels: Dict[str, str] = field(default_factory=dict)  # 技术字段名 -> 业务名称，仅用于审核页和报告显示
    feature: str = ""  # 所属功能，如「企业定存存入」；一个功能下可以有多个场景。不填则取所在目录名
    kind: str = "主流程"  # 主流程 / 核心异常 / 其他，审核页用来说明覆盖面


def _parse_step(raw: Dict[str, Any], idx: int) -> Step:
    if not isinstance(raw, dict):
        raise ScenarioError(f"第 {idx + 1} 步不是键值结构")
    do = raw.get("do")
    if do not in STEP_SPECS:
        raise ScenarioError(f"第 {idx + 1} 步动作 {do!r} 不存在，可用：{sorted(STEP_SPECS)}")
    return Step(
        id=str(raw.get("id") or f"s{idx + 1}"),
        do=do,
        text=str(raw.get("说明") or raw.get("text") or ""),
        args=dict(raw.get("args") or {}),
        role=raw.get("as"),
    )


def parse_scenario(raw: Dict[str, Any]) -> Scenario:
    if not isinstance(raw, dict):
        raise ScenarioError("场景必须是键值结构")
    for key in ("id", "title", "module"):
        if not raw.get(key):
            raise ScenarioError(f"场景缺少 {key}")
    steps = [_parse_step(s, i) for i, s in enumerate(raw.get("steps") or [])]
    seen = set()
    for s in steps:
        if s.id in seen:
            raise ScenarioError(f"步骤 id 重复：{s.id}")
        seen.add(s.id)
    return Scenario(
        id=str(raw["id"]), title=str(raw["title"]), module=str(raw["module"]), steps=steps,
        data=dict(raw.get("data") or {}), roles=dict(raw.get("roles") or {}),
        preconditions=list(raw.get("preconditions") or []),
        requirement=str(raw.get("requirement") or ""), extends=str(raw.get("extends") or ""),
        goal=str(raw.get("goal") or ""), source=list(raw.get("source") or []),
        unconfirmed=list(raw.get("unconfirmed") or []), labels=dict(raw.get("labels") or {}),
        feature=str(raw.get("feature") or ""), kind=str(raw.get("kind") or "主流程"),
    )


def _read(path: Path) -> Dict[str, Any]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ScenarioError(f"场景不是有效的 YAML：{path}") from exc


def _set_path(data: Dict[str, Any], dotted: str, value: Any) -> None:
    keys = dotted.split(".")
    cur = data
    for k in keys[:-1]:
        cur = cur.setdefault(k, {})
    cur[keys[-1]] = value


def load_scenario(path: str | Path, search_dir: Optional[Path] = None, _chain: Optional[List[str]] = None) -> Scenario:
    """加载场景；有 extends 时先加载基线，再应用增量。基线在同目录或 search_dir 下按 <id>.yaml 查找。"""
    p = Path(path)
    raw = _read(p)
    chain = list(_chain or [])
    base_id = raw.get("extends")
    if not base_id:
        return _with_feature(parse_scenario(raw), p)
    if base_id in chain or base_id == raw.get("id"):
        raise ScenarioError(f"场景继承出现环：{chain + [raw.get('id'), base_id]}")
    base_path = _find_base(p, str(base_id), search_dir)
    merged = _apply_increment(load_scenario(base_path, search_dir, chain + [str(raw.get("id"))]), raw)
    if raw.get("feature"):
        merged.feature = str(raw["feature"])
    if raw.get("kind"):
        merged.kind = str(raw["kind"])
    return _with_feature(merged, p)


def _find_base(path: Path, base_id: str, search_dir: Optional[Path]) -> Path:
    """基线场景：先找同目录的 <id>.yaml；找不到就在本模块目录（scenarios/<模块>/）下按场景 id 找，基线可以在别的功能目录里。"""
    direct = (search_dir or path.parent) / f"{base_id}.yaml"
    if direct.is_file():
        return direct
    roots = [search_dir] if search_dir else [path.parent, path.parent.parent]
    for root in roots:
        for cand in sorted(Path(root).rglob("*.yaml")):
            if cand == path or cand.name.endswith(".review.yaml"):
                continue
            try:
                if str(_read(cand).get("id")) == base_id:
                    return cand
            except ScenarioError:
                continue
    raise ScenarioError(f"找不到基线场景 {base_id}（在 {path.parent} 及其上一级目录下按场景 id 查找）")


def _with_feature(sc: Scenario, path: Path) -> Scenario:
    """scenarios/<模块>/<功能>/<场景>.yaml：没写 feature 时取目录名；两层目录（目录名就是模块）视为没有功能分组。"""
    if not sc.feature and path.parent.name.upper() != sc.module.upper():
        sc.feature = path.parent.name
    return sc


def _apply_increment(base: Scenario, inc: Dict[str, Any]) -> Scenario:
    sc = copy.deepcopy(base)
    for key in ("id", "title", "module"):
        if not inc.get(key):
            raise ScenarioError(f"增量场景缺少 {key}")
    sc.id, sc.title, sc.module = str(inc["id"]), str(inc["title"]), str(inc["module"])
    sc.extends = str(inc["extends"])
    sc.requirement = str(inc.get("requirement") or "")
    sc.roles.update(inc.get("roles") or {})
    sc.preconditions += list(inc.get("preconditions") or [])
    if inc.get("goal"):
        sc.goal = str(inc["goal"])
    sc.source += list(inc.get("source") or [])
    sc.unconfirmed += list(inc.get("unconfirmed") or [])
    sc.labels.update(inc.get("labels") or {})
    sc.data.update(inc.get("data") or {})  # 增量场景新增的数据；要改基线已有数据用 set
    for dotted, value in (inc.get("set") or {}).items():
        _set_path(sc.data, dotted.removeprefix("data."), value)
    ids = [s.id for s in sc.steps]
    for rid in inc.get("remove_steps") or []:
        if rid not in ids:
            raise ScenarioError(f"remove_steps 里的步骤 {rid} 在基线里不存在")
        sc.steps = [s for s in sc.steps if s.id != rid]
    for after_id, new_steps in (inc.get("add_steps_after") or {}).items():
        ids = [s.id for s in sc.steps]
        if after_id not in ids:
            raise ScenarioError(f"add_steps_after 里的步骤 {after_id} 在基线里不存在")
        pos = ids.index(after_id) + 1
        parsed = [_parse_step(s, i) for i, s in enumerate(new_steps)]
        for s in parsed:
            if s.id in ids:
                raise ScenarioError(f"新增步骤 id 与基线重复：{s.id}")
        sc.steps[pos:pos] = parsed
    return sc


# --- 变量 ---
def relative_date(sign: Optional[str], n: Optional[str], unit: Optional[str], today: Optional[date] = None) -> str:
    """${today}、${today+365}（天）、${today+12m}（月）、${today-1}：按运行当天推算，格式 YYYY-MM-DD；
    后面加 :compact（如 ${today+12m:compact}）得到 YYYYMMDD，数据库里的日期列通常存这种格式。
    加月时日数超出当月天数则取当月最后一天。"""
    base = today or date.today()
    if not n:
        return base.isoformat()
    k = int(n) * (1 if sign == "+" else -1)
    if unit == "m":
        total = base.year * 12 + base.month - 1 + k
        y, mo = divmod(total, 12)
        mo += 1
        last = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1)).day
        return date(y, mo, min(base.day, last)).isoformat()
    return (base + timedelta(days=k)).isoformat()


def resolve(value: Any, ctx: Dict[str, Any]) -> Any:
    """把 ${data.x}、${captured.y} 替换成实际值；整个字符串就是一个变量时保留原类型。"""
    if isinstance(value, dict):
        return {k: resolve(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, ctx) for v in value]
    if not isinstance(value, str):
        return value

    def lookup(name: str) -> Any:
        m = _DATE.fullmatch(name)
        if m:
            out = relative_date(m.group(1), m.group(2), m.group(3))
            return out.replace("-", "") if m.group(4) else out
        cur: Any = ctx
        for part in name.split("."):
            if not isinstance(cur, dict) or part not in cur:
                raise ScenarioError(f"变量 ${{{name}}} 没有值")
            cur = cur[part]
        return cur

    whole = _VAR.fullmatch(value)
    if whole:
        return lookup(whole.group(1))
    return _VAR.sub(lambda m: str(lookup(m.group(1))), value)


def resolve_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """场景数据里的日期变量（${today+12m} 等）在运行时换成当天推算的日期；其他变量原样保留。"""

    def one(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: one(x) for k, x in v.items()}
        if isinstance(v, list):
            return [one(x) for x in v]
        if isinstance(v, str):
            return _VAR.sub(lambda m: str(resolve(m.group(0), {})) if _DATE.fullmatch(m.group(1)) else m.group(0), v)
        return v

    return one(data)


def describe_date_macro(text: str) -> str:
    """给审核页用：把 ${today+12m} 这类写法说成业务话。"""

    def desc(m: "re.Match[str]") -> str:
        d = _DATE.fullmatch(m.group(1))
        if not d:
            return m.group(0)
        if not d.group(2):
            return "运行当天"
        n, unit = d.group(2), d.group(3)
        word = "个月" if unit == "m" else "天"
        return f"运行当天{'后' if d.group(1) == '+' else '前'} {n} {word}"

    return _VAR.sub(desc, text)


# --- 离线校验：用表单元数据和状态模型检查场景，不碰浏览器 ---
@dataclass
class Issue:
    level: str  # error 或 warning
    step: str
    message: str


def validate_scenario(sc: Scenario, forms: Dict[str, FormMeta], registry: Optional[AdapterRegistry] = None,
                      bills: Optional[Dict[str, Any]] = None) -> List[Issue]:
    issues: List[Issue] = []
    err = lambda s, m: issues.append(Issue("error", s, m))
    warn = lambda s, m: issues.append(Issue("warning", s, m))

    for s in sc.steps:
        missing = [k for k in STEP_SPECS[s.do] if k not in s.args]
        if missing:
            err(s.id, f"动作 {s.do} 缺少参数：{missing}")
        if s.role and s.role not in sc.roles:
            err(s.id, f"角色 {s.role} 没有在 roles 里声明")

    checkpoints = [s for s in sc.steps if s.do in CHECKPOINT_STEPS]
    if not checkpoints:
        err("-", "场景没有任何业务检查点（expect_*），不算有效场景")

    filled: Dict[str, set] = {}
    saved_forms: set = set()
    for s in sc.steps:
        a = s.args
        form_id = a.get("form")
        if form_id is not None and not str(form_id).startswith("${"):
            form = forms.get(form_id)
            if form is None:
                err(s.id, f"没有加载表单 {form_id} 的元数据")
                continue
            if s.do in ("fill", "expect_field", "capture_field", "expect_visible"):
                labels = list((a.get("values") or {}).keys()) if s.do == "fill" else [a.get("label")]
                for label in labels:
                    hits = form.field_by_label(label, a.get("within"))
                    if not hits:
                        err(s.id, f"表单 {form_id} 里没有字段「{label}」")
                        continue
                    if len(hits) > 1 and "occurrence" not in a and not a.get("within"):
                        warn(s.id, f"字段「{label}」在表单里出现 {len(hits)} 次，运行时取页面上可见的那个；"
                                   "若同时可见会阻塞，请用 within 或 occurrence 指定")
                    if len(hits) > 1 and "occurrence" in a and int(a["occurrence"]) >= len(hits):
                        err(s.id, f"字段「{label}」只有 {len(hits)} 个，没有第 {int(a['occurrence']) + 1} 个")
                    f = hits[min(int(a.get("occurrence", 0)), len(hits) - 1)]
                    if registry is not None and f.type not in registry.types():
                        warn(s.id, f"字段「{label}」是 {f.type} 组件，目前没有适配器，运行会阻塞")
                    if s.do == "fill":
                        if not f.editable:
                            warn(s.id, f"字段「{label}」在表单里是只读的，填写可能无效")
                        filled.setdefault(form_id, set()).add(f.key)
            if s.do in ("fill_grid", "expect_grid"):
                if not any(g.key == a.get("grid") for g in form.grids):
                    err(s.id, f"表单 {form_id} 里没有网格 {a.get('grid')}（可用：{[g.key for g in form.grids]}）")
            if s.do == "save":
                saved_forms.add(form_id)
                required = [f for f in form.fields if f.required and f.editable and f.key not in filled.get(form_id, set())]
                if required:
                    warn(s.id, "保存前这些必填字段没有填写：" + "、".join(f.label for f in required))
        if s.do.startswith("expect_db") and bills is not None and a.get("flow") not in bills:
            err(s.id, f"项目配置里没有流程 {a.get('flow')} 的状态模型")
        if s.do == "expect_db_status" and bills is not None and a.get("flow") in bills:
            try:
                state = str(a.get("state"))
                bills[a["flow"]].state_value(state[4:] if state.startswith("not:") else state)
            except Exception as exc:
                err(s.id, str(exc))
        if s.do == "expect_db_record" and bills is not None and a.get("flow") in bills:
            m = bills[a["flow"]]
            if a.get("table") != "head" and a.get("table") not in m.results:
                err(s.id, f"流程 {a['flow']} 没有结果表 {a.get('table')}（可用：head、{'、'.join(m.results)}）")
    return issues


# --- 渲染成业务人员审的文字版 ---
_DO_TEXT = {
    "open": "打开", "fill": "填写", "fill_grid": "填写表格", "save": "保存", "submit": "提交审批",
    "approve": "同意", "reject": "退回", "pick_record": "选择记录", "expect_query": "检查查询结果", "expect_not_listed": "检查选不到", "capture_field": "记录字段值", "capture_db": "从数据库记录单据信息",
    "expect_field": "检查界面", "expect_flow_completed": "检查流程办结", "expect_grid": "检查表格", "expect_db_status": "检查单据状态",
    "expect_db_result": "检查业务结果", "expect_db_record": "检查数据库记录", "edit": "点编辑修改", "open_todo": "在待办里打开单据",
    "submit_with_warning": "提交并检查提示", "approve_blocked": "同意被拦截", "expect_visible": "检查是否显示",
}


def render_markdown(sc: Scenario) -> str:
    out = [f"# {sc.title}", ""]
    if sc.requirement:
        out.append(f"对应需求：{sc.requirement}")
    if sc.extends:
        out.append(f"基于基线场景：{sc.extends}（本场景是增量，基线步骤已一并列出）")
    out += ["", "## 前提"] + ([f"- {p}" for p in sc.preconditions] or ["- 无"])
    if sc.roles:
        out += ["", "## 角色"] + [f"- {k}：{v}" for k, v in sc.roles.items()]
    out += ["", "## 步骤与检查点", ""]
    for i, s in enumerate(sc.steps, 1):
        who = f"（{sc.roles.get(s.role, s.role)}）" if s.role else ""
        mark = "【检查点】" if s.do in CHECKPOINT_STEPS else ""
        out.append(f"{i}. {mark}{who}{s.text or _DO_TEXT[s.do]}")
    out += ["", "业务审核只需要看：步骤是否是真实用户会走的，检查点是否是真正关心的。"]
    return "\n".join(out) + "\n"
