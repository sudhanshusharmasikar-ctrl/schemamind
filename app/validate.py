"""
Validates generated SQL before it ever touches the database.

A prompt instruction like "only write SELECT statements" is not a safety
control -- it's a suggestion the model can ignore or get wrong under a
confusing question. This module parses the SQL into an actual syntax tree
and rejects anything that isn't a read. That's the difference between hoping
and checking.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Statement types that must never reach the database, however they're phrased.
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
             exp.Alter, exp.TruncateTable)


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None
    parsed: object | None = None


def validate(sql: str, dialect: str = "sqlite") -> ValidationResult:
    sql = sql.strip().rstrip(";")
    if not sql:
        return ValidationResult(False, "Empty query.")

    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
    except Exception as e:
        return ValidationResult(False, f"SQL does not parse: {e}")

    if isinstance(parsed, FORBIDDEN):
        return ValidationResult(
            False, f"Query type {type(parsed).__name__} is not allowed. Read-only access only."
        )

    if not isinstance(parsed, (exp.Select, exp.Union)):
        return ValidationResult(
            False, f"Only SELECT queries are allowed, got {type(parsed).__name__}."
        )

    # Belt-and-braces: even inside a syntactically valid SELECT, reject any
    # forbidden node type buried in a subquery or CTE.
    for node in parsed.walk():
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, FORBIDDEN):
            return ValidationResult(False, "Write operation found nested inside query.")

    return ValidationResult(True, parsed=parsed)
