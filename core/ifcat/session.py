"""浏览器会话：登录、切换角色、打开表单。

登录页与菜单的具体操作依赖真实环境，目前没有页面证据，所以只提供两种方式：
1. env_params.login 里显式给出登录页定位（user / password / submit 三个 CSS 选择器）；
2. 没给时退回启发式（登录页恰好两个可见输入框加一个主按钮），并在记录里标明这是启发式。
口令只从配置读，不写入日志与结果。表单打开方式见 open_form：按 env_params.forms 里配置的菜单路径点击，没有配置就阻塞，不猜。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .config import EnvConfig
from .result import BlockedError


class Session:
    def __init__(self, cfg: EnvConfig, headless: bool = True):
        self.cfg = cfg
        self.headless = headless
        self._pw: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self.role: Optional[str] = None
        self.login_mode = ""

    def start(self) -> Any:
        from playwright.sync_api import sync_playwright  # 延迟导入，离线命令不需要浏览器
        self._pw = sync_playwright().start()
        # 默认直连：测试环境在内网，本机开着代理软件（如 7890 端口的系统代理）时，浏览器经代理访问会得到 502。
        # 确实需要走代理时，配置 env_params.browser_proxy（"system" 表示沿用系统代理，或具体代理地址）。
        proxy = self.cfg.env_params.get("browser_proxy")
        if not proxy:
            self.browser = self._pw.chromium.launch(headless=self.headless, args=["--proxy-server=direct://", "--proxy-bypass-list=*"])
        elif proxy == "system":
            self.browser = self._pw.chromium.launch(headless=self.headless)
        else:
            self.browser = self._pw.chromium.launch(headless=self.headless, proxy={"server": str(proxy)})
        self._new_context()
        return self.page

    def _new_context(self) -> None:
        if self.context is not None:
            self.context.close()
        self.context = self.browser.new_context(viewport={"width": 1600, "height": 900}, locale=self.cfg.locale)
        self.page = self.context.new_page()

    def fresh_context(self) -> Any:
        """批量运行时，每个场景用全新的浏览器上下文，场景之间不串会话。"""
        self._new_context()
        self.role = None
        return self.page

    def login(self, role: str) -> None:
        acc = self.cfg.account(role)
        page = self.page
        # 开发环境首页偶发慢到超时（同一时刻 curl 只要 1 秒），重试几次再判定环境有问题
        for attempt in range(3):
            try:
                page.goto(self.cfg.base_url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception:
                if attempt == 2:
                    raise
                page.wait_for_timeout(3000)
        sel: Dict[str, str] = (self.cfg.env_params.get("login") or {})
        if sel.get("user") and sel.get("password") and sel.get("submit"):
            self.login_mode = "configured"
            page.wait_for_selector(sel["user"], timeout=40000)
            page.fill(sel["user"], acc.username)
            page.fill(sel["password"], acc.password)
            page.click(sel["submit"])
        else:
            # 启发式：登录页恰好两个可见输入框（账号、口令，口令框不一定是 type=password），加一个主按钮
            self.login_mode = "heuristic"
            page.wait_for_selector("input", timeout=40000)
            boxes = page.locator("input:visible:not([type=hidden]):not([type=checkbox])")
            if boxes.count() != 2:
                raise BlockedError(f"登录页有 {boxes.count()} 个可见输入框，不是账号加口令两个，请在配置 env_params.login 给出选择器")
            boxes.nth(0).fill(acc.username)
            boxes.nth(1).fill(acc.password)
            btn = page.locator("button.ant-btn-primary:visible, button[type=submit]:visible")
            if btn.count() != 1:
                raise BlockedError(f"登录页有 {btn.count()} 个候选登录按钮，请在配置 env_params.login 给出选择器")
            btn.first.click()
        try:
            page.wait_for_function("!location.href.toLowerCase().includes('login')", timeout=40000)
        except Exception as exc:
            raise BlockedError("登录后地址仍含 login，登录可能失败（账号、口令或环境问题）") from exc
        page.wait_for_timeout(2500)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)  # 登录后菜单是异步加载的，没好之前点不到
        except Exception:
            pass
        self.role = role

    def switch_role(self, role: str) -> Any:
        """换账号：新开干净的浏览器上下文再登录，避免会话串号。"""
        if role != self.role:
            self._new_context()
            self.login(role)
        return self.page

    def open_form(self, form_id: str) -> None:
        """按配置的菜单路径点开表单。env_params.forms.<表单ID>.menu 是菜单文字列表，
        同名菜单用「文字#序号」（序号从 0 开始）区分。菜单文字随界面语言变化，换语言要改配置。"""
        if self.page.locator(f".osp-root-{form_id}:visible").count():
            return  # 表单已在前台，不重复点菜单（菜单弹层会挡住后续操作）
        spec = (self.cfg.env_params.get("forms") or {}).get(form_id) or {}
        menu = spec.get("menu")
        if not menu:
            raise BlockedError(f"没有配置表单 {form_id} 的菜单路径（env_params.forms.{form_id}.menu）")
        # 菜单是三栏：左侧一级 > 模块 > 右栏里「分组标题 + 功能」。分组标题（如「企业定存」「单据查询」）点不了，
        # 还可能和左栏的同名模块混淆，所以四级路径只点 一级、模块、功能 三个。数据库里查到的完整路径可以直接填。
        clicks = [menu[0], menu[1], menu[-1]] if len(menu) > 3 else list(menu)
        for item in clicks:
            text, _, nth = str(item).partition("#")
            self._click_menu(text, nth)
            self.page.wait_for_timeout(1200)
        self.page.wait_for_timeout(int(spec.get("settle_ms", 5000)))
        # 表单打开后还会异步加载默认值（如财资中心），没加载完就填写会得到「保存失败」，等网络空闲再往下
        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        self.page.wait_for_timeout(1500)

    def _click_menu(self, text: str, nth: str) -> None:
        """菜单展开有动画，刚展开时点击可能被相邻菜单项挡住；重新选目标再点，最多 4 次。"""
        last: Optional[Exception] = None
        for _ in range(5):
            try:
                self._menu_target(text, nth).click(timeout=10000)
                return
            except Exception as exc:
                last = exc
                self.page.wait_for_timeout(1500)
        raise BlockedError(f"点不到菜单「{text}」：{str(last).splitlines()[0] if last else ''}")

    def _menu_target(self, text: str, nth: str) -> Any:
        """同名菜单文字可能同时存在于被其他菜单盖住的子菜单里（点了会被别的菜单项拦截）。
        没有显式序号时，只选真正在最上层、点得到的那一个。"""
        loc = self.page.get_by_text(text, exact=True)
        if nth:
            return loc.nth(int(nth))
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                reachable = el.evaluate(
                    "e => { const r = e.getBoundingClientRect(); if (!r.width || !r.height) return false;"
                    " const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);"
                    " return !!t && (t === e || e.contains(t) || t.contains(e)); }")
            except Exception:
                continue
            if reachable:
                return el
        return loc.first

    def go_home(self) -> None:
        """回到首页（待办、已办、已完成所在页）。首页页签文字随语言变化，可用 env_params.ui_text.home_tab 覆盖。"""
        tab = (self.cfg.env_params.get("ui_text") or {}).get("home_tab", "HomePage")
        self.page.get_by_text(tab, exact=True).first.click()
        self.page.wait_for_timeout(2500)

    def close(self) -> None:
        for obj in (self.context, self.browser):
            try:
                if obj:
                    obj.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()
