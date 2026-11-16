"""智能体用的测试库只读查询小工具（经 MCP，白名单只读）。

用法：
  python tools/db_mcp.py entries <功能号|菜单名|表单ID>       找菜单入口
  python tools/db_mcp.py messages <表单ID|功能号|文字>        找系统提示消息（核心异常预期文案）
  python tools/db_mcp.py columns <业务表名>                    每列的中文含义（写数据库检查点前先看）
  python tools/db_mcp.py mask <掩码key>                       下拉选项
  python tools/db_mcp.py call <工具名> '<JSON参数>'           其他只读工具
地址：环境变量 IFCAT_DB_MCP_URL。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))
from ifcat.mcpdb import McpDbError, ReadOnlyMcpDb  # noqa: E402


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    cmd, arg = argv[1], argv[2]
    try:
        db = ReadOnlyMcpDb()
        if cmd == "entries":
            out = db.form_entries(arg)
        elif cmd == "messages":
            out = db.messages(arg)
        elif cmd == "columns":
            out = db.table_columns(arg)
        elif cmd == "mask":
            out = db.mask_options(arg)
        elif cmd == "call":
            out = db.call(arg, json.loads(argv[3]) if len(argv) > 3 else {})
        else:
            print(__doc__)
            return 2
    except McpDbError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
