"""Tests for the MCP server tool wiring (list_tables, describe_table).

FastMCP's ``call_tool`` is async and returns ``(content_list, structured)``;
``_text`` pulls out the rendered text a client would display.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from mcp_db_server.config import Settings
from mcp_db_server.server import build_server


@pytest.fixture
def server(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL);
        CREATE TABLE secrets (id INTEGER PRIMARY KEY, token TEXT);
        """
    )
    conn.executemany(
        "INSERT INTO items (id, name, price) VALUES (?,?,?)",
        [(i, f"item{i}", i * 1.5) for i in range(1, 6)],
    )
    conn.commit()
    conn.close()

    audit_path = tmp_path / "audit.log"

    def _build(**overrides):
        overrides.setdefault("audit_log_path", str(audit_path))
        return build_server(Settings(database_url=f"sqlite:///{path}", **overrides))

    _build.audit_path = audit_path
    return _build


def _text(call_result) -> str:
    content_list, _structured = call_result
    return content_list[0].text


def call(server, name, args=None):
    return asyncio.run(server.call_tool(name, args or {}))


def _audit_records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_tools_are_registered(server):
    s = server()
    tools = asyncio.run(s.list_tools())
    assert {t.name for t in tools} == {
        "list_tables", "describe_table", "explain_query", "run_query"
    }


def test_list_tables_tool(server):
    s = server()
    text = _text(call(s, "list_tables"))
    assert "items" in text
    assert "secrets" in text


def test_list_tables_respects_policy(server):
    s = server(denied_tables=["secrets"])
    text = _text(call(s, "list_tables"))
    assert "items" in text
    assert "secrets" not in text


def test_describe_table_tool(server):
    s = server()
    text = _text(call(s, "describe_table", {"table_name": "items"}))
    assert "| column |" in text
    assert "id" in text and "name" in text


def test_describe_table_denied_returns_error(server):
    s = server(denied_tables=["secrets"])
    text = _text(call(s, "describe_table", {"table_name": "secrets"}))
    assert text.startswith("Error:")


def test_describe_missing_table_returns_error(server):
    s = server()
    text = _text(call(s, "describe_table", {"table_name": "nope"}))
    assert text.startswith("Error:")


# --------------------------------------------------------------------------- #
# run_query
# --------------------------------------------------------------------------- #
def test_run_query_returns_rows(server):
    s = server()
    text = _text(call(s, "run_query", {"sql": "SELECT id, name FROM items ORDER BY id"}))
    assert "| id | name |" in text
    assert "item1" in text
    assert "row(s)" in text


def test_run_query_blocks_write(server):
    s = server()
    text = _text(call(s, "run_query", {"sql": "DROP TABLE items"}))
    assert "rejected by safety policy" in text.lower()


def test_run_query_enforces_row_cap(server):
    s = server(max_rows=2)
    text = _text(call(s, "run_query", {"sql": "SELECT * FROM items"}))
    assert "truncated at the row cap" in text


def test_run_query_respects_deny_list(server):
    s = server(denied_tables=["secrets"])
    text = _text(call(s, "run_query", {"sql": "SELECT * FROM secrets"}))
    assert "rejected by safety policy" in text.lower()


# --------------------------------------------------------------------------- #
# explain_query
# --------------------------------------------------------------------------- #
def test_explain_query_returns_plan_without_rows(server):
    s = server()
    text = _text(call(s, "explain_query", {"sql": "SELECT * FROM items"}))
    assert "Normalized SQL" in text
    assert "Query plan" in text
    assert "item1" not in text  # no data rows leaked


def test_explain_query_blocks_write(server):
    s = server()
    text = _text(call(s, "explain_query", {"sql": "DELETE FROM items"}))
    assert "rejected by safety policy" in text.lower()


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
def test_audit_logs_allowed_query(server):
    s = server()
    call(s, "run_query", {"sql": "SELECT * FROM items"})
    records = _audit_records(server.audit_path)
    assert records[-1]["tool"] == "run_query"
    assert records[-1]["outcome"] == "allowed"
    assert records[-1]["tables"] == ["items"]


def test_audit_logs_blocked_query(server):
    s = server()
    call(s, "run_query", {"sql": "DROP TABLE items"})
    records = _audit_records(server.audit_path)
    assert records[-1]["outcome"] == "blocked"
    assert records[-1]["error"]
