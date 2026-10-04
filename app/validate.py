"""
Validates generated SQL before it ever touches the database.

A prompt instruction like "only write SELECT statements" is not a safety
control -- it's a suggestion the model can ignore or get wrong under a
confusing question. This module parses the SQL into an actual syntax tree
and rejects anything that isn't a single read query. That's the difference
between hoping and checking.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# Statement types that must never reach the database, however they're phrased.
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
             exp.Alter, exp.TruncateTable)

# A read query: a SELECT, or SELECTs combined with UNION / INTERSECT / EXCEPT.
# (Older sqlglot versions have no SetOperation; there all three subclass Union.)
READ_QUERY = (exp.Select, getattr(exp, "SetOperation", exp.Union))


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None
    parsed: object | None = None


def validate(sql: str, dialect: str = "sqlite") -> ValidationResult:
    if not sql.strip().strip(";").strip():
        return ValidationResult(False, "Empty query.")

    try:
        # parse() returns every statement in the string. parse_one() looked
        # only at the first one in older sqlglot versions, so a hidden
        # "...; DROP TABLE customers" behind a SELECT was never checked.
        statements = [s for s in sqlglot.parse(sql, dialect=dialect) if s is not None]
    except Exception as e:
        return ValidationResult(False, f"SQL does not parse: {e}")

    if len(statements) != 1:
        return ValidationResult(
            False, f"Exactly one statement is allowed, got {len(statements)}."
        )
    parsed = statements[0]

    if isinstance(parsed, FORBIDDEN):
        return ValidationResult(
            False, f"Query type {type(parsed).__name__} is not allowed. Read-only access only."
        )

    if not isinstance(parsed, READ_QUERY):
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
