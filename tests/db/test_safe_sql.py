"""Tests for the safe_sql validator + executor.

This is the W2 D2 critical security boundary: prove no user input can
escape into mutating SQL.
"""

from __future__ import annotations

import pytest

from backend.app.db.safe_sql import (
    UnsafeSQLError,
    _ensure_limit,
    validate_sql,
)


# ---------- positive cases ----------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM meals WHERE user_id = :uid",
        "select id, total_kcal from meals where user_id = :uid limit 10",
        "WITH recent AS (SELECT * FROM meals WHERE user_id = :uid) SELECT count(*) FROM recent",
        "SELECT m.id FROM meals m JOIN users u ON m.user_id = u.id WHERE u.id = :uid",
    ],
)
def test_validate_accepts_safe(sql):
    out = validate_sql(sql)
    assert out  # returns normalized form


def test_ensure_limit_appends_when_missing():
    sql = "SELECT * FROM meals WHERE user_id = :uid"
    assert _ensure_limit(sql, 50).endswith("LIMIT 50")


def test_ensure_limit_idempotent():
    sql = "SELECT * FROM meals LIMIT 5"
    assert _ensure_limit(sql, 100) == sql


# ---------- negative cases (security) ----------


@pytest.mark.parametrize(
    "sql, reason",
    [
        ("DROP TABLE meals", "drop"),
        ("DELETE FROM meals", "delete"),
        ("UPDATE users SET goal='cut'", "update"),
        ("INSERT INTO meals VALUES (1)", "insert"),
        ("SELECT * FROM meals; DROP TABLE meals", "multi-statement"),
        ("SELECT * FROM meals -- comment", "comment"),
        ("SELECT * FROM meals /* x */", "block comment"),
        ("SELECT * FROM secret_table", "non-whitelist table"),
        ("PRAGMA table_info(meals)", "pragma"),
        ("ATTACH DATABASE 'evil.db' AS evil", "attach"),
        ("SELECT * FROM users; ATTACH DATABASE 'x' AS y", "multi"),
        ("VACUUM", "vacuum"),
        ("CREATE TABLE x (id int)", "create"),
        ("ALTER TABLE meals ADD COLUMN x INT", "alter"),
        ("", "empty"),
        ("DESCRIBE meals", "non-select"),
    ],
)
def test_validate_rejects_unsafe(sql, reason):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


def test_validate_rejects_classic_injection_payload():
    """Even though the tool is read-only, classic OR 1=1 should still be
    parameterized; the validator can't detect this semantically, but
    the comment / chain / DML guards make it impossible to escalate.
    Here we just ensure typical injection terminators fail."""
    bad = "SELECT * FROM meals WHERE user_id = '' OR '1'='1' -- '"
    with pytest.raises(UnsafeSQLError):
        validate_sql(bad)


# ---------- live execution ----------


@pytest.mark.asyncio
async def test_execute_safe_select_with_params(tmp_path, monkeypatch):
    """End-to-end: spin up a temp sqlite, insert a meal, query it back via safe SQL."""
    monkeypatch.setenv("STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "test.db"))

    from backend.app.core import config as cfg
    from backend.app.db import engine as eng
    cfg.get_settings.cache_clear()
    eng._engine = None
    eng.AsyncSessionLocal = None

    from backend.app.db import init_db, repository as repo, session_scope
    from backend.app.db.safe_sql import execute_safe_select

    await init_db()
    async with session_scope() as s:
        await repo.upsert_user(s, "u1", goal="cut")
        await repo.add_meal(
            s, "u1", dishes=[{"name": "rice"}], total_kcal=200.0
        )

    async with session_scope() as s:
        rows = await execute_safe_select(
            s,
            "SELECT user_id, total_kcal FROM meals WHERE user_id = :uid",
            params={"uid": "u1"},
        )
    assert len(rows) == 1
    assert rows[0]["user_id"] == "u1"
    assert rows[0]["total_kcal"] == 200.0

    await eng.dispose_engine()
