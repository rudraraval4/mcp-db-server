"""Application service layer — the single implementation of every operation.

Both front-ends (the MCP server and the demo CLI) call ``QueryService`` so their
behaviour, safety enforcement, and audit logging can never drift apart. Methods
return display-ready strings; the front-end only deals with transport.
"""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from .audit import write_audit
from .config import Settings
from .engine import Database, TableAccessError
from .formatting import render_result, render_schema, render_table_list
from .safety import UnsafeQueryError, validate_query


class QueryService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db = Database(settings)

    # -- introspection ------------------------------------------------------
    def list_tables(self) -> str:
        return render_table_list(self._db.list_tables())

    def describe_table(self, table_name: str) -> str:
        try:
            columns = self._db.describe_table(table_name)
        except TableAccessError as e:
            return f"Error: {e}"
        return render_schema(table_name, columns)

    # -- query --------------------------------------------------------------
    def run_query(self, sql: str) -> str:
        try:
            validated = validate_query(sql, self._settings, dialect=self._db.sqlglot_dialect)
        except UnsafeQueryError as e:
            self._audit("run_query", sql, "blocked", error=str(e))
            return f"Query rejected by safety policy: {e}"

        try:
            result = self._db.execute(validated)
        except SQLAlchemyError as e:
            self._audit("run_query", validated.sql, "error",
                        tables=validated.tables, error=str(e))
            return f"Query failed: {e}"

        self._audit("run_query", validated.sql, "allowed",
                    tables=validated.tables, row_count=result.row_count)
        return render_result(result)

    def explain_query(self, sql: str) -> str:
        try:
            validated = validate_query(sql, self._settings, dialect=self._db.sqlglot_dialect)
        except UnsafeQueryError as e:
            self._audit("explain_query", sql, "blocked", error=str(e))
            return f"Query rejected by safety policy: {e}"

        try:
            plan = self._db.explain(validated)
        except SQLAlchemyError as e:
            self._audit("explain_query", validated.sql, "error",
                        tables=validated.tables, error=str(e))
            return f"Could not explain query: {e}"

        self._audit("explain_query", validated.sql, "explained", tables=validated.tables)
        tables = ", ".join(validated.tables) or "(none)"
        return (
            f"Normalized SQL (enforced LIMIT {validated.enforced_limit}):\n"
            f"```sql\n{validated.sql}\n```\n"
            f"Reads tables: {tables}\n\nQuery plan:\n```\n{plan}\n```"
        )

    # -- internals ----------------------------------------------------------
    def _audit(self, tool: str, sql: str, outcome, **kw) -> None:
        write_audit(self._settings.audit_log_path, tool=tool, sql=sql,
                    outcome=outcome, **kw)
