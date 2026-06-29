"""Unit tests for the pure rendering helpers."""

from __future__ import annotations

from mcp_db_server.engine import QueryResult
from mcp_db_server.formatting import _cell, render_result, render_table_list


def test_empty_table_list():
    assert "No tables" in render_table_list([])


def test_cell_handles_none_and_pipes_and_length():
    assert _cell(None) == "NULL"
    assert _cell("a|b") == "a\\|b"
    long = _cell("x" * 500)
    assert len(long) <= 200 and long.endswith("…")


def test_render_result_no_columns():
    result = QueryResult(columns=[], rows=[], row_count=0, truncated=False)
    assert "no columns" in render_result(result).lower()


def test_render_result_truncated_note():
    result = QueryResult(columns=["n"], rows=[(1,)], row_count=1, truncated=True)
    assert "truncated at the row cap" in render_result(result)


def test_render_result_empty_rows():
    result = QueryResult(columns=["n"], rows=[], row_count=0, truncated=False)
    out = render_result(result)
    assert "(no rows)" in out
