"""从 IFC 业务代码里自动提取任意流程的单据头模型，生成项目状态模型骨架。

依据：每个流程类继承 FlowMovementAbstract，并在 initParam() 里声明
单据头表、主键列、状态列（见 docs/exploration/PanUI产品操作规约.md）。流程编号即类名。

用法：
  python tools/discover_bill.py --root <代码根目录> FLOW_NO [FLOW_NO ...]
  python tools/discover_bill.py --root <代码根目录> --list [--module DP]
只读代码，不连数据库。输出是骨架：结果表（审批完成后写入的业务表）需要人工或智能体读
processSubmitToEnd 补充，工具不猜。
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

_SETTERS = {
    "setBillHeadTable": "head_table",
    "setGuidField": "key_col",
    "setBillStatusField": "status_col",
    "setBillBranchField": "branch_col",
    "setOperationDateField": "date_col",
}
_SET_RE = re.compile(r"param\w*\.(set\w+)\(\s*\"([^\"]+)\"\s*\)")
_NULL_STATUS_RE = re.compile(r"setBillStatusField\(\s*null\s*\)")
_CLASS_RE = re.compile(r"class\s+(\w+)\s+extends\s+FlowMovementAbstract")
_DOC_RE = re.compile(r"/\*\*\s*\n?\s*\*\s*([^\n*@]+)")


@dataclass
class Found:
    flow_no: str
    path: Path
    module: str
    title: str
    fields: Dict[str, str]

    @property
    def complete(self) -> bool:
        return all(k in self.fields for k in ("head_table", "key_col", "status_col")) and not self.status_null

    @property
    def status_null(self) -> bool:
        return self.fields.get("status_null") == "1"


def _module_of(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).parts[0]
    except ValueError:
        return ""


def scan(root: Path) -> List[Found]:
    out: List[Found] = []
    for p in root.rglob("*.java"):
        if "/test/" in p.as_posix():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = _CLASS_RE.search(text)
        if not m:
            continue
        fields: Dict[str, str] = {}
        for setter, value in _SET_RE.findall(text):
            if setter in _SETTERS:
                fields.setdefault(_SETTERS[setter], value)
        if "status_col" not in fields and _NULL_STATUS_RE.search(text):
            fields["status_col"] = ""
            fields["status_null"] = "1"
        doc = _DOC_RE.search(text[: m.start()][-400:])
        out.append(Found(m.group(1), p, _module_of(p, root), doc.group(1).strip() if doc else "", fields))
    return out


def to_yaml(f: Found, root: Path) -> str:
    rel = f.path.relative_to(root).as_posix() if f.path.is_relative_to(root) else str(f.path)
    lines = [
        f"  {f.flow_no}:",
        f"    name: {f.title or f.flow_no}",
        f"    # 来源：{rel}（initParam）",
    ]
    for key in ("head_table", "key_col", "status_col"):
        note = ""
        if key not in f.fields:
            note = "   # 未能从代码提取，需人工确认"
        elif key == "status_col" and f.status_null:
            note = "   # 代码显式设为 null：基类不维护单据头状态，不能用「状态=3」判断审批完成，需另找完成标志"
        lines.append(f"    {key}: {f.fields.get(key, '')}{note}")
    lines += [
        "    results: {}   # 待补：读 processSubmitToEnd，找出审批完成后写入的业务表及关联列",
        "    states: {}    # 待补：业务自定义状态别名，值取自代码常量；通用态 1/2/3/4 已内置",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="代码根目录，如 .../01.ifc/00.code")
    ap.add_argument("--list", action="store_true", help="列出所有流程及提取完整度")
    ap.add_argument("--module", help="与 --list 合用，按模块代号过滤，如 DP")
    ap.add_argument("flows", nargs="*", help="流程编号（类名）")
    args = ap.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    found = scan(root)

    if args.list:
        rows = [f for f in found if not args.module or f.module == args.module]
        for f in sorted(rows, key=lambda x: (x.module, x.flow_no)):
            print(f"{f.module:4} {f.flow_no:48} {f.fields.get('head_table', '-'):24} "
                  f"{(f.fields.get('status_col') or ('(null)' if f.status_null else '-')):16} "
                  f"{'完整' if f.complete else ('状态列为null' if f.status_null else '不完整')}")
        done = sum(1 for f in rows if f.complete)
        print(f"\n共 {len(rows)} 个流程，提取完整 {done} 个", file=sys.stderr)
        return 0

    if not args.flows:
        ap.error("请给出流程编号，或使用 --list")
    index = {f.flow_no: f for f in found}
    print("bills:")
    code = 0
    for no in args.flows:
        f = index.get(no)
        if f is None:
            print(f"  # 找不到流程 {no}：代码根目录下没有继承 FlowMovementAbstract 的同名类", file=sys.stderr)
            code = 1
            continue
        print(to_yaml(f, root))
    return code


if __name__ == "__main__":
    sys.exit(main())
