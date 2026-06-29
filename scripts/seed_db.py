"""Create and seed the demo SQLite database (``demo.db``).

A small but realistic e-commerce schema so reviewers get something meaningful to
ask in natural language: customers, products, orders, order_items. The data is
generated deterministically (fixed RNG seed) so the demo DB is reproducible and
queries return stable answers.

Usage:
    python scripts/seed_db.py [--db PATH]

Try asking the LLM things like:
    - "Which 5 customers have spent the most?"
    - "What's total revenue by product category?"
    - "How many orders were placed each month in 2025?"
    - "Which products have never been ordered?"
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

# Deterministic so the seeded DB and all example answers are reproducible.
SEED = 42

SCHEMA = """
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL,
    email        TEXT    NOT NULL UNIQUE,
    country      TEXT    NOT NULL,
    signup_date  TEXT    NOT NULL          -- ISO date
);

CREATE TABLE products (
    id        INTEGER PRIMARY KEY,
    name      TEXT    NOT NULL,
    category  TEXT    NOT NULL,
    price     REAL    NOT NULL CHECK (price >= 0)
);

CREATE TABLE orders (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    order_date   TEXT    NOT NULL,         -- ISO date
    status       TEXT    NOT NULL          -- 'completed' | 'shipped' | 'pending' | 'cancelled'
);

CREATE TABLE order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id),
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  REAL    NOT NULL           -- price captured at time of order
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
"""

FIRST_NAMES = [
    "Ava", "Liam", "Noah", "Emma", "Olivia", "Aarav", "Priya", "Wei", "Mei", "Sofia",
    "Mateo", "Lucas", "Amara", "Yuki", "Omar", "Fatima", "Hiro", "Nina", "Diego", "Zoe",
]
LAST_NAMES = [
    "Patel", "Smith", "Garcia", "Chen", "Kim", "Mueller", "Rossi", "Silva", "Khan", "Nguyen",
    "Johnson", "Lopez", "Ali", "Tanaka", "Okafor", "Novak", "Haddad", "Ivanov", "Costa", "Reed",
]
COUNTRIES = ["USA", "India", "Germany", "UK", "Canada", "Australia", "Japan", "Brazil"]

# (name, category, price)
PRODUCTS = [
    ("Wireless Mouse", "Electronics", 24.99),
    ("Mechanical Keyboard", "Electronics", 89.00),
    ("USB-C Hub", "Electronics", 39.50),
    ("Noise-Cancelling Headphones", "Electronics", 199.00),
    ("4K Monitor", "Electronics", 329.00),
    ("Webcam 1080p", "Electronics", 59.99),
    ("Standing Desk", "Furniture", 449.00),
    ("Ergonomic Chair", "Furniture", 279.00),
    ("Desk Lamp", "Furniture", 34.00),
    ("Bookshelf", "Furniture", 120.00),
    ("Cotton T-Shirt", "Apparel", 19.99),
    ("Hoodie", "Apparel", 44.99),
    ("Running Shoes", "Apparel", 89.99),
    ("Baseball Cap", "Apparel", 14.99),
    ("Winter Jacket", "Apparel", 159.00),
    ("Stainless Water Bottle", "Home", 22.00),
    ("Ceramic Mug", "Home", 12.50),
    ("Scented Candle", "Home", 18.00),
    ("Throw Blanket", "Home", 39.00),
    ("Cutting Board", "Home", 27.50),
    ("Yoga Mat", "Sports", 29.99),
    ("Dumbbell Set", "Sports", 79.00),
    ("Resistance Bands", "Sports", 16.99),
    ("Foam Roller", "Sports", 24.00),
    ("Jump Rope", "Sports", 9.99),
    ("Notebook A5", "Stationery", 6.50),
    ("Gel Pen Pack", "Stationery", 8.99),
    ("Sticky Notes", "Stationery", 4.25),
    ("Desk Planner", "Stationery", 15.00),
    ("Highlighter Set", "Stationery", 7.75),
]

STATUSES = ["completed", "completed", "completed", "shipped", "pending", "cancelled"]

N_CUSTOMERS = 60
N_ORDERS = 400
DATE_START = date(2024, 1, 1)
DATE_END = date(2025, 12, 31)


def _random_date(rng: random.Random) -> str:
    span = (DATE_END - DATE_START).days
    return (DATE_START + timedelta(days=rng.randint(0, span))).isoformat()


def seed(db_path: Path) -> None:
    rng = random.Random(SEED)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)

        # Customers ----------------------------------------------------------
        customers = []
        used_emails: set[str] = set()
        for cid in range(1, N_CUSTOMERS + 1):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            name = f"{first} {last}"
            base = f"{first}.{last}".lower()
            email = f"{base}@example.com"
            n = 1
            while email in used_emails:
                n += 1
                email = f"{base}{n}@example.com"
            used_emails.add(email)
            customers.append((cid, name, email, rng.choice(COUNTRIES), _random_date(rng)))
        conn.executemany(
            "INSERT INTO customers (id, name, email, country, signup_date) VALUES (?,?,?,?,?)",
            customers,
        )

        # Products -----------------------------------------------------------
        products = [(pid, name, cat, price) for pid, (name, cat, price) in enumerate(PRODUCTS, 1)]
        conn.executemany(
            "INSERT INTO products (id, name, category, price) VALUES (?,?,?,?)", products
        )
        price_by_id = {pid: price for pid, _, _, price in products}

        # Orders + items -----------------------------------------------------
        orders = []
        items = []
        item_id = 1
        # A few products are intentionally never ordered (nice "which products have
        # never been ordered?" demo query). Reserve the last 3 product ids.
        orderable_ids = [p[0] for p in products][:-3]

        for oid in range(1, N_ORDERS + 1):
            cust = rng.randint(1, N_CUSTOMERS)
            orders.append((oid, cust, _random_date(rng), rng.choice(STATUSES)))
            for _ in range(rng.randint(1, 4)):
                pid = rng.choice(orderable_ids)
                qty = rng.randint(1, 5)
                items.append((item_id, oid, pid, qty, price_by_id[pid]))
                item_id += 1

        conn.executemany(
            "INSERT INTO orders (id, customer_id, order_date, status) VALUES (?,?,?,?)", orders
        )
        conn.executemany(
            "INSERT INTO order_items (id, order_id, product_id, quantity, unit_price) "
            "VALUES (?,?,?,?,?)",
            items,
        )

        conn.commit()
        _print_summary(conn, db_path)
    finally:
        conn.close()


def _print_summary(conn: sqlite3.Connection, db_path: Path) -> None:
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("customers", "products", "orders", "order_items")
    }
    print(f"Seeded {db_path.resolve()}")
    for table, n in counts.items():
        print(f"  {table:<12} {n:>5} rows")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the demo e-commerce SQLite database.")
    parser.add_argument(
        "--db",
        default="demo.db",
        type=Path,
        help="Path to the SQLite database file to create (default: demo.db).",
    )
    args = parser.parse_args()
    seed(args.db)


if __name__ == "__main__":
    main()
