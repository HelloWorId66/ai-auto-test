"""单据级动作：存、报、批，以及在首页待办/已完成里找单据。

依据真实环境（V6.2.4 开发环境）的观察，不是源码推断：
- 工具栏按钮的类名是 ${formID}-${工具栏key}-${动作key}-show-form（不可用时是 -hidden-form）
- 点「提交」后弹出确认框（表单 ZJ_SYS_FlowOpNoteConfirm），点框内「提交」才真正提交
- 审批在首页「我的待办」里，行内「同意」打开审批框，点框内「同意」；一张单可能连续经过多个节点
- 待办、已办、已完成都是 osp-grid，同一行的左/中/右区域共用 row-index
界面文字（按钮、页签）随语言和产品版本变化，放在 UI_TEXT 里，可由 env_params.ui_text 覆盖。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import waits
from .meta import ButtonMeta, FormMeta
from .result import BlockedError

UI_TEXT: Dict[str, str] = {
    "tab_todo": "我的待办",
    "tab_done": "已完成",
    "refresh": "刷新",
    "agree": "同意",
    "reject": "退回",
    "edit": "编辑",
    "confirm_submit": "提交",
    "query": "查询",
    "export": "导出",
    "confirm_pick": "确定",
    "toast_fail_words": "失败,错误,异常,fail,error",
}

_TOAST = ".ant-message-notice, .ant-notification-notice"


def text(ui: Optional[Dict[str, str]], key: str) -> str:
    return (ui or {}).get(key) or UI_TEXT[key]


def collect_toasts(page: Any, window_ms: int = 3000, step_ms: int = 250) -> List[str]:
    """提示 3 秒会消失且可被配置关闭，只能当辅助证据：采集一小段时间内出现过的提示文字。"""
    seen: List[str] = []
    for _ in range(max(1, window_ms // step_ms)):
        page.wait_for_timeout(step_ms)
        for t in page.evaluate(f"[...document.querySelectorAll('{_TOAST}')].map(e => e.innerText)"):
            if t and t not in seen:
                seen.append(t)
    return seen


def wait_toasts(page: Any, timeout_ms: int = 20000, step_ms: int = 250) -> List[str]:
    """保存、提交是异步的，服务端慢时提示出现得晚：等到第一条提示出现（最长 timeout_ms），再多收 1 秒。
    一直没出现提示也不算失败（提示可被配置关闭），由随后的检查点判断。"""
    for _ in range(max(1, timeout_ms // step_ms)):
        if page.evaluate(f"document.querySelectorAll('{_TOAST}').length"):
            return collect_toasts(page, 1000, step_ms)
        page.wait_for_timeout(step_ms)
    return []


def failed_toast(toasts: List[str], ui: Optional[Dict[str, str]]) -> Optional[str]:
    words = [w.strip().lower() for w in text(ui, "toast_fail_words").split(",") if w.strip()]
    for t in toasts:
        if any(w in t.lower() for w in words):
            return t
    return None


def toolbar_button(form: FormMeta, label: str, action_type: Optional[str] = None) -> ButtonMeta:
    hits = [b for b in form.button_by_label(label, action_type) if b.source == "toolbar"]
    if not hits:
        raise BlockedError(f"表单 {form.form_id} 的工具栏里没有按钮「{label}」")
    if len(hits) > 1:
        raise BlockedError(f"表单 {form.form_id} 的工具栏里有 {len(hits)} 个「{label}」按钮，无法确定")
    return hits[0]


def click_toolbar(page: Any, form: FormMeta, btn: ButtonMeta) -> None:
    css = f".{form.form_id}-{btn.path[-1]}-{btn.action_key}-show-form"
    loc = page.locator(css)
    if loc.count() == 0:
        raise BlockedError(f"按钮「{btn.label}」当前不可见（页面上没有 {css}），单据可能不在能执行该操作的状态")
    loc.first.click()


def confirm_dialog(page: Any, button_text: str) -> None:
    dialog = page.locator(".ant-modal-wrap:visible")
    waits.poll(lambda: dialog.count() >= 1, 8.0, "确认框出现")
    dialog.last.get_by_role("button", name=button_text, exact=True).click()
    waits.poll(lambda: page.locator(".ant-modal-wrap:visible").count() == 0, 10.0, "确认框关闭")


def _row_index(page: Any, bill_no: str) -> Optional[str]:
    return page.evaluate(
        """(no) => { const r = [...document.querySelectorAll('.osp-row')].find(x => x.innerText.includes(no));
                     return r ? r.getAttribute('row-index') : null; }""", bill_no)


def bill_row_text(page: Any, bill_no: str) -> Optional[str]:
    return page.evaluate(
        """(no) => { const r = [...document.querySelectorAll('.osp-row')].find(x => x.innerText.includes(no));
                     return r ? r.innerText.replace(/\\n/g, '/') : null; }""", bill_no)


def open_tab(page: Any, tab: str) -> None:
    """点页签。刚提交/同意后的提示条会盖住页签几秒，点不到时等提示消失再点，最多四次。"""
    for attempt in range(4):
        try:
            page.get_by_text(tab, exact=True).first.click(timeout=8000)
            break
        except Exception:
            if attempt == 3:
                raise
            page.wait_for_timeout(3000)
    page.wait_for_timeout(2500)


def approve_until_done(page: Any, bill_no: str, ui: Optional[Dict[str, str]] = None, max_nodes: int = 8) -> int:
    """在待办里反复「同意」直到该单离开本人待办。返回同意的次数。
    单据后面如果还有别的人的节点，它会离开本人待办但并未完成，是否完成要另用 expect_flow_completed 判断。"""
    agree = text(ui, "agree")
    done = 0
    open_tab(page, text(ui, "tab_todo"))
    for _ in range(max_nodes):
        idx = _row_index(page, bill_no)
        if idx is None:
            return done
        page.locator(f".osp-row[row-index='{idx}']").get_by_text(agree, exact=True).first.click()
        confirm_dialog(page, agree)
        done += 1
        page.wait_for_timeout(3000)
        page.get_by_text(text(ui, "refresh"), exact=True).first.click()
        page.wait_for_timeout(2500)
    raise BlockedError(f"单据 {bill_no} 同意了 {max_nodes} 次仍在待办里，流程节点异常多，请人工确认")


def visible_modal_texts(page: Any) -> List[str]:
    return page.evaluate(
        "[...document.querySelectorAll('.ant-modal-wrap')].filter(e => getComputedStyle(e).display !== 'none')"
        ".map(e => e.innerText)")


def row_action(page: Any, bill_no: str, label: str) -> None:
    """点待办行内的操作链接（同意、退回等）。"""
    idx = _row_index(page, bill_no)
    if idx is None:
        raise BlockedError(f"待办里找不到单据 {bill_no}")
    page.locator(f".osp-row[row-index='{idx}']").get_by_text(label, exact=True).first.click()


def row_flow_name(page: Any, bill_no: str) -> str:
    """待办行里「流程名称」那一格的文字（行文本第 2 项），点它可以打开单据。"""
    name = page.evaluate(
        """(no) => { const r = [...document.querySelectorAll('.osp-row')].find(x => x.innerText.includes(no));
                     if (!r) return null; const p = r.innerText.split('\\n').map(t => t.trim()).filter(Boolean);
                     return p.length > 1 ? p[1] : null; }""", bill_no)
    if not name:
        raise BlockedError(f"待办里找不到单据 {bill_no}")
    return name


def open_bill_from_todo(page: Any, bill_no: str) -> None:
    name = row_flow_name(page, bill_no)
    idx = _row_index(page, bill_no)
    page.locator(f".osp-row[row-index='{idx}']").get_by_text(name, exact=True).first.click()


def page_error_banner(page: Any) -> str:
    """保存失败时表单顶部会列出错误信息（如「当前单据有2条错误信息 1. …」），把它读出来，失败原因才说得清。"""
    texts = page.evaluate(
        "[...document.querySelectorAll('.ant-alert')].filter(e => e.offsetParent).map(e => e.innerText)")
    return "；".join(t.replace("\n", " ").strip() for t in texts if t.strip())[:300]
