"""
What the model is shown about each table, and which tables retrieval brings
along. Both fix what the evaluation caught: the model took two sample rows as
the complete list of a column's values, and without the table that names
product ids it guessed an id.
"""
import sqlite3

import numpy as np

from app import schema_retriever
from app.schema_introspect import introspect
from app.schema_retriever import with_join_tables


def names(tables):
    return [t.name for t in tables]


def pick(all_tables, *wanted):
    by_name = {t.name: t for t in all_tables}
    return [by_name[n] for n in wanted]


def test_a_short_text_column_lists_every_value(db):
    tables = {t.name: t for t in introspect(db)}
    assert "method (TEXT, one of: 'card', 'cod', 'upi')" in tables["payments"].describe()
    assert "'Monitor'" in tables["products"].describe()  # not in the two sample rows


def test_long_lists_numbers_dates_and_ids_are_not_listed(db):
    customers = {t.name: t for t in introspect(db)}["customers"]
    assert {c.name: c.values for c in customers.columns} == {
        "customer_id": None,
        "name": None,  # 40 names: too many to list
        "city": ["Bengaluru", "Delhi", "Indore", "Jaipur", "Mumbai", "Pune"],
        "signup_date": None,
    }


def test_free_text_is_not_listed_and_quotes_are_escaped(tmp_path):
    path = tmp_path / "notes.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, kind VARCHAR(10), body TEXT)")
    con.executemany("INSERT INTO notes (kind, body) VALUES (?, ?)",
                    [("o'clock", "a long note " * 5), ("plain", "short")])
    con.commit()
    con.close()
    notes = introspect(path)[0]
    assert {c.name: c.values for c in notes.columns} == {"id": None, "kind": ["o'clock", "plain"], "body": None}
    assert "kind (VARCHAR(10), one of: 'o''clock', 'plain')" in notes.describe()


def test_value_lists_can_be_turned_off(db):
    assert "one of" not in "".join(t.describe() for t in introspect(db, max_values=0))


def test_a_table_brings_the_tables_its_ids_point_to(db):
    tables = introspect(db)
    assert names(with_join_tables(pick(tables, "order_items"), tables)) == ["order_items", "orders", "products"]
    assert names(with_join_tables(pick(tables, "payments", "customers"), tables)) == \
        ["payments", "customers", "orders"]


def test_a_table_that_links_two_chosen_ones_is_added(db):
    # the Backpack question: customers and products only meet through order_items
    tables = introspect(db)
    assert names(with_join_tables(pick(tables, "customers", "products", "orders"), tables)) == \
        ["customers", "products", "orders", "order_items"]


def test_nothing_is_added_when_nothing_is_missing(db):
    tables = introspect(db)
    assert names(with_join_tables(pick(tables, "customers"), tables)) == ["customers"]
    assert names(with_join_tables(pick(tables, "orders", "customers"), tables)) == ["orders", "customers"]


class OneHot:
    """Stands in for the embedding model: each text points at one table, the
    one a description starts with ("Table orders: ...") or a question names."""

    NAMES = ["customers", "products", "orders", "order_items", "payments"]

    def encode(self, texts, **kwargs):
        return np.eye(len(self.NAMES))[[self.NAMES.index(t.removeprefix("Table ").split(":")[0]) for t in texts]]


def test_retrieval_adds_the_join_tables_unless_turned_off(db, monkeypatch):
    monkeypatch.setattr(schema_retriever, "get_model", lambda: OneHot())
    retriever = schema_retriever.SchemaRetriever(db)
    assert names(retriever.relevant_tables("order_items", top_k=1)) == ["order_items", "orders", "products"]
    monkeypatch.setattr(schema_retriever, "JOIN_TABLES", False)
    assert names(retriever.relevant_tables("order_items", top_k=1)) == ["order_items"]
