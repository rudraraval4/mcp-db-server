"""Tests for the demo CLI. Drives mcp_db_server.cli.main with argv and captures
stdout, against a real temporary SQLite database.
"""

from __future__ import annotations

import sqlite3

import pytest

from mcp_db_server import cli


@pytest.fixture
def db_url(tmp_path):
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL, price REAL);"
    )
    conn.executemany(
        "INSERT INTO items (id, name, price) VALUES (?,?,?)",
        [(i, f"item{i}", i * 1.5) for i in range(1, 6)],
    )
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


def run(capsys, db_url, *args, max_rows=None):
    argv = ["--database-url", db_url]
    if max_rows is not None:
        argv += ["--max-rows", str(max_rows)]
    argv += list(args)
    code = cli.main(argv)
    assert code == 0
    return capsys.readouterr().out


def test_tables_command(capsys, db_url):
    out = run(capsys, db_url, "tables")
    assert "items" in out


def test_describe_command(capsys, db_url):
    out = run(capsys, db_url, "describe", "items")
    assert "| column |" in out and "price" in out


def test_query_command(capsys, db_url):
    out = run(capsys, db_url, "query", "SELECT id, name FROM items ORDER BY id")
    assert "item1" in out and "row(s)" in out


def test_query_blocks_write(capsys, db_url):
    out = run(capsys, db_url, "query", "DROP TABLE items")
    assert "rejected by safety policy" in out.lower()


def test_explain_command(capsys, db_url):
    out = run(capsys, db_url, "explain", "SELECT * FROM items")
    assert "Normalized SQL" in out and "Query plan" in out


def test_max_rows_override_truncates(capsys, db_url):
    out = run(capsys, db_url, "query", "SELECT * FROM items", max_rows=2)
    assert "truncated at the row cap" in out


def test_requires_a_subcommand(capsys, db_url):
    with pytest.raises(SystemExit):
        cli.main(["--database-url", db_url])


def test_query_runtime_error_is_reported(capsys, db_url):
    """A query that passes validation but fails at execution is reported, not raised."""
    out = run(capsys, db_url, "query", "SELECT * FROM ghost_table")
    assert "query failed" in out.lower()


def test_explain_runtime_error_is_reported(capsys, db_url):
    out = run(capsys, db_url, "explain", "SELECT * FROM ghost_table")
    assert "could not explain" in out.lower()
