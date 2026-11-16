"""场景运行器：逐步解释执行场景，不生成代码。

遇到第一个未通过的步骤就停止，后面的步骤依赖前面的结果，继续执行没有意义。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .primitives import Primitives
from .result import BlockedError, Status, StepResult
from .scenario import CHECKPOINT_STEPS, Scenario, ScenarioError, Step, resolve, resolve_data


def _occ(a: Dict[str, Any]) -> Optional[int]:
    return int(a["occurrence"]) if a.get("occurrence") is not None else None


class ScenarioRunner:
    def __init__(self, prim: Primitives, switch_role: Optional[Callable[[str], Any]] = None):
        self.prim = prim
        self.switch_role = switch_role
        self.captured: Dict[str, Any] = {}
        self._role: Optional[str] = None

    def run(self, sc: Scenario, data_override: Optional[Dict[str, Any]] = None) -> Status:
        data = resolve_data({**sc.data, **(data_override or {})})
        for step in sc.steps:
            start = len(self.prim.rec.steps)
            result = self._run_step(step, {"data": data, "captured": self.captured}, sc)
            self.prim.rec.annotate_steps_since(
                start, sid=step.id, text=step.text, role=step.role, role_name=sc.roles.get(step.role or "", step.role),
                checkpoint=step.do in CHECKPOINT_STEPS)
            if not result.ok:
                break
        self.prim.rec.meta["captured"] = {k: str(v) for k, v in self.captured.items()}
        return self.prim.finish()

    def _run_step(self, step: Step, ctx: Dict[str, Any], sc: Scenario) -> StepResult:
        try:
            args = resolve(step.args, ctx)
            self._ensure_role(step, sc)
        except (ScenarioError, BlockedError) as exc:
            res = StepResult.blocked(f"{step.id}: {exc}")
            self.prim.rec.record_step(f"{step.id} {step.do}", res)
            return res
        except Exception as exc:  # 角色切换等环境问题
            res = StepResult.blocked(f"{step.id}: {type(exc).__name__}: {exc}")
            self.prim.rec.record_step(f"{step.id} {step.do}", res)
            return res
        return self._dispatch(step, args)

    def _ensure_role(self, step: Step, sc: Scenario) -> None:
        if step.role and step.role != self._role:
            if self.switch_role is None:
                raise BlockedError(f"需要切换到角色 {step.role}，但运行环境没有提供切换能力")
            new_page = self.switch_role(step.role)
            if new_page is not None:
                self.prim.page = new_page  # 换账号会换浏览器上下文，原语必须用新页面
            self._role = step.role

    def _dispatch(self, step: Step, a: Dict[str, Any]) -> StepResult:
        p = self.prim
        do = step.do
        if do == "fill":
            return p.fill(a["form"], a["values"], a.get("within"), _occ(a))
        if do == "expect_field":
            return p.expect_field(a["form"], a["label"], a["expected"], a.get("within"), _occ(a))
        if do == "expect_db_status":
            return p.expect_db_status(a["flow"], a["key"], a["state"])
        if do == "expect_db_result":
            return p.expect_db_result(a["flow"], a["result"], a["where"], int(a.get("min_rows", 1)), a.get("max_rows"))
        if do == "expect_db_record":
            return p.expect_db_record(a["flow"], a["key"], a["table"], a.get("expect"), bool(a.get("absent", False)),
                                      int(a.get("wait", 0)))
        if do == "capture_field":
            return self._capture(step, a)
        if do == "capture_db":
            return self._capture_db(a)
        if do in ("open", "save", "expect_flow_completed", "submit", "approve", "reject", "pick_record", "expect_query", "expect_not_listed", "fill_grid", "expect_grid",
                  "edit", "open_todo", "expect_visible", "submit_with_warning", "approve_blocked"):
            kwargs = {k: v for k, v in a.items()}
            return getattr(p, do)(**kwargs)
        res = StepResult.blocked(f"未知动作 {do}")
        p.rec.record_step(do, res)
        return res

    def _capture_db(self, a: Dict[str, Any]) -> StepResult:
        def run() -> StepResult:
            value = self.prim.read_head_value(a["flow"], a["key"], a["column"])
            if value in (None, ""):
                return StepResult.failed(f"数据库里 {a['column']} 没有值，无法记录为 {a['name']}")
            self.captured[a["name"]] = value
            return StepResult.passed(f"记录 {a['name']}={value}")

        return self.prim._step(f"记录 {a['name']}", run)

    def _capture(self, step: Step, a: Dict[str, Any]) -> StepResult:
        def run() -> StepResult:
            value = self.prim.read_field(a["form"], a["label"], a.get("within"), _occ(a))
            if value in (None, ""):
                return StepResult.failed(f"「{a['label']}」没有值，无法记录为 {a['name']}")
            self.captured[a["name"]] = value
            return StepResult.passed(f"记录 {a['name']}={value}")

        return self.prim._step(f"记录 {a['label']}", run)
