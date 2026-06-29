"""MCP server entry point — wires the tools to the Safety Core + engine.

Run as a stdio MCP server (how Claude Desktop / Cursor launch it):

    mcp-db-server

Tools exposed:
    list_tables()            -> tables visible under the access policy
    describe_table(name)     -> columns, types, keys
    explain_query(sql)       -> normalized SQL, tables, and the engine query plan
    run_query(sql)           -> validated, capped, read-only result set

Every run_query / explain_query attempt is validated through the Safety Core and
recorded in the audit log. Tool docstrings double as the descriptions the client
LLM reads, so they are written for that audience.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from sqlalchemy.exc import SQLAlchemyError

from .audit import write_audit
from .config import Settings, load_settings
from .engine import Database, QueryResult, TableAccessError
from .safety import UnsafeQueryError, validate_query

_MAX_CELL = 200  # truncate very wide cell values so a result stays readable


def _render_table_list(tables: list[str]) -> str:
    if not tables:
        return "No tables are visible under the current access policy."
    lines = "\n".join(f"- {t}" for t in tables)
    return f"Tables ({len(tables)}):\n{lines}"


def _render_schema(table: str, columns) -> str:
    header = f"Schema for `{table}`:\n\n| column | type | nullable | primary key |\n|---|---|---|---|"
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


def _render_result(result: QueryResult) -> str:
    if not result.columns:
        return "Query executed; no columns returned."
    header = "| " + " | ".join(result.columns) + " |"
    sep = "| " + " | ".join("---" for _ in result.columns) + " |"
    body = "\n".join("| " + " | ".join(_cell(v) for v in row) + " |" for row in result.rows)
    note = f"\n\n_{result.row_count} row(s)._"
    if result.truncated:
        note = f"\n\n_{result.row_count} row(s) — results truncated at the row cap._"
    table = f"{header}\n{sep}\n{body}" if body else f"{header}\n{sep}\n_(no rows)_"
    return table + note


def build_server(settings: Settings | None = None) -> FastMCP:
    """Build a configured FastMCP server. Kept separate from ``main`` for testing."""
    settings = settings or load_settings()
    db = Database(settings)
    mcp = FastMCP("mcp-db-server")

    @mcp.tool()
    def list_tables() -> str:
        """List the database tables you are allowed to query.

        Returns the visible table names. Always call this first to discover the
        schema; tables excluded by the server's access policy will not appear.
        """
        return _render_table_list(db.list_tables())

    @mcp.tool()
    def describe_table(table_name: str) -> str:
        """Describe one table's columns: name, type, nullability, and primary key.

        Use this to learn a table's structure before writing a query. Returns an
        error message if the table does not exist or is not permitted by policy.
        """
        try:
            columns = db.describe_table(table_name)
        except TableAccessError as e:
            return f"Error: {e}"
        return _render_schema(table_name, columns)

    @mcp.tool()
    def explain_query(sql: str) -> str:
        """Explain a read-only SQL query WITHOUT returning any data rows.

        Validates the query through the safety policy, then returns the normalized
        SQL that would actually run (with the enforced row limit), the tables it
        reads, and the database's query plan. Call this to preview a query before
        running it.
        """
        try:
            validated = validate_query(sql, settings, dialect=db.sqlglot_dialect)
        except UnsafeQueryError as e:
            write_audit(settings.audit_log_path, tool="explain_query", sql=sql,
                        outcome="blocked", error=str(e))
            return f"Query rejected by safety policy: {e}"

        try:
            plan = db.explain(validated)
        except SQLAlchemyError as e:
            write_audit(settings.audit_log_path, tool="explain_query", sql=validated.sql,
                        outcome="error", tables=validated.tables, error=str(e))
            return f"Could not explain query: {e}"

        write_audit(settings.audit_log_path, tool="explain_query", sql=validated.sql,
                    outcome="explained", tables=validated.tables)
        tables = ", ".join(validated.tables) or "(none)"
        return (
            f"Normalized SQL (enforced LIMIT {validated.enforced_limit}):\n"
            f"```sql\n{validated.sql}\n```\n"
            f"Reads tables: {tables}\n\nQuery plan:\n```\n{plan}\n```"
        )

    @mcp.tool()
    def run_query(sql: str) -> str:
        """Run a read-only SQL query and return the results as a table.

        The query is validated through the safety policy first: only a single
        read-only SELECT is allowed, a row limit is enforced, and a statement
        timeout applies. Writes, DDL, and stacked statements are rejected. Call
        list_tables / describe_table first to ground your SQL in the real schema.
        """
        try:
            validated = validate_query(sql, settings, dialect=db.sqlglot_dialect)
        except UnsafeQueryError as e:
            write_audit(settings.audit_log_path, tool="run_query", sql=sql,
                        outcome="blocked", error=str(e))
            return f"Query rejected by safety policy: {e}"

        try:
            result = db.execute(validated)
        except SQLAlchemyError as e:
            write_audit(settings.audit_log_path, tool="run_query", sql=validated.sql,
                        outcome="error", tables=validated.tables, error=str(e))
            return f"Query failed: {e}"

        write_audit(settings.audit_log_path, tool="run_query", sql=validated.sql,
                    outcome="allowed", tables=validated.tables, row_count=result.row_count)
        return _render_result(result)

    return mcp


def main() -> None:
    """Console-script entry point. Builds the server and serves over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
