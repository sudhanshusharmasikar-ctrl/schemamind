"""
The eval that produces your resume numbers for SchemaMind.

Compares execution accuracy with schema RETRIEVAL against dumping the FULL
schema into the prompt, on the same question set. This needs SCHEMAMIND_GEN_MODE
= mistral to mean anything -- template mode is deterministic pattern matching,
so it will score identically both ways and that comparison teaches you nothing.

Build eval/questions.jsonl yourself: a question in plain English, and the
gold SQL you'd consider correct. Comparing RESULTS (not exact SQL text) is
what "execution accuracy" means, since two different queries can return the
same correct rows.

Usage:
    export SCHEMAMIND_GEN_MODE=mistral
    export MISTRAL_API_KEY=...
    python -m eval.run_eval
"""
from __future__ import annotations

import json
from pathlib import Path

from app.agent import Agent
from app.executor import execute

QUESTIONS = Path(__file__).parent / "questions.jsonl"


def load_questions() -> list[dict]:
    if not QUESTIONS.exists():
        raise SystemExit(
            f"{QUESTIONS} not found. Copy questions.example.jsonl and write "
            "questions with gold SQL for the sample shop.db schema."
        )
    rows = [json.loads(l) for l in QUESTIONS.read_text().splitlines() if l.strip()]
    for r in rows:
        assert "question" in r and "gold_sql" in r, f"bad row: {r}"
    return rows


def rows_match(a: list[tuple], b: list[tuple]) -> bool:
    # order-independent comparison: two queries that return the same rows
    # in a different order both count as correct
    return sorted(map(str, a)) == sorted(map(str, b))


def run(rows: list[dict], use_full_schema: bool, agent: Agent) -> dict:
    correct = 0
    failed_to_run = 0
    details = []

    for row in rows:
        gold = execute(row["gold_sql"])
        result = agent.ask(row["question"], use_full_schema=use_full_schema)

        if not result.ok:
            failed_to_run += 1
            details.append({"question": row["question"], "outcome": "did_not_run",
                             "error": result.error})
            continue

        is_correct = gold.ok and rows_match(gold.rows, result.rows)
        correct += int(is_correct)
        details.append({
            "question": row["question"],
            "outcome": "correct" if is_correct else "wrong_result",
            "sql": result.sql,
            "tables_used": result.tables_used,
        })

    n = len(rows)
    return {
        "schema_mode": "full" if use_full_schema else "retrieved",
        "n_questions": n,
        "execution_accuracy_pct": round(correct / n * 100, 1),
        "failed_to_run_pct": round(failed_to_run / n * 100, 1),
        "details": details,
    }


def main() -> None:
    rows = load_questions()
    agent = Agent()

    retrieved = run(rows, use_full_schema=False, agent=agent)
    full = run(rows, use_full_schema=True, agent=agent)

    print(json.dumps({"retrieved_schema": {k: v for k, v in retrieved.items() if k != "details"},
                       "full_schema": {k: v for k, v in full.items() if k != "details"}},
                      indent=2))
    print(
        "\nResume line:\n"
        f"  {retrieved['execution_accuracy_pct']}% execution accuracy with retrieved "
        f"schema vs {full['execution_accuracy_pct']}% with full schema, on "
        f"{retrieved['n_questions']} hand-written questions"
    )


if __name__ == "__main__":
    main()
