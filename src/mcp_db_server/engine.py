"""Database access layer (SQLAlchemy) — read-only connections for SQLite & Postgres.

The engine layer connects, introspects, and executes *already-validated* queries.
Safety is the Safety Core's job; this layer adds **defence in depth** so that even
a query that somehow slipped the gate cannot mutate data:

  * every connection is opened read-only at the driver level
    (SQLite ``PRAGMA query_only=ON`` / Postgres ``default_transaction_read_only``);
  * a statement timeout aborts runaway queries
    (Postgres ``statement_timeout`` / SQLite progress-handler deadline);
  * results are capped and a ``truncated`` flag is reported.

Introspection (``list_tables`` / ``describe_table``) honours the same allow/deny
policy as query execution, so the model can never even *see* a forbidden table.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine

from .config import Settings
from .safety import ValidatedQuery

# Map SQLAlchemy dialect names to sqlglot dialect names.
_SQLGLOT_DIALECTS = {"sqlite": "sqlite", "postgresql": "postgres"}

# How often (in VM instructions) SQLite checks the timeout deadline.
_SQLITE_PROGRESS_OPS = 10_000


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    row_count: int
    truncated: bool  # True if the result was cut at settings.max_rows


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool
    primary_key: bool


class TableAccessError(Exception):
    """Raised when introspection targets a table the policy forbids."""


class Database:
    """Owns the SQLAlchemy engine and exposes safe introspection + execution."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine = create_engine(settings.database_url, pool_pre_ping=True)
        self._dialect = self._engine.dialect.name
        self._install_read_only_guard()

    # -- public API ---------------------------------------------------------
    @property
    def sqlglot_dialect(self) -> str | None:
        """The sqlglot dialect name to validate/render SQL with for this engine."""
        return _SQLGLOT_DIALECTS.get(self._dialect)

    def list_tables(self) -> list[str]:
        """Tables visible under the access policy (allow-list then deny-list)."""
        names = inspect(self._engine).get_table_names()
        return sorted(n for n in names if self._table_permitted(n))

    def describe_table(self, name: str) -> list[ColumnInfo]:
        """Columns, types, nullability and primary-key flags for ``name``."""
        if not self._table_permitted(name):
            raise TableAccessError(f"Access to table '{name}' is not permitted.")
        inspector = inspect(self._engine)
        if name not in inspector.get_table_names():
            raise TableAccessError(f"Table '{name}' does not exist.")
        pk_cols = set(inspector.get_pk_constraint(name).get("constrained_columns") or [])
        return [
            ColumnInfo(
                name=col["name"],
                type=str(col["type"]),
                nullable=bool(col.get("nullable", True)),
                primary_key=col["name"] in pk_cols,
            )
            for col in inspector.get_columns(name)
        ]

    def execute(self, query: ValidatedQuery) -> QueryResult:
        """Run a validated query under the statement timeout and report results."""
        with self._engine.connect() as conn:
            self._apply_statement_timeout(conn)
            result = conn.execute(text(query.sql))
            columns = list(result.keys())
            rows = [tuple(row) for row in result.fetchall()]

        max_rows = self._settings.max_rows
        truncated = query.enforced_limit >= max_rows and len(rows) >= max_rows
        return QueryResult(
            columns=columns, rows=rows, row_count=len(rows), truncated=truncated
        )

    def dispose(self) -> None:
        self._engine.dispose()

    # -- access policy ------------------------------------------------------
    def _table_permitted(self, name: str) -> bool:
        lname = name.lower()
        allowed = {t.lower() for t in self._settings.allowed_tables}
        denied = {t.lower() for t in self._settings.denied_tables}
        if allowed and lname not in allowed:
            return False
        return lname not in denied

    # -- read-only enforcement (defence in depth) ---------------------------
    def _install_read_only_guard(self) -> None:
        dialect = self._dialect

        @event.listens_for(self._engine, "connect")
        def _set_read_only(dbapi_conn, _record):  # pragma: no cover - driver callback
            cursor = dbapi_conn.cursor()
            try:
                if dialect == "sqlite":
                    cursor.execute("PRAGMA query_only = ON")
                elif dialect == "postgresql":
                    cursor.execute("SET SESSION default_transaction_read_only = on")
            finally:
                cursor.close()

    # -- statement timeout --------------------------------------------------
    def _apply_statement_timeout(self, conn) -> None:
        seconds = self._settings.statement_timeout_seconds
        if self._dialect == "postgresql":
            conn.execute(text("SET statement_timeout = :ms"), {"ms": seconds * 1000})
        elif self._dialect == "sqlite":
            raw = conn.connection.dbapi_connection
            deadline = time.monotonic() + seconds
            raw.set_progress_handler(
                lambda: 1 if time.monotonic() > deadline else 0, _SQLITE_PROGRESS_OPS
            )
