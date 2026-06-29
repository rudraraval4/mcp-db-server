"""Demo CLI — drive the server's tools from a terminal, no MCP client needed.

This is the fastest way for a reviewer to see the safety layer in action and the
basis for the README demo GIF. It uses the exact same :class:`QueryService` as
the MCP server, so what you see here is what an LLM client gets.

    mcp-db-demo tables
    mcp-db-demo describe customers
    mcp-db-demo query "SELECT country, COUNT(*) FROM customers GROUP BY country"
    mcp-db-demo explain "SELECT * FROM orders"

Point it at any database with --database-url (default: sqlite:///demo.db).
"""

from __future__ import annotations

import argparse

from .config import load_settings
from .service import QueryService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-db-demo",
        description="Query a database through the same safe service the MCP server uses.",
    )
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy URL (default: from MCP_DB_DATABASE_URL or sqlite:///demo.db).",
    )
    parser.add_argument(
        "--max-rows", type=int, help="Override the row cap for this invocation."
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("tables", help="List queryable tables.")

    describe = sub.add_parser("describe", help="Show a table's columns.")
    describe.add_argument("table")

    query = sub.add_parser("query", help="Run a read-only SELECT and print the rows.")
    query.add_argument("sql")

    explain = sub.add_parser("explain", help="Preview a query's plan without running it.")
    explain.add_argument("sql")

    return parser


def _make_service(args: argparse.Namespace) -> QueryService:
    settings = load_settings()
    if args.database_url:
        settings.database_url = args.database_url
    if args.max_rows is not None:
        settings.max_rows = args.max_rows
    return QueryService(settings)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    service = _make_service(args)

    if args.command == "tables":
        print(service.list_tables())
    elif args.command == "describe":
        print(service.describe_table(args.table))
    elif args.command == "query":
        print(service.run_query(args.sql))
    elif args.command == "explain":
        print(service.explain_query(args.sql))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
