"""Tests for the MCP server tool wiring (list_tables, describe_table).

FastMCP's ``call_tool`` is async and returns ``(content_list, structured)``;
``_text`` pulls out the rendered text a client would display.
"""

from __future__ import annotations

import asyncio
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
    conn.commit()
    conn.close()

    def _build(**overrides):
        return build_server(Settings(database_url=f"sqlite:///{path}", **overrides))

    return _build


def _text(call_result) -> str:
    content_list, _structured = call_result
    return content_list[0].text


def call(server, name, args=None):
    return asyncio.run(server.call_tool(name, args or {}))


def test_tools_are_registered(server):
    s = server()
    tools = asyncio.run(s.list_tools())
    assert {t.name for t in tools} == {"list_tables", "describe_table"}


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
