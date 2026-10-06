"""
Reads the database's own schema so the rest of the system doesn't need it
hardcoded anywhere. This is what makes the project work on ANY SQLite
database, not just the sample shop.db.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .config import DB_PATH, VALUE_LIST_MAX

# Values longer than this are free text, not categories worth listing.
_MAX_VALUE_LENGTH = 40


@dataclass
class ColumnInfo:
    name: str
    type: str
    is_pk: bool
    references: str | None  # "other_table.other_column" if a foreign key
    values: list[str] | None = None  # every value, for a short text column


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[tuple] = field(default_factory=list)

    def describe(self) -> str:
        """
        A plain-English rendering of the table, used both as the text that
        gets embedded for retrieval and as the schema text shown to the LLM.
        Sample rows show what a row looks like ('shipped', not an integer
        code). A short text column also lists every value it holds, because
        the model takes two sample rows as the whole list; and the values
        help retrieval too, since a question names them ("UPI", "Monitor").
        """
        cols = ", ".join(
            f"{c.name} ({c.type}{', PK' if c.is_pk else ''}"
            f"{', -> ' + c.references if c.references else ''}"
            f"{', one of: ' + ', '.join(_sql_literal(v) for v in c.values) if c.values else ''})"
            for c in self.columns
        )
        lines = [f"Table {self.name}: {cols}"]
        if self.sample_rows:
            col_names = [c.name for c in self.columns]
            lines.append(f"Sample rows from {self.name}:")
            for row in self.sample_rows:
                lines.append("  " + ", ".join(f"{n}={v}" for n, v in zip(col_names, row)))
        return "\n".join(lines)


def _sql_literal(value: str) -> str:
    # 'upi', written the way the model should put it in a query
    return "'" + str(value).replace("'", "''") + "'"


def _value_list(cur, table: str, column: ColumnInfo, max_values: int) -> list[str] | None:
    """Every value of a text column that holds only a few short ones, like
    a status or a payment method; None for anything else."""
    # SQLite's own rule for a text column: CHAR, CLOB or TEXT in the type
    text = any(k in column.type.upper() for k in ("CHAR", "CLOB", "TEXT"))
    if max_values <= 0 or column.is_pk or column.references or not text:
        return None
    cur.execute(f'SELECT DISTINCT "{column.name}" FROM "{table}" '
                f'WHERE "{column.name}" IS NOT NULL LIMIT {max_values + 1}')
    values = [r[0] for r in cur.fetchall()]
    if not values or len(values) > max_values or any(len(str(v)) > _MAX_VALUE_LENGTH for v in values):
        return None
    return sorted(values, key=str)


def introspect(db_path=DB_PATH, sample_rows: int = 2,
               max_values: int = VALUE_LIST_MAX) -> list[TableInfo]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    table_names = [r["name"] for r in cur.fetchall()]

    tables: list[TableInfo] = []
    for tname in table_names:
        cur.execute(f"PRAGMA table_info('{tname}')")
        col_rows = cur.fetchall()

        cur.execute(f"PRAGMA foreign_key_list('{tname}')")
        fk_rows = {r["from"]: f"{r['table']}.{r['to']}" for r in cur.fetchall()}

        columns = [
            ColumnInfo(
                name=r["name"],
                type=r["type"],
                is_pk=bool(r["pk"]),
                references=fk_rows.get(r["name"]),
            )
            for r in col_rows
        ]
        for c in columns:
            c.values = _value_list(cur, tname, c, max_values)

        cur.execute(f"SELECT * FROM '{tname}' LIMIT {sample_rows}")
        rows = [tuple(r) for r in cur.fetchall()]

        tables.append(TableInfo(name=tname, columns=columns, sample_rows=rows))

    conn.close()
    return tables


if __name__ == "__main__":
    for t in introspect():
        print(t.describe())
        print()
