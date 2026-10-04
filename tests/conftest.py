"""
Shared fixtures. The tests build the sample database in a throwaway folder,
so they never touch data/shop.db, and they never load the embedding model.
"""
from __future__ import annotations

import os
import tempfile

# app.config reads these when it is first imported, so set them before any
# app import.
_TMP = tempfile.mkdtemp(prefix="schemamind-tests-")
os.environ.update(
    {
        "SCHEMAMIND_DB": os.path.join(_TMP, "shop.db"),
        "SCHEMAMIND_STORAGE": os.path.join(_TMP, "storage"),
        "SCHEMAMIND_GEN_MODE": "template",
    }
)

import pytest

from app import seed_db
from app.config import DB_PATH


@pytest.fixture(scope="session")
def db():
    """The sample shop database (40 customers, 150 orders), built once per run."""
    seed_db.build()
    return DB_PATH
