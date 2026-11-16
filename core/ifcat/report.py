"""HTML 测试报告：批次总览、场景详情、历史索引。

目录结构（永不覆盖，每次运行新建一个批次目录）：
  results/runs/<项目>/<环境>/<批次>/batch.json、report.html
  results/runs/<项目>/<环境>/<批次>/<场景>/result.json、截图、report.html
  results/index.html   所有批次的历史索引与最近几次的状态点阵

报告只引用相对路径，把整个批次目录打包就能离线查看。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .htmlkit import STATUS_TEXT, badge, esc, metrics, page

STATUS_ORDER = ["failed", "blocked", "invalid", "skipped", "passed"]
MEANING = {
    "failed": "检查点和预期不一致，疑似产品问题，需要业务或开发判断",
    "blocked": "自动化没能跑完（环境、定位、数据等），由智能体处理，不需要你操作",
    "invalid": "场景没有业务检查点，不能证明任何事",
    "skipped": "没有运行（例如还没经业务审核）",
}


def counts(scenarios: List[Dict[str, Any]]) -> Dict[str, int]:
    c = {k: 0 for k in STATUS_ORDER}
    for s in scenarios:
        c[s["status"]] = c.get(s["status"], 0) + 1
    return c


def first_problem(steps: List[Dict[str, Any]]) -> str:
    for i, st in enumerate(steps, 1):
        if st["status"] != "passed":
            what = st.get("text") or st.get("name", "")
            return f"第 {i} 步「{what}」：{st.get('message', '')}"
    return ""


def _fmt_time(ts: str) -> str:
    # 20261113-180609 -> 2026-11-13 18:06:09
    return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}" if len(ts) >= 15 else ts


def _dur(sec: Optional[float]) -> str:
    if sec is None:
        return ""
    sec = int(sec)
    return f"{sec // 60} 分 {sec % 60} 秒" if sec >= 60 else f"{sec} 秒"


# --- 场景详情 ---
def write_scenario_report(scn_dir: Path, summary: Dict[str, Any]) -> Path:
    res_file = scn_dir / "result.json"
    data = json.loads(res_file.read_text(encoding="utf-8")) if res_file.is_file() else {"meta": {}, "steps": []}
    steps, meta = data["steps"], data["meta"]
    st = summary["status"]
    body = [f'<div class="sub"><a href="../report.html">← 返回批次总览</a></div>',
            f'<h1>{esc(summary["title"])}</h1>',
            f'<div class="sub">模块 {esc(summary["module"])} · {esc(summary["id"])} · {badge(st)} · '
            f'耗时 {esc(_dur(summary.get("duration_s")))} · {esc(summary.get("review", ""))}</div>']
    if not summary.get("reviewed"):
        body.append('<div class="warn-box">本场景运行时未经业务审核，只用于调试，不能作为回归结论。</div>')
    if st in MEANING:
        body.append(f'<div class="{"err-box" if st == "failed" else "warn-box"}"><b>{esc(STATUS_TEXT[st])}：</b>'
                    f'{esc(MEANING[st])}<br>{esc(summary.get("problem", ""))}</div>')
    if meta.get("extensions_used"):
        kinds = {"adapter": "控件", "action": "动作"}
        used = "、".join(f'{kinds.get(x.get("kind"), x.get("kind"))} {x.get("name")}' for x in meta["extensions_used"])
        body.append(f'<div class="card">本场景用到了工作区里临时补的扩展（尚未并入框架）：{esc(used)}。'
                    '结果照常有效；这些扩展由框架维护者定期归纳。</div>')
    if meta.get("unique"):
        body.append(f'<div class="card">本次运行的不重复编号（${{unique}}）：<b>{esc(meta["unique"])}</b></div>')
    if meta.get("captured"):
        body.append('<div class="card">运行中取得的值：' + "；".join(
            f"{esc(k)} = <b>{esc(v)}</b>" for k, v in meta["captured"].items()) + "</div>")
    body.append('<h2>执行过程</h2><table><tr><th style="width:36px">#</th><th style="width:100px">角色</th>'
                '<th>步骤</th><th style="width:110px">结果</th></tr>')
    for i, s in enumerate(steps, 1):
        chk = '<span class="badge check">检查点</span> ' if s.get("checkpoint") else ""
        shots = "".join(f'<a href="{esc(e)}"><img src="{esc(e)}" loading="lazy"></a>'
                        for e in s.get("evidence", []) if e.endswith(".png"))
        cls = "bad" if s["status"] in ("failed", "blocked") else ("hl" if s.get("checkpoint") else "")
        body.append(f'<tr class="{cls}"><td>{i}</td><td>{esc(s.get("role_name") or "")}</td>'
                    f'<td>{chk}{esc(s.get("text") or s["name"])}<div class="sub">{esc(s.get("message", ""))}</div>'
                    f'<div class="shots">{shots}</div></td><td>{badge(s["status"])}</td></tr>')
    body.append("</table>")
    out = scn_dir / "report.html"
    out.write_text(page(f"{summary['title']} 结果", "".join(body)), encoding="utf-8")
    return out


# --- 批次总览 ---
def previous_batch(batch_dir: Path) -> Optional[Dict[str, Any]]:
    siblings = sorted(p for p in batch_dir.parent.iterdir() if p.is_dir() and p.name < batch_dir.name
                      and (p / "batch.json").is_file())
    return json.loads((siblings[-1] / "batch.json").read_text(encoding="utf-8")) if siblings else None


def _compare(cur: List[Dict[str, Any]], prev: Optional[Dict[str, Any]]) -> Tuple[List[str], List[str], str]:
    if not prev:
        return [], [], ""
    before = {s["id"]: s["status"] for s in prev["scenarios"]}
    new_bad = [s["id"] for s in cur if s["status"] in ("failed", "blocked") and before.get(s["id"]) == "passed"]
    fixed = [s["id"] for s in cur if s["status"] == "passed" and before.get(s["id"]) in ("failed", "blocked")]
    return new_bad, fixed, prev["batch_id"]


_FILTER_JS = """
const rows=[...document.querySelectorAll('tr[data-status]')];let cur='all';
function apply(){const q=document.getElementById('q').value.trim();
rows.forEach(r=>{const ok=(cur==='all'||r.dataset.status===cur)&&(!q||r.dataset.text.includes(q));r.style.display=ok?'':'none'});
document.querySelectorAll('details.mod').forEach(d=>{const any=[...d.querySelectorAll('tr[data-status]')].some(r=>r.style.display!=='none');
d.style.display=any?'':'none';if(cur!=='all'||q){d.open=any}})}
document.querySelectorAll('.filter button').forEach(b=>b.onclick=()=>{cur=b.dataset.f;
document.querySelectorAll('.filter button').forEach(x=>x.classList.toggle('on',x===b));apply()});
document.getElementById('q').oninput=apply;
"""


def write_batch_report(batch_dir: Path, batch: Dict[str, Any]) -> Path:
    scs = batch["scenarios"]
    c = counts(scs)
    new_bad, fixed, prev_id = _compare(scs, previous_batch(batch_dir))
    title = f"{batch['scope']} · {batch['env']} · {_fmt_time(batch['batch_id'][:15])}"
    body = ['<div class="sub"><a href="../../../../index.html">← 历史索引</a></div>',
            f"<h1>测试报告：{esc(batch['scope'])}</h1>",
            f'<div class="sub">项目 {esc(batch["project"])} · 环境 {esc(batch["env"])} · 产品版本 {esc(batch["product_version"])} · '
            f'语言 {esc(batch["locale"])} · 开始 {esc(_fmt_time(batch["started"]))} · 耗时 {esc(_dur(batch.get("duration_s")))} · '
            f'批次 {esc(batch["batch_id"])}</div>']
    if not batch.get("complete"):
        body.append('<div class="warn-box">本批次还在运行，或运行被中断。下面是已完成的部分。</div>')
    if batch.get("draft"):
        body.append('<div class="warn-box">本批次含未经业务审核的场景（调试模式），结果不能作为回归结论。</div>')
    body.append(metrics([("场景总数", len(scs), ""), ("通过", c["passed"], "passed"), ("检查未通过", c["failed"], "failed"),
                         ("自动化未能完成", c["blocked"], "blocked"), ("没有检查点", c["invalid"], "blocked"),
                         ("未运行", c["skipped"], "skipped")]))
    if prev_id:
        body.append(f'<div class="card">和上一批次（{esc(prev_id)}）对比：新增失败 <b>{len(new_bad)}</b> 个，已恢复 <b>{len(fixed)}</b> 个。'
                    + (f'<br>新增失败：{esc("、".join(new_bad))}' if new_bad else "") + "</div>")
    body.append('<div class="sub" style="margin-top:12px">'
                + "　".join(f"{badge(k)} {esc(v)}" for k, v in MEANING.items() if c.get(k)) + "</div>")
    body.append('<h2>按模块</h2><div class="filter">'
                + "".join(f'<button data-f="{k}"{" class=on" if k == "all" else ""}>{t}</button>'
                          for k, t in [("all", "全部"), ("failed", "检查未通过"), ("blocked", "未能完成"),
                                       ("skipped", "未运行"), ("passed", "通过")])
                + '<input id="q" placeholder="搜索场景"></div>')
    modules: Dict[str, List[Dict[str, Any]]] = {}
    for s in scs:
        modules.setdefault(s["module"], []).append(s)
    for mod in sorted(modules, key=lambda m: (all(s["status"] == "passed" for s in modules[m]), m)):
        ms = modules[mod]
        mc = counts(ms)
        bad = mc["failed"] + mc["blocked"] + mc["invalid"]
        summary = f'{esc(mod)} <small>共 {len(ms)}　通过 {mc["passed"]}'
        for k in ("failed", "blocked", "invalid", "skipped"):
            if mc[k]:
                summary += f'　{STATUS_TEXT[k]} {mc[k]}'
        summary += "</small>"
        rows = ""
        for s in sorted(ms, key=lambda x: STATUS_ORDER.index(x["status"])):
            link = f'<a href="{esc(s["dir"])}/report.html">{esc(s["title"])}</a>' if s.get("dir") else esc(s["title"])
            note = esc(s.get("problem") or s.get("review") or "")
            if s.get("extensions"):
                note += ' <span class="badge info">用到工作区扩展</span>'
            text = esc(f'{s["title"]} {s["id"]}')
            rows += (f'<tr data-status="{s["status"]}" data-text="{text}"><td>{badge(s["status"])}</td>'
                     f'<td>{link}<div class="sub">{esc(s["id"])}</div></td>'
                     f'<td class="sub">{note}</td><td class="sub">{esc(_dur(s.get("duration_s")))}</td></tr>')
        body.append(f'<details class="mod"{" open" if bad else ""}><summary>{summary}</summary><div class="body">'
                    f'<table><tr><th style="width:130px">结果</th><th>场景</th><th>说明</th><th style="width:80px">耗时</th></tr>'
                    f'{rows}</table></div></details>')
    out = batch_dir / "report.html"
    out.write_text(page(title, "".join(body), _FILTER_JS), encoding="utf-8")
    return out


def write_batch(batch_dir: Path, batch: Dict[str, Any]) -> None:
    (batch_dir / "batch.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    write_batch_report(batch_dir, batch)


# --- 历史索引 ---
def write_index(results_root: Path, matrix_n: int = 10) -> Path:
    runs = Path(results_root) / "runs"
    body = ["<h1>测试结果历史</h1><div class=\"sub\">每次运行都是独立批次，历史结果不会被覆盖。</div>"]
    groups: Dict[Tuple[str, str], List[Tuple[Path, Dict[str, Any]]]] = {}
    for f in sorted(runs.glob("*/*/*/batch.json"), reverse=True) if runs.is_dir() else []:
        try:
            groups.setdefault((f.parents[2].name, f.parents[1].name), []).append((f.parent, json.loads(f.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    if not groups:
        body.append('<div class="card">还没有运行记录。</div>')
    for (proj, env), items in sorted(groups.items()):
        body.append(f"<h2>{esc(proj)} / {esc(env)}</h2><table><tr><th>批次</th><th>范围</th><th>开始</th>"
                    "<th>场景</th><th>通过</th><th>未通过</th><th>未能完成</th><th>未运行</th><th>对比上次</th></tr>")
        for i, (d, b) in enumerate(items):
            c = counts(b["scenarios"])
            prev = items[i + 1][1] if i + 1 < len(items) else None
            nb, fx, _ = _compare(b["scenarios"], prev)
            cmp_txt = f'新增失败 {len(nb)}，恢复 {len(fx)}' if prev else "首次"
            tag = " <small>（调试）</small>" if b.get("draft") else ""
            rel = d.relative_to(results_root)
            body.append(f'<tr><td><a href="{esc(str(rel))}/report.html">{esc(b["batch_id"])}</a>{tag}</td><td>{esc(b["scope"])}</td>'
                        f'<td>{esc(_fmt_time(b["started"]))}</td><td>{len(b["scenarios"])}</td><td>{c["passed"]}</td>'
                        f'<td>{c["failed"]}</td><td>{c["blocked"] + c["invalid"]}</td><td>{c["skipped"]}</td><td>{cmp_txt}</td></tr>')
        body.append("</table>")
        recent = items[:matrix_n]
        ids = sorted({s["id"]: s.get("title", s["id"]) for _, b in recent for s in b["scenarios"]}.items())
        if ids:
            body.append(f'<details><summary>最近 {len(recent)} 次每个场景的状态（最新在左）</summary><div class="body"><table>'
                        "<tr><th>场景</th><th>状态</th></tr>")
            for sid, title in ids:
                dots = ""
                for d, b in recent:
                    hit = next((s for s in b["scenarios"] if s["id"] == sid), None)
                    st = hit["status"] if hit else "none"
                    href = f'{d.relative_to(results_root)}/{hit["dir"]}/report.html' if hit and hit.get("dir") else ""
                    tip = esc(f'{b["batch_id"]} {STATUS_TEXT.get(st, "未包含")}')
                    dots += (f'<a href="{esc(href)}" title="{tip}"><span class="dot {st}"></span></a>' if href
                             else f'<span class="dot {st}" title="{tip}"></span>')
                body.append(f"<tr><td>{esc(title)}<div class=\"sub\">{esc(sid)}</div></td><td>{dots}</td></tr>")
            body.append("</table></div></details>")
    out = Path(results_root) / "index.html"
    out.write_text(page("测试结果历史", "".join(body)), encoding="utf-8")
    return out
