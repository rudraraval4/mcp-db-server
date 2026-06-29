"""Append-only audit log of every query attempt — allowed, blocked, or errored.

One JSON object per line (JSONL) so the log is both human-skimmable and trivially
machine-parseable. Logging is best-effort: a failure to write the audit line must
never take down a tool call, so write errors are swallowed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

Outcome = Literal["allowed", "blocked", "error", "explained"]


def write_audit(
    path: str,
    *,
    tool: str,
    sql: str,
    outcome: Outcome,
    tables: list[str] | None = None,
    row_count: int | None = None,
    error: str | None = None,
) -> None:
    """Append one audit record. Never raises."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "outcome": outcome,
        "sql": sql,
        "tables": tables or [],
        "row_count": row_count,
        "error": error,
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # auditing is best-effort; never break a query over a log write
