# SchemaMind

A text-to-SQL agent that answers plain-English questions against a database, retrieves only the tables relevant to the question instead of dumping the whole schema into the prompt, and refuses to run anything that isn't a read.

> **Status: core pipeline built and tested.** Schema introspection, retrieval, validation and execution all run correctly against the included sample database (verified below). Real LLM-based generation and the full-vs-retrieved-schema benchmark need your own API key and your own question set — see Evaluation.

---

## The problem

Three specific failure modes in naive text-to-SQL:

**Schema overflow.** A real warehouse has hundreds of tables. Pasting the whole schema into every prompt doesn't scale, and you can't just pick a random subset — picking the *right* subset is itself a retrieval problem.

**Silent wrongness.** A model can return SQL that's syntactically valid, runs without error, and answers the wrong question — a bad join produces a number, not a crash.

**Destructive output.** Nothing stops a language model from generating a `DROP TABLE` if a question is phrased ambiguously.

SchemaMind has a specific mechanism for each of these, not a longer prompt.

## How it works

```
question
   │
   ▼
Schema Retriever ──► embeds table descriptions (with sample rows),
   │                  returns only the top-k relevant tables
   ▼
SQL Generator ────► template mode (pattern match, no key) or
   │                  mistral mode (real LLM text-to-SQL)
   ▼
Validator ────────► parses the SQL into an AST, rejects anything
   │                  that isn't a SELECT, even nested in a subquery
   ▼
Executor ─────────► runs against a connection opened read-only at
   │                  the OS level — a second, independent safety net
   ▼
error? ──yes──► Repair loop: real DB error goes back to the model,
   │              bounded retries, then gives up cleanly
   no
   ▼
result + the SQL that produced it, always shown together
```

### Two independent safety layers, tested

The AST validator (`app/validate.py`) rejects `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, and multi-statement injection attempts (`SELECT ...; DROP TABLE ...`), including when a write is nested inside a subquery. Verified:

```
'DROP TABLE customers;'                              -> blocked
'DELETE FROM orders;'                                -> blocked
'SELECT * FROM customers; DROP TABLE customers;'     -> blocked
```

Independently, the database connection itself is opened with `mode=ro`. If a write ever got past the validator, SQLite refuses it at the file level:

```
DELETE FROM orders;  -> attempt to write a readonly database
```

Two layers because a prompt instruction is not a security control, and neither is a single point of enforcement.

### Schema retrieval instead of schema dumping

Table descriptions (columns, types, foreign keys, two sample rows) are embedded once with MiniLM. At query time the top-k most relevant tables go into the prompt. Sample rows matter here — they tell the model a `status` column contains the string `'shipped'`, not an integer code, which a bare column list can't.

### Why template mode exists

`SCHEMAMIND_GEN_MODE=template` pattern-matches a question against five known shapes (count, top-N by spend, filter by city, group-by revenue, filter by status) and fills in SQL. It needs no API key and always runs, which is what let every claim in this README be tested without a paid key. **It is not text-to-SQL** — it only knows the shapes it's given. `SCHEMAMIND_GEN_MODE=mistral` is the real thing: an LLM writes novel SQL from the retrieved schema. Say this distinction out loud if asked; it's the honest answer.

---

## What's tested vs what needs your own run

| Claim | Status |
|---|---|
| Database seeds correctly (150 orders, 40 customers, 5 tables) | Tested, works |
| Schema introspection reads columns, types, foreign keys correctly | Tested, works |
| Validator blocks DROP / DELETE / UPDATE / INSERT / injection | Tested, works |
| Read-only DB connection blocks writes independently | Tested, works |
| Template mode generates correct SQL for 5 question shapes | Tested, works |
| Full pipeline: question → SQL → validated → executed → correct rows | Tested, works |
| Real LLM (mistral mode) text-to-SQL accuracy | Needs your API key |
| Retrieved-schema vs full-schema accuracy comparison | Needs your API key + your question set |

## Planned features

- [x] Schema introspection for any SQLite database
- [x] Embedding-based schema retrieval
- [x] Template generation mode (no API key)
- [x] LLM generation mode (Mistral)
- [x] AST-level SQL validation
- [x] Read-only execution with row limits
- [x] Bounded repair loop on execution/validation failure
- [x] FastAPI backend
- [x] Streamlit UI
- [ ] Hand-written eval set with gold SQL
- [ ] Retrieved-vs-full-schema accuracy benchmark (needs the above)
- [ ] Support for a second SQL dialect

## Stack

Python · FastAPI · SQLite · sqlglot (AST parsing) · sentence-transformers · Streamlit

## Evaluation

The benchmark that matters — retrieved schema vs full schema — needs `SCHEMAMIND_GEN_MODE=mistral` and a written question set with gold SQL, because template mode is deterministic pattern matching and would score identically either way.

```bash
cp eval/questions.example.jsonl eval/questions.jsonl   # then write your own, 15-20 questions
export SCHEMAMIND_GEN_MODE=mistral
export MISTRAL_API_KEY=your_key
python -m eval.run_eval
```

Results table, to be filled from that run:

| Metric | Retrieved schema | Full schema |
|---|---|---|
| Execution accuracy | — | — |
| Failed to run | — | — |

On a 5-table database, expect these to be close, possibly with full schema slightly ahead — that would be the honest finding. The technique is what's being demonstrated; it's built for warehouses with hundreds of tables, where dumping the full schema stops being possible at all.

## Known limitations

- SQLite only.
- Template mode covers 5 fixed question shapes; anything else returns "could not generate a query" in that mode.
- No handling of multi-turn follow-up questions.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.seed_db          # creates the sample database
uvicorn app.api:app --reload   # terminal 1
streamlit run ui/streamlit_app.py   # terminal 2
```

Try: *how many orders*, *top 5 customers by spend*, *orders from Indore*, *revenue by category*, *cancelled orders*.

## License

MIT
