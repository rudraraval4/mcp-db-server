"""Tests for the engine layer against a real temporary SQLite database.

The engine receives already-validated queries, so these tests build
:class:`ValidatedQuery` objects directly — including a deliberately malicious one
to prove the read-only connection is a genuine second line of defence.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from mcp_db_server.config import Settings
from mcp_db_server.engine import Database, TableAccessError
from mcp_db_server.safety import ValidatedQuery


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE items (
            id    INTEGER PRIMARY KEY,
            name  TEXT NOT NULL,
            price REAL
        );
        CREATE TABLE secrets (id INTEGER PRIMARY KEY, token TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO items (id, name, price) VALUES (?,?,?)",
        [(i, f"item{i}", i * 1.5) for i in range(1, 6)],
    )
    conn.execute("INSERT INTO secrets (id, token) VALUES (1, 'sshhh')")
    conn.commit()
    conn.close()
    return path


def make_db(db_path, **overrides) -> Database:
    settings = Settings(database_url=f"sqlite:///{db_path}", **overrides)
    return Database(settings)


def vq(sql: str, limit: int) -> ValidatedQuery:
    return ValidatedQuery(sql=sql, tables=[], enforced_limit=limit)


# --------------------------------------------------------------------------- #
# Introspection
# --------------------------------------------------------------------------- #
def test_list_tables(db_path):
    db = make_db(db_path)
    assert db.list_tables() == ["items", "secrets"]


def test_list_tables_respects_allow_list(db_path):
    db = make_db(db_path, allowed_tables=["items"])
    assert db.list_tables() == ["items"]


def test_list_tables_respects_deny_list(db_path):
    db = make_db(db_path, denied_tables=["secrets"])
    assert db.list_tables() == ["items"]


def test_describe_table(db_path):
    db = make_db(db_path)
    cols = {c.name: c for c in db.describe_table("items")}
    assert cols["id"].primary_key is True
    assert cols["name"].nullable is False
    assert "INT" in cols["id"].type.upper()


def test_describe_table_blocks_denied(db_path):
    db = make_db(db_path, denied_tables=["secrets"])
    with pytest.raises(TableAccessError):
        db.describe_table("secrets")


def test_describe_missing_table_raises(db_path):
    db = make_db(db_path)
    with pytest.raises(TableAccessError):
        db.describe_table("nope")


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def test_execute_returns_rows_and_columns(db_path):
    db = make_db(db_path)
    result = db.execute(vq("SELECT id, name FROM items ORDER BY id LIMIT 100", 100))
    assert result.columns == ["id", "name"]
    assert result.row_count == 5
    assert result.rows[0] == (1, "item1")
    assert result.truncated is False


def test_truncated_flag_set_at_cap(db_path):
    db = make_db(db_path, max_rows=2)
    result = db.execute(vq("SELECT * FROM items LIMIT 2", 2))
    assert result.row_count == 2
    assert result.truncated is True


def test_truncated_flag_false_below_cap(db_path):
    db = make_db(db_path, max_rows=100)
    result = db.execute(vq("SELECT * FROM items LIMIT 3", 3))
    assert result.truncated is False


# --------------------------------------------------------------------------- #
# Defence in depth: the connection itself is read-only
# --------------------------------------------------------------------------- #
def test_connection_rejects_writes_even_if_gate_bypassed(db_path):
    """If a write somehow reached the engine, the read-only connection blocks it."""
    db = make_db(db_path)
    with pytest.raises(OperationalError):
        db.execute(vq("INSERT INTO items (id, name) VALUES (99, 'x')", 100))

    # And the data is untouched.
    result = db.execute(vq("SELECT COUNT(*) FROM items", 100))
    assert result.rows[0][0] == 5


def test_sqlglot_dialect_for_sqlite(db_path):
    db = make_db(db_path)
    assert db.sqlglot_dialect == "sqlite"
