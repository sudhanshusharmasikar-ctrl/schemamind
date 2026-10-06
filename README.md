# SchemaMind

[![tests](https://github.com/sudhanshusharmasikar-ctrl/schemamind/actions/workflows/tests.yml/badge.svg)](https://github.com/sudhanshusharmasikar-ctrl/schemamind/actions/workflows/tests.yml)

A text-to-SQL agent that answers plain-English questions against a database, retrieves only the tables relevant to the question instead of dumping the whole schema into the prompt, and refuses to run anything that isn't a read.

> **Status: built, tested and evaluated.** Schema introspection, retrieval, validation and execution all run correctly against the included sample database (verified below). On 24 hand-written questions, Mistral's Codestral answers 19 of 20 correctly with retrieved tables, up from 14 before two fixes the evaluation pointed to, and 18 of 20 with the full schema. Evaluation explains every miss.

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

### Safety layers, tested

**1. The validator** (`app/validate.py`) parses the SQL with sqlglot and allows exactly one read query: a `SELECT`, or `SELECT`s combined with `UNION`, `INTERSECT` or `EXCEPT`. Everything else is refused, including a write hidden behind a read or inside a CTE:

```
SELECT * FROM customers; DROP TABLE customers;  -> Exactly one statement is allowed, got 2.
DELETE FROM orders                              -> Query type Delete is not allowed. Read-only access only.
PRAGMA writable_schema = 1                      -> Only SELECT queries are allowed, got Pragma.
```

It counts the statements itself (`sqlglot.parse`), so it doesn't depend on how a particular sqlglot version treats a second statement; its tests pass on sqlglot 26 through 30.

**2. The connection** is opened with `mode=ro`. If a write ever got past the validator, SQLite refuses it at the file level:

```
DELETE FROM orders  -> attempt to write a readonly database
```

**3. Limits.** A read can still hurt: a recursive query that never ends, or a cross join with hundreds of millions of rows, would tie up the server. The executor stops any query after 5 seconds (`SCHEMAMIND_QUERY_TIMEOUT`) using SQLite's progress handler, because `connect(timeout=...)` only limits waiting for a locked file. It also returns at most 200 rows.

```
WITH RECURSIVE n(x) AS (...) SELECT COUNT(*) FROM n  -> Query stopped: it ran longer than the 5-second limit.
```

Several layers, because a prompt instruction is not a security control, and neither is a single point of enforcement.

### Schema retrieval instead of schema dumping

Table descriptions (columns, types, foreign keys, two sample rows) are embedded once with MiniLM. At query time the top-k most relevant tables go into the prompt, together with the tables needed to read and join them:

- every table a retrieved table's foreign keys point to, because an `order_items` row names its product only by id;
- a table that links two retrieved ones, as `order_items` links `orders` to `products`.

A short text column also lists every value it holds, for example `method (TEXT, one of: 'card', 'cod', 'upi')`. Two sample rows show what a row looks like, but the model takes them as the complete list of values, and a listed value also helps retrieval match a question that names it. Both changes came out of the evaluation below; `SCHEMAMIND_JOIN_TABLES=0` and `SCHEMAMIND_VALUE_LIST_MAX=0` turn them off.

### Why template mode exists

`SCHEMAMIND_GEN_MODE=template` matches a question against a fixed list of shapes (counts, overall or by city or status; top-N customers by spend or by number of orders; orders from a city; revenue by category or city; orders with a given status) and fills in SQL. It needs no API key and always runs, which is what let every claim in this README be tested without a paid key. **It is not text-to-SQL** — it only knows the shapes it's given. `SCHEMAMIND_GEN_MODE=mistral` is the real thing: an LLM writes novel SQL from the retrieved schema. Say this distinction out loud if asked; it's the honest answer.

The whole question has to match a shape. A question with words left over, like *orders in the last month*, is refused rather than half-answered: half-matching is how this mode used to give valid but wrong answers, such as 150 for *how many orders from Pune?* (all orders) when the answer is 22. Both revenue questions use one definition of revenue, the value of items in orders that weren't cancelled, so they agree with each other and with total payments.

---

## What's tested vs what needs your own run

| Claim | Status |
|---|---|
| Database seeds correctly (150 orders, 40 customers, 5 tables) | Tested, works |
| Schema introspection reads columns, types, foreign keys correctly | Tested, works |
| Validator allows one read query and blocks writes, hidden second statements, PRAGMA, ATTACH, VACUUM | Tested (`tests/test_validate.py`) |
| Read-only DB connection blocks writes independently | Tested (`tests/test_executor.py`) |
| Runaway queries stop at the time limit; results are capped at 200 rows | Tested (`tests/test_executor.py`) |
| An unsafe query from the generator never reaches the data, end to end | Tested (`tests/test_agent_safety.py`) |
| Short text columns list their values; long lists, free text, numbers, dates and ids don't | Tested (`tests/test_schema.py`) |
| Retrieval adds the tables needed to read and join the retrieved ones | Tested (`tests/test_schema.py`) |
| Template mode answers its question shapes correctly and refuses partial matches | Tested (`tests/test_templates.py`) |
| Full pipeline: question → SQL → validated → executed → correct rows | Tested, works |
| The Mistral client spaces its requests, retries rate limits and server errors, and stops at once on a missing or rejected key | Tested with a fake server (`tests/test_mistral_client.py`) |
| The evaluation scores answers correctly, and every gold query is safe, runs and returns rows | Tested (`tests/test_eval.py`) |
| Settings load from `.env`; a variable set in the shell wins | Tested (`tests/test_config.py`) |
| The web page starts in the server's generation mode and shows why a request failed | Tested (`tests/test_ui.py`) |
| Real LLM (mistral mode) text-to-SQL accuracy | Measured: 19 of 20 with retrieval, 18 of 20 with the full schema (see Evaluation) |
| Retrieved-schema vs full-schema accuracy comparison | Measured before and after two fixes, with every miss explained (see Evaluation) |

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
- [x] Hand-written eval set with gold SQL
- [x] Retrieved-vs-full-schema accuracy benchmark
- [x] Value lists for short text columns, and join tables for retrieval (fixes for the two causes the benchmark found)
- [x] Re-run the benchmark with those fixes: 14 to 19 of 20 correct with retrieval
- [ ] Tell the model what `quantity` means and that the shop records no costs (the remaining misses)
- [ ] Support for a second SQL dialect

## Stack

Python · FastAPI · SQLite · sqlglot (AST parsing) · sentence-transformers · Streamlit

## Evaluation

`eval/questions.jsonl` holds 24 hand-written questions about the sample shop database:

- **20 answerable**, each with gold SQL, the query you'd accept as correct. They range from one table (*How many customers are there?*) to four joined tables with two filters (*How many Laptops were bought by customers in Indore, in orders that were not cancelled?*). Some check classic mistakes, such as counting order lines when the question asks for orders: 18 lines, but 17 orders, contain a delivered Monitor.
- **4 unanswerable**: they ask for data the database doesn't hold (a customer's email, employees, profit, stock). The right answer is to refuse; the prompt tells the model to reply `CANNOT_ANSWER`.

`python -m eval.run_eval` asks every question twice with Mistral: once with only the retrieved tables in the prompt (how SchemaMind normally runs) and once with the full schema.

**How an answer is scored.** An answer is correct when its rows match the gold query's rows ("execution accuracy"); the SQL text may differ, since the same question can be answered by many queries. Rows can come in any order, numbers are compared to 2 decimal places (2705800 and 2705800.0 are the same answer, and an average shouldn't fail on rounding), and extra columns are allowed: an answer that shows a customer's id next to the name the question asked for still answers it. A missing column, a missing or extra row, or a different value is wrong. Before asking anything, the script checks the gold SQL itself: each query must pass the validator, run, and return rows. `tests/test_eval.py` repeats that check on every push.

The report has one column per schema:

| Row | What it counts |
|---|---|
| Correct answers | execution accuracy over the 20 answerable questions |
| Ran, but returned the wrong rows | the dangerous kind: a valid query that answers a different question |
| Failed to run after all repairs | SQL that still failed after the repair loop |
| No answer from Mistral | Mistral still refused after every retry; the error gives Mistral's own reason |
| Answerable, but refused | the model replied `CANNOT_ANSWER` to a question it could answer |
| Correct only after a repair | the repair loop turned a failing query into a right one |
| Unanswerable questions refused | out of the 4 |
| Every needed table in the prompt | retrieval recall: whether the retrieved tables included every table the gold SQL reads (always 20 of 20 with the full schema) |
| Tables in the prompt (average) | what that recall costs: the prompt grows with every table added (always 5 with the full schema) |
| Seconds per question | median and 95th percentile, including any wait for Mistral's rate limit |

After the table it lists every miss with the SQL the model wrote, then prints a resume line built from the counts.

### Running it

Put your Mistral key in `.env` (see Setup), then:

```bash
python -m eval.run_eval --mode template   # free dry run of the whole script, no key needed
python -m eval.run_eval                   # the evaluation, with Mistral
```

The dry run only shows that everything works end to end: template mode knows a few fixed question shapes, so it answers 1 of the 20 and refuses the rest. The real run sends about 50 requests and takes a couple of minutes.

Mistral's free plan limits how many requests you can send per second. The client sends at most one request every 1.1 seconds (`SCHEMAMIND_LLM_MIN_INTERVAL`) and retries a rate-limit reply (429), a server error or a dropped connection up to 4 times (`SCHEMAMIND_LLM_RETRIES`), waiting 1, 2, 4 and 8 seconds, or as long as the server's `Retry-After` header asks. A missing or rejected key stops the run at once with a message saying so, instead of failing all 48 requests one by one. So does Mistral giving no answer to 3 questions in a row: a 429 that outlasts every retry isn't the per-second limit but something that fails every question, such as a used-up limit or a model with no free capacity left, and the message quotes Mistral's reason. The Limits page of Mistral's admin console shows your plan's limits. A run in which any question got no answer prints no resume line. `tests/test_mistral_client.py` checks the client with a fake server and a fake clock, so the tests send nothing and never wait, and `tests/test_eval.py` checks the early stop.

### Results

Measured on 6 October 2026 with `codestral-2508`, Mistral's model for code, on the free plan (on that plan every request to `mistral-small-latest` was refused as over the rate limit): temperature 0, the 3 most relevant tables retrieved, at most 2 repairs. *Before* is the first run; *after* adds the two fixes that run pointed to, the value lists and join tables described under Schema retrieval.

| Metric | Retrieved, before | Retrieved, after | Full schema, before | Full schema, after |
|---|---|---|---|---|
| Correct answers (of 20) | 14 (70%) | **19 (95%)** | 17 (85%) | 18 (90%) |
| Ran, but returned the wrong rows | 3 | 1 | 0 | 2 |
| Failed to run | 0 | 0 | 0 | 0 |
| Answerable, but refused | 3 | 0 | 3 | 0 |
| Unanswerable questions refused (of 4) | 4 | 3 | 3 | 3 |
| Every needed table in the prompt (of 20) | 15 | 20 | 20 | 20 |
| Tables in the prompt (average) | 3 | 4.2 | 5 | 5 |
| Seconds per question (median / p95) | 1.11 / 1.54 | 1.13 / 1.74 | 1.13 / 1.64 | 1.19 / 1.96 |

The seconds are mostly the 1.1-second spacing between requests (`SCHEMAMIND_LLM_MIN_INTERVAL`); Codestral itself usually answered sooner. Every miss in both runs was checked against the database.

**Before: two causes behind most misses.**

- *When retrieval left out a table, the model guessed instead of refusing.* For *How many delivered orders included a Monitor?* the query never touched `products`, the table that maps names to ids, and filtered on `product_id = 5`, an id from the sample rows of `order_items`. Product 5 is the Mouse: 14 instead of 17. *How many Laptops were bought by customers in Indore, in orders that were not cancelled?* needs 4 tables, one more than the 3 retrieved, and its query lost the Laptop condition: 23 instead of 14.
- *The model read the two sample rows as the full list of a column's values.* They show payment methods `card` and `cod`, so it refused to total the UPI payments, though UPI is the most common method (69 of 126 payments). Questions about the Monitor and the Backpack, which aren't in the products' sample rows, were refused the same way.

The other misses: retrieval refused the Electronics question, most likely for lack of a table; it named the top 3 customers by id instead of name (the right customers, but the scoring rule counts it as wrong); and with the full schema the model invented a profit (below).

**After: what the two fixes changed.**

- Listing the values of short text columns removed every refusal of an answerable question: 3 to 0 with both schemas.
- Join tables gave retrieval every table it needed for all 20 questions, up from 15, with 4.2 tables in an average prompt instead of all 5. Retrieval went from 14 to 19 correct and now matches the full schema: 19 against 18 is a difference of one question, too small to call a win on 20 questions.

**After: what still goes wrong.**

- *Counting order lines instead of items*, behind all three wrong answers. For *Counting only orders that were not cancelled, which city's customers bought the most Backpacks?* both schemas counted order lines: Indore has the most lines (8), but Pune bought the most Backpacks (14 against Indore's 13). With the full schema, the Indore Laptop question counted 6 lines instead of 14 Laptops.
- *Inventing a profit.* The database records no costs, yet with both schemas the model computed a profit as the selling price minus the list price, which are equal everywhere in this data, and reported 0. With retrieval it refused this question before the fixes; now its prompt holds `order_items` and `products`, and it doesn't.

Next: tell the model what `quantity` means (the number of items in an order line) and that the shop records no costs, then measure again.

## Known limitations

- SQLite only.
- Template mode covers a fixed list of question shapes; anything else returns "could not generate a query" in that mode.
- No handling of multi-turn follow-up questions.
- The evaluation set is small (24 questions) and was written by hand for the sample database, so it measures this setup, not text-to-SQL in general.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.11 or newer
pip install -r requirements.txt   # pinned, tested versions
python -m app.seed_db          # creates the sample database
cp .env.example .env           # settings; the Mistral key goes here
uvicorn app.api:app --reload   # terminal 1
streamlit run ui/streamlit_app.py   # terminal 2
```

Tested on macOS (Apple Silicon) with Python 3.14.

Try: *how many orders*, *how many orders from Pune*, *top 5 customers by spend*, *orders from Indore*, *revenue by category*, *cancelled orders*.

For mistral mode, create a free API key at [console.mistral.ai](https://console.mistral.ai), uncomment `MISTRAL_API_KEY=` in `.env` and paste the key after the `=`. Set `SCHEMAMIND_GEN_MODE=mistral` as well if you want the app to start in that mode; you can also switch in the sidebar. `.env` is in `.gitignore`, so the key is never committed, and a variable set in your shell wins over the file.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests build their own copy of the sample database in a temporary folder, never load the embedding model and never call Mistral, so they run offline in seconds. They cover the validator (one read query only), the executor (read-only connection, time limit, row limit), template mode (each question shape gives the right answer; questions it only partly understands are refused), an end-to-end check that an injected `DROP TABLE` is refused while the data stays intact, the value lists and join tables, the Mistral client (pacing, retries, key errors) against a fake server, the evaluation's scoring and gold SQL, settings from `.env`, and the web page.

GitHub Actions runs the same tests after every push, on Python 3.11 and 3.14 (see `.github/workflows/tests.yml`). The badge at the top shows the result for `main`.

## License

MIT
