"""证据与结果落盘：每次运行一个目录，保存截图、查询结果和步骤记录。"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import redact
from .result import StepResult

_UNSAFE = re.compile(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+")


def _slug(text: str) -> str:
    return _UNSAFE.sub("_", text).strip("_")[:60] or "x"


class RunRecorder:
    def __init__(self, results_root: str | Path, project: str, env_name: str, scenario: str,
                 now: Optional[datetime] = None, batch_dir: Optional[Path] = None):
        ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        if batch_dir is not None:
            # 批次内每个场景一个子目录，批次目录本身永不覆盖
            self.dir = Path(batch_dir) / _slug(scenario)
            n = 1
            while self.dir.exists():
                n += 1
                self.dir = Path(batch_dir) / f"{_slug(scenario)}-{n}"
        else:
            self.dir = Path(results_root) / _slug(project) / _slug(env_name) / f"{ts}_{_slug(scenario)}"
        self.dir.mkdir(parents=True, exist_ok=False)
        self._t0 = time.monotonic()
        self.meta: Dict[str, Any] = {
            "project": project,
            "env": env_name,
            "scenario": scenario,
            "started": ts,
        }
        self.steps: List[Dict[str, Any]] = []
        self._seq = 0

    def _next(self, label: str) -> str:
        self._seq += 1
        return f"{self._seq:03d}_{_slug(label)}"

    def save_screenshot(self, label: str, shoot: Callable[[str], Any]) -> str:
        """shoot 接收目标路径并写出 PNG。返回相对路径。"""
        name = self._next(label) + ".png"
        shoot(str(self.dir / name))
        return name

    def save_query(self, label: str, sql: str, rows: List[Dict[str, Any]]) -> str:
        name = self._next(label) + ".json"
        payload = {"sql": sql, "row_count": len(rows), "rows": rows}
        (self.dir / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return name

    def save_file(self, label: str, ext: str, write: Callable[[str], Any]) -> str:
        """write 接收目标路径并写出文件（如导出的 Excel）。返回相对路径。"""
        name = self._next(label) + ext
        write(str(self.dir / name))
        return name

    def record_step(self, name: str, result: StepResult) -> None:
        self.steps.append(
            {"name": name, "status": result.status.value, "message": result.message, "evidence": result.evidence}
        )

    def annotate_steps_since(self, start: int, **info: Any) -> None:
        """给 start 之后新记录的步骤补上场景里的业务信息（步骤号、说明、角色、是否检查点）。"""
        for st in self.steps[start:]:
            st.update(info)

    def finish(self, final_status: str) -> Path:
        self.meta["final_status"] = final_status
        self.meta["duration_s"] = round(time.monotonic() - self._t0, 1)
        self.meta["finished"] = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = self.dir / "result.json"
        out.write_text(
            json.dumps({"meta": redact(self.meta), "steps": redact(self.steps)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return out
