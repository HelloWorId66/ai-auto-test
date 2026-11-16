import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from ifcat.mcpdb import McpDbError, READ_ONLY_TOOLS, ReadOnlyMcpDb

CALLS = []
MODE = {"tree": False}


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        CALLS.append(body.get("method") + ":" + str(body.get("params", {}).get("name", "")))
        if body["method"] == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return
        if body["method"] == "initialize":
            result = {"protocolVersion": "2025-03-26"}
        else:
            name = body["params"]["name"]
            if name == "findFormEntries" and MODE["tree"]:
                payload = {"verityTreeEntries": {"data": [{"VTREE_BH": "000100010016" "0001", "TREE_BH": "home",
                           "VTREE_MC": "企业定存存入", "VTREE_FORM": "F1", "VTREE_GNBH": "ZJ0086"}]}}
                result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
            elif name == "readConfigRows":
                names = {"0001": "左侧菜单", "00010001": "企业业务", "000100010016": "企业定存_Panui", "0001000100160001": "企业定存"}
                got = body["params"]["arguments"]["filters"]["VTREE_BH"]
                payload = {"data": [{"VTREE_BH": k, "VTREE_MC": names[k]} for k in got if k in names]}
                result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
            else:
              payload = {"data": [{"TREE_BH": "home", "VTREE_MC": "企业定存存入", "VTREE_FORM": "F1",
                                 "VTREE_GNBH": "ZJ0086", "menuPath": "['企业定存存入']"}]} if name == "findMenuPaths" else {}
              result = {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "s1")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def server():
    CALLS.clear()
    srv = HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()


def test_write_tools_are_refused_without_any_request(server):
    db = ReadOnlyMcpDb(server)
    with pytest.raises(McpDbError):
        db.call("executeI18nChanges", {"changes": []})
    assert CALLS == []


def test_whitelist_has_no_write_style_names():
    assert not [t for t in READ_ONLY_TOOLS if t.lower().startswith(("execute", "write", "update", "delete", "insert"))]


def test_form_entries_roundtrip(server):
    rows = ReadOnlyMcpDb(server).form_entries("企业定存存入")
    assert rows == [{"tree": "home", "menu": "企业定存存入", "form": "F1", "function": "ZJ0086", "path": "['企业定存存入']"}]
    assert "tools/call:findMenuPaths" in CALLS


def test_missing_url_is_explained(monkeypatch):
    monkeypatch.delenv("IFCAT_DB_MCP_URL", raising=False)
    with pytest.raises(McpDbError, match="IFCAT_DB_MCP_URL"):
        ReadOnlyMcpDb()


def test_form_entry_path_is_completed_from_menu_number_prefixes(server):
    MODE["tree"] = True
    try:
        rows = ReadOnlyMcpDb(server).form_entries("F1")
    finally:
        MODE["tree"] = False
    assert rows[0]["path"] == ["企业业务", "企业定存_Panui", "企业定存"]
