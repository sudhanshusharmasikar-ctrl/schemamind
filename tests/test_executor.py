"""The executor: a read-only connection, a row limit and a time limit."""
import time

import pytest

from app.config import MAX_RESULT_ROWS
from app.executor import execute


def test_a_read_returns_its_rows(db):
    r = execute("SELECT COUNT(*) FROM orders", db)
    assert r.ok
    assert r.rows == [(150,)]


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "DROP TABLE customers",
    "UPDATE orders SET status = 'cancelled'",
])
def test_the_database_itself_refuses_writes(db, sql):
    r = execute(sql, db)
    assert not r.ok
    assert "readonly" in r.error
    assert execute("SELECT COUNT(*) FROM orders", db).rows == [(150,)]  # nothing changed


def test_the_driver_runs_only_one_statement(db):
    r = execute("SELECT 1; DROP TABLE customers", db)
    assert not r.ok
    assert "one statement" in r.error


def test_a_large_result_is_cut_at_the_row_limit(db):
    r = execute("SELECT * FROM orders, customers", db)  # 150 x 40 = 6,000 rows
    assert r.ok and r.truncated
    assert len(r.rows) == MAX_RESULT_ROWS


@pytest.mark.parametrize("sql", [
    "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n) SELECT COUNT(*) FROM n",
    "SELECT COUNT(*) FROM orders a, orders b, orders c, orders d",  # 150^4 rows to count
])
def test_a_runaway_query_is_stopped_at_the_time_limit(db, sql):
    start = time.monotonic()
    r = execute(sql, db, time_limit=0.5)
    assert not r.ok
    assert "0.5-second limit" in r.error
    assert time.monotonic() - start < 3
