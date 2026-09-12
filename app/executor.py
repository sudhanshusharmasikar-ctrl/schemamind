"""
Executes a validated SELECT and nothing else. Opens the connection read-only
at the OS level as a second, independent layer under the AST check in
validate.py -- if the parser is ever fooled, the database itself still
refuses to accept a write.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .config import DB_PATH, MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS


@dataclass
class ExecutionResult:
    ok: bool
    columns: list[str]
    rows: list[tuple]
    error: str | None = None
    truncated: bool = False


def execute(sql: str, db_path=DB_PATH) -> ExecutionResult:
    # mode=ro opens the SQLite file itself as read-only; a write reaching
    # this point (validator bypassed somehow) fails at the OS/file level.
    uri = f"file:{db_path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=QUERY_TIMEOUT_SECONDS)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(MAX_RESULT_ROWS + 1)
        columns = [d[0] for d in cur.description] if cur.description else []
        truncated = len(rows) > MAX_RESULT_ROWS
        conn.close()
        return ExecutionResult(
            ok=True, columns=columns, rows=rows[:MAX_RESULT_ROWS], truncated=truncated
        )
    except sqlite3.Error as e:
        return ExecutionResult(ok=False, columns=[], rows=[], error=str(e))
