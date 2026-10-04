"""The validator lets exactly one read query through and refuses everything else."""
import pytest

from app.validate import validate


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) FROM orders",
    "SELECT COUNT(*) FROM orders;",  # a trailing semicolon is fine
    "WITH paid AS (SELECT order_id FROM payments) SELECT COUNT(*) FROM paid",
    "SELECT name FROM customers WHERE customer_id IN (SELECT customer_id FROM orders)",
    "SELECT city FROM customers UNION SELECT category FROM products",
    "SELECT city FROM customers INTERSECT SELECT city FROM customers WHERE city = 'Pune'",
    "SELECT customer_id FROM customers EXCEPT SELECT customer_id FROM orders",
])
def test_read_queries_are_allowed(sql):
    result = validate(sql)
    assert result.ok, result.reason


@pytest.mark.parametrize("sql", [
    "SELECT * FROM customers; DROP TABLE customers;",  # a write hidden behind a read
    "SELECT 1; SELECT 2",
])
def test_a_second_statement_is_refused(sql):
    result = validate(sql)
    assert not result.ok
    assert "one statement" in result.reason


@pytest.mark.parametrize("sql", [
    "DROP TABLE customers",
    "DELETE FROM orders",
    "UPDATE orders SET status = 'cancelled'",
    "INSERT INTO customers VALUES (99, 'Eve', 'Pune', '2025-01-01')",
    "ALTER TABLE orders ADD COLUMN note TEXT",
    "CREATE TABLE notes (body TEXT)",
    "WITH gone AS (DELETE FROM orders RETURNING *) SELECT * FROM gone",  # write inside a CTE
    "PRAGMA writable_schema = 1",
    "ATTACH DATABASE 'other.db' AS other",
    "VACUUM INTO 'copy.db'",  # would copy the whole database to a file
])
def test_anything_but_a_read_is_refused(sql):
    assert not validate(sql).ok


@pytest.mark.parametrize("sql", ["", "   ", ";", "SELEC * FROM orders"])
def test_empty_or_broken_sql_is_refused(sql):
    assert not validate(sql).ok
