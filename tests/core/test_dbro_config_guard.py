import sqlite3
import textwrap

import pytest

from ifcat import guard
from ifcat.config import ConfigError, load_config, redact
from ifcat.dbro import ReadOnlyDb, ReadOnlyViolation, check_read_only


@pytest.mark.parametrize("sql", [
    "select 1", "SELECT a FROM t WHERE x = :k;", "with c as (select 1 a from dual) select * from c",
    "select 'a;b' from t", "select * from t -- delete me",
])
def test_read_only_accepts(sql):
    check_read_only(sql)


@pytest.mark.parametrize("sql", [
    "", "delete from t", "update t set a=1", "insert into t values (1)", "select 1; select 2",
    "select * from t; drop table t", "begin null; end;", "select 1 /* x */ ; commit",
    "with a as (select 1 x from t) delete from t",
])
def test_read_only_rejects(sql):
    with pytest.raises(ReadOnlyViolation):
        check_read_only(sql)


def test_query_binds_params_and_lowercases_columns():
    c = sqlite3.connect(":memory:")
    c.execute("create table t(F_ID text, F_ST text)")
    c.execute("insert into t values('1','3')")
    db = ReadOnlyDb(connection=c)
    assert db.query("select F_ID, F_ST from t where F_ID = :key", {"key": "1"}) == [{"f_id": "1", "f_st": "3"}]
    with pytest.raises(ReadOnlyViolation):
        db.query("delete from t")


def test_config_load_and_redact(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(textwrap.dedent("""
        project: demo
        env_name: sit
        base_url: http://host/
        accounts:
          maker: {username: u1, password: p1}
        db: {kind: oracle, dsn: x, username: ro, password: pw}
    """), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.base_url == "http://host" and cfg.account("maker").username == "u1"
    assert "p1" not in repr(cfg) and "pw" not in repr(cfg)
    assert redact({"db": {"password": "pw"}, "n": 1}) == {"db": {"password": "***"}, "n": 1}
    with pytest.raises(ConfigError):
        cfg.account("nobody")


def test_config_missing_pieces(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("project: a\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(p)
    with pytest.raises(ConfigError):
        load_config(tmp_path / "none.yaml")


def test_integrity_detects_tamper_missing_and_extra(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("x=1", encoding="utf-8")
    manifest = guard.build_manifest(pkg)
    import json
    (pkg / guard.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    guard.verify_integrity(pkg)
    (pkg / "a.py").write_text("x=2", encoding="utf-8")
    with pytest.raises(guard.IntegrityError, match="被改动"):
        guard.verify_integrity(pkg)
    (pkg / "a.py").write_text("x=1", encoding="utf-8")
    (pkg / "b.py").write_text("", encoding="utf-8")
    with pytest.raises(guard.IntegrityError, match="多出"):
        guard.verify_integrity(pkg)
    (pkg / "b.py").unlink()
    (pkg / "a.py").unlink()
    with pytest.raises(guard.IntegrityError, match="缺失"):
        guard.verify_integrity(pkg)
    (pkg / guard.MANIFEST_NAME).unlink()
    with pytest.raises(guard.IntegrityError):
        guard.verify_integrity(pkg)
