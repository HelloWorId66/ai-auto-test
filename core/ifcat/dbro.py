"""只读数据库连接器。

只允许单条 SELECT 或 WITH 查询，绑定参数，不提供任何写入能力。
方言和连接工厂可注册，Oracle 与信创库用不同的连接工厂接入。
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from .config import DbConfig


class ReadOnlyViolation(Exception):
    pass


_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|truncate|create|grant|revoke|"
    r"commit|rollback|execute|exec|call|begin|declare|lock|replace|rename)\b",
    re.IGNORECASE,
)
_STRIP_STRINGS = re.compile(r"'(?:[^']|'')*'")
_STRIP_COMMENTS = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def check_read_only(sql: str) -> str:
    """校验是只读单条查询，返回去掉末尾分号的语句。违规抛 ReadOnlyViolation。"""
    cleaned = _STRIP_COMMENTS.sub(" ", sql).strip()
    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()
    if not cleaned:
        raise ReadOnlyViolation("空语句")
    if ";" in _STRIP_STRINGS.sub("''", cleaned):
        raise ReadOnlyViolation("只允许单条语句")
    head = cleaned.split(None, 1)[0].lower()
    if head not in ("select", "with"):
        raise ReadOnlyViolation(f"只允许 SELECT 或 WITH，收到 {head!r}")
    if _FORBIDDEN.search(_STRIP_STRINGS.sub("''", cleaned)):
        raise ReadOnlyViolation("语句包含非只读关键字")
    return cleaned


ConnectFactory = Callable[[DbConfig], Any]
_FACTORIES: Dict[str, ConnectFactory] = {}
# 方言提供的「开启只读事务」语句。让数据库自己也拒绝写入，不只靠上面的语句检查
_READONLY_BEGIN: Dict[str, str] = {}


def register_dialect(kind: str, factory: ConnectFactory, readonly_begin: Optional[str] = None) -> None:
    _FACTORIES[kind] = factory
    if readonly_begin:
        _READONLY_BEGIN[kind] = readonly_begin


def _oracle_factory(cfg: DbConfig) -> Any:
    import oracledb  # 延迟导入，未装驱动时不影响其他功能

    conn = oracledb.connect(user=cfg.username, password=cfg.password, dsn=cfg.dsn)
    conn.autocommit = False
    return conn


register_dialect("oracle", _oracle_factory, readonly_begin="SET TRANSACTION READ ONLY")
_CORE_KINDS = frozenset(_FACTORIES)
_EXT_KINDS: Dict[str, bool] = {}


def register_extension_dialect(kind: str, factory: ConnectFactory, readonly_begin: Optional[str] = None) -> None:
    """工作区扩展接入其他数据库（如信创库）。factory 接收 DbConfig，返回 DB-API 连接；
    readonly_begin 是该库「开启只读事务」的语句，有就给，让数据库自己也拒绝写入。不能替换框架自带的方言。"""
    if kind in _CORE_KINDS:
        raise ReadOnlyViolation(f"扩展层不能覆盖框架自带的数据库类型：{kind}")
    register_dialect(kind, factory, readonly_begin)
    _EXT_KINDS[kind] = True


def extension_dialects() -> List[str]:
    return sorted(_EXT_KINDS)


def clear_extension_dialects() -> None:
    for kind in list(_EXT_KINDS):
        _FACTORIES.pop(kind, None)
        _READONLY_BEGIN.pop(kind, None)
    _EXT_KINDS.clear()


class ReadOnlyDb:
    def __init__(self, cfg: Optional[DbConfig] = None, connection: Any = None):
        self._begin: Optional[str] = None
        if connection is None:
            if cfg is None:
                raise ReadOnlyViolation("没有数据库配置，无法连接")
            if cfg.kind not in _FACTORIES:
                raise ReadOnlyViolation(f"未注册的数据库类型 {cfg.kind!r}，已注册：{sorted(_FACTORIES)}")
            connection = _FACTORIES[cfg.kind](cfg)
            self._begin = _READONLY_BEGIN.get(cfg.kind)
        self._conn = connection

    def query(self, sql: str, params: Optional[Sequence[Any] | Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        stmt = check_read_only(sql)
        cur = self._conn.cursor()
        try:
            # 每次查询单独开一个只读事务：只读事务看到的是开启时刻的快照，
            # 长时间复用会读不到审批后台刚提交的数据
            if self._begin:
                cur.execute(self._begin)
            cur.execute(stmt, params or [])
            cols = [d[0].lower() for d in cur.description or []]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
        finally:
            cur.close()
            if self._begin:
                self._conn.rollback()

    def close(self) -> None:
        try:
            self._conn.rollback()
        finally:
            self._conn.close()

    def __enter__(self) -> "ReadOnlyDb":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
