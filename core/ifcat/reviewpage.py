"""把一个功能的全部场景渲染成给业务人员审核的 HTML 页面。

业务人员看的是：这个功能有哪些场景、各自要保证什么、依据是什么、前提、每一步谁做什么、检查点是什么、
哪些内容还没有确认。页面里不出现代码；技术字段名通过场景的 labels 换成业务名称。
没有功能分组的单个场景，用同一个页面渲染成只有一个场景的功能。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .htmlkit import badge, esc, page
from .scenario import CHECKPOINT_STEPS, Scenario, describe_date_macro

_VAR = re.compile(r"\$\{([^}]+)\}")

_DO_TEXT = {
    "open": "打开", "fill": "填写", "fill_grid": "填写表格", "save": "保存", "submit": "提交审批",
    "approve": "同意", "reject": "退回", "pick_record": "选择记录", "expect_query": "检查查询结果", "expect_not_listed": "检查选不到", "capture_field": "记录字段值", "capture_db": "从数据库记录单据信息",
    "expect_field": "检查界面", "expect_flow_completed": "检查流程办结", "expect_grid": "检查表格",
    "expect_db_status": "检查单据状态", "expect_db_result": "检查业务结果", "expect_db_record": "检查数据库记录",
    "edit": "点编辑修改", "open_todo": "在待办里打开单据", "submit_with_warning": "提交并检查提示",
    "approve_blocked": "同意被拦截", "expect_visible": "检查是否显示",
}
_REVIEW_CLS = {"approved": "passed", "unreviewed": "skipped", "changed": "blocked"}

PAGE_CSS = """
<style>
.hero{background:linear-gradient(135deg,#0b3d91,#1565c0);color:#fff;border-radius:12px;padding:22px 26px;margin-bottom:16px}
.hero h1{color:#fff;font-size:24px}.hero .sub{color:#d6e4ff}
.hero .stats{display:flex;gap:28px;margin-top:14px}.hero .stats b{font-size:24px;display:block;line-height:1.1}
.hero .stats span{font-size:12px;color:#d6e4ff}
.ask{border-left:5px solid #cf222e;background:#fff;border-radius:8px;padding:12px 18px;margin:14px 0;box-shadow:0 1px 2px rgba(0,0,0,.05)}
.ask h3{margin:0 0 6px;font-size:15px;color:#cf222e}.ask li{margin:3px 0}.ask small{color:#6e7781}
.sc{background:#fff;border:1px solid var(--line);border-radius:12px;margin:22px 0;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.sc-h{padding:16px 22px;border-bottom:1px solid var(--line);background:#fbfcfe}
.sc-h h2{margin:0 0 4px;font-size:18px}.sc-b{padding:6px 22px 20px}
.kv{display:grid;grid-template-columns:90px 1fr;gap:4px 14px;margin:10px 0}.kv dt{color:var(--mute)}.kv dd{margin:0}
.kv ul{margin:0;padding-left:18px}
.kind{display:inline-block;white-space:nowrap;border-radius:4px;padding:0 8px;font-size:12px;font-weight:600;margin-right:6px}
.kind.main{background:#ddf4ff;color:#0969da}.kind.exc{background:#ffeff7;color:#bf3989}.kind.oth{background:#eaeef2;color:#57606a}
.lane{display:grid;gap:0 14px;align-items:start;margin-top:10px}
.lane .head{font-weight:700;text-align:center;padding:6px;border-radius:6px;background:#eef3fb;color:#0b3d91;margin-bottom:8px}
.lane .no{display:flex;justify-content:center;position:relative;height:100%}
.lane .no i{width:26px;height:26px;border-radius:50%;background:#0b3d91;color:#fff;font-style:normal;text-align:center;line-height:26px;
 font-size:12px;font-weight:700;z-index:1}
.lane .no.chk i{background:#d4a72c;color:#1f2328}
.lane .no:before{content:"";position:absolute;top:0;bottom:-12px;width:2px;background:#d0d7de}
.lane .cell{padding:0 0 12px}
.card2{border:1px solid var(--line);border-radius:8px;padding:8px 12px;background:#fff}
.card2.chk{background:#fffbe6;border-color:#d4a72c}
.card2 .tag{font-size:12px;font-weight:700;color:#7d4e00;margin-right:6px}
.card2 .data{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px 6px}
.card2 .data span{background:#f3f4f6;border-radius:4px;padding:0 7px;font-size:12px}
.card2 .data span b{color:var(--mute);font-weight:500}
.card2 .expect{margin-top:4px;color:#7d4e00;font-size:13px}
.toc a{display:block;padding:2px 0}
.note{background:#fff;border:1px dashed var(--line);border-radius:8px;padding:10px 16px;margin-top:18px;color:#57606a}
</style>
"""


def _label(key: str, sc: Scenario) -> str:
    return sc.labels.get(key, key)


def _show(value: Any, sc: Scenario) -> str:
    """把 ${data.x} 换成实际数据，${captured.x} 说明是运行时才知道的值。"""
    if isinstance(value, dict):
        return "；".join(f"{_label(k, sc)}：{_show(v, sc)}" for k, v in value.items())
    if isinstance(value, list):
        return "、".join(_show(v, sc) for v in value)

    def sub(m: "re.Match[str]") -> str:
        parts = m.group(1).split(".")
        if parts[0] == "data":
            cur: Any = sc.data
            for p in parts[1:]:
                cur = cur.get(p, "?") if isinstance(cur, dict) else "?"
            return describe_date_macro(str(cur))
        if parts[0] == "captured":
            return f"〔运行时取得的「{_label(parts[-1], sc)}」〕"
        return m.group(0)

    return _VAR.sub(sub, str(value))


def _detail(s: Any, sc: Scenario) -> str:
    a: Dict[str, Any] = s.args
    if s.do == "fill":
        chips = "".join(f"<span><b>{esc(_label(k, sc))}</b> {esc(_show(v, sc))}</span>" for k, v in a["values"].items())
        return f'<div class="data">{chips}</div>'
    if s.do == "expect_field":
        return f'<div class="expect">「{esc(_label(a["label"], sc))}」应为 <b>{esc(_show(a["expected"], sc))}</b></div>'
    if s.do == "expect_visible":
        return (f'<div class="expect">「{esc(_label(a["label"], sc))}」应'
                f'{"显示" if a["visible"] else "不显示"}</div>')
    if s.do == "submit_with_warning":
        return (f'<div class="expect">系统应弹出提示，内容包含「{esc(_show(a["warning"], sc))}」；'
                f'确认后点「{esc(str(a["then"]))}」</div>')
    if s.do == "approve_blocked":
        return (f'<div class="expect">同意应被拦截，提示包含「{esc(_show(a["message"], sc))}」，单据仍留在待办</div>'
                f'<div class="sub">单据：{esc(_show(a["bill"], sc))}</div>')
    if s.do in ("reject", "open_todo"):
        return f'<div class="sub">单据：{esc(_show(a["bill"], sc))}</div>'
    if s.do == "capture_field":
        return f'<div class="sub">记下「{esc(_label(a["label"], sc))}」，后面步骤要用</div>'
    if s.do == "capture_db":
        return f'<div class="sub">从数据库记下「{esc(_label(a["name"], sc))}」，后面步骤要用</div>'
    if s.do in ("approve", "expect_flow_completed"):
        return f'<div class="sub">单据：{esc(_show(a["bill"], sc))}</div>'
    if s.do in ("fill_grid", "expect_grid"):
        return f'<div class="sub">表格「{esc(_label(a["grid"], sc))}」：{esc(_show(a["rows"], sc))}</div>'
    if s.do == "expect_db_status":
        st = str(a["state"])
        st = f"不是「{_label(st[4:], sc)}」" if st.startswith("not:") else f"「{_label(st, sc)}」"
        return f'<div class="expect">数据库里单据状态应为{esc(st)}</div>'
    if s.do == "expect_db_record":
        what = _label(str(a["table"]), sc)
        if a.get("absent"):
            return f'<div class="expect">数据库里不应生成「{esc(what)}」</div>'
        exp = a.get("expect") or {}
        # 库里存的是代码值（如到期指示 3），labels 里写「列名=值」可换成业务名称
        chips = "".join(f"<span><b>{esc(_label(k, sc))}</b> {esc(_label(f'{k}={v}', sc) if f'{k}={v}' in sc.labels else _show(v, sc))}</span>"
                        for k, v in exp.items())
        wait = f'<div class="sub">后台异步生成，最多等待 {int(a["wait"])} 秒</div>' if a.get("wait") else ""
        return f'<div class="expect">数据库里应已生成「{esc(what)}」</div><div class="data">{chips}</div>{wait}'
    if s.do == "pick_record":
        return f'<div class="sub">在选择弹窗里选「{esc(_show(a["find"], sc))}」并确定</div>'
    if s.do == "expect_not_listed":
        return f'<div class="expect">选择弹窗里不应该出现「{esc(_show(a["find"], sc))}」</div>'
    if s.do == "expect_query":
        cond = "".join(f"<span><b>{esc(_label(str(k), sc))}</b> {esc(_show(v, sc))}</span>" for k, v in (a.get("conditions") or {}).items())
        out = f'<div class="sub">查询条件</div><div class="data">{cond}</div>'
        for want in a.get("rows") or []:
            chips = "".join(f"<span><b>{esc(str(k))}</b> {esc(_show(v, sc))}</span>" for k, v in want.items())
            out += f'<div class="expect">查询结果里应有一行</div><div class="data">{chips}</div>'
        if a.get("count") is not None:
            out += f'<div class="expect">查询结果应为 {int(a["count"])} 行</div>'
        return out
    if s.do == "expect_db_result":
        return f'<div class="expect">业务结果「{esc(str(a["result"]))}」应已生成</div>'
    return ""


def _list(items: List[str]) -> str:
    return "<ul>" + "".join(f"<li>{esc(str(i))}</li>" for i in items) + "</ul>"


def _kind_chip(kind: str) -> str:
    cls = {"主流程": "main", "核心异常": "exc"}.get(kind, "oth")
    return f'<span class="kind {cls}">{esc(kind)}</span>'


def _swimlane(sc: Scenario) -> str:
    roles: List[str] = []
    for s in sc.steps:
        r = s.role or ""
        if r not in roles:
            roles.append(r)
    cols = f"34px repeat({len(roles)}, minmax(0,1fr))"
    out = [f'<div class="lane" style="grid-template-columns:{cols}"><div></div>']
    out += [f'<div class="head">{esc(sc.roles.get(r, r) or "—")}</div>' for r in roles]
    for i, s in enumerate(sc.steps, 1):
        chk = s.do in CHECKPOINT_STEPS
        out.append(f'<div class="no {"chk" if chk else ""}"><i>{i}</i></div>')
        for r in roles:
            if (s.role or "") == r:
                mark = '<span class="tag">✓ 检查点</span>' if chk else ""
                out.append(f'<div class="cell"><div class="card2 {"chk" if chk else ""}">{mark}'
                           f'{esc(s.text or _DO_TEXT[s.do])}{_detail(s, sc)}</div></div>')
            else:
                out.append('<div class="cell"></div>')
    out.append("</div>")
    return "".join(out)


def _scenario_section(sc: Scenario, state: Any, idx: int) -> str:
    checks = sum(1 for s in sc.steps if s.do in CHECKPOINT_STEPS)
    body = [f'<section class="sc" id="sc{idx}"><div class="sc-h"><h2>{_kind_chip(sc.kind)}{esc(sc.title)}</h2>'
            f'<div class="sub">场景编号 {esc(sc.id)} · {len(sc.steps)} 步，{checks} 个检查点 · '
            f'{badge(_REVIEW_CLS[state.status], state.describe())}'
            + (f" · 对应需求 {esc(sc.requirement)}" if sc.requirement else "")
            + (f" · 增量场景，基于「{esc(sc.extends)}」" if sc.extends else "") + "</div></div><div class=\"sc-b\">"]
    body.append('<dl class="kv">')
    body.append(f"<dt>要保证什么</dt><dd>{esc(sc.goal) if sc.goal else '<span class=sub>未填写</span>'}</dd>")
    if sc.source:
        body.append(f"<dt>依据</dt><dd>{_list(sc.source)}</dd>")
    body.append(f"<dt>前提</dt><dd>{_list(sc.preconditions) if sc.preconditions else '无'}</dd>")
    body.append("</dl>")
    body.append(_swimlane(sc))
    body.append("</div></section>")
    return "".join(body)


def render_feature_html(items: List[Tuple[Scenario, Any]]) -> str:
    """items：同一功能下的（场景，审核状态）。"""
    first = items[0][0]
    title = first.feature or first.title
    n_chk = sum(1 for sc, _ in items for s in sc.steps if s.do in CHECKPOINT_STEPS)
    approved = sum(1 for _, st in items if st.approved)
    hero = (f'<div class="hero"><div class="sub">模块 {esc(first.module)} · 用例审核</div><h1>{esc(title)}</h1>'
            f'<div class="stats"><div><b>{len(items)}</b><span>个业务场景</span></div>'
            f'<div><b>{n_chk}</b><span>个检查点</span></div>'
            f'<div><b>{approved}/{len(items)}</b><span>已审核</span></div></div></div>')
    parts = [hero]
    if len(items) > 1 or first.feature:
        rows = "".join(
            f'<tr><td>{_kind_chip(sc.kind)}</td><td><a href="#sc{i}">{esc(sc.title)}</a>'
            f'<div class="sub">{esc(sc.goal)}</div></td>'
            f'<td>{sum(1 for s in sc.steps if s.do in CHECKPOINT_STEPS)}</td>'
            f'<td>{badge(_REVIEW_CLS[st.status], st.describe())}</td></tr>'
            for i, (sc, st) in enumerate(items))
        parts.append('<h2>这个功能覆盖的场景</h2><table><tr><th style="width:90px">类型</th><th>场景</th>'
                     f'<th style="width:70px">检查点</th><th style="width:230px">审核状态</th></tr>{rows}</table>')
    asks = [(sc.title, u) for sc, _ in items for u in sc.unconfirmed]
    if asks:
        li = "".join(f"<li>{esc(u)} <small>（{esc(t)}）</small></li>" for t, u in asks)
        parts.append(f'<div class="ask"><h3>请先确认这些问题（目前没有证据，我不会替你定）</h3><ul>{li}</ul></div>')
    for i, (sc, st) in enumerate(items):
        parts.append(_scenario_section(sc, st, i))
    parts.append('<div class="note"><b>请重点看：</b>步骤是不是真实用户会走的？检查点是不是你真正关心的？'
                 '这个功能还有没有漏掉的核心场景？审核结果直接告诉智能体（「通过」或要改的地方），由它记录。</div>')
    return page(f"审核：{title}", "".join(parts)).replace("</head>", PAGE_CSS + "</head>", 1)


def render_review_html(sc: Scenario, review_state: Any) -> str:
    return render_feature_html([(sc, review_state)])


def review_page_name(sc: Scenario) -> str:
    """审核页文件名：有功能分组按「模块-功能」，否则按场景编号。"""
    name = f"{sc.module}-{sc.feature}" if sc.feature else sc.id
    return name.replace("/", "_") + ".html"
