"""Safety Core — the heart of the project.

Every SQL string the client LLM produces passes through :func:`validate_query`
BEFORE it is allowed near the database. Validation is done on the parsed AST
(via sqlglot), never on raw string/regex matching, so comment tricks, stacked
statements, and casing games cannot slip a write past the gate.

Guarantees enforced here:
  1. The input parses and is exactly one statement (no stacked queries).
  2. The top-level statement is a read (SELECT / set-op / parenthesised SELECT).
  3. No DDL/DML nodes appear anywhere in the tree (INSERT/UPDATE/DELETE/DROP/...),
     including inside subqueries and CTEs, and no ``SELECT ... INTO``.
  4. Every referenced base table satisfies the allow/deny lists (CTE names are
     not treated as tables).
  5. A LIMIT is present and never exceeds ``settings.max_rows`` — if the query
     omits one or asks for more, it is rewritten down to the cap.

The returned :class:`ValidatedQuery` carries normalised, hardened SQL that the
engine layer can execute as-is.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from .config import Settings


class UnsafeQueryError(Exception):
    """Raised when a query violates a safety guarantee. Message is user-facing."""


@dataclass
class ValidatedQuery:
    """A query that has passed every safety check and is cleared to execute."""

    sql: str  # normalized SQL, with an enforced LIMIT, ready to run
    tables: list[str]  # base tables the query reads from
    enforced_limit: int


# Statement types that are legitimate top-level reads.
_READ_TYPES: tuple[type, ...] = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)

# Node types that must never appear anywhere in a read query. Resolved by name so
# the set degrades gracefully across sqlglot versions rather than crashing on import.
_FORBIDDEN_NAMES = (
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "AlterTable",
    "TruncateTable", "Merge", "Command", "Set", "Use", "Into", "Grant",
    "Copy", "Attach", "Detach", "Pragma",
)
_FORBIDDEN_TYPES: tuple[type, ...] = tuple(
    getattr(exp, name) for name in _FORBIDDEN_NAMES if hasattr(exp, name)
)


def validate_query(
    sql: str, settings: Settings, *, dialect: str | None = None
) -> ValidatedQuery:
    """Parse, inspect, and harden ``sql``; raise :class:`UnsafeQueryError` if unsafe.

    ``dialect`` is the sqlglot dialect to parse/render with (e.g. ``"sqlite"`` or
    ``"postgres"``); ``None`` uses sqlglot's generic dialect.
    """
    if not sql or not sql.strip():
        raise UnsafeQueryError("Empty query.")

    statement = _parse_single_statement(sql, dialect)

    if not isinstance(statement, _READ_TYPES):
        raise UnsafeQueryError(
            "Only read-only SELECT queries are allowed; "
            f"got a {type(statement).__name__.upper()} statement."
        )

    _reject_forbidden_nodes(statement)

    tables = _extract_base_tables(statement)
    _enforce_table_access(tables, settings)

    hardened, enforced_limit = _enforce_limit(statement, settings.max_rows)

    return ValidatedQuery(
        sql=hardened.sql(dialect=dialect),
        tables=tables,
        enforced_limit=enforced_limit,
    )


def _parse_single_statement(sql: str, dialect: str | None) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as e:
        raise UnsafeQueryError(f"Could not parse SQL: {e}") from e

    if not statements:
        raise UnsafeQueryError("Empty query.")
    if len(statements) > 1:
        raise UnsafeQueryError(
            "Only a single statement is allowed; stacked queries are rejected."
        )
    return statements[0]


def _reject_forbidden_nodes(statement: exp.Expression) -> None:
    for node in statement.find_all(*_FORBIDDEN_TYPES):
        raise UnsafeQueryError(
            f"Disallowed operation: {type(node).__name__.upper()}. "
            "This server is strictly read-only."
        )


def _extract_base_tables(statement: exp.Expression) -> list[str]:
    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    tables: set[str] = set()
    for table in statement.find_all(exp.Table):
        name = table.name
        if name and name.lower() not in cte_names:
            tables.add(name)
    return sorted(tables)


def _enforce_table_access(tables: list[str], settings: Settings) -> None:
    allowed = {t.lower() for t in settings.allowed_tables}
    denied = {t.lower() for t in settings.denied_tables}
    for name in tables:
        lname = name.lower()
        if allowed and lname not in allowed:
            raise UnsafeQueryError(f"Access to table '{name}' is not on the allow-list.")
        if lname in denied:
            raise UnsafeQueryError(f"Access to table '{name}' is denied.")


def _enforce_limit(statement: exp.Expression, max_rows: int) -> tuple[exp.Expression, int]:
    existing = _existing_limit(statement)
    effective = max_rows if existing is None else min(existing, max_rows)
    return statement.limit(effective), effective


def _existing_limit(statement: exp.Expression) -> int | None:
    limit_node = statement.args.get("limit")
    if limit_node is None:
        return None
    value = limit_node.expression
    if isinstance(value, exp.Literal) and value.is_int:
        return int(value.name)
    # Non-literal limit (expression/parameter): treat as unknown and let the cap apply.
    return None
