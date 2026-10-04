"""End to end through the agent loop: unsafe SQL never reaches the database."""
from app import agent as agent_mod
from app.agent import Agent
from app.config import MAX_REPAIR_ATTEMPTS
from app.executor import execute
from app.schema_introspect import introspect


class AllTables:
    """Stands in for SchemaRetriever, so no embedding model is loaded."""

    def __init__(self, db):
        self.tables = introspect(db)

    def relevant_tables(self, question, top_k=3):
        return self.tables[:top_k]

    def full_schema(self):
        return self.tables


def test_a_normal_question_still_works(db):
    result = Agent(retriever=AllTables(db)).ask("How many orders are there?", mode="template")
    assert result.ok
    assert result.rows == [(150,)]


def test_an_injected_drop_is_refused_and_the_data_survives(db, monkeypatch):
    monkeypatch.setattr(agent_mod, "generate_sql",
                        lambda *args, **kwargs: "SELECT * FROM customers; DROP TABLE customers")
    result = Agent(retriever=AllTables(db)).ask("How many customers are there?")
    assert not result.ok
    assert "one statement" in result.error
    assert result.attempts == MAX_REPAIR_ATTEMPTS + 1  # tried, repaired, then gave up
    assert execute("SELECT COUNT(*) FROM customers", db).rows == [(40,)]
