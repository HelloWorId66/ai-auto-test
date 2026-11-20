import sqlite3

import pytest

from ifcat.adapters import Adapter, AdapterRegistry, RegistryError, build_default_registry
from ifcat.dbro import ReadOnlyDb
from ifcat.evidence import RunRecorder
from ifcat.meta import load_form
from ifcat.primitives import Primitives
from ifcat.result import BlockedError, Status
from ifcat.statemodel import BillModel, ResultTable, StateModelError


def test_extension_cannot_override_core_and_unknown_type_blocks():
    reg = build_default_registry()
    class Fake(Adapter):
        type_name = "FormTextInput"
    with pytest.raises(RegistryError):
        reg.register_extension(Fake)
    class New(Adapter):
        type_name = "BrandNewComp"
    reg.register_extension(New)
    assert "BrandNewComp" in reg.types() and "BrandNewComp" not in reg.core_types()
    with pytest.raises(BlockedError):
        reg.get("FormCheckBox")
    with pytest.raises(RegistryError):
        reg.register_core(New)


def _model():
    return BillModel(
        flow_no="DEMO", name="演示", head_table="ZJ_HEAD", status_col="F_ZT", key_col="F_ID",
        results={"detail": ResultTable("ZJ_DETAIL", {"F_CKNM": "F_ID"})},
        states={"issued": "7"},
    )


@pytest.fixture
def prim(tmp_path):
    c = sqlite3.connect(":memory:")
    c.execute("create table ZJ_HEAD(F_ID text, F_ZT text)")
    c.execute("create table ZJ_DETAIL(F_CKNM text, F_AMT text)")
    c.execute("insert into ZJ_HEAD values('K1','3')")
    c.execute("insert into ZJ_DETAIL values('K1','100.00')")
    rec = RunRecorder(tmp_path, "p", "e", "s")
    form = load_form({"formID": "F", "components": [], "formName": "x"})
    return Primitives(page=None, forms={"F": form}, registry=build_default_registry(), recorder=rec,
                      db=ReadOnlyDb(connection=c), bills={"DEMO": _model()})


def test_db_status_pass_fail_and_unknown_alias(prim):
    assert prim.expect_db_status("DEMO", "K1", "approved").ok
    r = prim.expect_db_status("DEMO", "K1", "draft")
    assert r.status is Status.FAILED and "期望 1" in r.message
    assert prim.expect_db_status("DEMO", "NOPE", "approved").status is Status.FAILED
    # 别名不存在是模型错误，应该阻塞而不是悄悄通过
    assert prim.expect_db_status("DEMO", "K1", "ghost").status is not Status.PASSED


def test_db_result_counts(prim):
    assert prim.expect_db_result("DEMO", "detail", {"F_CKNM": "K1"}).ok
    assert prim.expect_db_result("DEMO", "detail", {"F_CKNM": "K2"}).status is Status.FAILED
    assert prim.expect_db_result("DEMO", "detail", {"F_CKNM": "K1"}, max_rows=0).status is Status.FAILED
    assert prim.expect_db_result("DEMO", "missing", {"F_CKNM": "K1"}).status is Status.BLOCKED


def test_db_record_values_absent_and_status_negation(prim):
    assert prim.expect_db_record("DEMO", "K1", "head", {"F_ZT": "3"}).ok
    assert prim.expect_db_record("DEMO", "K1", "detail", {"F_AMT": "100"}).ok  # 金额按十进制比较
    bad = prim.expect_db_record("DEMO", "K1", "detail", {"F_AMT": "200"})
    assert bad.status is Status.FAILED and "期望 200" in bad.message
    assert prim.expect_db_record("DEMO", "K1", "detail", absent=True).status is Status.FAILED
    prim.db._conn.execute("insert into ZJ_HEAD values('K2','1')")
    assert prim.expect_db_record("DEMO", "K2", "detail", absent=True).ok
    assert prim.expect_db_record("DEMO", "K2", "detail").status is Status.FAILED
    assert prim.expect_db_record("DEMO", "NOPE", "detail", absent=True).status is Status.FAILED
    assert prim.expect_db_record("DEMO", "K1", "ghost").status is Status.BLOCKED
    assert prim.expect_db_status("DEMO", "K2", "not:approved").ok
    assert prim.expect_db_status("DEMO", "K1", "not:approved").status is Status.FAILED


def test_result_sql_rejects_bad_identifiers_and_missing_link():
    bad = BillModel("X", "x", "T; DROP", "S", "K")
    with pytest.raises(StateModelError):
        bad.head_sql()
    m = BillModel("X", "x", "T", "S", "K", results={"r": ResultTable("R", {})})
    with pytest.raises(StateModelError):
        m.result_sql("r")


def test_uncalibrated_primitives_block_and_no_checkpoint_is_invalid(prim):
    assert prim.submit("F").status is Status.BLOCKED  # 没有导航能力或按钮时阻塞，不会假装成功
    assert prim.finish() is Status.BLOCKED


def test_no_checkpoint_means_invalid(tmp_path):
    rec = RunRecorder(tmp_path, "p", "e", "s")
    p = Primitives(None, {}, build_default_registry(), rec)
    assert p.finish() is Status.INVALID


def test_checkpoints_pass_and_result_json_redacted(prim):
    prim.expect_db_status("DEMO", "K1", "approved")
    assert prim.finish() is Status.PASSED
    import json
    out = json.loads((prim.rec.dir / "result.json").read_text(encoding="utf-8"))
    assert out["meta"]["final_status"] == "passed" and out["steps"][0]["evidence"]


def test_read_head_value_and_bill_models_load(prim, tmp_path):
    assert prim.read_head_value("DEMO", "K1", "F_ZT") == "3"
    with pytest.raises(BlockedError):
        prim.read_head_value("DEMO", "K1", "F_ZT; DROP")
    from ifcat.statemodel import load_bill_models
    f = tmp_path / "demo.bills.yaml"
    f.write_text(
        "bills:\n  DEMO_BILL:\n    name: 样例\n    form_id: DEMO_FORM\n    head_table: T_HEAD\n    key_col: F_GUID\n"
        "    status_col: F_ZT\n    results:\n      detail:\n        table: T_DETAIL\n        link: {F_HEAD_ID: F_GUID}\n",
        encoding="utf-8")
    models = load_bill_models(f)
    assert models["DEMO_BILL"].status_col == "F_ZT"
    assert models["DEMO_BILL"].result_sql("detail").endswith("F_HEAD_ID = :f_head_id")

def test_db_record_where_and_count(prim):
    c = prim.db._conn
    c.execute("insert into ZJ_DETAIL values('K1','-50.00')")
    c.execute("insert into ZJ_DETAIL values('K1','-50.00')")
    # 不给 count：只要有一条全部一致就算通过（不再只看第一条）
    assert prim.expect_db_record("DEMO", "K1", "detail", {"F_AMT": "-50"}).ok
    assert prim.expect_db_record("DEMO", "K1", "detail", count=3).ok
    r = prim.expect_db_record("DEMO", "K1", "detail", count=2)
    assert r.status is Status.FAILED and "3 条，期望 2 条" in r.message
    # where 先圈出记录，count 数条数，expect 要求每一条都一致
    assert prim.expect_db_record("DEMO", "K1", "detail", {"F_AMT": "-50"}, where={"F_AMT": "-50.00"}, count=2).ok
    bad = prim.expect_db_record("DEMO", "K1", "detail", {"F_AMT": "-50"}, count=3)
    assert bad.status is Status.FAILED and "第 1 条不一致" in bad.message
    assert prim.expect_db_record("DEMO", "K1", "detail", where={"F_AMT": "999"}, count=0).ok
    assert prim.expect_db_record("DEMO", "K1", "detail", where={"F_AMT": "999"}, absent=True).ok
    assert prim.expect_db_record("DEMO", "K1", "detail", where={"F_AMT": "999"}).status is Status.FAILED
    assert prim.expect_db_record("DEMO", "K1", "head", where={"F_ZT": "3"}, count=1).ok
    assert prim.expect_db_record("DEMO", "K1", "head", where={"F_ZT": "1"}, count=0).ok
    # 列名不是合法标识符时阻塞，不拼进语句
    assert prim.expect_db_record("DEMO", "K1", "detail", where={"F_AMT; DROP": "1"}).status is Status.BLOCKED


def test_where_clause_binds_values_and_handles_null():
    from ifcat.statemodel import where_clause
    sql, params = where_clause({"F_A": 1, "F_B": None, "F_C": "x' or '1'='1"})
    assert sql == " AND F_A = :w0 AND F_B IS NULL AND F_C = :w2"
    assert params == {"w0": "1", "w2": "x' or '1'='1"}
    assert where_clause(None) == ("", {})
    with pytest.raises(StateModelError):
        where_clause(["F_A"])
