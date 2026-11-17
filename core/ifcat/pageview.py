"""只看不动地查看一张真实表单：打开表单的新建页，列出每个字段当前是否显示、能不能填、默认值是什么，
以及工具栏上哪些按钮可用，并留一张整页截图。不填写、不保存、不提交，环境里不会多出单据。

用在写用例之前：弄清真实页面和表单定义、设计文档是否一致。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, List

from . import waits
from .adapters.registry import AdapterRegistry
from .locator import find_field_root
from .meta import FormMeta


def _one_line(v: Any) -> str:
    return " ".join(str(v if v is not None else "").split())[:60]


def field_lines(page: Any, form: FormMeta, registry: AdapterRegistry) -> List[str]:
    lines = []
    for f in form.fields:
        need = "必填" if f.required else ""
        try:
            root = find_field_root(page, form, f)
            if not root.first.is_visible():
                lines.append(f"{f.label}\t{f.type}\t{need}\t当前不显示\t")
                continue
        except Exception:
            lines.append(f"{f.label}\t{f.type}\t{need}\t页面上没找到（可能按条件显示，或被部署隐藏）\t")
            continue
        try:
            adapter = registry.get(f.type)
        except Exception:
            lines.append(f"{f.label}\t{f.type}\t{need}\t显示；引擎不带这种控件，要用需在 extensions/ 里补\t")
            continue
        try:
            state = "只读" if adapter.is_readonly(page, root) else "可填"
        except Exception:
            state = "能否填写未知"
        try:
            value = _one_line(adapter.get(page, root))
        except Exception:
            value = "（读不出）"
        lines.append(f"{f.label}\t{f.type}\t{need}\t{state}\t{value}")
    return lines


def button_lines(page: Any, form: FormMeta) -> List[str]:
    lines = []
    for b in form.buttons:
        if b.source != "toolbar" or not b.label or not b.path:
            continue
        base = f".{form.form_id}-{b.path[-1]}-{b.action_key}"
        if page.locator(f"{base}-show-form").count():
            lines.append(f"{b.label}\t可用")
        elif page.locator(f"{base}-hidden-form").count():
            lines.append(f"{b.label}\t当前不可用")
    return lines


def grid_lines(form: FormMeta) -> List[str]:
    return [f"{g.key}\t" + "、".join(f"{c.header}（编辑器码 {c.editor_type}，{'可填' if c.editable else '只读'}）"
                                     for c in g.columns if c.visible and c.header) for g in form.grids]


_OPEN_POPUP = ".ant-select-dropdown:not(.ant-select-dropdown-hidden)"
_READ_POPUP = """e => {
  const vis = x => x.getClientRects().length > 0;
  const rows = [...e.querySelectorAll('tr.ant-table-row')].filter(vis)
    .map(r => [...r.cells].map(c => c.innerText.trim()).filter(Boolean).join(' '));
  if (rows.length) return {heads: [...e.querySelectorAll('th')].map(h => h.innerText.trim()).filter(Boolean), items: rows};
  const opts = [...e.querySelectorAll('.ant-select-item-option')].map(o => o.getAttribute('title') || o.innerText.trim());
  if (opts.length) return {heads: [], items: opts};
  return {heads: [], items: e.innerText.split('\\n').map(s => s.trim()).filter(Boolean)};
}"""
OPTION_LIMIT = 30


def option_lines(page: Any, form: FormMeta) -> List[str]:
    """把每个可填的下拉、弹层选择字段点开，读出里面的选项，再按 Esc 关掉。不选任何一项。"""
    lines = []
    for f in form.fields:
        try:
            root = find_field_root(page, form, f)
            trigger = root.locator(".ant-select-selector")
            if not root.first.is_visible() or not trigger.count() or root.locator(".ant-select-disabled").count():
                continue
            trigger.first.click()
        except Exception:
            continue
        popup = page.locator(_OPEN_POPUP)
        try:
            waits.poll(lambda: popup.count() >= 1 and popup.last.is_visible(), 5.0, "选项弹层出现")
            page.wait_for_timeout(800)  # 选项是异步加载的，弹层出现后稍等数据到齐
            got = popup.last.evaluate(_READ_POPUP)
            items = [_one_line(i) for i in got["items"] if _one_line(i)]
            head = f"（列：{'、'.join(got['heads'])}）" if got["heads"] else ""
            more = f" …… 只列出前 {OPTION_LIMIT} 项，更多的在页面上滚动或搜索" if len(items) >= OPTION_LIMIT else ""
            name = f"{f.label}的币种" if f.type == "AmountComp" else f.label
            lines.append(f"{name}{head}\t" + ("；".join(items[:OPTION_LIMIT]) + more if items else "点开后没有选项"))
        except Exception:
            lines.append(f"{f.label}\t点开后没有读到选项")
        page.keyboard.press("Escape")
        try:
            waits.poll(lambda: page.locator(f"{_OPEN_POPUP}:visible").count() == 0, 3.0, "选项弹层关闭")
        except Exception:
            page.mouse.click(5, 5)
            page.wait_for_timeout(400)
    return lines

def view_form(sess: Any, form: FormMeta, registry: AdapterRegistry, out_dir: Path, options: bool = False) -> str:
    """调用前已登录。返回给人看的文字。"""
    page = sess.page
    title = _one_line(page.title())
    sess.open_form(form.form_id)
    page = sess.page
    out_dir.mkdir(parents=True, exist_ok=True)
    shot = out_dir / f"{form.form_id}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
    parts = [f"登录后的页面标题：{title}（环境配置里的 product_version 填其中的版本号，如 6.2.7-SNAPSHOT）",
             f"表单 {form.form_id}（{form.name}）新建页，只看不动：", "", "字段\t类型\t必填\t状态\t当前值"]
    parts += field_lines(page, form, registry)
    grids = grid_lines(form)
    if grids:
        parts += ["", "表格\t列"] + grids
    buttons = button_lines(page, form)
    if buttons:
        parts += ["", "工具栏按钮\t状态"] + buttons
    page.screenshot(path=str(shot), full_page=True)
    if options:
        opts = option_lines(page, form)
        parts += ["", "可选项（点开看了一眼，没有选）\t选项", *(opts or ["这张表单上没有可填的下拉或弹层选择字段"]),
                  "表格里的下拉不在这里列出；用例设计确认后试跑时再看。"]
    parts += ["", f"截图：{shot}"]
    return "\n".join(parts)
