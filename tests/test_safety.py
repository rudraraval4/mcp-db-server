"""Adversarial tests for the Safety Core.

These tests are the proof behind the README's safety claims. Each one pins a
specific guarantee so a regression can never quietly weaken the gate.
"""

from __future__ import annotations

import pytest

from mcp_db_server.config import Settings
from mcp_db_server.safety import UnsafeQueryError, validate_query

DIALECT = "sqlite"


def make_settings(**overrides) -> Settings:
    base = dict(max_rows=100, allowed_tables=[], denied_tables=[])
    base.update(overrides)
    return Settings(**base)


def validate(sql: str, **overrides):
    return validate_query(sql, make_settings(**overrides), dialect=DIALECT)


# --------------------------------------------------------------------------- #
# Legitimate read queries are allowed
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM customers",
        "SELECT id, name FROM customers WHERE country = 'India'",
        "SELECT country, COUNT(*) FROM customers GROUP BY country",
        "SELECT * FROM customers JOIN orders ON orders.customer_id = customers.id",
        "WITH recent AS (SELECT * FROM orders) SELECT * FROM recent",
        "SELECT * FROM customers WHERE id IN (SELECT customer_id FROM orders)",
        "SELECT id FROM customers UNION SELECT customer_id FROM orders",
        "SELECT 1",
    ],
)
def test_allows_read_queries(sql):
    result = validate(sql)
    assert result.sql  # produced hardened SQL
    assert result.enforced_limit == 100


# --------------------------------------------------------------------------- #
# Writes / DDL are blocked at the AST level
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO customers (id, name) VALUES (1, 'x')",
        "UPDATE customers SET name = 'x' WHERE id = 1",
        "DELETE FROM customers WHERE id = 1",
        "DROP TABLE customers",
        "CREATE TABLE evil (id INT)",
        "ALTER TABLE customers ADD COLUMN ssn TEXT",
        "TRUNCATE TABLE customers",
        "CREATE TABLE t AS SELECT * FROM customers",
    ],
)
def test_blocks_writes_and_ddl(sql):
    with pytest.raises(UnsafeQueryError):
        validate(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "InSeRt INTO customers VALUES (1)",
        "dRoP TABLE customers",
        "DeLeTe FROM customers",
    ],
)
def test_casing_does_not_bypass(sql):
    """Keyword casing tricks must not slip past — AST parsing is case-insensitive."""
    with pytest.raises(UnsafeQueryError):
        validate(sql)


# --------------------------------------------------------------------------- #
# Stacked / injected statements are blocked
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM customers; DROP TABLE customers",
        "SELECT 1; DELETE FROM orders",
        "SELECT * FROM customers WHERE id = 1; DROP TABLE customers --",
        "SELECT 1; SELECT 2",  # even two reads: single-statement rule
    ],
)
def test_blocks_stacked_queries(sql):
    with pytest.raises(UnsafeQueryError):
        validate(sql)


def test_trailing_semicolon_is_fine():
    """A single statement with a trailing semicolon is not 'stacked'."""
    result = validate("SELECT * FROM customers;")
    assert result.enforced_limit == 100


# --------------------------------------------------------------------------- #
# Other non-read statements
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * INTO backup FROM customers",   # SELECT ... INTO writes a table
        "PRAGMA table_info(customers)",
        "ATTACH DATABASE 'other.db' AS other",
        "VACUUM",
    ],
)
def test_blocks_other_non_read_statements(sql):
    with pytest.raises(UnsafeQueryError):
        validate(sql)


# --------------------------------------------------------------------------- #
# Empty / unparseable input
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sql", ["", "   ", "\n\t", "this is not sql ;;;"])
def test_blocks_empty_or_garbage(sql):
    with pytest.raises(UnsafeQueryError):
        validate(sql)


# --------------------------------------------------------------------------- #
# Table access control
# --------------------------------------------------------------------------- #
def test_allow_list_blocks_other_tables():
    with pytest.raises(UnsafeQueryError):
        validate("SELECT * FROM orders", allowed_tables=["customers"])


def test_allow_list_permits_listed_table():
    result = validate("SELECT * FROM customers", allowed_tables=["customers"])
    assert result.tables == ["customers"]


def test_deny_list_blocks_table():
    with pytest.raises(UnsafeQueryError):
        validate("SELECT * FROM orders", denied_tables=["orders"])


def test_deny_list_is_case_insensitive():
    with pytest.raises(UnsafeQueryError):
        validate("SELECT * FROM Orders", denied_tables=["orders"])


def test_cte_name_is_not_treated_as_a_table():
    """A CTE alias must not be mistaken for a base table in the deny-list check."""
    sql = "WITH orders AS (SELECT * FROM customers) SELECT * FROM orders"
    result = validate(sql, denied_tables=["orders"])
    assert result.tables == ["customers"]


# --------------------------------------------------------------------------- #
# LIMIT enforcement
# --------------------------------------------------------------------------- #
def test_injects_limit_when_missing():
    result = validate("SELECT * FROM customers")
    assert result.enforced_limit == 100
    assert "LIMIT 100" in result.sql.upper()


def test_caps_oversized_limit():
    result = validate("SELECT * FROM customers LIMIT 10000")
    assert result.enforced_limit == 100
    assert "LIMIT 100" in result.sql.upper()


def test_keeps_smaller_limit():
    result = validate("SELECT * FROM customers LIMIT 5")
    assert result.enforced_limit == 5
    assert "LIMIT 5" in result.sql.upper()


def test_non_literal_limit_falls_back_to_cap():
    """A non-literal LIMIT can't be trusted as a number, so the cap is enforced."""
    result = validate("SELECT * FROM customers LIMIT (SELECT COUNT(*) FROM orders)")
    assert result.enforced_limit == 100


def test_reports_referenced_tables():
    result = validate(
        "SELECT * FROM customers JOIN orders ON orders.customer_id = customers.id"
    )
    assert result.tables == ["customers", "orders"]
