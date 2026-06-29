"""MCP server entry point — wires the tools to the Safety Core + engine.

Run as a stdio MCP server (how Claude Desktop / Cursor launch it):

    mcp-db-server

Tools exposed:
    list_tables()            -> tables visible under the access policy
    describe_table(name)     -> columns, types, keys
    explain_query(sql)       -> human + engine explanation, no rows returned   [Day 5]
    run_query(sql)           -> validated, capped, read-only result set        [Day 5]

Tool docstrings double as the descriptions the client LLM reads, so they are
written for that audience.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings
from .engine import Database, TableAccessError


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

    return mcp


def main() -> None:
    """Console-script entry point. Builds the server and serves over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
