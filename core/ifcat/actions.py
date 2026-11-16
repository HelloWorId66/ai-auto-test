"""工作区扩展动作：框架没有的动作，由工作区在 extensions/ 里临时补上，先完成当次工作。

做具体功能的人不改框架。缺动作时（如撤回、上传附件），在工作区写一个函数并用 @action 声明，
场景里就能像内置动作一样用它。这些临时动作由维护者定期用 `ifc harvest` 汇总，筛选后并入框架。

    from ifcat.ext import action, StepResult

    @action("withdraw", required=["bill"], text="撤回单据")
    def withdraw(ctx, bill, **_):
        ...
        return StepResult.passed("已撤回", ctx.screenshot("withdraw"))

扩展动作不能与内置动作同名。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Tuple

_TAG = "__ifcat_action__"


class ActionError(Exception):
    pass


@dataclass(frozen=True)
class ActionSpec:
    name: str
    required: Tuple[str, ...]
    text: str
    checkpoint: bool
    fn: Callable[..., Any]
    source: str = ""


# 当前已加载工作区的扩展动作。场景解析、校验、审核页、运行器都从这里认动作名
_EXT: Dict[str, ActionSpec] = {}


def action(name: str, *, required: Iterable[str] = (), text: str = "", checkpoint: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """声明一个扩展动作。required 是场景里必须给的参数名；text 是审核页和报告里显示的业务说法；
    checkpoint=True 表示它是业务检查点（返回 failed 即「检查未通过」）。
    这里只做标记，真正注册由扩展加载器完成，所以导入扩展文件没有副作用。"""

    def mark(fn: Callable[..., Any]) -> Callable[..., Any]:
        setattr(fn, _TAG, ActionSpec(str(name), tuple(required), text or str(name), bool(checkpoint), fn))
        return fn

    return mark


def declared_in(module: Any) -> List[ActionSpec]:
    return [getattr(v, _TAG) for v in vars(module).values()
            if callable(v) and hasattr(v, _TAG) and getattr(v, "__module__", None) == module.__name__]


def register_extension_action(spec: ActionSpec, reserved: Iterable[str], source: str = "") -> ActionSpec:
    if spec.name in set(reserved):
        raise ActionError(f"扩展层不能覆盖内置动作：{spec.name}（要改内置动作请走提案）")
    if spec.name in _EXT:
        raise ActionError(f"扩展动作重复注册：{spec.name}")
    spec = ActionSpec(spec.name, spec.required, spec.text, spec.checkpoint, spec.fn, source)
    _EXT[spec.name] = spec
    return spec


def extension_actions() -> Dict[str, ActionSpec]:
    return _EXT


def clear_extension_actions() -> None:
    _EXT.clear()


class ActionContext:
    """扩展动作拿到的运行上下文。prim 是内置原语，可以直接复用（如 ctx.prim.fill(...)）。"""

    def __init__(self, prim: Any, captured: Dict[str, Any]):
        self.prim = prim
        self.captured = captured

    @property
    def page(self) -> Any:
        return self.prim.page

    @property
    def nav(self) -> Any:
        return self.prim.nav

    @property
    def db(self) -> Any:
        return self.prim.db

    @property
    def bills(self) -> Dict[str, Any]:
        return self.prim.bills

    @property
    def ui(self) -> Dict[str, str]:
        return self.prim.ui

    def form(self, form_id: str) -> Any:
        return self.prim._form(form_id)

    def screenshot(self, label: str) -> List[str]:
        return self.prim._screenshot(label)
