"""
Turns a question plus retrieved schema into SQL.

Two modes:

  template -- pattern-matches the question against a handful of known
              question shapes for the sample shop.db and fills in SQL.
              No API key needed, always runs, but only covers questions
              shaped like the ones it knows. This exists so the retrieval,
              validation and execution layers are demonstrable for free.
              It is NOT text-to-SQL -- say that plainly if asked.

  mistral  -- the real thing. Sends the retrieved schema and the question
              to an LLM and asks for SQL back. This is the mode you want
              running, and evaluated, before this goes on a resume as
              "text-to-SQL".
"""
from __future__ import annotations

import re
import textwrap

import requests

from .config import MISTRAL_API_KEY, MISTRAL_MODEL
from .schema_introspect import TableInfo

SYSTEM_PROMPT = textwrap.dedent(
    """\
    You write a single SQLite SELECT query that answers the user's question,
    using only the tables and columns given below. Never write INSERT,
    UPDATE, DELETE, DROP, ALTER or CREATE. Return ONLY the SQL, no
    explanation, no markdown fences.

    If the question cannot be answered with the given tables, return exactly:
    CANNOT_ANSWER
    """
)


def _mistral_generate(question: str, schema_text: str, extra_note: str = "") -> str:
    if not MISTRAL_API_KEY:
        raise RuntimeError("SCHEMAMIND_GEN_MODE=mistral but MISTRAL_API_KEY is unset.")
    user_content = f"Schema:\n{schema_text}\n\nQuestion: {question}"
    if extra_note:
        user_content += f"\n\n{extra_note}"

    resp = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": MISTRAL_MODEL,
            "max_tokens": 300,
            "temperature": 0.0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
        },
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"].strip()
    # strip markdown fences if the model adds them despite instructions
    text = re.sub(r"^```(sql)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    return text.strip()


# ---------------------------------------------------------------------------
# Template mode: a small, explicit set of question shapes for the sample DB.
# ---------------------------------------------------------------------------
_TEMPLATES = [
    (
        re.compile(r"how many (orders|customers|products)", re.I),
        lambda m: f"SELECT COUNT(*) AS count FROM {m.group(1)};",
    ),
    (
        re.compile(r"top (\d+) customers by (spend|total|orders)", re.I),
        lambda m: (
            "SELECT c.name, SUM(p.amount) AS total_spend "
            "FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
            "JOIN payments p ON p.order_id = o.order_id "
            "GROUP BY c.customer_id ORDER BY total_spend DESC "
            f"LIMIT {m.group(1)};"
        ),
    ),
    (
        re.compile(r"orders (from|in) (\w+)", re.I),
        lambda m: (
            "SELECT o.order_id, c.name, o.order_date, o.status "
            "FROM orders o JOIN customers c ON c.customer_id = o.customer_id "
            f"WHERE c.city = '{m.group(2).capitalize()}';"
        ),
    ),
    (
        re.compile(r"revenue by (category|city)", re.I),
        lambda m: (
            "SELECT pr.category, SUM(oi.quantity * oi.unit_price) AS revenue "
            "FROM order_items oi JOIN products pr ON pr.product_id = oi.product_id "
            "GROUP BY pr.category ORDER BY revenue DESC;"
            if m.group(1) == "category" else
            "SELECT c.city, SUM(p.amount) AS revenue "
            "FROM customers c JOIN orders o ON o.customer_id = c.customer_id "
            "JOIN payments p ON p.order_id = o.order_id "
            "GROUP BY c.city ORDER BY revenue DESC;"
        ),
    ),
    (
        re.compile(r"cancelled orders", re.I),
        lambda m: "SELECT * FROM orders WHERE status = 'cancelled';",
    ),
]


def _template_generate(question: str) -> str | None:
    for pattern, builder in _TEMPLATES:
        m = pattern.search(question)
        if m:
            return builder(m)
    return None


def generate_sql(
    question: str,
    tables: list[TableInfo],
    mode: str,
    error_context: str = "",
) -> str | None:
    """Returns SQL, or None if generation could not produce anything."""
    schema_text = "\n\n".join(t.describe() for t in tables)

    if mode == "template":
        sql = _template_generate(question)
        if sql is None:
            return None
        return sql

    if mode == "mistral":
        note = f"Your previous query failed with this error, fix it:\n{error_context}" if error_context else ""
        sql = _mistral_generate(question, schema_text, note)
        if sql.strip() == "CANNOT_ANSWER":
            return None
        return sql

    raise ValueError(f"Unknown generation mode: {mode}")
