#!/usr/bin/env python3
"""调用团队知识库 MCP 的一个工具（每次自动建会话）。

用法：IFCAT_KB_MCP_URL=<知识库 MCP 地址> python3 tools/kb_query.py <工具名> '<json 参数>' [最大字符数]
地址不写在代码里；日常由智能体通过自己的 MCP 设置直接调用，本脚本只用于没有 MCP 工具的场景。
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get("IFCAT_KB_MCP_URL", "")
if not URL or len(sys.argv) < 3:
    sys.exit(__doc__)
# 与框架其他工具一致：直连，不走系统代理（本机代理软件会让内网地址 502）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(body, sid=None):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    with OPENER.open(urllib.request.Request(URL, json.dumps(body).encode(), h), timeout=90) as r:
        return r.headers.get("Mcp-Session-Id"), r.read().decode()


def parse(text):
    text = text.strip()
    if text.startswith("{"):
        return json.loads(text)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])


sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "ifcat", "version": "1"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
_, out = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
               "params": {"name": sys.argv[1], "arguments": json.loads(sys.argv[2])}}, sid)
d = parse(out)
if "error" in d:
    print(d["error"])
for c in d.get("result", {}).get("content", []):
    print(c.get("text", "")[: int(sys.argv[3]) if len(sys.argv) > 3 else 6000])
