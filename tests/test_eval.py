"""
eval/run_eval.py turns the agent's answers into the README's numbers, so check
how it compares rows and counts outcomes, and that every gold query in
eval/questions.jsonl is a fair reference.
"""
import pytest

from app.agent import AgentResult
from app.executor import execute
from app.sql_generate import LLMAuthError, LLMError
from eval.run_eval import evaluate, gold_problems, gold_tables, load_questions, rows_match


def test_rows_match_ignores_row_order_and_number_formats():
    assert rows_match([("Pune", 1174100.0), ("Delhi", 521100)],
                      [("Delhi", 521100.0), ("Pune", 1174100)])
    assert rows_match([(38025.39682539683,)], [(38025.4,)])  # an average, rounded


def test_rows_match_allows_extra_columns_in_any_position():
    assert rows_match([("Customer 7",)], [(7, "Customer 7", 476000.0)])
    assert rows_match([("Pune", 22)], [(22, "x", "Pune")])


def test_rows_match_rejects_a_different_answer():
    assert not rows_match([(17,)], [(18,)])
    assert not rows_match([("Customer 21",), ("Customer 38",)], [("Customer 21",)])
    assert not rows_match([("Pune", 22)], [("Pune",)])  # a column is missing


def test_gold_tables_lists_every_table_a_query_reads():
    sql = "SELECT c.city FROM customers c JOIN orders o ON o.customer_id = c.customer_id"
    assert gold_tables(sql) == {"customers", "orders"}


def test_the_question_file_is_a_fair_reference(db):
    rows = load_questions()
    assert gold_problems(rows) == []
    answerable = [r for r in rows if r["answerable"]]
    assert len(answerable) >= 15 and len(rows) > len(answerable)
    assert len({r["question"] for r in rows}) == len(rows), "a question appears twice"


def test_gold_problems_catches_unsafe_broken_and_empty_gold_sql(db):
    rows = [{"question": "a", "answerable": True, "gold_sql": "DELETE FROM orders"},
            {"question": "b", "answerable": True, "gold_sql": "SELECT nope FROM customers"},
            {"question": "c", "answerable": True, "gold_sql": "SELECT name FROM customers WHERE city = 'Atlantis'"}]
    problems = gold_problems(rows)
    assert "validator refuses" in problems[0] and "fails" in problems[1] and "no rows" in problems[2]
    assert execute("SELECT COUNT(*) FROM orders").rows == [(150,)]  # the DELETE never ran


class ScriptedAgent:
    """Answers each question with a fixed SQL; None means the model said
    CANNOT_ANSWER, and an exception is raised as if the LLM call failed."""

    def __init__(self, script, tables_used=("customers", "orders", "payments")):
        self.script, self.tables_used = script, list(tables_used)

    def ask(self, question, mode, use_full_schema):
        sql, attempts = self.script[question]
        if isinstance(sql, Exception):
            raise sql
        if sql is None:
            return AgentResult(question, None, [], [], False, "Could not generate a query.",
                               attempts, use_full_schema, self.tables_used)
        r = execute(sql)
        return AgentResult(question, sql, r.columns, r.rows, r.ok, r.error, attempts,
                           use_full_schema, self.tables_used)


ROWS = [
    {"question": "customers", "answerable": True, "gold_sql": "SELECT COUNT(*) FROM customers"},
    {"question": "monitors", "answerable": True, "gold_sql":
        "SELECT COUNT(DISTINCT o.order_id) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id "
        "JOIN products p ON p.product_id = oi.product_id WHERE p.name = 'Monitor' AND o.status = 'delivered'"},
    {"question": "city", "answerable": True, "gold_sql":
        "SELECT city FROM customers GROUP BY city ORDER BY COUNT(*) DESC LIMIT 1"},
    {"question": "pune", "answerable": True, "gold_sql":
        "SELECT COUNT(*) FROM orders o JOIN customers c ON c.customer_id = o.customer_id WHERE c.city = 'Pune'"},
    {"question": "employees", "answerable": False},
    {"question": "email", "answerable": False},
]


def test_evaluate_counts_each_kind_of_outcome(db):
    script = {
        "customers": ("SELECT COUNT(*) AS n FROM customers", 2),        # right, after one repair
        "monitors": ("SELECT COUNT(*) FROM orders o JOIN order_items oi ON oi.order_id = o.order_id "
                     "JOIN products p ON p.product_id = oi.product_id "
                     "WHERE p.name = 'Monitor' AND o.status = 'delivered'", 1),  # 18 lines, not 17 orders
        "city": (None, 1),                                               # refused an answerable one
        "pune": (LLMError("Mistral answered 503, still failing after 5 tries"), 1),
        "employees": (None, 1),                                          # refused, rightly
        "email": ("SELECT name FROM customers WHERE customer_id = 12", 1),  # answered anyway
    }
    m = evaluate(ROWS, ScriptedAgent(script), use_full_schema=False, mode="mistral")
    assert (m["n_answerable"], m["n_unanswerable"]) == (4, 2)
    assert (m["correct"], m["wrong_rows"], m["refused_answerable"], m["failed_to_run"]) == (1, 1, 1, 1)
    assert m["execution_accuracy_pct"] == 25.0
    assert m["correct_after_repair"] == 1
    assert m["unanswerable_refused"] == 1
    # customers and city need only `customers`; monitors needs order_items and products too
    assert m["gold_tables_in_prompt"] == 2
    outcomes = {r["question"]: r["outcome"] for r in m["records"]}
    assert outcomes["email"] == "answered" and outcomes["pune"] == "error"


def test_a_rejected_api_key_stops_the_evaluation(db):
    script = {r["question"]: (LLMAuthError("Mistral rejected the API key (401)."), 1) for r in ROWS}
    with pytest.raises(LLMAuthError):
        evaluate(ROWS, ScriptedAgent(script), use_full_schema=False, mode="mistral")
