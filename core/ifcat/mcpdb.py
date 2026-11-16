"""测试库（配置元数据库）MCP 的只读客户端。

该 MCP 服务同时带写工具（如 executeI18nChanges），所以这里用**白名单**：只有明确列出的只读查询工具能被调用，
其余一律拒绝，不靠工具名猜。地址来自环境变量 IFCAT_DB_MCP_URL，不写死在代码里。直连、不走系统代理（本机代理软件会让内网地址 502）。
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, Optional

URL_ENV = "IFCAT_DB_MCP_URL"

READ_ONLY_TOOLS = frozenset({
    "health", "findMenus", "findMenuPaths", "findFormEntries", "findFlows", "findMessages", "findMasks",
    "getMaskDetail", "getFieldDetail", "findObjects", "findModels", "findNumberRules", "describeConfigTable",
    "readConfigRows", "readConfigLob", "snapshotFeature", "findCustomQueries", "findSystemVariables",
    "findBusinessVariables", "findVariableCategories", "findBusinessLabels", "findBusinessAbstractConfigs",
    "findBusinessReminders", "findAutoTasks", "findCommQueryConfigs", "findMailTemplates", "findFormI18n",
    "findMlangData", "readFlowI18n", "readQueryI18n", "auditFormI18n", "findI18nGlossary",
    "findMaxMessageId", "findMaxMaskSequence", "findMaxBusinessLabelNo", "findMaxBusinessReminderId",
    "i18nWriteCapabilities",
})


class McpDbError(Exception):
    pass


class ReadOnlyMcpDb:
    def __init__(self, url: Optional[str] = None, timeout: float = 60.0):
        self.url = url or os.environ.get(URL_ENV, "")
        if not self.url:
            raise McpDbError(f"没有配置测试库 MCP 地址：请设置环境变量 {URL_ENV}")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._sid: Optional[str] = None
        self._next_id = 1

    def _post(self, body: Dict[str, Any]) -> "tuple[Optional[str], str]":
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._sid:
            headers["Mcp-Session-Id"] = self._sid
        req = urllib.request.Request(self.url, json.dumps(body).encode("utf-8"), headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as r:
                return r.headers.get("Mcp-Session-Id"), r.read().decode("utf-8")
        except Exception as exc:
            raise McpDbError(f"测试库 MCP 访问失败：{type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        text = text.strip()
        if text.startswith("{"):
            return json.loads(text)
        for line in text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        raise McpDbError("测试库 MCP 返回了无法解析的内容")

    def _init(self) -> None:
        if self._sid:
            return
        sid, _ = self._post({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "ifc-autotest", "version": "1"}}})
        self._sid = sid
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        except McpDbError:
            pass

    def call(self, tool: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        if tool not in READ_ONLY_TOOLS:
            raise McpDbError(f"工具 {tool} 不在只读白名单内，拒绝调用（测试库 MCP 带有写工具，框架只允许查询）")
        self._init()
        self._next_id += 1
        _, text = self._post({"jsonrpc": "2.0", "id": self._next_id, "method": "tools/call",
                              "params": {"name": tool, "arguments": arguments or {}}})
        msg = self._parse(text)
        if "error" in msg:
            raise McpDbError(f"{tool} 返回错误：{msg['error']}")
        parts = [c.get("text", "") for c in msg.get("result", {}).get("content", [])]
        raw = "\n".join(parts)
        try:
            return json.loads(raw)
        except ValueError:
            return raw

    def form_entries(self, keyword: str, limit: int = 50) -> list:
        """按功能号、菜单名、表单 ID 找菜单入口，返回每个入口的树、功能号、表单 ID、菜单路径。"""
        # 表单 ID 走 findFormEntries；中文菜单名走 findMenuPaths
        res = self.call("findFormEntries", {"keyword": keyword, "limit": limit})
        rows = ((res.get("verityTreeEntries") or {}).get("data") or []) if isinstance(res, dict) else []
        if not rows:
            res = self.call("findMenuPaths", {"keyword": keyword, "limit": limit})
            rows = res.get("data", []) if isinstance(res, dict) else []
        return [{"tree": r.get("TREE_BH"), "menu": r.get("VTREE_MC"), "form": r.get("VTREE_FORM"),
                 "function": r.get("VTREE_GNBH"), "path": self._menu_path(r)} for r in rows]

    def _menu_path(self, row: Dict[str, Any]) -> list:
        """菜单编号每 4 位是一层，前缀就是各级父菜单。React 表单入口的父子关系没填在父节点列里，
        只能按编号前缀逐级取名字。第一层是树根（如「左侧菜单」），界面上不显示，去掉。"""
        bh, tree = str(row.get("VTREE_BH") or ""), row.get("TREE_BH")
        if len(bh) < 8 or not tree:
            return row.get("menuPath") or [row.get("VTREE_MC")]
        prefixes = [bh[:i] for i in range(4, len(bh) + 1, 4)]
        res = self.call("readConfigRows", {"tableName": "SYS_VERITY_TREE", "columns": ["VTREE_BH", "VTREE_MC"],
                                           "filters": {"TREE_BH": [tree], "VTREE_BH": prefixes}})
        names = {r["VTREE_BH"]: r["VTREE_MC"] for r in (res.get("data") or [])} if isinstance(res, dict) else {}
        if not all(p in names for p in prefixes):
            return row.get("menuPath") or [row.get("VTREE_MC")]
        return [names[p] for p in prefixes[1:]]

    def messages(self, keyword: str, limit: int = 100) -> list:
        """按表单 ID、功能号或文字找系统提示消息（核心异常的预期文案取这里）。"""
        res = self.call("findMessages", {"keyword": keyword, "limit": limit})
        block = res.get("messages", {}) if isinstance(res, dict) else {}
        return [{"id": r.get("MESSAGE_ID"), "text": r.get("DEFAULT_MESSAGE"), "form": r.get("FORM_ID")}
                for r in block.get("data", [])]

    def table_columns(self, table: str) -> list:
        """业务表每一列的中文含义（来自平台元数据）。写数据库检查点前先看，别按列名猜。
        元数据只有名称和类型，没有代码值含义（如到期指示 1/3），值含义要看代码或对照真实数据。"""
        res = self.call("findObjects", {"tableName": table, "limit": 200})
        block = res.get("sysObjcols", {}) if isinstance(res, dict) else {}
        return [{"column": r.get("COL_ID"), "name": r.get("COL_MC"), "type": r.get("COL_TYPE")}
                for r in block.get("data", [])]

    def mask_options(self, mask_key: str) -> list:
        res = self.call("getMaskDetail", {"maskConfigKey": mask_key})
        rows = res.get("maskViewOptions", []) if isinstance(res, dict) else []
        rows = rows.get("data", []) if isinstance(rows, dict) else rows
        return [r.get("ITEM_NAME") for r in rows]
