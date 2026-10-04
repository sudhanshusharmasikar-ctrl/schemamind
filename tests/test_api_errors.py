"""When the LLM fails, /ask says why instead of answering "500 Internal Server Error"."""
import pytest
from fastapi import HTTPException

from app import api
from app.sql_generate import LLMError


class BrokenAgent:
    def ask(self, *args, **kwargs):
        raise LLMError("Mistral answered 503, still failing after 5 tries")


def test_an_llm_failure_becomes_a_502_with_the_reason(monkeypatch):
    monkeypatch.setitem(api._state, "agent", BrokenAgent())
    with pytest.raises(HTTPException) as caught:
        api.ask(api.AskRequest(question="How many orders are there?", mode="mistral"))
    assert caught.value.status_code == 502
    assert "503" in caught.value.detail
