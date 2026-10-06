"""
Central configuration. Same philosophy as PaperRAG's config.py: every tunable
value lives here with a comment on why, so you can defend each choice.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# Read settings from a .env file in the project folder, if there is one
# (cp .env.example .env). A variable already set in your shell wins over the
# file, so you can still change a setting for a single command.
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("SCHEMAMIND_DB", ROOT / "data" / "shop.db"))
STORAGE_DIR = Path(os.getenv("SCHEMAMIND_STORAGE", ROOT / "storage"))
SCHEMA_INDEX_PATH = STORAGE_DIR / "schema_index.json"

# ---------- schema retrieval ----------
EMBED_MODEL = os.getenv("SCHEMAMIND_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
TOP_K_TABLES = int(os.getenv("SCHEMAMIND_TOP_K_TABLES", 3))
# Also give the model the tables needed to read and join the retrieved ones:
# the tables their foreign keys point to (an order_items row names its
# product only by id), and a table that links two retrieved ones. Without
# them the evaluation's model guessed ids and dropped conditions. 0 = off.
JOIN_TABLES = os.getenv("SCHEMAMIND_JOIN_TABLES", "1") != "0"
# A text column with at most this many distinct (short) values lists them
# all in the schema the model sees. Two sample rows aren't enough: the model
# read them as the complete list and refused questions about UPI payments
# when the samples showed only card and cod. 0 = off.
VALUE_LIST_MAX = int(os.getenv("SCHEMAMIND_VALUE_LIST_MAX", 10))

# ---------- generation ----------
# "template" -> pattern-matches the question against a small set of known
#               question shapes and fills in a SQL template. No API key,
#               always works, but only covers the shapes it knows about.
#               This exists so the pipeline (retrieval, validation, execution)
#               is demonstrable without needing a paid key.
# "mistral"  -> calls an LLM to actually write novel SQL from the retrieved
#               schema. This is the real text-to-SQL mode.
GEN_MODE = os.getenv("SCHEMAMIND_GEN_MODE", "template")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
# Codestral, Mistral's model for code, and SQL is code. It is also what the
# README's numbers were measured with, on a free plan that refused every
# request to mistral-small-latest as over the rate limit. The Limits page of
# Mistral's admin console lists the models your plan allows.
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "codestral-2508")
# Mistral's free plan limits how many requests you may send per second, so
# calls are spaced at least this far apart. A "too many requests" reply (429)
# or a temporary server error is retried, waiting longer each time.
LLM_MIN_INTERVAL = float(os.getenv("SCHEMAMIND_LLM_MIN_INTERVAL", 1.1))
LLM_RETRIES = int(os.getenv("SCHEMAMIND_LLM_RETRIES", 4))

MAX_REPAIR_ATTEMPTS = int(os.getenv("SCHEMAMIND_MAX_REPAIR", 2))
# A query on this database takes milliseconds; one still running after this
# many seconds is a runaway (a never-ending recursive CTE, a huge cross join)
# and executor.py stops it.
QUERY_TIMEOUT_SECONDS = float(os.getenv("SCHEMAMIND_QUERY_TIMEOUT", 5))
MAX_RESULT_ROWS = 200  # a runaway SELECT should not flood the response

STORAGE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
