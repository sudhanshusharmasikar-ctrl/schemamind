"""
Template mode: each question shape gives the right answer, and a question it
only partly understands is refused instead of answered wrongly. The first
five tests are answers it used to get wrong without any error.
"""
import pytest

from app.executor import execute
from app.sql_generate import generate_sql
from app.validate import validate


def ask(db, question):
    """Generate template SQL for a question, check it, and run it."""
    sql = generate_sql(question, [], mode="template")
    assert sql is not None, f"template mode refused {question!r}"
    assert validate(sql).ok
    result = execute(sql, db)
    assert result.ok, result.error
    return result


def test_a_count_with_a_city_counts_only_that_city(db):
    # used to answer 150: "how many orders" matched and "from Pune" was ignored
    assert ask(db, "How many orders from Pune?").rows == [(22,)]


def test_revenue_by_category_is_grouped_by_category(db):
    # used to group by city, because "Category" != "category"
    r = ask(db, "Revenue by Category")
    assert r.columns[0] == "category"
    assert r.rows == [("Electronics", 4703200.0), ("Accessories", 88000.0)]


def test_a_question_with_words_left_over_is_refused():
    # used to filter on city = 'The' and answer "no orders"
    assert generate_sql("Show orders in the last month", [], mode="template") is None


def test_top_customers_by_orders_ranks_by_number_of_orders(db):
    # used to rank by money spent
    r = ask(db, "Top 3 customers by orders")
    truth = execute(
        "SELECT COUNT(*) AS n FROM orders GROUP BY customer_id ORDER BY n DESC LIMIT 3", db
    ).rows
    assert [row[1] for row in r.rows] == [n for (n,) in truth]  # 9, 7, 7


def test_how_many_cancelled_orders_gives_a_number(db):
    # used to list the 24 orders instead of counting them
    assert ask(db, "How many cancelled orders?").rows == [(24,)]


def test_both_revenue_questions_use_one_definition_of_revenue(db):
    total_paid = execute("SELECT SUM(amount) FROM payments", db).rows[0][0]  # 4,791,200
    by_category = sum(revenue for _, revenue in ask(db, "revenue by category").rows)
    by_city = sum(revenue for _, revenue in ask(db, "What is the revenue by city?").rows)
    assert by_category == by_city == total_paid


@pytest.mark.parametrize("question, count", [
    ("how many orders", 150),
    ("How many customers are there?", 40),
    ("how many orders in Indore", 31),
])
def test_counts(db, question, count):
    assert ask(db, question).rows == [(count,)]


@pytest.mark.parametrize("question", [  # the examples in the README
    "how many orders",
    "top 5 customers by spend",
    "orders from Indore",
    "revenue by category",
    "cancelled orders",
    "Show me all cancelled orders",
])
def test_readme_examples_still_work(db, question):
    assert ask(db, question).rows


@pytest.mark.parametrize("question", [
    "What is the average order value?",
    "How many orders from Pune last year?",
    "revenue by product and month",
    "orders",
])
def test_questions_it_does_not_know_are_refused(question):
    assert generate_sql(question, [], mode="template") is None
