"""
Reads the database's own schema so the rest of the system doesn't need it
hardcoded anywhere. This is what makes the project work on ANY SQLite
database, not just the sample shop.db.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .config import DB_PATH


@dataclass
class ColumnInfo:
    name: str
    type: str
    is_pk: bool
    references: str | None  # "other_table.other_column" if a foreign key


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    sample_rows: list[tuple] = field(default_factory=list)

    def describe(self) -> str:
        """
        A plain-English rendering of the table, used both as the text that
        gets embedded for retrieval and as the schema text shown to the LLM.
        Sample rows matter: they tell the model what a 'status' column
        actually contains ('shipped', not an integer code), which a bare
        column list can't.
        """
        cols = ", ".join(
            f"{c.name} ({c.type}{', PK' if c.is_pk else ''}"
            f"{', -> ' + c.references if c.references else ''})"
            for c in self.columns
        )
        lines = [f"Table {self.name}: {cols}"]
        if self.sample_rows:
            col_names = [c.name for c in self.columns]
            lines.append(f"Sample rows from {self.name}:")
            for row in self.sample_rows:
                lines.append("  " + ", ".join(f"{n}={v}" for n, v in zip(col_names, row)))
        return "\n".join(lines)


def introspect(db_path=DB_PATH, sample_rows: int = 2) -> list[TableInfo]:
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

        cur.execute(f"SELECT * FROM '{tname}' LIMIT {sample_rows}")
        rows = [tuple(r) for r in cur.fetchall()]

        tables.append(TableInfo(name=tname, columns=columns, sample_rows=rows))

    conn.close()
    return tables


if __name__ == "__main__":
    for t in introspect():
        print(t.describe())
        print()
