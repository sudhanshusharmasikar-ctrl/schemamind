"""
Builds a small sample e-commerce database so the project is runnable the
moment you install it, without needing your own data source.

Run:  python -m app.seed_db
"""
import sqlite3
from datetime import date, timedelta
import random

from .config import DB_PATH

SCHEMA = """
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    city        TEXT NOT NULL,
    signup_date DATE NOT NULL
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL,
    price      REAL NOT NULL
);

CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date  DATE NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('placed','shipped','delivered','cancelled'))
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL
);

CREATE TABLE payments (
    payment_id INTEGER PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(order_id),
    amount     REAL NOT NULL,
    method     TEXT NOT NULL CHECK (method IN ('card','upi','cod')),
    paid_on    DATE NOT NULL
);
"""

CITIES = ["Indore", "Pune", "Bengaluru", "Delhi", "Jaipur", "Mumbai"]
CATEGORIES = {
    "Laptop": 55000, "Headphones": 2500, "Keyboard": 1800,
    "Monitor": 12000, "Mouse": 800, "Webcam": 2200,
    "Desk Lamp": 1200, "Backpack": 1600,
}
STATUSES = ["placed", "shipped", "delivered", "delivered", "delivered", "cancelled"]
METHODS = ["card", "upi", "upi", "cod"]


def build(n_customers=40, n_products=8, n_orders=150, seed=7) -> None:
    random.seed(seed)
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    base_day = date(2025, 1, 1)

    customers = [
        (i, f"Customer {i}", random.choice(CITIES),
         (base_day + timedelta(days=random.randint(0, 500))).isoformat())
        for i in range(1, n_customers + 1)
    ]
    conn.executemany(
        "INSERT INTO customers VALUES (?,?,?,?)", customers
    )

    products = [
        (i, name, "Electronics" if name != "Backpack" else "Accessories", price)
        for i, (name, price) in enumerate(CATEGORIES.items(), start=1)
    ]
    conn.executemany("INSERT INTO products VALUES (?,?,?,?)", products)

    order_item_id = 1
    payment_id = 1
    for order_id in range(1, n_orders + 1):
        cust = random.randint(1, n_customers)
        odate = base_day + timedelta(days=random.randint(0, 600))
        status = random.choice(STATUSES)
        conn.execute(
            "INSERT INTO orders VALUES (?,?,?,?)",
            (order_id, cust, odate.isoformat(), status),
        )
        total = 0.0
        for _ in range(random.randint(1, 3)):
            pid = random.randint(1, n_products)
            price = products[pid - 1][3]
            qty = random.randint(1, 3)
            conn.execute(
                "INSERT INTO order_items VALUES (?,?,?,?,?)",
                (order_item_id, order_id, pid, qty, price),
            )
            total += price * qty
            order_item_id += 1

        if status != "cancelled":
            conn.execute(
                "INSERT INTO payments VALUES (?,?,?,?,?)",
                (payment_id, order_id, round(total, 2), random.choice(METHODS),
                 (odate + timedelta(days=1)).isoformat()),
            )
            payment_id += 1

    conn.commit()
    conn.close()


if __name__ == "__main__":
    build()
    print(f"Seeded sample database at {DB_PATH}")
