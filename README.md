# mcp-db-server

> A production-grade **MCP server** that lets any LLM client (Claude Desktop, Cursor, …)
> query a SQL database in natural language — **read-only, AST-validated, and capped.**

The LLM writes the SQL. This server **never trusts it.** Every query is parsed to an
abstract syntax tree and forced through a safety gate before it is allowed near a
read-only database connection.

<!-- TODO(Day 8): demo GIF here -->

## Why this exists

Letting an LLM run SQL against your database is powerful and terrifying in equal
measure. The hard part isn't generating SQL — clients already do that well. The hard
part is **guaranteeing** the generated SQL can't read what it shouldn't, can't write,
and can't run away with your database. That guarantee is this project.

## Safety guarantees

Every `run_query` call must pass the Safety Core before execution:

- **Read-only** — only `SELECT` / `WITH … SELECT` survive; all DML/DDL is rejected at
  the AST level (not by keyword regex, so comment and casing tricks don't help).
- **Single statement** — stacked queries (`SELECT …; DROP …`) are rejected.
- **Table access control** — allow-list and deny-list enforced against the parsed tables.
- **Row caps** — a `LIMIT` is injected/enforced at `MCP_DB_MAX_ROWS`.
- **Statement timeout** — long queries are aborted.
- **Audit log** — every attempt (allowed or blocked) is logged.

## Tools

| Tool | Purpose |
|------|---------|
| `list_tables()` | Tables visible under the access policy |
| `describe_table(name)` | Columns, types, keys |
| `explain_query(sql)` | Explains a query (and engine plan) without returning rows |
| `run_query(sql)` | Validated, capped, read-only result set |

## Quickstart

```bash
git clone https://github.com/rudraraval4/mcp-db-server
cd mcp-db-server
pip install -e ".[dev]"
python scripts/seed_db.py     # creates demo.db (e-commerce sample data)
```

## Use it in Claude Desktop

<!-- TODO(Day 7): finalize once entry point is verified -->

```json
{
  "mcpServers": {
    "db": {
      "command": "mcp-db-server",
      "env": {
        "MCP_DB_DATABASE_URL": "sqlite:////absolute/path/to/demo.db",
        "MCP_DB_MAX_ROWS": "1000"
      }
    }
  }
}
```

## Configuration

All knobs are environment variables (prefix `MCP_DB_`):

| Variable | Default | Meaning |
|----------|---------|---------|
| `MCP_DB_DATABASE_URL` | `sqlite:///./demo.db` | SQLAlchemy URL (SQLite or Postgres) |
| `MCP_DB_MAX_ROWS` | `1000` | Hard row cap |
| `MCP_DB_STATEMENT_TIMEOUT_SECONDS` | `10` | Abort slow queries |
| `MCP_DB_ALLOWED_TABLES` | _(empty)_ | Allow-list; if set, only these tables |
| `MCP_DB_DENIED_TABLES` | _(empty)_ | Deny-list |
| `MCP_DB_AUDIT_LOG_PATH` | `audit.log` | Audit log location |

## Architecture

<!-- TODO(Day 8): diagram -->

```
LLM client ──MCP/stdio──▶ tools ──▶ Safety Core (sqlglot AST) ──▶ read-only engine (SQLite/Postgres)
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
