# How I built a safe "talk to your database" MCP server

I let an LLM run SQL against a real database — and made it safe by construction.
Here's the design and the one decision that made it work.

![Architecture](assets/architecture.svg)

## The problem

Connecting an LLM to a SQL database is equal parts useful and terrifying. Ask
"which five customers spent the most?" and a model will happily write the join.
But the same channel that returns `SELECT` results can, with one bad token,
return `DROP TABLE`. The interesting engineering isn't generating SQL — clients
already do that well. It's **guaranteeing** the generated SQL can only ever read,
can only touch what it's allowed to, and can't run away with the database.

That guarantee is the whole project.

## The decision that shaped everything

The natural instinct is to put the natural-language → SQL step *inside* the
server. I deliberately didn't. The client LLM (Claude Desktop, Cursor, …) writes
the SQL; the server's only job is to be an **enforced boundary** around what that
SQL is allowed to do.

This inverts where the value sits. The server isn't a thin LLM wrapper — it's the
thing a client *can't* safely do for itself: a hard gate. It also means no API
key, no provider lock-in, and behaviour that's identical for any MCP client.

## Two independent layers

A query has to get past both to touch data:

1. **The Safety Core** parses every query to a [sqlglot](https://github.com/tobymao/sqlglot)
   AST — not a regex. On the parsed tree it enforces: read-only (only `SELECT`
   survives), a single statement (no `SELECT …; DROP …`), table allow/deny lists,
   and an injected `LIMIT` cap. Because it reasons over the AST, the usual bypasses
   — uppercase `DrOp`, `-- comment` injection, stacked statements, `SELECT … INTO`
   — have nothing to grab onto.

2. **The engine** opens every connection read-only at the driver level
   (`PRAGMA query_only=ON` for SQLite, `default_transaction_read_only` for
   Postgres) and applies a statement timeout. So even a write that somehow slipped
   the gate is refused by the connection itself.

Defence in depth: the gate refuses to *emit* a write; the connection refuses to
*execute* one.

## Proving it, not claiming it

Safety claims are only as good as their tests, so the adversarial cases are the
spec. The suite fires casing tricks, comment injection, stacked queries,
`PRAGMA`/`ATTACH`/`VACUUM`, and `SELECT … INTO` at the gate and asserts each is
rejected — and a separate test pushes an `INSERT` straight past the gate to prove
the read-only connection still blocks it and the data is untouched. 73 tests,
97% coverage.

## What it looks like

The same logic backs both an MCP server (over stdio) and a tiny `mcp-db-demo`
CLI, so they can't drift. In Claude Desktop:

> **You:** Which five customers spent the most?
> **Claude:** *(writes the join, calls `run_query`, returns a table)*
> **You:** Now delete the orders table.
> **Claude:** Query rejected by safety policy: only read-only SELECT queries are allowed.

## Stack & what's next

Python 3.11+, the official MCP SDK (FastMCP), SQLAlchemy (SQLite + Postgres),
sqlglot, Pydantic. Every query — allowed or blocked — lands in a JSONL audit log.

Next I'd add column-level masking (e.g. never return a `password_hash` column) and
per-tool rate limits. But the core idea holds: give the model freedom to ask, and
put the guarantees in a layer it can't talk its way around.

Repo: https://github.com/rudraraval4/mcp-db-server

---

## Short version (LinkedIn / X)

I let an LLM run SQL on a real database — safely.

The trick: don't put natural-language → SQL *in* the server. Let the client LLM
write the SQL, and make the server an enforced, read-only boundary it can't talk
its way around.

Two layers, both tested:
• A sqlglot **AST gate** — only a single, capped SELECT survives. Casing tricks,
  comment injection, stacked `DROP`s, `SELECT … INTO`: all rejected on the parse
  tree, not by regex.
• A **read-only connection** — even a write that slips the gate is refused by the
  driver itself.

73 adversarial tests, 97% coverage, works in Claude Desktop, SQLite + Postgres.
It's an MCP server, so any MCP client can plug in.

Ask it "who are my top customers?" → table. Ask it to "drop the orders table" →
politely refused.

Built with Python + the MCP SDK. Repo 👇
https://github.com/rudraraval4/mcp-db-server

#MCP #LLM #AIAgents #Python
