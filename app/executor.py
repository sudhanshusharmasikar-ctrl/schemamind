"""
Executes a validated SELECT and nothing else. Opens the connection read-only
at the OS level as a second, independent layer under the AST check in
validate.py -- if the parser is ever fooled, the database itself still
refuses to accept a write. A time limit and a row limit stop a runaway read
(a never-ending recursive query, a huge cross join) from hanging the API.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .config import DB_PATH, MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS

# SQLite calls the progress handler every PROGRESS_STEPS virtual-machine
# instructions: cheap enough to cost nothing, frequent enough to stop a query
# within milliseconds of its deadline.
PROGRESS_STEPS = 10_000


@dataclass
class ExecutionResult:
    ok: bool
    columns: list[str]
    rows: list[tuple]
    error: str | None = None
    truncated: bool = False


def execute(
    sql: str, db_path=DB_PATH, time_limit: float = QUERY_TIMEOUT_SECONDS
) -> ExecutionResult:
    # mode=ro opens the SQLite file itself as read-only; a write reaching
    # this point (validator bypassed somehow) fails at the OS/file level.
    uri = f"file:{db_path}?mode=ro"
    conn = None
    try:
        # connect(timeout=...) only limits waiting for a locked file; it does
        # not stop a slow query. The progress handler does: once it returns
        # True, SQLite aborts the running statement with "interrupted".
        conn = sqlite3.connect(uri, uri=True, timeout=time_limit)
        deadline = time.monotonic() + time_limit
        conn.set_progress_handler(lambda: time.monotonic() > deadline, PROGRESS_STEPS)
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchmany(MAX_RESULT_ROWS + 1)
        columns = [d[0] for d in cur.description] if cur.description else []
        truncated = len(rows) > MAX_RESULT_ROWS
        return ExecutionResult(
            ok=True, columns=columns, rows=rows[:MAX_RESULT_ROWS], truncated=truncated
        )
    except sqlite3.Error as e:
        error = str(e)
        if error == "interrupted":
            error = f"Query stopped: it ran longer than the {time_limit:g}-second limit."
        return ExecutionResult(ok=False, columns=[], rows=[], error=error)
    finally:
        if conn is not None:
            conn.close()
