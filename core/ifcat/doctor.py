"""环境自检：换一台机器、换一个人、换一个环境时，先跑 `ifc doctor`，一次看清还缺什么。

每一项给出「通过 / 未通过」和下一步怎么办；不修改任何东西，不打印口令。
"""
from __future__ import annotations

import platform
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .config import ConfigError, EnvConfig, load_config
from .workspace import Workspace, WorkspaceError, load_workspace

MIN_PYTHON = (3, 10)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""


def _python() -> Check:
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PYTHON
    return Check("Python 版本", ok, f"{platform.python_version()}（{platform.system()}）",
                 "" if ok else f"需要 Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} 或更高")


def _browser() -> Check:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return Check("浏览器自动化组件", False, "没有安装 playwright", "在框架的虚拟环境里执行：pip install playwright pyyaml")
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
    except Exception as exc:
        return Check("浏览器自动化组件", False, str(exc).splitlines()[0][:120], "执行：python -m playwright install chromium")
    return Check("浏览器自动化组件", True, "Chromium 可启动")


def _workspace(path: Optional[str]) -> "tuple[Check, Optional[Workspace]]":
    try:
        ws = load_workspace(path)
    except WorkspaceError as exc:
        return Check("工作区", False, str(exc).splitlines()[0],
                     "进入工作区目录执行，或用 --workspace 指定，或设置环境变量 IFCAT_WORKSPACE"), None
    return Check("工作区", True, f"{ws.project}（{ws.root.name}）"), ws


def _config(ws: Workspace, env: str) -> "tuple[Check, Optional[EnvConfig]]":
    try:
        cfg = load_config(ws.env_config(env))
    except (ConfigError, WorkspaceError) as exc:
        return Check(f"环境配置（{env}）", False, str(exc).splitlines()[0],
                     "复制工作区 config/local/dev.yaml.example 为 <环境>.yaml 并填写；"
                     "口令可直接写在该文件里（该目录不入库），或用 password_env 指向环境变量"), None
    roles = "、".join(f"{r}={a.username}" for r, a in cfg.accounts.items())
    return Check(f"环境配置（{env}）", True, f"产品版本 {cfg.product_version}，语言 {cfg.locale}，账号 {roles}"), cfg


def _system_proxy() -> str:
    return next((v for k, v in urllib.request.getproxies().items() if k in ("http", "https")), "")


def _reachable(cfg: EnvConfig) -> Check:
    # 与浏览器一致：直连，不走系统代理（本机代理软件会让内网地址返回 502）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(cfg.base_url, timeout=15) as r:
            code = r.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except Exception as exc:
        return Check("环境可访问", False, f"{type(exc).__name__}: {exc}"[:140],
                     "确认已连上公司内网/VPN，且 base_url 正确")
    if code >= 400:
        return Check("环境可访问", False, f"HTTP {code}", "环境可能没启动，或地址有误；请联系环境负责人")
    note = f"（本机有系统代理 {_system_proxy()}，自动化浏览器已默认直连，不受影响）" if _system_proxy() else ""
    return Check("环境可访问", True, f"HTTP {code}{note}")


def _login(cfg: EnvConfig) -> Check:
    from .session import Session

    sess = Session(cfg, headless=True)
    try:
        sess.start()
        done: List[str] = []
        for role in cfg.accounts:
            sess.fresh_context()
            sess.login(role)
            done.append(role)
        return Check("账号登录", True, "、".join(done) + " 均可登录")
    except Exception as exc:
        return Check("账号登录", False, f"{type(exc).__name__}: {exc}".splitlines()[0][:140],
                     "核对账号口令、界面语言（locale）和 env_params.login 配置")
    finally:
        sess.close()


def _scenarios(ws: Workspace) -> Check:
    files = ws.scenario_files()
    return Check("场景文件", bool(files), f"{len(files)} 个" if files else "工作区 scenarios/ 下没有场景",
                 "" if files else "让智能体按「用例生成规程」先写用例草案")


def run_doctor(workspace: Optional[str], env: Optional[str], login: bool = False) -> int:
    checks: List[Check] = [_python(), _browser()]
    wc, ws = _workspace(workspace)
    checks.append(wc)
    cfg: Optional[EnvConfig] = None
    if ws is not None:
        env_name = env or ws.default_env
        if env_name:
            cc, cfg = _config(ws, env_name)
            checks.append(cc)
        else:
            checks.append(Check("环境配置", False, "没有指定环境", "用 --env 指定，或在 workspace.yaml 设置 default_env"))
        checks.append(_scenarios(ws))
    if cfg is not None:
        checks.append(_reachable(cfg))
        if login and checks[-1].ok:
            checks.append(_login(cfg))
    for c in checks:
        print(f"{'通过' if c.ok else '未通过'}  {c.name}：{c.detail}")
        if not c.ok and c.fix:
            print(f"        怎么办：{c.fix}")
    if cfg is not None and not login:
        print("提示：加 --login 会实际用各账号登录一次，验证账号口令。")
    return 0 if all(c.ok for c in checks) else 1
