"""用例设计：做自动化之前，先用业务话把「测什么、怎么测、预期是什么」定下来，请业务人员确认。

用例设计写成 scenarios/<模块>/<功能>/用例设计.yaml，渲染成 HTML 审核页给业务人员看。
这里面没有任何技术内容，也不被引擎执行；确认之后才据此写场景文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .htmlkit import esc, page
from .reviewpage import PAGE_CSS
from .workspace import DESIGN_FILE as FILE_NAME

DESIGN_CSS = """
<style>
.steps th:nth-child(1){white-space:nowrap}.steps td:nth-child(1){width:52px;text-align:center;color:var(--mute)}
.steps td:nth-child(2){width:110px;font-weight:600;color:#0b3d91}
.steps td:nth-child(4){background:#fffbe6;width:42%}
.chips{display:flex;flex-wrap:wrap;gap:4px 6px}.chips span{background:#f3f4f6;border-radius:4px;padding:0 7px;font-size:13px}
.chips span b{color:var(--mute);font-weight:500}
.yes{color:var(--ok)}.no{color:var(--bad);font-weight:600}
</style>
"""


class DesignError(Exception):
    pass


def find_design(scenarios_dir: Path, target: str) -> Path:
    """target 可以是用例设计文件、功能目录，或「模块/功能」。"""
    for cand in (Path(target), scenarios_dir / target):
        if cand.is_file():
            return cand
        if (cand / FILE_NAME).is_file():
            return cand / FILE_NAME
    raise DesignError(f"找不到用例设计：{target}（应该是 scenarios/<模块>/<功能>/{FILE_NAME}）")


def _text(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _items(v: Any) -> List[str]:
    if v is None:
        return []
    return [_text(i) for i in v if _text(i)] if isinstance(v, list) else [_text(v)]


def load_design(path: Path) -> Dict[str, Any]:
    try:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise DesignError(f"{path.name} 不是合法的 YAML：{exc}") from exc
    if not isinstance(d, dict):
        raise DesignError(f"{path.name} 内容为空或格式不对")
    errors: List[str] = []
    for key in ("module", "feature"):
        if not _text(d.get(key)):
            errors.append(f"缺少 {key}")
    cases = d.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases 里至少要有一条用例")
        cases = []
    for i, c in enumerate(cases, 1):
        name = f"第 {i} 条用例"
        if not isinstance(c, dict):
            errors.append(f"{name} 格式不对")
            continue
        for key in ("title", "kind", "goal"):
            if not _text(c.get(key)):
                errors.append(f"{name} 缺少 {key}")
        steps = c.get("steps")
        if not isinstance(steps, list) or not steps:
            errors.append(f"{name} 没有步骤")
            continue
        for j, s in enumerate(steps, 1):
            if not isinstance(s, dict) or not _text(s.get("who")) or not _text(s.get("do")):
                errors.append(f"{name} 第 {j} 步要写明 who（谁）和 do（做什么）")
        if not any(isinstance(s, dict) and _text(s.get("expect")) for s in steps):
            errors.append(f"{name} 没有任何一步写了 expect（预期结果）")
    for i, r in enumerate(d.get("rules") or [], 1):
        if not isinstance(r, dict) or not _text(r.get("rule")) or not _text(r.get("source")):
            errors.append(f"第 {i} 条业务规则要写明 rule（规则）和 source（依据）")
    if errors:
        raise DesignError(f"{path.name} 还不完整：\n- " + "\n- ".join(errors))
    return d


def _kind_chip(kind: str) -> str:
    cls = {"主流程": "main", "核心异常": "exc"}.get(kind, "oth")
    return f'<span class="kind {cls}">{esc(kind)}</span>'


def _list(items: List[str]) -> str:
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>" if items else "无"


def _case_section(c: Dict[str, Any], idx: int) -> str:
    data = c.get("data") or {}
    chips = "".join(f"<span><b>{esc(_text(k))}</b> {esc(_text(v))}</span>" for k, v in data.items()) if isinstance(data, dict) \
        else "".join(f"<span>{esc(i)}</span>" for i in _items(data))
    rows = "".join(
        f"<tr><td>{n}</td><td>{esc(_text(s.get('who')))}</td><td>{esc(_text(s.get('do')))}</td>"
        f"<td>{esc(_text(s.get('expect'))) or '<span class=sub>—</span>'}</td></tr>"
        for n, s in enumerate(c["steps"], 1))
    return (f'<section class="sc" id="case{idx}"><div class="sc-h"><h2>{_kind_chip(_text(c["kind"]))}'
            f'用例 {idx}：{esc(_text(c["title"]))}</h2></div><div class="sc-b"><dl class="kv">'
            f'<dt>要保证什么</dt><dd>{esc(_text(c["goal"]))}</dd>'
            f'<dt>前提</dt><dd>{_list(_items(c.get("preconditions")))}</dd>'
            f'<dt>测试数据</dt><dd><div class="chips">{chips or "无"}</div></dd></dl>'
            f'<table class="steps"><tr><th>步骤</th><th>谁</th><th>做什么</th><th>预期结果</th></tr>{rows}</table>'
            f"</div></section>")


def render_design_html(d: Dict[str, Any]) -> str:
    cases: List[Dict[str, Any]] = d["cases"]
    rules: List[Dict[str, Any]] = d.get("rules") or []
    questions = _items(d.get("questions"))
    skipped: List[Dict[str, Any]] = [x for x in (d.get("not_tested") or []) if isinstance(x, dict)]
    parts = [
        f'<div class="hero"><div class="sub">模块 {esc(_text(d["module"]))} · 用例设计（确认后才开始做自动化）</div>'
        f'<h1>{esc(_text(d["feature"]))}</h1><div class="stats">'
        f'<div><b>{len(cases)}</b><span>条用例</span></div><div><b>{len(rules)}</b><span>条业务规则</span></div>'
        f'<div><b>{len(questions)}</b><span>个问题请你确认</span></div></div></div>']
    about = [(k, _text(d.get(f))) for k, f in (("功能入口", "menu"), ("审批怎么走", "flow"), ("测试环境", "env")) if _text(d.get(f))]
    roles = d.get("roles") or {}
    if isinstance(roles, dict) and roles:
        about.insert(1, ("谁来用", "；".join(f"{k}：{_text(v)}" for k, v in roles.items())))
    if about:
        parts.append('<div class="card"><dl class="kv">' + "".join(f"<dt>{esc(k)}</dt><dd>{esc(v)}</dd>" for k, v in about)
                     + "</dl></div>")
    if questions:
        parts.append('<div class="ask"><h3>请先确认这些问题（目前没有证据，我不会替你定）</h3><ul>'
                     + "".join(f"<li>{esc(q)}</li>" for q in questions) + "</ul></div>")
    toc = "".join(f'<tr><td>{_kind_chip(_text(c["kind"]))}</td><td><a href="#case{i}">{esc(_text(c["title"]))}</a>'
                  f'<div class="sub">{esc(_text(c["goal"]))}</div></td><td>{len(c["steps"])}</td></tr>'
                  for i, c in enumerate(cases, 1))
    parts.append('<h2>准备测的用例</h2><table><tr><th style="width:90px">类型</th><th>用例</th>'
                 f'<th style="width:60px">步骤</th></tr>{toc}</table>')
    if rules:
        rows = "".join(f"<tr><td>{esc(_text(r.get('id')) or f'R{i}')}</td><td>{esc(_text(r['rule']))}</td>"
                       f"<td>{esc(_text(r['source']))}</td><td>{esc(_text(r.get('verified')) or '未核实')}</td></tr>"
                       for i, r in enumerate(rules, 1))
        parts.append('<h2>业务规则和依据</h2><table><tr><th style="width:56px">编号</th><th>规则</th>'
                     f'<th style="width:26%">依据</th><th style="width:20%">在真实页面上核实了吗</th></tr>{rows}</table>')
    parts += [_case_section(c, i) for i, c in enumerate(cases, 1)]
    if skipped:
        rows = "".join(f"<tr><td>{esc(_text(x.get('what')))}</td><td>{esc(_text(x.get('why')))}</td></tr>" for x in skipped)
        parts.append(f"<h2>这次不测的</h2><table><tr><th>不测什么</th><th>为什么</th></tr>{rows}</table>")
    parts.append('<div class="note"><b>请重点看：</b>这几条用例是不是你们日常真正会走的？有没有漏掉的核心场景？'
                 '每一步的预期结果对不对？确认或要改的地方直接告诉智能体。<b>你确认之后，才会开始做自动化。</b></div>')
    return page(f"用例设计：{_text(d['feature'])}", "".join(parts)).replace("</head>", PAGE_CSS + DESIGN_CSS + "</head>", 1)


def design_page_name(d: Dict[str, Any]) -> str:
    return f"{_text(d['module'])}-{_text(d['feature'])}-用例设计.html".replace("/", "_")
