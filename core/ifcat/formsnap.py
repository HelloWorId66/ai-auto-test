"""表单定义快照：把用到的表单定义保存到工作区 knowledge/forms/，随工作区入库、团队共享。

运行和离线校验只读快照，不需要每个人本机都有产品源码。快照从哪来，由「导入」一步完成，两种来源：
- 被测环境：登录后向环境要表单定义（页面自己打开表单时走的同一个接口），拿到的就是环境上实际部署的那一版，
  客户化定制的表单也在内；
- 本地的产品表单定义目录：谁手上有就谁导入一次。
导入时记录产品版本、来源说明和内容摘要。快照索引 _index.yaml 里不记录任何本机路径和环境地址。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

import yaml

from .meta import find_form_file, load_form, load_form_file
from .workspace import Workspace

INDEX = "_index.yaml"
LOADJSON = "/rest/react/loadjson"


class SnapshotError(Exception):
    pass


def _read_index(d: Path) -> Dict[str, Dict[str, str]]:
    f = d / INDEX
    return (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("forms", {}) if f.is_file() else {}


def list_snapshots(ws: Workspace) -> Dict[str, Dict[str, str]]:
    return _read_index(ws.forms_dir)


def _store(ws: Workspace, items: Dict[str, bytes], product_version: str, source: str) -> List[str]:
    if not items:
        return []
    ws.forms_dir.mkdir(parents=True, exist_ok=True)
    forms = _read_index(ws.forms_dir)
    for fid, raw in items.items():
        (ws.forms_dir / f"{fid}.json").write_bytes(raw)
        forms[fid] = {"product_version": product_version, "source": source,
                      "sha256": hashlib.sha256(raw).hexdigest(), "imported_at": datetime.now().isoformat(timespec="seconds")}
    (ws.forms_dir / INDEX).write_text(yaml.safe_dump({"forms": dict(sorted(forms.items()))}, allow_unicode=True,
                                                     sort_keys=False), encoding="utf-8")
    return list(items)


def import_forms(ws: Workspace, src_dir: Path, form_ids: List[str], product_version: str, source: str) -> List[str]:
    """从 src_dir 导入表单定义。每个表单先解析一遍，解析不了的不入库。返回已导入的表单 ID。"""
    if not product_version:
        raise SnapshotError("导入快照必须写明产品版本（--product-version）")
    items: Dict[str, bytes] = {}
    for fid in form_ids:
        src = find_form_file(fid, [src_dir])
        load_form_file(src)  # 解析失败直接报错，不留下坏快照
        raw = src.read_bytes()
        json.loads(raw.decode("utf-8"))
        items[fid] = raw
    return _store(ws, items, product_version, source)


def parse_loadjson(form_id: str, status: int, body: str) -> str:
    """解读环境对「加载表单定义」的回答，返回表单定义原文；环境说没有或回答看不懂时报错，不猜。"""
    if status != 200:
        raise SnapshotError(f"环境返回 HTTP {status}")
    try:
        reply = json.loads(body)
    except ValueError as exc:
        raise SnapshotError("环境的回答不是 JSON（可能登录已失效）") from exc
    data = reply.get("data") if isinstance(reply, dict) else None
    if not isinstance(reply, dict) or reply.get("code") != 1 or not isinstance(data, str) or not data:
        msg = str(reply.get("message") or "") if isinstance(reply, dict) else ""
        raise SnapshotError(msg or "环境没有返回表单定义")
    try:
        form = load_form(json.loads(data))
    except Exception as exc:
        raise SnapshotError(f"环境返回的内容不是可识别的表单定义：{exc}") from exc
    if form.form_id != form_id:
        raise SnapshotError(f"环境返回的是另一个表单（{form.form_id}）")
    return data


def fetch_from_env(cfg: Any, form_ids: List[str]) -> Tuple[Dict[str, str], Dict[str, str]]:
    """登录被测环境，逐个取表单定义。返回（取到的原文，取不到的原因）。

    登录后首页自己会加载一次表单定义；照着那次请求（同样的地址、登录凭据和参数）换一个表单 ID 再问一遍，
    这样不用猜各环境的服务地址和鉴权方式。"""
    from .session import Session

    role = next(iter(cfg.accounts), None)
    if role is None:
        raise SnapshotError("环境配置里没有账号，无法登录环境读取表单定义")
    sess = Session(cfg, headless=True)
    seen: List[Any] = []
    try:
        page = sess.start()
        page.on("request", lambda r: seen.append(r) if LOADJSON in r.url and r.method == "POST" else None)
        try:
            sess.login(role)
        except Exception as exc:
            raise SnapshotError(f"登录环境失败：{str(exc).splitlines()[0]}") from exc
        for _ in range(20):
            if seen:
                break
            page.wait_for_timeout(500)
        try:
            sample = seen[0]
            params = json.loads(sample.post_data or "")
            headers = {k: v for k, v in sample.headers.items() if k.lower() not in ("content-length", "host")}
        except (IndexError, ValueError) as exc:
            raise SnapshotError("登录后没有观察到页面加载表单定义的请求，这个环境不能用 --from-env，"
                                "请改用 --from <产品表单定义目录>") from exc
        found: Dict[str, str] = {}
        missing: Dict[str, str] = {}
        for fid in form_ids:
            try:
                resp = sess.context.request.post(sample.url, data=json.dumps({**params, "FormID": fid, "sign": ""}),
                                                 headers={**headers, "ospformid": fid}, timeout=60000)
                found[fid] = parse_loadjson(fid, resp.status, resp.text())
            except SnapshotError as exc:
                missing[fid] = str(exc)
            except Exception as exc:
                missing[fid] = f"请求失败：{str(exc).splitlines()[0]}"
        return found, missing
    finally:
        sess.close()


def import_forms_from_env(ws: Workspace, cfg: Any, form_ids: List[str], product_version: str,
                          fetch: Callable[[Any, List[str]], Tuple[Dict[str, str], Dict[str, str]]] = fetch_from_env,
                          ) -> Tuple[List[str], Dict[str, str]]:
    """从被测环境导入。取到的入库，取不到的连同原因一并返回。"""
    version = product_version or (cfg.product_version if cfg.product_version != "unknown" else "")
    if not version:
        raise SnapshotError("导入快照必须写明产品版本：在环境配置里填 product_version，或加 --product-version")
    found, missing = fetch(cfg, form_ids)
    done = _store(ws, {fid: text.encode("utf-8") for fid, text in found.items()}, version, f"从被测环境 {cfg.env_name} 读取")
    return done, missing
