"""具名等待点。每个都等具体信号，带超时，超时抛出说明，不用无理由的固定 sleep。"""
from __future__ import annotations

import time
from typing import Any, Callable

# 文本类组件的 onChange 有 800ms 防抖（01 §2.1 FormTextInput.tsx:306），
# 填值后值才会写入数据集；这是源码里的具体计时器，不是随意的等待。
INPUT_DEBOUNCE_MS = 900


class WaitTimeout(Exception):
    pass


def poll(predicate: Callable[[], bool], timeout_s: float, what: str, interval_s: float = 0.2) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # 页面切换中的瞬时错误，继续轮询
            last_err = exc
        time.sleep(interval_s)
    detail = f"（最后一次错误：{last_err}）" if last_err else ""
    raise WaitTimeout(f"等待超时（{timeout_s}s）：{what}{detail}")


def wait_input_debounce(page: Any) -> None:
    page.wait_for_timeout(INPUT_DEBOUNCE_MS)


def wait_open_dropdown(page: Any, timeout_s: float = 8.0) -> Any:
    """等下拉弹层出现。弹层挂在 body 下，且同一时刻只会有一个处于打开状态。"""
    sel = ".ant-select-dropdown:not(.ant-select-dropdown-hidden)"
    poll(lambda: page.locator(sel).count() >= 1, timeout_s, "下拉弹层出现")
    return page.locator(sel).first


def wait_dropdown_items_stable(dropdown: Any, timeout_s: float = 8.0) -> int:
    """下拉帮助是分页加载的，等选项数量连续两次一致。"""
    state = {"last": -1}

    def stable() -> bool:
        n = dropdown.locator(".ant-select-item").count()
        ok = n == state["last"] and n > 0
        state["last"] = n
        return ok

    poll(stable, timeout_s, "下拉选项加载稳定", interval_s=0.4)
    return state["last"]


def wait_modal_open(page: Any, timeout_s: float = 8.0) -> Any:
    poll(lambda: page.locator(".ant-modal:visible").count() >= 1, timeout_s, "弹窗出现")
    return page.locator(".ant-modal:visible").last


def wait_modal_closed(page: Any, timeout_s: float = 8.0) -> None:
    poll(lambda: page.locator(".ant-modal:visible").count() == 0, timeout_s, "弹窗关闭")
