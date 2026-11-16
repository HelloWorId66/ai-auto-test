"""场景的业务审核记录。

测试用例必须经业务人员审核后才能正式运行。审核记录放在场景旁边的 <场景>.review.yaml，
记录审核人、时间和场景内容摘要。内容摘要按「展开继承后的完整场景」计算：场景自己或基线场景被改过，
旧的审核都会失效，必须重新审。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from .scenario import Scenario


def scenario_digest(sc: Scenario) -> str:
    payload = {
        "id": sc.id, "title": sc.title, "module": sc.module, "requirement": sc.requirement,
        "preconditions": sc.preconditions, "roles": sc.roles, "data": sc.data,
        "goal": sc.goal, "source": sc.source, "unconfirmed": sc.unconfirmed, "labels": sc.labels, "feature": sc.feature, "kind": sc.kind,
        "steps": [{"id": s.id, "do": s.do, "text": s.text, "args": s.args, "as": s.role} for s in sc.steps],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def review_path(scenario_file: Path) -> Path:
    return scenario_file.with_name(scenario_file.stem + ".review.yaml")


@dataclass
class ReviewState:
    status: str  # approved / unreviewed / changed
    by: str = ""
    at: str = ""

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    def describe(self) -> str:
        return {
            "approved": f"已审核（{self.by}，{self.at}）",
            "unreviewed": "未审核",
            "changed": f"审核后被修改，需要重新审核（上次审核：{self.by}，{self.at}）",
        }[self.status]


def check_review(sc: Scenario, scenario_file: Path) -> ReviewState:
    rp = review_path(scenario_file)
    if not rp.is_file():
        return ReviewState("unreviewed")
    rec = yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
    by, at = str(rec.get("by", "")), str(rec.get("at", ""))
    if rec.get("status") == "approved" and rec.get("digest") == scenario_digest(sc):
        return ReviewState("approved", by, at)
    return ReviewState("changed", by, at)


DEFAULT_APPROVER = "业务人员对话确认"


def record_approval(sc: Scenario, scenario_file: Path, by: str = "", now: Optional[datetime] = None) -> Path:
    """只应在业务人员明确表示审核通过之后调用，不能由智能体自行审批。不填姓名时记为对话确认。"""
    rp = review_path(scenario_file)
    rec = {"status": "approved", "by": by.strip() or DEFAULT_APPROVER, "at": (now or datetime.now()).isoformat(timespec="seconds"),
           "scenario": sc.id, "digest": scenario_digest(sc)}
    rp.write_text(yaml.safe_dump(rec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return rp
