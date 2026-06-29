"""Pure rendering helpers shared by the MCP tools and the demo CLI.

Kept dependency-free (no DB, no MCP) so output formatting is trivially testable
and identical no matter which front-end calls it.
"""

from __future__ import annotations

from .engine import ColumnInfo, QueryResult

_MAX_CELL = 200  # truncate very wide cell values so a result stays readable


def render_table_list(tables: list[str]) -> str:
    if not tables:
        return "No tables are visible under the current access policy."
    lines = "\n".join(f"- {t}" for t in tables)
    return f"Tables ({len(tables)}):\n{lines}"


def render_schema(table: str, columns: list[ColumnInfo]) -> str:
    header = (
        f"Schema for `{table}`:\n\n"
        "| column | type | nullable | primary key |\n|---|---|---|---|"
    )
    rows = "\n".join(
        f"| {c.name} | {c.type} | {'yes' if c.nullable else 'no'} | "
        f"{'yes' if c.primary_key else 'no'} |"
        for c in columns
    )
    return f"{header}\n{rows}"


def _cell(value) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= _MAX_CELL else text[: _MAX_CELL - 1] + "…"


def render_result(result: QueryResult) -> str:
    if not result.columns:
        return "Query executed; no columns returned."
    header = "| " + " | ".join(result.columns) + " |"
    sep = "| " + " | ".join("---" for _ in result.columns) + " |"
    body = "\n".join("| " + " | ".join(_cell(v) for v in row) + " |" for row in result.rows)
    table = f"{header}\n{sep}\n{body}" if body else f"{header}\n{sep}\n_(no rows)_"
    if result.truncated:
        note = f"\n\n_{result.row_count} row(s) — results truncated at the row cap._"
    else:
        note = f"\n\n_{result.row_count} row(s)._"
    return table + note
