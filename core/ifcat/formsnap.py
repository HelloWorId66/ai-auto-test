"""表单定义快照：把用到的表单定义保存到工作区 knowledge/forms/，随工作区入库、团队共享。

运行和离线校验只读快照，不需要每个人本机都有产品源码。快照从哪来，由「导入」一步完成：
可以从任意一份产品表单定义目录导入（谁手上有就谁导入一次），导入时记录产品版本、来源说明和内容摘要。
快照索引 _index.yaml 里不记录任何本机路径。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import yaml

from .meta import find_form_file, load_form_file
from .workspace import Workspace

INDEX = "_index.yaml"


class SnapshotError(Exception):
    pass


def _read_index(d: Path) -> Dict[str, Dict[str, str]]:
    f = d / INDEX
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("forms", {}) if f.is_file() else {}


def list_snapshots(ws: Workspace) -> Dict[str, Dict[str, str]]:
    return _read_index(ws.forms_dir)


def import_forms(ws: Workspace, src_dir: Path, form_ids: List[str], product_version: str, source: str) -> List[str]:
    """从 src_dir 导入表单定义。每个表单先解析一遍，解析不了的不入库。返回已导入的表单 ID。"""
    if not product_version:
        raise SnapshotError("导入快照必须写明产品版本（--product-version）")
    ws.forms_dir.mkdir(parents=True, exist_ok=True)
    forms = _read_index(ws.forms_dir)
    done = []
    for fid in form_ids:
        src = find_form_file(fid, [src_dir])
        load_form_file(src)  # 解析失败直接报错，不留下坏快照
        raw = src.read_bytes()
        json.loads(raw.decode("utf-8"))
        shutil.copyfile(src, ws.forms_dir / f"{fid}.json")
        forms[fid] = {"product_version": product_version, "source": source,
                      "sha256": hashlib.sha256(raw).hexdigest(), "imported_at": datetime.now().isoformat(timespec="seconds")}
        done.append(fid)
    (ws.forms_dir / INDEX).write_text(yaml.safe_dump({"forms": dict(sorted(forms.items()))}, allow_unicode=True,
                                                     sort_keys=False), encoding="utf-8")
    return done
