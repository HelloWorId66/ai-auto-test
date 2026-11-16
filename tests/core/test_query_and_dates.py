import zipfile
from datetime import date

from ifcat import xlsxread
from ifcat.primitives import _query_problem
from ifcat.scenario import relative_date, resolve


def _make_xlsx(path, rows):
    """造一个不写行号/列号、带空共享字符串的 xlsx，和 IFC 查询页导出的格式一致。"""
    strings = []

    def sid(t):
        if t not in strings:
            strings.append(t)
        return strings.index(t)

    body = ""
    for r in rows:
        cells = ""
        for c in r:
            if isinstance(c, (int, float)):
                cells += f"<c><v>{c}</v></c>"
            elif c == "":
                cells += '<c t="s"><v/></c>'
            else:
                cells += f'<c t="s"><v>{sid(c)}</v></c>'
        body += f"<row>{cells}</row>"
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{ns}"><sheetData>{body}</sheetData></worksheet>')
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{ns}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")


def test_read_xlsx_without_refs_and_find_table(tmp_path):
    f = tmp_path / "q.xlsx"
    _make_xlsx(f, [["标题"], ["存款编号", "金额", "状态"], ["ZIC-1", 2000, "生效"], ["分币种小计", "", ""], ["", "合计", ""]])
    rows = xlsxread.read_first_sheet(str(f))
    assert rows[2] == ["ZIC-1", "2000", "生效"]
    table = xlsxread.find_table(rows, ["存款编号", "状态"])
    assert table == [{"存款编号": "ZIC-1", "金额": "2000", "状态": "生效"}]  # 合计行被跳过


def test_find_table_missing_header(tmp_path):
    f = tmp_path / "q.xlsx"
    _make_xlsx(f, [["a", "b"]])
    try:
        xlsxread.find_table(xlsxread.read_first_sheet(str(f)), ["x"])
    except ValueError as exc:
        assert "x" in str(exc)
    else:
        raise AssertionError


def test_query_problem():
    table = [{"存款编号": "A", "金额": "2000"}, {"存款编号": "B", "金额": "5"}]
    assert _query_problem(table, [{"存款编号": "A", "金额": "2,000.00"}], None) == ""
    assert "没有满足" in _query_problem(table, [{"存款编号": "A", "金额": "1"}], None)
    assert "期望 1 行" in _query_problem(table, None, 1)


def test_relative_dates():
    d = date(2026, 1, 31)
    assert relative_date(None, None, None, d) == "2026-01-31"
    assert relative_date("+", "7", "", d) == "2026-02-07"
    assert relative_date("+", "1", "m", d) == "2026-02-28"
    assert relative_date("+", "12", "m", d) == "2027-01-31"
    assert relative_date("-", "1", "m", d) == "2025-12-31"
    assert relative_date("+", "1", "m", date(2026, 12, 15)) == "2027-01-15"


def test_resolve_date_variables():
    out = resolve({"a": "${today}", "b": "${today+365}", "c": "x ${data.k}"}, {"data": {"k": 1}})
    assert out["a"] == date.today().isoformat() and len(out["b"]) == 10 and out["c"] == "x 1"


def test_compact_date_variable():
    out = resolve("${today+12m:compact}", {})
    assert len(out) == 8 and out.isdigit()


def test_resolve_data_and_describe():
    from ifcat.scenario import describe_date_macro, resolve_data
    d = resolve_data({"a": "${today}", "b": "${data.x}", "n": {"c": "${today+12m:compact}"}})
    assert d["a"] == date.today().isoformat() and d["b"] == "${data.x}" and len(d["n"]["c"]) == 8
    assert describe_date_macro("${today+12m}") == "运行当天后 12 个月"
    assert describe_date_macro("${today}") == "运行当天"
