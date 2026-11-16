"""审核页和报告共用的 HTML 片段。生成的页面是单个文件，不依赖网络，浏览器直接打开。"""
from __future__ import annotations

import html
from typing import Iterable, Tuple

esc = html.escape

CSS = """
:root{--ok:#1a7f37;--bad:#cf222e;--warn:#b35900;--mute:#6e7781;--line:#d8dee4;--bg:#f6f8fa;--ink:#1f2328;--blue:#0969da}
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);background:var(--bg)}
main{max-width:1080px;margin:0 auto;padding:24px 20px 60px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.sub{color:var(--mute);font-size:13px}
.card{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px 18px;margin:10px 0}
.row{display:flex;flex-wrap:wrap;gap:12px}
.metric{flex:1;min-width:120px;background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.metric b{display:block;font-size:26px;line-height:1.2}.metric span{color:var(--mute);font-size:12px}
.metric b.passed{color:var(--ok);background:none}.metric b.failed{color:var(--bad);background:none}
.metric b.blocked{color:var(--warn);background:none}.metric b.skipped{color:var(--mute);background:none}
.badge{display:inline-block;padding:1px 9px;border-radius:10px;font-size:12px;font-weight:600;white-space:nowrap}
.passed{background:#dafbe1;color:var(--ok)}.failed{background:#ffebe9;color:var(--bad)}
.blocked{background:#fff1e5;color:var(--warn)}.invalid{background:#fff8c5;color:#7d4e00}
.skipped{background:#eaeef2;color:var(--mute)}.info{background:#ddf4ff;color:var(--blue)}
.check{background:#fff8c5;color:#7d4e00}.todo{background:#ffebe9;color:var(--bad)}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:8px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--bg);font-weight:600;font-size:13px}tr:last-child td{border-bottom:0}
tr.hl td{background:#fffbe6}tr.bad td{background:#fff5f5}
details{background:#fff;border:1px solid var(--line);border-radius:8px;margin:10px 0}
details>summary{cursor:pointer;padding:10px 16px;font-weight:600;list-style:none}
details>summary::-webkit-details-marker{display:none}
details>summary:before{content:"▸ ";color:var(--mute)}details[open]>summary:before{content:"▾ "}
details>.body{padding:0 16px 14px}
.warn-box{border:1px solid #d4a72c;background:#fff8c5;border-radius:8px;padding:10px 16px;margin:10px 0}
.err-box{border:1px solid #ff8182;background:#ffebe9;border-radius:8px;padding:10px 16px;margin:10px 0}
.shots img{max-width:260px;border:1px solid var(--line);border-radius:4px;margin:4px 6px 0 0;vertical-align:top}
.dot{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:2px;background:#d0d7de}
.dot.passed{background:#2da44e}.dot.failed{background:#cf222e}.dot.blocked{background:#e0872e}
.dot.invalid{background:#d4a72c}.dot.skipped{background:#d0d7de}
.filter button{border:1px solid var(--line);background:#fff;border-radius:14px;padding:2px 12px;margin-right:6px;cursor:pointer}
.filter button.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.filter input{border:1px solid var(--line);border-radius:6px;padding:3px 8px;margin-left:8px}
small{color:var(--mute)}
"""

STATUS_TEXT = {
    "passed": "通过",
    "failed": "检查未通过",
    "blocked": "自动化未能完成",
    "invalid": "没有检查点",
    "skipped": "未运行",
}


def badge(status: str, text: str | None = None) -> str:
    return f'<span class="badge {esc(status)}">{esc(text or STATUS_TEXT.get(status, status))}</span>'


def page(title: str, body: str, script: str = "") -> str:
    return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title>'
            f"<style>{CSS}</style></head><body><main>{body}</main>"
            f"{('<script>' + script + '</script>') if script else ''}</body></html>")


def metrics(items: Iterable[Tuple[str, "int | str", str]]) -> str:
    cells = "".join(f'<div class="metric"><b class="{esc(cls)}">{esc(str(v))}</b><span>{esc(k)}</span></div>'
                    for k, v, cls in items)
    return f'<div class="row">{cells}</div>'
