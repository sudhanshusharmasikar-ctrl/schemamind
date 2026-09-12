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

from .config import EMBED_MODEL, TOP_K_TABLES
from .schema_introspect import TableInfo, introspect

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBED_MODEL)
    return _model


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
        return [self.tables[i] for i in order]

    def full_schema(self) -> list[TableInfo]:
        return self.tables

    def schema_text(self, tables: list[TableInfo]) -> str:
        return "\n\n".join(t.describe() for t in tables)
