"""离线解析 PanUI 表单 JSON（ReactFormSpace/<FormID>.json）。

字段全集只来自表单 JSON，不从截图或页面猜测。
结构依据：docs/exploration/02-表单模型.md §3、§7。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class FormMetaError(Exception):
    pass


# 不是业务字段的组件类型；它们可能带 dataSetColID，但不是用户填写的字段
_NON_FIELD_TYPES = {"AGGrid", "Column", "ColumnModel", "FormButton", "GridToolBar"}


@dataclass
class FieldMeta:
    key: str
    type: str
    label: str
    dataset_id: str
    column_id: str
    required: bool
    required_check: bool
    editable: bool
    placeholder: str
    mask_key: str
    # 从根到本字段的组件 key 链，用于区分同名标签（如「变更前」「变更后」两栏）
    path: List[str] = field(default_factory=list)
    props: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ButtonMeta:
    key: str
    label: str
    action_key: str
    action_type: str
    path: List[str] = field(default_factory=list)
    # 同样叫「提交」的按钮可能有多个，靠显示条件区分在哪个节点可见
    visible_expression: str = ""
    enable_expression: str = ""
    source: str = "button"


@dataclass
class GridColumnMeta:
    key: str
    header: str
    column_id: str
    editor_type: str
    mask_key: str
    editable: bool
    visible: bool


@dataclass
class GridMeta:
    key: str
    dataset_id: str
    column_model: str
    columns: List[GridColumnMeta]
    path: List[str] = field(default_factory=list)


@dataclass
class FormMeta:
    form_id: str
    name: str
    version: str
    fields: List[FieldMeta]
    buttons: List[ButtonMeta]
    grids: List[GridMeta]
    actions: Dict[str, Dict[str, Any]]
    # 数据集码（已去掉 '!' 前缀） -> 数据集中文名
    datasets: Dict[str, str]
    raw: Dict[str, Any] = field(repr=False, default_factory=dict)

    def field_by_label(self, label: str, within: Optional[str] = None) -> List[FieldMeta]:
        """按标签查字段，可能返回多个；within 为祖先组件 key，用来区分同名标签。"""
        hits = [f for f in self.fields if f.label == label]
        if not hits:
            # 设计器里的标签可能与页面上用户看到的不同（例如设计占位文字），允许用组件 key 或数据列名指定
            hits = [f for f in self.fields if label in (f.key, f.column_id)]
        if within is not None:
            hits = [f for f in hits if within in f.path]
        return hits

    def field_by_column(self, dataset_id: str, column_id: str) -> List[FieldMeta]:
        return [f for f in self.fields if f.dataset_id == dataset_id and f.column_id == column_id]

    def button_by_label(self, label: str, action_type: Optional[str] = None) -> List[ButtonMeta]:
        hits = [b for b in self.buttons if b.label == label]
        if action_type is not None:
            hits = [b for b in hits if b.action_type == action_type]
        return hits

    def grid_by_dataset(self, dataset_id: str) -> List[GridMeta]:
        return [g for g in self.grids if g.dataset_id == dataset_id]


def _children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    return node.get("children") or node.get("components") or []


def _walk(nodes: Iterable[Dict[str, Any]], path: List[str]):
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node, path
        yield from _walk(_children(node), path + [str(node.get("key", ""))])


def _truthy(v: Any, default: bool) -> bool:
    if v is None or v == "":
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("false", "0", "no")


def _strip_bang(table_id: str) -> str:
    return table_id[1:] if table_id.startswith("!") else table_id


def _parse_columns(model: Dict[str, Any]) -> List[GridColumnMeta]:
    cols: List[GridColumnMeta] = []
    for node, _ in _walk(_children(model), []):
        if node.get("type") != "Column":
            continue
        p = node.get("props") or {}
        cols.append(
            GridColumnMeta(
                key=str(node.get("key", "")),
                header=str(p.get("headerText", "")),
                column_id=str(p.get("dataSetColID", "")),
                editor_type=str(p.get("editorType", "")),
                mask_key=str(p.get("maskConfigKey", "")),
                editable=_truthy(p.get("editable"), True),
                visible=_truthy(p.get("visible"), True),
            )
        )
    return cols


def _clean_label(text: Any) -> str:
    return str(text or "").strip().rstrip("：:").strip()


def _sibling_labels(components: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """很多表单不在字段上写标签，而是同一容器里字段前面放一个独立的 FormLabel（textVal）。

    规则：同一容器内，字段取它前面最近一个、自身没有绑定数据列、且文字不是「*」的 FormLabel。
    """
    out: Dict[str, str] = {}
    for node, _ in _walk(components, []):
        pending = ""
        for child in _children(node):
            if not isinstance(child, dict):
                continue
            p = child.get("props") or {}
            if child.get("type") == "FormLabel" and not p.get("dataSetColID"):
                text = _clean_label(p.get("textVal"))
                if text and text != "*":
                    pending = text
            elif p.get("dataSetColID") and pending:
                out[str(child.get("key", ""))] = pending
                pending = ""
    return out


def load_form(data: Dict[str, Any]) -> FormMeta:
    if not isinstance(data, dict) or "components" not in data:
        raise FormMetaError("不是有效的表单 JSON：缺少 components")

    actions = {
        str(a.get("key")): {"type": a.get("type"), "props": a.get("props") or {}}
        for a in data.get("actionComps") or []
        if isinstance(a, dict)
    }
    # 列模型常被设计器放进 Folder 分组里，必须递归找，不能只看 dataModels 第一层
    column_models = {
        str(m.get("key")): m
        for m, _ in _walk(data.get("dataModels") or [], [])
        if m.get("type") == "ColumnModel"
    }

    fields: List[FieldMeta] = []
    buttons: List[ButtonMeta] = []
    grids: List[GridMeta] = []

    sibling = _sibling_labels(data["components"])
    for node, path in _walk(data["components"], []):
        ntype = str(node.get("type", ""))
        p = node.get("props") or {}
        key = str(node.get("key", ""))

        if ntype == "GridToolBar":
            # 保存、提交、同意等工具栏按钮不是 FormButton，而是 actionList 引用的动作组件
            for action_key in p.get("actionList") or []:
                act = actions.get(str(action_key))
                if act is None:
                    continue
                ap = act["props"]
                buttons.append(
                    ButtonMeta(
                        key=str(action_key),
                        label=str(ap.get("actionText") or ""),
                        action_key=str(action_key),
                        action_type=str(act.get("type") or ""),
                        path=path + [key],
                        visible_expression=str(ap.get("visibleExpression") or ""),
                        enable_expression=str(ap.get("enableExpression") or ""),
                        source="toolbar",
                    )
                )
        elif ntype == "FormButton":
            action_key = str(p.get("action", ""))
            buttons.append(
                ButtonMeta(
                    key=key,
                    label=str(p.get("labelText", "")),
                    action_key=action_key,
                    action_type=str((actions.get(action_key) or {}).get("type", "")),
                    path=path,
                )
            )
        elif ntype == "AGGrid":
            cm_key = str(p.get("columnModel", ""))
            model = column_models.get(cm_key)
            grids.append(
                GridMeta(
                    key=key,
                    dataset_id=_strip_bang(str(p.get("dataSetID", ""))),
                    column_model=cm_key,
                    columns=_parse_columns(model) if model else [],
                    path=path,
                )
            )
        elif ntype == "AmountComp":
            # 币种和金额合在一个组件里，标签写在 labelText，金额列是 moneyColID
            fields.append(
                FieldMeta(
                    key=key, type=ntype, label=_clean_label(p.get("labelText") or p.get("showLabelText")),
                    dataset_id=_strip_bang(str(p.get("dataSetID", ""))),
                    column_id=str(p.get("moneyColID", "")),
                    required=False, required_check=_truthy(p.get("enableNotNullCheck"), False),
                    editable=_truthy(p.get("edit"), True), placeholder=str(p.get("inputPlaceholder", "")),
                    mask_key="", path=path, props=p,
                )
            )
        elif ntype not in _NON_FIELD_TYPES and p.get("dataSetColID") and (p.get("showLabelText") or key in sibling):
            fields.append(
                FieldMeta(
                    key=key,
                    type=ntype,
                    label=_clean_label(p.get("showLabelText")) or sibling[key],
                    dataset_id=_strip_bang(str(p.get("dataSetID", ""))),
                    column_id=str(p.get("dataSetColID")),
                    required=_truthy(p.get("enableNotNull"), False),
                    required_check=_truthy(p.get("enableNotNullCheck"), False),
                    editable=_truthy(p.get("edit"), True) and ntype != "FormLabel",
                    placeholder=str(p.get("placeholder", "")),
                    mask_key=str(p.get("maskConfigKey", "")),
                    path=path,
                    props=p,
                )
            )

    datasets = {
        _strip_bang(str(t.get("tableID", ""))): str(t.get("tableName", ""))
        for t in data.get("tableSource") or []
        if isinstance(t, dict)
    }

    return FormMeta(
        form_id=str(data.get("formID", "")),
        name=str(data.get("formName", "")),
        version=str(data.get("version", "")),
        fields=fields,
        buttons=buttons,
        grids=grids,
        actions=actions,
        datasets=datasets,
        raw=data,
    )


def load_form_file(path: str | Path) -> FormMeta:
    p = Path(path)
    if not p.is_file():
        raise FormMetaError(f"表单文件不存在：{p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FormMetaError(f"表单 JSON 解析失败：{p}：{exc}") from exc
    return load_form(data)


def find_form_file(form_id: str, search_dirs: Iterable[str | Path]) -> Path:
    """在给定目录里按 <FormID>.json 找表单文件，依次尝试，找不到就报错，不猜。"""
    tried = []
    for d in search_dirs:
        cand = Path(d) / f"{form_id}.json"
        tried.append(str(cand))
        if cand.is_file():
            return cand
    raise FormMetaError(f"找不到表单 {form_id}，已尝试：{tried}。"
                        f"可以用 ifc forms import {form_id} --from-env 从被测环境读取")
