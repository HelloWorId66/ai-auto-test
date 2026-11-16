"""八个业务原语：开、填、存、报、批、变、查、验。

脚本只通过 Primitives 操作系统。每个原语返回步骤结果：
- passed：做完了，或检查点与预期一致；
- failed：检查点与预期不一致（系统行为不符，疑似产品问题）；
- blocked：步骤没能执行完（定位、等待、数据、环境、缺适配器），属于自动化问题。
"""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional

from .adapters import Adapter, AdapterRegistry
from .calibration import CalibrationGate
from .dbro import ReadOnlyDb
from .evidence import RunRecorder
from .locator import find_field_root, pick_field
from .meta import FormMeta
from . import flowops, waits
from . import grid as grid_mod
from . import xlsxread
from .adapters.business import _click_unique_text
from .result import BlockedError, Status, StepResult
from .statemodel import BillModel, StateModelError


def _same_value(expected: Any, actual: Any) -> bool:
    """金额类用十进制比较，避免浮点误差；其他按去空白后的文本比较。"""
    e, a = str(expected).strip(), str(actual).strip()
    if e == a:
        return True
    try:
        return Decimal(e.replace(",", "")) == Decimal(a.replace(",", ""))
    except InvalidOperation:
        return False


SETTLE_MS = 1200


def _was_reset(expected: Any, actual: str) -> bool:
    """填完后读回的值是空，或是 0（而期望值不是 0），说明被联动重置了。"""
    exp = str(expected).strip()
    if not exp:
        return False
    if actual == "":
        return True
    try:
        nums = [Decimal(x.replace(",", "")) for x in (actual.split()[-1], exp.split()[-1])]
    except (InvalidOperation, IndexError):
        return False
    return nums[0] == 0 and nums[1] != 0


def _norm_cell(v: Any) -> str:
    return str(v).strip()


def _query_problem(table: List[Dict[str, str]], rows: Optional[List[Dict[str, Any]]], count: Optional[int]) -> str:
    if count is not None and len(table) != int(count):
        return f"查询结果 {len(table)} 行，期望 {count} 行"
    for want in rows or []:
        if not any(all(_same_value(v, rec.get(h, "")) for h, v in want.items()) for rec in table):
            near = [{h: rec.get(h, "") for h in want} for rec in table[:3]]
            return f"查询结果里没有满足 {want} 的行；结果共 {len(table)} 行，前几行：{near}"
    return ""


def query_export(page: Any, form: str, rec: RunRecorder, ui: Dict[str, str], conditions: Dict[str, Any],
                 headers: List[str]) -> "tuple[List[Dict[str, str]], List[str]]":
    """填条件、查询、导出 Excel，返回（表格行，证据文件）。"""
    for label, value in conditions.items():
        _set_query_condition(page, label, value)
    root = page.locator(f".osp-root-{form}:visible")
    root.get_by_text(flowops.text(ui, "query"), exact=True).first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(2500)
    with page.expect_download(timeout=30000) as dl:
        root.get_by_text(flowops.text(ui, "export"), exact=True).first.click()
    saved: List[str] = []
    name = rec.save_file("query_export", ".xlsx", lambda p: dl.value.save_as(p))
    saved.append(name)
    sheet = xlsxread.read_first_sheet(str(rec.dir / name))
    return xlsxread.find_table(sheet, headers), saved


# 在查询条件区按标签文字找到对应控件所在的容器，并打上标记，返回是否找到
_MARK_CONTROL_JS = """(label)=>{const norm=t=>t.replace(/[:：\\s]/g,'');
document.querySelectorAll('[data-ifcat-target]').forEach(e=>e.removeAttribute('data-ifcat-target'));
const leaves=[...document.querySelectorAll('*')].filter(e=>e.children.length==0&&norm(e.textContent)===label&&e.getClientRects().length);
for(const l of leaves){const lr=l.getBoundingClientRect();let n=l.parentElement;
 for(let i=0;i<6&&n;i++){
  const ctl=[...n.querySelectorAll('input, .ant-select-selector')].filter(x=>!['checkbox','radio'].includes(x.type)&&x.getClientRects().length);
  if(ctl.length){
   const d=x=>{const r=x.getBoundingClientRect();return Math.abs(r.top+r.height/2-lr.top-lr.height/2)+(r.left<lr.left-4?1000:0)};
   ctl.sort((a,b)=>d(a)-d(b));
   const t=ctl[0].closest('.ant-select')||ctl[0];
   t.setAttribute('data-ifcat-target','1');return true}
  n=n.parentElement}}
return false}"""


def _set_query_condition(page: Any, label: str, value: Any) -> None:
    """填查询条件：下拉/选择类控件点开后按文字点选项，普通输入框直接输入。"""
    if not page.evaluate(_MARK_CONTROL_JS, str(label)):
        raise BlockedError(f"查询页上找不到条件「{label}」")
    target = page.locator('[data-ifcat-target="1"]').first
    if target.evaluate("e => e.classList.contains('ant-select')"):
        target.locator(".ant-select-selector").first.click()
        popup = page.locator(".ant-select-dropdown:visible, .panui-custom-selector-dropdown:visible")
        waits.poll(lambda: popup.count() >= 1, 8.0, f"条件「{label}」的选项弹层出现")
        _click_unique_text(popup.last, str(value), f"条件「{label}」")
        if target.evaluate("e => e.classList.contains('ant-select-multiple')"):
            page.keyboard.press("Escape")  # 多选下拉选完不会自动收起
        waits.poll(lambda: page.locator(".ant-select-dropdown:visible").count() == 0, 8.0, f"条件「{label}」的弹层关闭")
    else:
        target.click()
        page.keyboard.press("ControlOrMeta+A")
        page.keyboard.type(str(value))
        page.keyboard.press("Tab")
    page.wait_for_timeout(600)


class Primitives:
    def __init__(
        self,
        page: Any,
        forms: Dict[str, FormMeta],
        registry: AdapterRegistry,
        recorder: RunRecorder,
        db: Optional[ReadOnlyDb] = None,
        bills: Optional[Dict[str, BillModel]] = None,
        gate: Optional[CalibrationGate] = None,
        nav: Any = None,
        ui_text: Optional[Dict[str, str]] = None,
    ):
        self.page = page
        self.forms = forms
        self.registry = registry
        self.rec = recorder
        self.db = db
        self.bills = bills or {}
        # 生产运行必须传入 gate；只有单元测试和标定本身可以不传
        self.gate = gate
        self.checkpoints = 0
        # nav 提供 open_form(form_id) 和 go_home()，由会话实现；没有就不能做「开」和审批
        self.nav = nav
        self.ui = ui_text or {}

    # --- 内部 ---
    def _step(self, name: str, fn: Callable[[], StepResult]) -> StepResult:
        try:
            result = fn()
        except BlockedError as exc:
            result = StepResult.blocked(str(exc))
        except Exception as exc:
            # 步骤没能执行完（定位、等待、超时、驱动报错）是自动化自身的问题，不是系统行为与预期不符。
            # failed 只留给检查点比对不一致，否则会把脚本问题当成产品缺陷报给业务人员。
            result = StepResult.blocked(f"{type(exc).__name__}: {exc}")
        if not result.ok and not result.evidence and self.page is not None:
            result.evidence = self._screenshot("出错")
        self.rec.record_step(name, result)
        return result

    def _adapter(self, type_name: str) -> Adapter:
        adapter = self.registry.get(type_name)
        source = self.registry.extension_source(type_name)
        if source is not None:
            self.rec.note_extension("adapter", type_name, source)
        if self.gate is not None:
            problem = self.gate.problem(type_name)
            if problem:
                raise BlockedError(problem)
        return adapter

    def _form(self, form_id: str) -> FormMeta:
        if form_id not in self.forms:
            raise BlockedError(f"没有加载表单元数据：{form_id}")
        return self.forms[form_id]

    def _screenshot(self, label: str) -> List[str]:
        try:
            return [self.rec.save_screenshot(label, lambda p: self.page.screenshot(path=p, full_page=True))]
        except Exception:
            return []

    # --- 填 ---
    def fill(self, form_id: str, values: Dict[str, Any], within: Optional[str] = None,
             occurrence: Optional[int] = None) -> StepResult:
        """values 的键是字段标签。同名标签用 within（祖先组件 key）或 occurrence 区分。"""

        def run() -> StepResult:
            form = self._form(form_id)
            for label, value in values.items():
                hits = form.field_by_label(label, within)
                if not hits:
                    where = f"（限定在 {within} 内）" if within else ""
                    raise BlockedError(f"表单 {form_id} 里没有字段「{label}」{where}")
                f = pick_field(self.page, form, hits, occurrence or 0, explicit=occurrence is not None or bool(within))
                adapter = self._adapter(f.type)
                root = find_field_root(self.page, form, f)
                adapter.set(self.page, root, value)
                # 字段间有联动（选存款方后加载账号、周期等），等联动请求落地再填下一个
                self.page.wait_for_timeout(SETTLE_MS)
            self._refill_if_reset(form, values, within, occurrence)
            return StepResult.passed(f"填写 {len(values)} 个字段", self._screenshot("fill"))

        return self._step(f"填 {form_id}", run)

    def _refill_if_reset(self, form: FormMeta, values: Dict[str, Any], within: Optional[str], occurrence: Optional[int]) -> None:
        """后填的字段会触发异步联动（如选周期后重新加载利率），可能把先填的值清空或归零。
        等页面安静后，只重填「被清空/归零」的字段；格式不同但有值的不算被改。"""
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        self.page.wait_for_timeout(SETTLE_MS)
        for label, value in values.items():
            try:
                f = pick_field(self.page, form, form.field_by_label(label, within), occurrence or 0,
                               explicit=occurrence is not None or bool(within))
                adapter = self._adapter(f.type)
                root = find_field_root(self.page, form, f)
                actual = str(adapter.get(self.page, root) or "").strip()
                if not _was_reset(value, actual):
                    continue
                adapter.set(self.page, root, value)
                self.page.wait_for_timeout(SETTLE_MS)
            except Exception:
                continue

    # --- 验 ---
    def expect_field(self, form_id: str, label: str, expected: Any, within: Optional[str] = None,
                     occurrence: Optional[int] = None) -> StepResult:
        def run() -> StepResult:
            form = self._form(form_id)
            hits = form.field_by_label(label, within)
            if not hits:
                raise BlockedError(f"表单 {form_id} 里没有字段「{label}」")
            f = pick_field(self.page, form, hits, occurrence or 0, explicit=occurrence is not None or bool(within))
            adapter = self._adapter(f.type)
            root = find_field_root(self.page, form, f)
            actual = adapter.get(self.page, root)
            # 联动字段（金额变了重算利息等）要等服务端算完：最多多等 6 秒，值对了立刻往下走
            for _ in range(24):
                if _same_value(expected, actual):
                    break
                self.page.wait_for_timeout(250)
                actual = adapter.get(self.page, root)
            self.checkpoints += 1
            ev = self._screenshot(f"expect_{label}")
            if _same_value(expected, actual):
                return StepResult.passed(f"「{label}」= {actual}", ev)
            return StepResult.failed(f"「{label}」期望 {expected}，实际 {actual}", ev)

        return self._step(f"验 界面 {label}", run)

    def expect_db_status(self, flow_no: str, key: Any, state_alias: str) -> StepResult:
        """断言单据头状态。状态值取自项目配置的状态字典，不在场景里写字面量。"""

        def run() -> StepResult:
            if self.db is None:
                raise BlockedError("没有配置只读数据库，不能做数据库校验")
            model = self.bills.get(flow_no)
            if model is None:
                raise BlockedError(f"项目配置里没有流程 {flow_no} 的状态模型")
            negate = state_alias.startswith("not:")
            want = model.state_value(state_alias[4:] if negate else state_alias)
            sql = model.head_sql()
            rows = self.db.query(sql, {"key": key})
            ev = [self.rec.save_query(f"head_{flow_no}", sql, rows)]
            self.checkpoints += 1
            if not rows:
                return StepResult.failed(f"单据头里没有 {model.key_col}={key} 的记录", ev)
            actual = str(rows[0][model.status_col.lower()])
            if (actual != want) if negate else (actual == want):
                return StepResult.passed(f"{model.status_col}={actual}（{state_alias}）", ev)
            shown = f"不应为 {want}" if negate else f"期望 {want}"
            return StepResult.failed(f"{model.status_col} {shown}（{state_alias}），实际 {actual}", ev)

        return self._step(f"验 数据库状态 {flow_no}", run)

    def expect_db_record(self, flow_no: str, key: Any, table: str, expect: Optional[Dict[str, Any]] = None,
                         absent: bool = False, wait: int = 0) -> StepResult:
        """按单据编号找到单据头，再检查单据头（table=head）或它关联的结果表里的记录：
        有没有、字段值对不对；absent=true 表示这条记录不应存在。
        wait 是最长等待秒数，用于后台线程异步生成的记录（如转账指令）。"""

        def run() -> StepResult:
            if self.db is None:
                raise BlockedError("没有配置只读数据库，不能做数据库校验")
            model = self.bills.get(flow_no)
            if model is None:
                raise BlockedError(f"项目配置里没有流程 {flow_no} 的状态模型")
            try:
                head_sql = model.head_row_sql()
                res_sql = None if table == "head" else model.result_sql(table)
            except StateModelError as exc:
                raise BlockedError(str(exc)) from exc
            want = {str(c).lower(): v for c, v in (expect or {}).items()}
            deadline = time.monotonic() + max(0, int(wait))
            while True:
                heads = self.db.query(head_sql, {"key": key})
                rows: List[Dict[str, Any]] = heads
                sql = head_sql
                if heads and res_sql:
                    links = model.results[table].link
                    params = {r.lower(): heads[0].get(h.lower()) for r, h in links.items()}
                    rows, sql = self.db.query(res_sql, params), res_sql
                bad = [f"{c} 期望 {v}，实际 {rows[0].get(c)}" for c, v in want.items()
                       if rows and not _same_value(v, rows[0].get(c))]
                done = (not rows) if absent else (bool(rows) and not bad)
                if done or time.monotonic() >= deadline:
                    break
                time.sleep(2)
            ev = [self.rec.save_query(f"{table}_{flow_no}", sql, rows)]
            self.checkpoints += 1
            if not heads:
                return StepResult.failed(f"单据头里没有 {model.key_col}={key} 的记录", ev)
            if absent:
                if rows:
                    return StepResult.failed(f"{table} 不应有记录，实际有 {len(rows)} 条", ev)
                return StepResult.passed(f"{table} 没有记录（符合预期）", ev)
            if not rows:
                return StepResult.failed(f"{table} 没有找到对应记录" + (f"（已等待 {wait} 秒）" if wait else ""), ev)
            if bad:
                return StepResult.failed("；".join(bad), ev)
            return StepResult.passed(f"{table} 已生成，{len(want)} 个字段值一致", ev)

        return self._step(f"验 数据库记录 {table}", run)

    def read_head_value(self, flow_no: str, key: Any, column: str) -> Any:
        """读单据头某列的值（如审批完成后回填的结果表内码），用于关联结果表。不是检查点。"""
        if self.db is None:
            raise BlockedError("没有配置只读数据库，不能读取单据头")
        model = self.bills.get(flow_no)
        if model is None:
            raise BlockedError(f"项目配置里没有流程 {flow_no} 的状态模型")
        try:
            sql = model.head_value_sql(column)
        except StateModelError as exc:
            raise BlockedError(str(exc)) from exc
        rows = self.db.query(sql, {"key": key})
        if not rows:
            raise BlockedError(f"单据头里没有 {model.key_col}={key} 的记录")
        return next(iter(rows[0].values()))

    def expect_db_result(self, flow_no: str, result_name: str, key_values: Dict[str, Any],
                         min_rows: int = 1, max_rows: Optional[int] = None) -> StepResult:
        """断言结果表有对应记录。key_values 的键是结果表关联列名（大小写不敏感）。"""

        def run() -> StepResult:
            if self.db is None:
                raise BlockedError("没有配置只读数据库，不能做数据库校验")
            model = self.bills.get(flow_no)
            if model is None:
                raise BlockedError(f"项目配置里没有流程 {flow_no} 的状态模型")
            try:
                sql = model.result_sql(result_name)
            except StateModelError as exc:
                raise BlockedError(str(exc)) from exc
            params = {k.lower(): v for k, v in key_values.items()}
            rows = self.db.query(sql, params)
            ev = [self.rec.save_query(f"result_{result_name}", sql, rows)]
            self.checkpoints += 1
            n = len(rows)
            if n < min_rows or (max_rows is not None and n > max_rows):
                return StepResult.failed(f"{result_name} 记录数 {n}，期望 {min_rows}..{max_rows or '不限'}", ev)
            return StepResult.passed(f"{result_name} 记录数 {n}", ev)

        return self._step(f"验 数据库结果 {result_name}", run)

    def read_field(self, form_id: str, label: str, within: Optional[str] = None, occurrence: Optional[int] = None) -> Any:
        """读界面字段当前值（用于记录单据编号等后续步骤要引用的值）。不是检查点。"""
        form = self._form(form_id)
        hits = form.field_by_label(label, within)
        if not hits:
            raise BlockedError(f"表单 {form_id} 里没有字段「{label}」")
        f = pick_field(self.page, form, hits, occurrence or 0, explicit=occurrence is not None or bool(within))
        adapter = self._adapter(f.type)
        return adapter.get(self.page, find_field_root(self.page, form, f))

    # --- 开、存、报、批、查 ---
    def _need_nav(self) -> Any:
        if self.nav is None:
            raise BlockedError("没有提供页面导航能力（会话），不能打开表单或回到首页")
        return self.nav

    def open(self, form: str, **_: Any) -> StepResult:
        """打开表单并新建一张单据（菜单路径来自配置）。"""

        def run() -> StepResult:
            self._form(form)
            self._need_nav().open_form(form)
            return StepResult.passed(f"打开 {form}", self._screenshot("open"))

        return self._step(f"开 {form}", run)

    def save(self, form: str, **_: Any) -> StepResult:
        """点「保存」。是否真的保存成功要靠随后的检查点（如单据编号已生成），提示文字只用来尽早发现失败。"""

        def run() -> StepResult:
            f = self._form(form)
            flowops.click_toolbar(self.page, f, flowops.toolbar_button(f, self.ui.get("save", "保存"), "GeneralAction"))
            toasts = flowops.wait_toasts(self.page)
            bad = flowops.failed_toast(toasts, self.ui)
            ev = self._screenshot("save")
            if bad:
                banner = flowops.page_error_banner(self.page)
                return StepResult.failed(f"保存提示：{bad}" + (f"；页面错误信息：{banner}" if banner else ""), ev)
            blocking = [t.replace("\n", " ") for t in flowops.visible_modal_texts(self.page) if t.strip()]
            if blocking:
                return StepResult.failed(f"保存被系统弹框拦住：{blocking[0][:120]}", ev)
            return StepResult.passed("已保存" + (f"（提示：{toasts[0]}）" if toasts else ""), ev)

        return self._step(f"存 {form}", run)

    def submit(self, form: str, **_: Any) -> StepResult:
        """点「提交」，在确认框里确认。提交后单据进入审批流。"""

        def run() -> StepResult:
            f = self._form(form)
            flowops.click_toolbar(self.page, f, flowops.toolbar_button(f, self.ui.get("submit", "提交"), "GeneralAction"))
            flowops.confirm_dialog(self.page, flowops.text(self.ui, "confirm_submit"))
            toasts = flowops.collect_toasts(self.page, 4000)
            bad = flowops.failed_toast(toasts, self.ui)
            ev = self._screenshot("submit")
            if bad:
                return StepResult.failed(f"提交提示：{bad}", ev)
            return StepResult.passed("已提交" + (f"（提示：{toasts[0]}）" if toasts else ""), ev)

        return self._step(f"报 {form}", run)

    def approve(self, bill: str, **_: Any) -> StepResult:
        """在首页待办里对该单据逐个节点「同意」，直到它离开本人待办。bill 是单据编号。"""

        def run() -> StepResult:
            self._need_nav().go_home()
            n = flowops.approve_until_done(self.page, str(bill), self.ui)
            ev = self._screenshot("approve")
            if n == 0:
                return StepResult.failed(f"待办里找不到单据 {bill}，没有可同意的节点", ev)
            return StepResult.passed(f"同意 {n} 个节点", ev)

        return self._step(f"批 {bill}", run)

    def expect_flow_completed(self, bill: str, **_: Any) -> StepResult:
        """检查点：单据出现在首页「已完成」里（流程走完），且已不在本人待办。"""

        def run() -> StepResult:
            self._need_nav().go_home()
            flowops.open_tab(self.page, flowops.text(self.ui, "tab_todo"))
            still = flowops.bill_row_text(self.page, str(bill))
            # 已完成列表是异步加载的，偶发在列表还没刷出来时就读了；找不到时重进首页再看，最多三次
            row = ""
            for attempt in range(3):
                flowops.open_tab(self.page, flowops.text(self.ui, "tab_done"))
                row = flowops.bill_row_text(self.page, str(bill))
                if row or attempt == 2:
                    break
                self.page.wait_for_timeout(4000)
                self._need_nav().go_home()
            self.checkpoints += 1
            ev = self._screenshot("flow_completed")
            if still:
                return StepResult.failed(f"单据 {bill} 仍在待办里：{still[:60]}", ev)
            if not row:
                return StepResult.failed(f"已完成列表里找不到单据 {bill}", ev)
            return StepResult.passed(f"单据 {bill} 已办结", ev)

        return self._step(f"验 流程办结 {bill}", run)

    def _pick_dialog(self, form: str, find: str, reopen: str, search: bool) -> "tuple[Any, str]":
        self._form(form)
        if reopen:
            self.page.locator(f".osp-root-{form}:visible").get_by_text(reopen, exact=True).first.click()
        modal = self.page.locator(".ant-modal-wrap:visible")
        waits.poll(lambda: modal.count() >= 1, 15.0, "选择弹窗出现")
        dlg = modal.last
        title = (dlg.locator(".ant-modal-title").first.inner_text() or "").strip()
        # 搜索框的提示文字因弹窗而异（「输入搜索内容」「请输入查询关键字」），也随界面语言变化
        words = [w.strip() for w in flowops.text(self.ui, "search_placeholders").split(",") if w.strip()]
        box = dlg.locator(", ".join(f'input[placeholder*="{w}"]' for w in words))
        if search and box.count():
            box.first.fill(str(find))
            box.first.press("Enter")
            self.page.wait_for_timeout(2000)
        return dlg, title

    def pick_record(self, form: str, find: str, reopen: str = "", search: bool = True, **_: Any) -> StepResult:
        """在「选择…」弹窗里选一条记录并确定（如变更/终止授信时先选要操作的授信额度）。
        弹窗在表单打开时自动出现；已经关掉或要换一条时，reopen 填表单上重新打开弹窗的按钮文字。
        find 是要选的那行里能唯一识别它的文字（如授信编号）。"""

        def run() -> StepResult:
            dlg, title = self._pick_dialog(form, find, reopen, search)
            hit = dlg.get_by_text(str(find), exact=True)
            if not hit.count():
                return StepResult.failed(f"「{title}」弹窗里找不到「{find}」", self._screenshot("pick_not_found"))
            hit.first.click()
            self.page.wait_for_timeout(500)
            dlg.get_by_role("button", name=flowops.text(self.ui, "confirm_pick"), exact=True).click()
            try:
                waits.poll(lambda: self.page.locator(".ant-modal-wrap:visible").count() == 0, 10.0, "弹窗关闭")
            except Exception:
                return StepResult.failed(f"选择「{find}」后弹窗没有关闭：{[t[:60] for t in flowops.visible_modal_texts(self.page)]}",
                                         self._screenshot("pick_not_closed"))
            # 选中后页面会带出该记录的数据，等带出完成再往下
            try:
                self.page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            self.page.wait_for_timeout(SETTLE_MS)
            return StepResult.passed(f"在「{title}」里选择 {find}", self._screenshot("pick_record"))

        return self._step(f"选 {find}", run)

    def expect_not_listed(self, form: str, find: str, reopen: str = "", search: bool = True, **_: Any) -> StepResult:
        """检查点：选择弹窗里选不到这条记录（如已终止的授信不能再被选来变更）。查完点「取消」关掉弹窗。"""

        def run() -> StepResult:
            dlg, title = self._pick_dialog(form, find, reopen, search)
            found = dlg.get_by_text(str(find), exact=True).count() > 0
            self.checkpoints += 1
            ev = self._screenshot("not_listed")
            dlg.get_by_role("button", name=flowops.text(self.ui, "cancel"), exact=True).click()
            if found:
                return StepResult.failed(f"「{title}」弹窗里仍能选到「{find}」，期望选不到", ev)
            return StepResult.passed(f"「{title}」弹窗里没有「{find}」，符合预期", ev)

        return self._step(f"验 选不到 {find}", run)

    def expect_query(self, form: str, conditions: Dict[str, Any], rows: Optional[List[Dict[str, Any]]] = None,
                     count: Optional[int] = None, wait: int = 0, columns: Optional[List[str]] = None,
                     **_: Any) -> StepResult:
        """检查点：在查询页填条件、点「查询」，导出结果 Excel 后按表头核对。
        查询页的结果表是画布渲染，界面读不到文字，所以读导出的 Excel。
        rows：每项是 {表头: 期望值}，结果里必须有一行同时满足；count：结果行数（不含合计）。
        columns：只数行数、不核对内容时，给出结果表里的任意表头用来定位表格。
        wait：结果还没出现（如办结后异步生成）时最多重试的秒数。"""

        def run() -> StepResult:
            headers = list(dict.fromkeys([*(columns or []), *(h for r in (rows or []) for h in r)]))
            if not headers or (rows is None and count is None):
                raise BlockedError("expect_query 需要 rows，或 count 加 columns")
            deadline = time.monotonic() + max(0, int(wait))
            attempt = 0
            while True:
                attempt += 1
                table, files = query_export(self.page, form, self.rec, self.ui, conditions, headers)
                problem = _query_problem(table, rows, count)
                if not problem or time.monotonic() >= deadline:
                    break
                self.page.wait_for_timeout(5000)
            self.checkpoints += 1
            ev = self._screenshot("query") + files
            if problem:
                return StepResult.failed(problem, ev)
            return StepResult.passed(f"查询结果 {len(table)} 行，核对通过", ev)

        return self._step("验 查询结果", run)

    def reject(self, bill: str, **_: Any) -> StepResult:
        """在首页待办里把单据退回（退回至制单），退回后它应不再在本人待办里。"""

        def run() -> StepResult:
            self._need_nav().go_home()
            flowops.open_tab(self.page, flowops.text(self.ui, "tab_todo"))
            flowops.row_action(self.page, str(bill), flowops.text(self.ui, "reject"))
            self.page.wait_for_timeout(1200)
            btn = flowops.text(self.ui, "reject")
            flowops.confirm_dialog(self.page, btn)
            toasts = flowops.collect_toasts(self.page, 3500)
            flowops.open_tab(self.page, flowops.text(self.ui, "tab_todo"))
            still = flowops.bill_row_text(self.page, str(bill))
            ev = self._screenshot("reject")
            if still:
                return StepResult.failed(f"退回后单据 {bill} 仍在本人待办里：{still[:60]}", ev)
            return StepResult.passed("已退回" + (f"（提示：{toasts[0]}）" if toasts else ""), ev)

        return self._step(f"退回 {bill}", run)

    def open_todo(self, bill: str, form: str, **_: Any) -> StepResult:
        """在本人待办里打开单据（如被退回的单据回到制单人待办），进入该单据的表单页。"""

        def run() -> StepResult:
            self._form(form)
            self._need_nav().go_home()
            flowops.open_tab(self.page, flowops.text(self.ui, "tab_todo"))
            flowops.open_bill_from_todo(self.page, str(bill))
            root = self.page.locator(f".osp-root-{form}:visible")
            waits.poll(lambda: root.count() >= 1, 15.0, "单据表单打开")
            return StepResult.passed(f"打开单据 {bill}", self._screenshot("open_todo"))

        return self._step(f"开待办 {bill}", run)

    def edit(self, form: str, **_: Any) -> StepResult:
        """点工具栏「编辑」，让已保存或被退回的单据可以修改。"""

        def run() -> StepResult:
            f = self._form(form)
            btn = flowops.toolbar_button(f, flowops.text(self.ui, "edit"), "FormEditAction")
            css = f".{f.form_id}-{btn.path[-1]}-{btn.action_key}-show-form"
            try:
                waits.poll(lambda: self.page.locator(css).count() >= 1, 10.0, "编辑按钮出现")
            except Exception:
                pass
            flowops.click_toolbar(self.page, f, btn)
            # 进入编辑后页面会重新加载单据数据（先出空表单再回填），回填完成前填写会被冲掉：
            # 等「保存」按钮出现，再等网络空闲，最后留一小段缓冲
            save = f".{f.form_id}-{btn.path[-1]}-GeneralActionSave-show-form"
            waits.poll(lambda: self.page.locator(save).count() >= 1, 10.0, "进入编辑后「保存」按钮出现")
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            self.page.wait_for_timeout(3000)
            return StepResult.passed("进入编辑", self._screenshot("edit"))

        return self._step(f"编辑 {form}", run)

    def expect_visible(self, form: str, label: str, visible: bool, within: Optional[str] = None,
                       occurrence: int = 0, **_: Any) -> StepResult:
        """检查点：字段当前是否显示（按条件显示的字段，如通知存款没有到期日期）。"""

        def run() -> StepResult:
            f = self._form(form)
            hits = f.field_by_label(label, within)
            if not hits:
                raise BlockedError(f"表单 {form} 里没有字段「{label}」")
            shown = False
            has_container = False
            for h in hits:
                base = f"{form}-{h.key}-form"
                loc = self.page.locator(f'[class~="{base}-container"], [id="{base}-container"], [id="{base}"]')
                has_container = has_container or loc.count() > 0
                if loc.count() and any(loc.nth(i).is_visible() for i in range(loc.count())):
                    shown = True
                    break
            if not shown and not has_container:
                # 页面上根本没有这类容器类名时，退回到页面可见文字判断
                shown = self.page.locator(f".osp-root-{form}:visible").get_by_text(label, exact=True).count() > 0
            self.checkpoints += 1
            ev = self._screenshot(f"visible_{label}")
            want = bool(visible)
            if shown == want:
                return StepResult.passed(f"「{label}」{'显示' if shown else '不显示'}，符合预期", ev)
            return StepResult.failed(f"「{label}」期望{'显示' if want else '不显示'}，实际{'显示' if shown else '不显示'}", ev)

        return self._step(f"验 显示 {label}", run)

    def submit_with_warning(self, form: str, warning: str, then: str, **_: Any) -> StepResult:
        """检查点：提交时系统弹出含 warning 文字的提醒，按 then 按钮继续后提交成功。"""

        def run() -> StepResult:
            f = self._form(form)
            flowops.click_toolbar(self.page, f, flowops.toolbar_button(f, self.ui.get("submit", "提交"), "GeneralAction"))
            # 提醒框会接在确认框之后出现，不能等确认框「关闭」，只点确认按钮
            confirm = self.page.locator(".ant-modal-wrap:visible")
            waits.poll(lambda: confirm.count() >= 1, 8.0, "确认框出现")
            confirm.last.get_by_role("button", name=flowops.text(self.ui, "confirm_submit"), exact=True).click()
            seen: List[str] = []

            def appeared() -> bool:
                seen[:] = [t for t in flowops.visible_modal_texts(self.page) if warning in t]
                return bool(seen)

            self.checkpoints += 1
            try:
                waits.poll(appeared, 10.0, f"提醒框出现（含「{warning}」）")
            except Exception:
                ev = self._screenshot("submit_no_warning")
                return StepResult.failed(f"提交后没有出现含「{warning}」的提醒；当前弹窗："
                                         f"{[t[:60] for t in flowops.visible_modal_texts(self.page)]}", ev)
            shown = seen[0].replace("\n", " ")
            ev = self._screenshot("submit_warning")
            self.page.locator(".ant-modal-wrap:visible").last.get_by_role("button", name=then, exact=True).click()
            toasts = flowops.collect_toasts(self.page, 4000)
            bad = flowops.failed_toast(toasts, self.ui)
            if bad:
                return StepResult.failed(f"提醒「{shown[:80]}」后点「{then}」，提示：{bad}", ev)
            return StepResult.passed(f"出现提醒：{shown[:100]}；点「{then}」" + (f"（提示：{toasts[0]}）" if toasts else ""), ev)

        return self._step(f"报(带提醒) {form}", run)

    def approve_blocked(self, bill: str, message: str, max_nodes: int = 8, **_: Any) -> StepResult:
        """检查点：审核人逐个节点点同意，直到某个节点被系统拦截（提示含 message），单据仍在待办。
        前面节点正常通过是允许的（同一审核人可能连续处理多个节点）；单据被同意到离开待办仍没被拦，判失败。"""

        def run() -> StepResult:
            self._need_nav().go_home()
            agree = flowops.text(self.ui, "agree")
            passed_nodes = 0
            for _ in range(max_nodes):
                flowops.open_tab(self.page, flowops.text(self.ui, "tab_todo"))
                if not flowops.bill_row_text(self.page, str(bill)):
                    break
                flowops.row_action(self.page, str(bill), agree)
                flowops.confirm_dialog(self.page, agree)
                toasts = flowops.collect_toasts(self.page, 4000)
                hit = next((t for t in toasts if message in t), None)
                if hit:
                    flowops.open_tab(self.page, flowops.text(self.ui, "tab_todo"))
                    still = flowops.bill_row_text(self.page, str(bill))
                    self.checkpoints += 1
                    ev = self._screenshot("approve_blocked")
                    if not still:
                        return StepResult.failed(f"提示了「{hit}」，但单据已不在待办里，没有被拦住", ev)
                    return StepResult.passed(f"同意第 {passed_nodes + 1} 个节点时被拦截：{hit}，单据仍在待办", ev)
                passed_nodes += 1
                self.page.get_by_text(flowops.text(self.ui, "refresh"), exact=True).first.click()
                self.page.wait_for_timeout(2500)
            self.checkpoints += 1
            return StepResult.failed(f"同意了 {passed_nodes} 个节点，一直没有出现含「{message}」的拦截提示", self._screenshot("approve_not_blocked"))

        return self._step(f"批(应被拦截) {bill}", run)

    # --- 网格 ---
    def fill_grid(self, form: str, grid: str, rows: List[Dict[str, Any]], add_button: str = "",
                  existing: bool = False) -> StepResult:
        """逐行填写，填完立即读回比较；rows 的键是列表头或列 key。
        默认逐行新增（需要 add_button）；existing=true 时不新增，按顺序填写系统已带出的前几行（如自动带出的利率分录）。"""

        def run() -> StepResult:
            if not add_button and not existing:
                raise BlockedError("fill_grid 需要 add_button（增加行的按钮文字），按钮文字因表单而异，不猜；"
                                   "填写系统已带出的行请用 existing: true")
            meta = grid_mod.find_grid_meta(self._form(form), grid)
            root = grid_mod.grid_root(self.page, self._form(form), meta)
            if existing and grid_mod.row_count(root) < len(rows):
                raise BlockedError(f"表格 {grid} 现有 {grid_mod.row_count(root)} 行，少于要填写的 {len(rows)} 行")
            for n, row in enumerate(rows):
                idx = n if existing else grid_mod.add_row(self.page, root, add_button)
                for name, value in row.items():
                    grid_mod.set_cell(self.page, root, idx, grid_mod.find_column(meta, name), value, self.gate)
                for name, value in row.items():
                    col = grid_mod.find_column(meta, name)
                    actual = grid_mod.read_cell(root, idx, col)
                    if not _same_value(value, actual):
                        return StepResult.failed(f"第 {idx + 1} 行「{name}」写入 {value}，读回 {actual}（也可能新增行不在末尾）",
                                                 self._screenshot("grid_mismatch"))
            return StepResult.passed(f"填写 {len(rows)} 行", self._screenshot("fill_grid"))

        return self._step(f"填表格 {grid}", run)

    def expect_grid(self, form: str, grid: str, rows: List[Dict[str, Any]]) -> StepResult:
        """按行序比较给出的列；行数必须一致。"""

        def run() -> StepResult:
            meta = grid_mod.find_grid_meta(self._form(form), grid)
            root = grid_mod.grid_root(self.page, self._form(form), meta)
            columns = list({k: 1 for r in rows for k in r})
            actual = grid_mod.read_rows(root, meta, columns)
            self.checkpoints += 1
            ev = self._screenshot("expect_grid")
            if len(actual) != len(rows):
                return StepResult.failed(f"网格 {grid} 期望 {len(rows)} 行，实际 {len(actual)} 行", ev)
            for i, (want, got) in enumerate(zip(rows, actual), 1):
                for k, v in want.items():
                    if not _same_value(v, got[grid_mod.find_column(meta, k).header]):
                        return StepResult.failed(f"第 {i} 行「{k}」期望 {v}，实际 {got[grid_mod.find_column(meta, k).header]}", ev)
            return StepResult.passed(f"网格 {grid} {len(rows)} 行一致", ev)

        return self._step(f"验表格 {grid}", run)

    # --- 场景收尾 ---
    def finish(self) -> Status:
        """没有任何业务检查点，场景判为无效；有阻塞或失败步骤，按严重程度汇总。"""
        statuses = [s["status"] for s in self.rec.steps]
        if "failed" in statuses:
            final = Status.FAILED
        elif "blocked" in statuses:
            final = Status.BLOCKED
        elif self.checkpoints == 0:
            final = Status.INVALID
        else:
            final = Status.PASSED
        self.rec.finish(final.value)
        return final
