"""MCP server entry point — wires the four tools to the Safety Core + engine.

Run as a stdio MCP server (how Claude Desktop / Cursor launch it):

    mcp-db-server

Tools exposed:
    list_tables()            -> tables visible under the access policy
    describe_table(name)     -> columns, types, keys
    explain_query(sql)       -> human + engine explanation, no rows returned
    run_query(sql)           -> validated, capped, read-only result set

Implemented Days 4–5. Stub below.
"""

from __future__ import annotations


def main() -> None:
    """Console-script entry point. Builds the server and serves over stdio."""
    raise NotImplementedError("Implemented on Days 4-5")


if __name__ == "__main__":
    main()
