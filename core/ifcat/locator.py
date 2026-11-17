"""按表单元数据里的标签文本，在页面上找到字段所在容器。

PanUI 多数控件没有稳定 id，标签与控件也没有 htmlFor 关联（01 §1、§6），
所以用「标签文本节点 -> 向上找到含该类型控件的最近容器」的办法，
同名标签按它在表单元数据里的出现顺序取第 N 个（假设 DOM 顺序与组件树顺序一致，需实测确认）。
"""
from __future__ import annotations

from typing import Any, List

from .meta import FieldMeta, FormMeta
from .result import BlockedError
from .selectors import COMPMARK_CONTAINER_TYPES, CONTROL_SELECTORS, compmark_container_css

_TAG = "data-ifcat-target"

_JS = """
([label, controlCss, occurrence, attr]) => {
  document.querySelectorAll('[' + attr + ']').forEach(e => e.removeAttribute(attr));
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const leaves = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  while (walker.nextNode()) {
    const el = walker.currentNode;
    if (el.children.length === 0 && visible(el)) {
      const t = (el.textContent || '').replace(/[\\s*：:]+$/g, '').replace(/^[\\s*]+/g, '').trim();
      if (t === label) leaves.push(el);
    }
  }
  const roots = [];
  for (const leaf of leaves) {
    let node = leaf.parentElement;
    while (node && node !== document.body) {
      const controls = node.querySelectorAll(controlCss);
      if (controls.length >= 1) {
        // 容器里只能有一个同类控件，否则说明爬过头，包含了别的字段
        if (controls.length === 1 && !roots.includes(node)) roots.push(node);
        break;
      }
      node = node.parentElement;
    }
  }
  const target = roots[occurrence];
  if (!target) return {found: false, labelHits: leaves.length, rootHits: roots.length};
  target.setAttribute(attr, '1');
  return {found: true, labelHits: leaves.length, rootHits: roots.length};
}
"""


def occurrence_index(form: FormMeta, field: FieldMeta) -> int:
    """同标签同类型的字段里，本字段排第几（从 0 起）。"""
    same: List[FieldMeta] = [f for f in form.fields if f.label == field.label and f.type == field.type]
    for i, f in enumerate(same):
        if f.key == field.key:
            return i
    raise BlockedError(f"元数据里找不到字段 {field.key}")


def _compmark_root(page: Any, form: FormMeta, field: FieldMeta) -> Any:
    """真实页面（V6.2.4）上多数 React 字段都带 compMark 容器：class 或 id 为 ${formID}-${key}-form-container，
    金额组件 AmountComp 的外层 id 是 ${formID}-${key}-form。命中且只有 1 处时优先用，比标签文本稳定。"""
    base = f"{form.form_id}-{field.key}-form"
    css = f'[class~="{base}-container"], [id="{base}-container"]'
    if field.type == "AmountComp":
        css = f'[id="{base}"]'
    loc = page.locator(css)
    return loc if loc.count() == 1 else None


_INPUT_ID_TYPES = ("FormTextInput", "FormNumberInput", "FormTextArea")


def _input_id_root(page: Any, form: FormMeta, field: FieldMeta) -> Any:
    """文本类输入框自身的 id 是 ${formID}-${key}-form（真实页面 V6.2.7 实测）。
    可编辑的文本框不带 FormTextInput 类名（只有禁用的才带），所以不能靠类名找，按 id 找最稳。"""
    if field.type not in _INPUT_ID_TYPES:
        return None
    base = f"{form.form_id}-{field.key}-form"
    loc = page.locator(f'input[id="{base}"], textarea[id="{base}"]')
    return loc.locator("xpath=..") if loc.count() == 1 else None


def find_field_root(page: Any, form: FormMeta, field: FieldMeta) -> Any:
    hit = _compmark_root(page, form, field)
    if hit is not None:
        return hit
    hit = _input_id_root(page, form, field)
    if hit is not None:
        return hit
    if field.type in COMPMARK_CONTAINER_TYPES:
        # 业务组件有稳定的容器类名，直接按元数据里的组件 key 定位，不依赖标签文本
        loc = page.locator(compmark_container_css(form.form_id, field.key))
        n = loc.count()
        if n != 1:
            raise BlockedError(
                f"按组件 key 定位「{field.label}」({field.type}) 命中 {n} 处，期望 1 处；"
                "可能表单 ID 与页面运行时 formID 不一致，需要标定"
            )
        return loc
    sel = CONTROL_SELECTORS.get(field.type)
    if sel is None:
        raise BlockedError(f"没有 {field.type} 的控件选择器，无法定位字段「{field.label}」")
    idx = occurrence_index(form, field)
    info = page.evaluate(_JS, [field.label, sel.css, idx, _TAG])
    if not info["found"]:
        raise BlockedError(
            f"页面上找不到字段「{field.label}」第 {idx + 1} 个（类型 {field.type}）："
            f"标签命中 {info['labelHits']} 处，可用容器 {info['rootHits']} 个"
        )
    return page.locator(f"[{_TAG}]")


def pick_field(page: Any, form: FormMeta, hits: List[FieldMeta], occurrence: int = 0, explicit: bool = False) -> FieldMeta:
    """同名字段有多个时选哪个。

    表单里常有按条件显示的同名字段（真实页面：企业定存存入有两个「起始日期」，同一时刻只有一个可见）。
    调用方没有显式给 occurrence/within 时，选当前页面上唯一可见的那个；可见数不是 1 就阻塞，不猜。
    """
    if len(hits) == 1:
        return hits[0]
    if explicit:
        if occurrence >= len(hits):
            raise BlockedError(f"字段「{hits[0].label}」只有 {len(hits)} 个，没有第 {occurrence + 1} 个")
        return hits[occurrence]
    visible = []
    marked = 0
    for f in hits:
        root = _compmark_root(page, form, f)
        if root is not None:
            marked += 1
            if root.first.is_visible():
                visible.append(f)
    if marked == 0:  # 页面没有 compMark 容器，只能按元数据里的出现顺序取
        return hits[min(occurrence, len(hits) - 1)]
    if len(visible) == 1:
        return visible[0]
    raise BlockedError(
        f"字段「{hits[0].label}」有 {len(hits)} 个，当前页面可见 {len(visible)} 个，无法确定；请用 occurrence 或 within 指定")
