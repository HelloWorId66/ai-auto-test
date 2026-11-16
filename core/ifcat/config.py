"""本机配置加载。

配置文件只放在本机（工作区 config/local/ 下，已被 .gitignore 排除），不进入代码、日志、场景或结果。
本模块只负责读取和校验，不提供写入口令的能力。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

CONFIG_ENV_VAR = "IFCAT_CONFIG"
_SECRET_KEYS = ("password", "passwd", "secret", "token", "pwd")


class ConfigError(Exception):
    pass


@dataclass
class Account:
    role: str
    username: str
    password: str = field(repr=False)


@dataclass
class DbConfig:
    kind: str  # oracle 或信创库的标识，由 dbro 的方言注册表解释
    dsn: str
    username: str
    password: str = field(repr=False)


@dataclass
class EnvConfig:
    project: str
    env_name: str
    base_url: str
    accounts: Dict[str, Account]
    db: Optional[DbConfig]
    # 例如提示形态、成功提示开关，首次运行时从环境读取后记录
    env_params: Dict[str, Any] = field(default_factory=dict)
    # 标定记录按产品版本区分；读不到时填 unknown，换版本必须改这里，否则会沿用旧标定
    product_version: str = "unknown"
    # 浏览器语言。界面语言取决于它：默认 en-US 时菜单是英文，业务人员平时看到的是 zh-CN
    locale: str = "zh-CN"

    def account(self, role: str) -> Account:
        if role not in self.accounts:
            raise ConfigError(f"配置里没有角色 {role!r}，已配置角色：{sorted(self.accounts)}")
        return self.accounts[role]


def _require(d: Dict[str, Any], key: str, where: str) -> Any:
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"配置缺少 {where}.{key}")
    return d[key]


def redact(obj: Any) -> Any:
    """日志、结果里输出配置前必须先脱敏。"""
    if isinstance(obj, dict):
        return {
            k: ("***" if any(s in str(k).lower() for s in _SECRET_KEYS) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    raw = explicit or os.environ.get(CONFIG_ENV_VAR)
    if not raw:
        raise ConfigError(f"未指定配置文件：传入路径或设置环境变量 {CONFIG_ENV_VAR}")
    p = Path(raw).expanduser()
    if not p.is_file():
        raise ConfigError(f"配置文件不存在：{p}")
    return p


def load_config(path: str | Path | None = None) -> EnvConfig:
    p = resolve_config_path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件不是有效的 YAML：{p}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置文件顶层必须是键值结构")

    accounts: Dict[str, Account] = {}
    for role, acc in (_require(raw, "accounts", "") or {}).items():
        if not isinstance(acc, dict):
            raise ConfigError(f"accounts.{role} 必须是键值结构")
        # 口令优先从环境变量读（password_env 给变量名），避免口令落在文件里
        env_name = acc.get("password_env")
        if env_name:
            password = os.environ.get(str(env_name), "")
            if not password:
                raise ConfigError(f"环境变量 {env_name} 没有设置，账号 {role} 无法登录")
        else:
            password = _require(acc, "password", f"accounts.{role}")
        accounts[role] = Account(role=role, username=_require(acc, "username", f"accounts.{role}"), password=password)
    if not accounts:
        raise ConfigError("accounts 不能为空")

    db: Optional[DbConfig] = None
    if raw.get("db"):
        d = raw["db"]
        if d.get("password_env"):
            db_pwd = os.environ.get(str(d["password_env"]), "")
            if not db_pwd:
                raise ConfigError(f"环境变量 {d['password_env']} 没有设置，数据库无法连接")
            d = {**d, "password": db_pwd}
        db = DbConfig(
            kind=_require(d, "kind", "db"),
            dsn=_require(d, "dsn", "db"),
            username=_require(d, "username", "db"),
            password=_require(d, "password", "db"),
        )

    return EnvConfig(
        project=_require(raw, "project", ""),
        env_name=_require(raw, "env_name", ""),
        base_url=str(_require(raw, "base_url", "")).rstrip("/"),
        accounts=accounts,
        db=db,
        env_params=dict(raw.get("env_params") or {}),
        product_version=str(raw.get("product_version") or "unknown"),
        locale=str(raw.get("locale") or "zh-CN"),
    )
