"""业务落库的断言模型：单据头状态字段 + 业务结果表。

审批完成的标志是单据头状态='3'，并且业务结果表有对应记录（见 docs/exploration/PanUI产品操作规约.md「存」「变」两行）。
状态值和表名来自项目配置，不散落在场景里。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# 产品基类里固定的通用单据态
GENERIC_STATES = {"draft": "1", "in_flow": "2", "approved": "3", "voided": "4"}

_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class StateModelError(Exception):
    pass


def _ident(value: str, what: str) -> str:
    if not isinstance(value, str) or not _IDENT.match(value):
        raise StateModelError(f"{what} 不是合法标识符：{value!r}")
    return value


@dataclass
class ResultTable:
    table: str
    # 结果表与单据头关联的列：结果表列名 -> 单据头列名
    link: Dict[str, str]
    note: str = ""


@dataclass
class BillModel:
    flow_no: str
    name: str
    head_table: str
    status_col: str
    key_col: str
    results: Dict[str, ResultTable] = field(default_factory=dict)
    # 业务自定义状态：别名 -> 值，来自代码常量，写明出处
    states: Dict[str, str] = field(default_factory=dict)
    # 单据头表被多种单据共用时（如授信申请/变更/终止同表，靠单据类型区分），用固定条件限定本流程：列 -> 值
    where: Dict[str, str] = field(default_factory=dict)

    def _extra(self) -> str:
        out = ""
        for col, val in self.where.items():
            _ident(col, "限定列")
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", str(val)):
                raise StateModelError(f"限定值不合法：{val!r}")
            out += f" AND {col} = '{val}'"
        return out

    def head_row_sql(self) -> str:
        t, k = (_ident(x, "表/列") for x in (self.head_table, self.key_col))
        return f"SELECT * FROM {t} WHERE {k} = :key{self._extra()}"

    def state_value(self, alias: str) -> str:
        if alias in self.states:
            return self.states[alias]
        if alias in GENERIC_STATES:
            return GENERIC_STATES[alias]
        raise StateModelError(f"{self.flow_no} 没有状态别名 {alias!r}")

    def head_sql(self) -> str:
        t, k, s = (_ident(x, "表/列") for x in (self.head_table, self.key_col, self.status_col))
        return f"SELECT {k}, {s} FROM {t} WHERE {k} = :key{self._extra()}"

    def head_value_sql(self, column: str) -> str:
        t, k, c = (_ident(x, "表/列") for x in (self.head_table, self.key_col, column))
        return f"SELECT {c} FROM {t} WHERE {k} = :key{self._extra()}"

    def result_sql(self, name: str) -> str:
        if name not in self.results:
            raise StateModelError(f"{self.flow_no} 没有结果表 {name!r}")
        rt = self.results[name]
        _ident(rt.table, "结果表")
        if not rt.link:
            raise StateModelError(f"结果表 {name} 没有关联列，无法限定范围")
        conds = " AND ".join(f"{_ident(c, '列')} = :{_ident(c, '列').lower()}" for c in rt.link)
        return f"SELECT * FROM {rt.table} WHERE {conds}"


def where_clause(where: Optional[Dict[str, Any]]) -> "tuple[str, Dict[str, Any]]":
    """场景里给的附加筛选条件（列 -> 值）变成 SQL 片段和绑定参数。列名校验为标识符，值一律绑定，不拼进语句。
    值为 None 表示该列为空。"""
    if not where:
        return "", {}
    if not isinstance(where, dict):
        raise StateModelError(f"筛选条件要写成「列: 值」，收到 {where!r}")
    sql, params = "", {}
    for i, (col, val) in enumerate(where.items()):
        _ident(str(col), "筛选列")
        if val is None:
            sql += f" AND {col} IS NULL"
        else:
            sql += f" AND {col} = :w{i}"
            params[f"w{i}"] = str(val)
    return sql, params


def load_bill_models(path: str | Path) -> Dict[str, BillModel]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    models: Dict[str, BillModel] = {}
    for flow_no, m in (raw.get("bills") or {}).items():
        results = {
            n: ResultTable(table=r["table"], link=dict(r.get("link") or {}), note=r.get("note", ""))
            for n, r in (m.get("results") or {}).items()
        }
        models[flow_no] = BillModel(
            flow_no=flow_no,
            name=m.get("name", flow_no),
            head_table=m["head_table"],
            status_col=m["status_col"],
            key_col=m["key_col"],
            results=results,
            states={k: str(v) for k, v in (m.get("states") or {}).items()},
            where={k: str(v) for k, v in (m.get("where") or {}).items()},
        )
    return models
