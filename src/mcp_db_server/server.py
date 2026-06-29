"""MCP server entry point — exposes the tools over stdio.

Run as a stdio MCP server (how Claude Desktop / Cursor launch it):

    mcp-db-server

Tools exposed:
    list_tables()            -> tables visible under the access policy
    describe_table(name)     -> columns, types, keys
    explain_query(sql)       -> normalized SQL, tables, and the engine query plan
    run_query(sql)           -> validated, capped, read-only result set

All logic lives in :class:`mcp_db_server.service.QueryService`, shared with the
demo CLI; these tools are thin transport wrappers. Tool docstrings double as the
descriptions the client LLM reads, so they are written for that audience.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import Settings, load_settings
from .service import QueryService


def build_server(settings: Settings | None = None) -> FastMCP:
    """Build a configured FastMCP server. Kept separate from ``main`` for testing."""
    service = QueryService(settings or load_settings())
    mcp = FastMCP("mcp-db-server")

    @mcp.tool()
    def list_tables() -> str:
        """List the database tables you are allowed to query.

        Returns the visible table names. Always call this first to discover the
        schema; tables excluded by the server's access policy will not appear.
        """
        return service.list_tables()

    @mcp.tool()
    def describe_table(table_name: str) -> str:
        """Describe one table's columns: name, type, nullability, and primary key.

        Use this to learn a table's structure before writing a query. Returns an
        error message if the table does not exist or is not permitted by policy.
        """
        return service.describe_table(table_name)

    @mcp.tool()
    def explain_query(sql: str) -> str:
        """Explain a read-only SQL query WITHOUT returning any data rows.

        Validates the query through the safety policy, then returns the normalized
        SQL that would actually run (with the enforced row limit), the tables it
        reads, and the database's query plan. Call this to preview a query before
        running it.
        """
        return service.explain_query(sql)

    @mcp.tool()
    def run_query(sql: str) -> str:
        """Run a read-only SQL query and return the results as a table.

        The query is validated through the safety policy first: only a single
        read-only SELECT is allowed, a row limit is enforced, and a statement
        timeout applies. Writes, DDL, and stacked statements are rejected. Call
        list_tables / describe_table first to ground your SQL in the real schema.
        """
        return service.run_query(sql)

    return mcp


def main() -> None:
    """Console-script entry point. Builds the server and serves over stdio."""
    build_server().run()


if __name__ == "__main__":
    main()
