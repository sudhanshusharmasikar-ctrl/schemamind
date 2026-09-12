"""
Run:  uvicorn app.api:app --reload
Docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .agent import Agent
from .config import DB_PATH, GEN_MODE, TOP_K_TABLES

_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DB_PATH.exists():
        _state["error"] = f"No database at {DB_PATH}. Run: python -m app.seed_db"
    else:
        _state["agent"] = Agent()
    yield
    _state.clear()


app = FastAPI(title="SchemaMind", version="1.0.0", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500)
    top_k_tables: int = Field(TOP_K_TABLES, ge=1, le=20)
    use_full_schema: bool = False
    mode: str | None = Field(None, pattern="^(template|mistral)$")


class AskResponse(BaseModel):
    question: str
    sql: str | None
    ok: bool
    error: str | None
    columns: list[str]
    rows: list[list]
    attempts: int
    tables_used: list[str]
    used_full_schema: bool
    latency_ms: float


def _agent() -> Agent:
    if "agent" not in _state:
        raise HTTPException(503, _state.get("error", "Agent not ready."))
    return _state["agent"]


@app.get("/health")
def health() -> dict:
    ready = "agent" in _state
    return {
        "status": "ok" if ready else "db_missing",
        "gen_mode": GEN_MODE,
        "tables": [t.name for t in _state["agent"].retriever.tables] if ready else [],
    }


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    t0 = time.perf_counter()
    r = _agent().ask(
        req.question,
        mode=req.mode,
        use_full_schema=req.use_full_schema,
        top_k=req.top_k_tables,
    )
    return AskResponse(
        question=r.question,
        sql=r.sql,
        ok=r.ok,
        error=r.error,
        columns=r.columns,
        rows=[list(row) for row in r.rows],
        attempts=r.attempts,
        tables_used=r.tables_used,
        used_full_schema=r.used_full_schema,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
