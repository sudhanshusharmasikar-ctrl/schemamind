"""
Schema retrieval: the core experiment of this project.

With a handful of tables you could paste the whole schema into every prompt
and it would work fine. The point here is to build and measure the technique
you'd actually need on a warehouse with hundreds of tables, where that stops
being possible. eval/run_eval.py compares accuracy WITH retrieval against
accuracy with the FULL schema dumped in, on this small database, specifically
so you have a number for whether retrieval helps or hurts at this scale.
Expect it to roughly tie or slightly underperform full-schema here -- that
would be the honest, reportable finding for a 5-table database. The technique
is what you're demonstrating, not a claim that retrieval always wins.
"""
from __future__ import annotations

from sentence_transformers import SentenceTransformer
import numpy as np

from .config import EMBED_MODEL, JOIN_TABLES, TOP_K_TABLES
from .schema_introspect import TableInfo, introspect

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


def _targets(table: TableInfo) -> set[str]:
    """The tables this table's foreign keys point to."""
    return {c.references.split(".")[0] for c in table.columns if c.references}


def with_join_tables(chosen: list[TableInfo], all_tables: list[TableInfo]) -> list[TableInfo]:
    """The chosen tables, plus what it takes to read and join them: every
    table a chosen table's foreign keys point to (an order_items row names
    its product only by id), then every table whose foreign keys link two of
    them (order_items links orders to products)."""
    by_name = {t.name: t for t in all_tables}
    out = list(chosen)
    names = {t.name for t in out}
    for t in chosen:
        for name in sorted(_targets(t) - names):
            if name in by_name:  # a foreign key to a missing table can't help
                out.append(by_name[name])
                names.add(name)
    for t in all_tables:
        if t.name not in names and len(_targets(t) & names) >= 2:
            out.append(t)
            names.add(t.name)
    return out


class SchemaRetriever:
    def __init__(self, db_path=None):
        self.tables: list[TableInfo] = introspect(db_path) if db_path else introspect()
        descriptions = [t.describe() for t in self.tables]
        self.embeddings = get_model().encode(
            descriptions, convert_to_numpy=True, normalize_embeddings=True
        )

    def relevant_tables(self, question: str, top_k: int = TOP_K_TABLES) -> list[TableInfo]:
        qv = get_model().encode([question], convert_to_numpy=True, normalize_embeddings=True)[0]
        scores = self.embeddings @ qv
        order = np.argsort(-scores)[:top_k]
        chosen = [self.tables[i] for i in order]
        return with_join_tables(chosen, self.tables) if JOIN_TABLES else chosen

    def full_schema(self) -> list[TableInfo]:
        return self.tables

    def schema_text(self, tables: list[TableInfo]) -> str:
        return "\n\n".join(t.describe() for t in tables)
