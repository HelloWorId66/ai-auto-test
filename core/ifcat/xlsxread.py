"""读 .xlsx 的第一张表，只用标准库（不依赖 openpyxl，业务人员机器不用多装东西）。

查询页的结果表是画布渲染，界面上读不到文字，所以靠页面的「导出」拿到 Excel 再读。
"""
from __future__ import annotations

import re
import zipfile
from typing import Dict, List
from xml.etree import ElementTree as ET

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REF = re.compile(r"([A-Z]+)(\d+)")


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(el: ET.Element) -> str:
    return "".join(t.text or "" for t in el.iter(f"{{{_NS['m']}}}t"))


def read_first_sheet(path: str) -> List[List[str]]:
    """返回第一张表的所有行，每行是按列位置排好的字符串（空单元格为空串）。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared: List[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = [_text(si) for si in root.findall("m:si", _NS)]
        sheet = "xl/worksheets/sheet1.xml"
        if sheet not in names:
            cands = sorted(n for n in names if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
            if not cands:
                raise ValueError("Excel 里没有工作表")
            sheet = cands[0]
        root = ET.fromstring(z.read(sheet))
    rows: Dict[int, Dict[int, str]] = {}
    # 有的导出工具不写行号 r 和列号 r，按出现顺序推算
    next_row = 0
    for row in root.iter(f"{{{_NS['m']}}}row"):
        next_row = int(row.get("r")) if row.get("r") else next_row + 1
        next_col = 0
        for c in row.findall("m:c", _NS):
            m = _REF.fullmatch(c.get("r", ""))
            col = _col_index(m.group(1)) if m else next_col
            next_col = col + 1
            kind = c.get("t")
            v = c.find("m:v", _NS)
            if kind == "s":
                value = shared[int(v.text)] if v is not None and v.text else ""
            elif kind == "inlineStr":
                is_ = c.find("m:is", _NS)
                value = _text(is_) if is_ is not None else ""
            else:
                value = (v.text or "") if v is not None else ""
            rows.setdefault(next_row, {})[col] = value
    out: List[List[str]] = []
    for r in sorted(rows):
        cells = rows[r]
        if not cells:
            continue
        width = max(cells) + 1
        out.append([cells.get(i, "").strip() for i in range(width)])
    return out


def find_table(rows: List[List[str]], headers: List[str]) -> List[Dict[str, str]]:
    """找到包含全部给定表头的那一行当表头，其后的行转成 {表头: 值}。
    表头行上方的标题、条件说明，以及下方的合计/小计行会被跳过。"""
    for i, row in enumerate(rows):
        if all(h in row for h in headers):
            cols = {name: idx for idx, name in enumerate(row) if name}
            data: List[Dict[str, str]] = []
            for r in rows[i + 1:]:
                rec = {name: (r[idx] if idx < len(r) else "") for name, idx in cols.items()}
                if not any(rec.values()):
                    continue
                first = r[min(cols.values())] if r else ""
                if not first and not rec.get(headers[0]):
                    continue
                if any(k in first for k in ("合计", "小计", "总计")):
                    continue
                data.append(rec)
            return data
    raise ValueError("导出的 Excel 里找不到表头：" + "、".join(headers))
