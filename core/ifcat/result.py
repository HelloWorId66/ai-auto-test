from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Status(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    # 缺少适配器、环境不可用等，不是产品问题，也不能算通过
    BLOCKED = "blocked"
    # 场景本身无法判定（例如没有业务检查点）
    INVALID = "invalid"


@dataclass
class StepResult:
    status: Status
    message: str = ""
    evidence: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status is Status.PASSED

    @classmethod
    def passed(cls, message: str = "", evidence: List[str] | None = None) -> "StepResult":
        return cls(Status.PASSED, message, list(evidence or []))

    @classmethod
    def failed(cls, message: str, evidence: List[str] | None = None) -> "StepResult":
        return cls(Status.FAILED, message, list(evidence or []))

    @classmethod
    def blocked(cls, message: str, evidence: List[str] | None = None) -> "StepResult":
        return cls(Status.BLOCKED, message, list(evidence or []))

    @classmethod
    def invalid(cls, message: str) -> "StepResult":
        return cls(Status.INVALID, message)


class BlockedError(Exception):
    """步骤无法执行（如无适配器），场景应判为阻塞而不是失败。"""
