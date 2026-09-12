"""
The agent loop: retrieve schema -> generate SQL -> validate -> execute ->
repair on failure, bounded.

This is the file that answers "what makes it an agent and not just a script"
-- it decides, based on what comes back at each step, whether to retry, how,
and when to give up.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import GEN_MODE, MAX_REPAIR_ATTEMPTS, TOP_K_TABLES
from .executor import ExecutionResult, execute
from .schema_retriever import SchemaRetriever
from .sql_generate import generate_sql
from .validate import validate


@dataclass
class AgentResult:
    question: str
    sql: str | None
    columns: list[str]
    rows: list[tuple]
    ok: bool
    error: str | None
    attempts: int
    used_full_schema: bool
    tables_used: list[str] = field(default_factory=list)


class Agent:
    def __init__(self, retriever: SchemaRetriever | None = None):
        self.retriever = retriever or SchemaRetriever()

    def ask(
        self,
        question: str,
        mode: str | None = None,
        use_full_schema: bool = False,
        top_k: int = TOP_K_TABLES,
    ) -> AgentResult:
        mode = mode or GEN_MODE
        tables = (
            self.retriever.full_schema()
            if use_full_schema
            else self.retriever.relevant_tables(question, top_k=top_k)
        )
        table_names = [t.name for t in tables]

        error_context = ""
        last_sql = None
        for attempt in range(1, MAX_REPAIR_ATTEMPTS + 2):  # first try + N repairs
            sql = generate_sql(question, tables, mode=mode, error_context=error_context)
            last_sql = sql

            if sql is None:
                return AgentResult(
                    question=question, sql=None, columns=[], rows=[],
                    ok=False, error="Could not generate a query for this question.",
                    attempts=attempt, used_full_schema=use_full_schema,
                    tables_used=table_names,
                )

            v = validate(sql)
            if not v.ok:
                error_context = f"Validation error: {v.reason}\nQuery was: {sql}"
                if attempt > MAX_REPAIR_ATTEMPTS:
                    return AgentResult(
                        question=question, sql=sql, columns=[], rows=[],
                        ok=False, error=v.reason, attempts=attempt,
                        used_full_schema=use_full_schema, tables_used=table_names,
                    )
                continue

            result: ExecutionResult = execute(sql)
            if result.ok:
                return AgentResult(
                    question=question, sql=sql, columns=result.columns,
                    rows=result.rows, ok=True, error=None, attempts=attempt,
                    used_full_schema=use_full_schema, tables_used=table_names,
                )

            error_context = f"Execution error: {result.error}\nQuery was: {sql}"
            if attempt > MAX_REPAIR_ATTEMPTS:
                return AgentResult(
                    question=question, sql=sql, columns=[], rows=[],
                    ok=False, error=result.error, attempts=attempt,
                    used_full_schema=use_full_schema, tables_used=table_names,
                )

        # Unreachable, but keeps type-checkers happy.
        return AgentResult(
            question=question, sql=last_sql, columns=[], rows=[], ok=False,
            error="Exhausted repair attempts.", attempts=MAX_REPAIR_ATTEMPTS + 1,
            used_full_schema=use_full_schema, tables_used=table_names,
        )
