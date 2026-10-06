"""
The evaluation behind SchemaMind's README numbers.

Every question in eval/questions.jsonl is asked twice: with only the retrieved
tables in the prompt (how SchemaMind normally runs) and with the full schema,
to see whether retrieval helps. An answerable question carries gold SQL, the
query you'd consider correct; an answer counts when its rows match the gold
rows ("execution accuracy": the SQL text itself may differ). An unanswerable
question asks for something the database doesn't hold, and the right answer
is to refuse.

It needs the LLM, so MISTRAL_API_KEY must be in .env. Template mode only knows
fixed question shapes, but it makes a free dry run of the whole script:

    python -m eval.run_eval                  # Mistral
    python -m eval.run_eval --mode template  # dry run, no key needed
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
import time
from pathlib import Path

import sqlglot
from sqlglot import exp

from app.agent import Agent
from app.config import DB_PATH, MISTRAL_API_KEY, MISTRAL_MODEL
from app.executor import execute
from app.sql_generate import LLMAuthError, LLMError
from app.validate import validate

QUESTIONS = Path(__file__).parent / "questions.jsonl"
# When Mistral gives no answer to this many questions in a row, something is
# wrong for every question (a used-up limit, a full model): stop and say why.
STOP_AFTER_NO_REPLY = 3


def load_questions() -> list[dict]:
    rows = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        r.setdefault("answerable", "gold_sql" in r)
        assert "question" in r and (not r["answerable"] or "gold_sql" in r), f"bad row: {r}"
    return rows


def gold_problems(rows: list[dict]) -> list[str]:
    """Gold SQL that wouldn't make a fair reference: unsafe, broken or empty."""
    problems = []
    for r in rows:
        if not r["answerable"]:
            continue
        v = validate(r["gold_sql"])
        result = execute(r["gold_sql"]) if v.ok else None
        if not v.ok:
            problems.append(f"{r['question']}: the validator refuses the gold SQL ({v.reason})")
        elif not result.ok:
            problems.append(f"{r['question']}: the gold SQL fails ({result.error})")
        elif not result.rows:
            problems.append(f"{r['question']}: the gold SQL returns no rows")
    return problems


def gold_tables(sql: str) -> set[str]:
    """The tables a query reads, to check whether retrieval offered all of them."""
    return {t.name for t in sqlglot.parse_one(sql, read="sqlite").find_all(exp.Table)}


def _norm(value):
    # 2705800 and 2705800.0 are the same answer; averages are compared to 2 decimals
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    return value


def rows_match(gold: list[tuple], got: list[tuple]) -> bool:
    """Same rows in any order. Extra columns are allowed, in any position: an
    answer that shows a customer's id next to the name the question asked for
    still answers it."""
    gold = [tuple(_norm(v) for v in r) for r in gold]
    got = [tuple(_norm(v) for v in r) for r in got]
    if len(gold) != len(got):
        return False
    if not gold:
        return True
    width, have = len(gold[0]), len(got[0])
    want = sorted(gold, key=repr)
    for cols in itertools.permutations(range(have), width):
        if sorted((tuple(r[c] for c in cols) for r in got), key=repr) == want:
            return True
    return False


def evaluate(rows: list[dict], agent: Agent, use_full_schema: bool, mode: str,
             progress: bool = False) -> dict:
    """Ask every question once; return the counts and what happened to each."""
    records = []
    no_reply_in_a_row = 0
    for r in rows:
        start = time.perf_counter()
        try:
            res = agent.ask(r["question"], mode=mode, use_full_schema=use_full_schema)
        except LLMAuthError:
            raise  # a missing or rejected key fails every question: stop now
        except LLMError as e:
            res, error = None, str(e)
        seconds = time.perf_counter() - start

        rec = {"question": r["question"], "answerable": r["answerable"], "seconds": seconds}
        if res is None:
            rec.update(outcome="error", error=error)
        elif res.sql is None:  # the model replied CANNOT_ANSWER
            rec.update(outcome="refused")
        elif not r["answerable"]:
            rec.update(outcome="answered", sql=res.sql)
        elif not res.ok:
            rec.update(outcome="failed", sql=res.sql, error=res.error)
        else:
            gold = execute(r["gold_sql"])
            rec.update(outcome="correct" if rows_match(gold.rows, res.rows) else "wrong_rows",
                       sql=res.sql)
        if res is not None:
            rec["attempts"] = res.attempts
            if r["answerable"]:
                rec["has_gold_tables"] = gold_tables(r["gold_sql"]) <= set(res.tables_used)
        records.append(rec)
        if progress:
            print({"correct": ".", "refused": "r", "answered": "a"}.get(rec["outcome"], "x"),
                  end="", flush=True)
        no_reply_in_a_row = no_reply_in_a_row + 1 if res is None else 0
        if no_reply_in_a_row == STOP_AFTER_NO_REPLY:
            raise LLMError(f"Mistral gave no answer to {STOP_AFTER_NO_REPLY} questions in a row, "
                           f"so the results would mean nothing. The last error: {error}")

    ans = [x for x in records if x["answerable"]]
    unans = [x for x in records if not x["answerable"]]
    times = sorted(x["seconds"] for x in records if x["outcome"] != "error")

    def count(group, outcome):
        return sum(x["outcome"] == outcome for x in group)

    return {
        "schema": "full" if use_full_schema else "retrieved",
        "n_answerable": len(ans),
        "n_unanswerable": len(unans),
        "correct": count(ans, "correct"),
        "execution_accuracy_pct": round(count(ans, "correct") / max(len(ans), 1) * 100, 1),
        "wrong_rows": count(ans, "wrong_rows"),
        "failed_to_run": count(ans, "failed"),
        "no_reply": count(records, "error"),
        "refused_answerable": count(ans, "refused"),
        "correct_after_repair": sum(x["outcome"] == "correct" and x.get("attempts", 1) > 1 for x in ans),
        "unanswerable_refused": count(unans, "refused"),
        # did the prompt contain every table the gold SQL reads?
        "gold_tables_in_prompt": sum(bool(x.get("has_gold_tables")) for x in ans),
        "median_seconds": round(statistics.median(times), 2) if times else None,
        "p95_seconds": round(times[min(len(times) - 1, int(0.95 * len(times)))], 2) if times else None,
        "records": records,
    }


def print_report(results: list[dict]) -> None:
    n, u = results[0]["n_answerable"], results[0]["n_unanswerable"]
    lines = [
        ("Correct answers (execution accuracy)", lambda m: f"{m['correct']} of {n} ({m['execution_accuracy_pct']}%)"),
        ("Ran, but returned the wrong rows", lambda m: str(m["wrong_rows"])),
        ("Failed to run after all repairs", lambda m: str(m["failed_to_run"])),
        ("No answer from Mistral", lambda m: str(m["no_reply"])),
        ("Answerable, but refused", lambda m: str(m["refused_answerable"])),
        ("Correct only after a repair", lambda m: str(m["correct_after_repair"])),
        ("Unanswerable questions refused", lambda m: f"{m['unanswerable_refused']} of {u}"),
        ("Every needed table in the prompt", lambda m: f"{m['gold_tables_in_prompt']} of {n}"),
        ("Seconds per question (median / p95)", lambda m: f"{m['median_seconds']} / {m['p95_seconds']}"),
    ]
    print(f"\n{'':38}" + "".join(f"{m['schema'] + ' schema':>22}" for m in results))
    for label, fmt in lines:
        print(f"{label:38}" + "".join(f"{fmt(m):>22}" for m in results))

    for m in results:
        misses = [x for x in m["records"]
                  if x["outcome"] not in ("correct", "refused") or (x["outcome"] == "refused" and x["answerable"])]
        print(f"\nWhat went wrong with the {m['schema']} schema ({len(misses)}):")
        for x in misses:
            print(f"  [{x['outcome']}] {x['question']}")
            if x.get("sql"):
                print(f"      SQL: {' '.join(x['sql'].split())}")
            if x.get("error"):
                print(f"      error: {x['error'][:200]}")


def resume_line(results: list[dict]) -> str:
    """The line for your resume, unless Mistral left questions unanswered."""
    r, f = results
    no_reply = r["no_reply"] + f["no_reply"]
    if no_reply:
        return (f"{no_reply} questions got no answer from Mistral (see above), so these numbers "
                "are incomplete. Run the evaluation again before using them.")
    return (
        "Resume line:\n"
        f"  on a hand-written set of {r['n_answerable'] + r['n_unanswerable']} questions, "
        f"SchemaMind answered {r['correct']} of {r['n_answerable']} correctly with retrieved "
        f"tables ({f['correct']} with the full schema) and refused {r['unanswerable_refused']} "
        f"of {r['n_unanswerable']} questions the database can't answer"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Execution accuracy, retrieved vs full schema.")
    ap.add_argument("--mode", choices=["mistral", "template"], default="mistral")
    args = ap.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"No database at {DB_PATH}. Run: python -m app.seed_db")
    rows = load_questions()
    problems = gold_problems(rows)
    if problems:
        raise SystemExit("Fix the gold SQL first:\n  " + "\n  ".join(problems))
    if args.mode == "mistral" and not MISTRAL_API_KEY:
        raise SystemExit("MISTRAL_API_KEY is not set. Put it in .env (see README) and run again.")

    agent = Agent()
    label = f"mistral ({MISTRAL_MODEL})" if args.mode == "mistral" else "template"
    print(f"Asking {len(rows)} questions twice with {label}.\n"
          "  . correct   r refused   a answered (should have refused)   x wrong or failed")
    results = []
    try:
        for full in (False, True):
            print(f"  {'full' if full else 'retrieved':>9} schema: ", end="", flush=True)
            results.append(evaluate(rows, agent, use_full_schema=full, mode=args.mode, progress=True))
            print()
    except LLMError as e:  # a rejected key, or Mistral failing every question
        raise SystemExit(f"\n{e}")

    print_report(results)
    print("\n" + resume_line(results))


if __name__ == "__main__":
    main()
