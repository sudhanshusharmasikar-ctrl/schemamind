"""
The Mistral client spaces its requests out and retries failures that pass on
their own (a rate limit, a server error, a dropped connection), but stops at
once on a missing or rejected key. Time and the server are fakes here: no
request leaves the machine and no test waits.
"""
import types

import pytest
import requests

from app import sql_generate as gen
from app.config import LLM_MIN_INTERVAL, LLM_RETRIES


class Reply:
    def __init__(self, status=200, content="SELECT 1", headers=None):
        self.status_code, self.text, self.headers = status, content, headers or {}

    def json(self):
        return {"choices": [{"message": {"content": self.text}}]}


@pytest.fixture
def server(monkeypatch):
    """Scripted replies, fake time; records every request and every sleep."""
    state = types.SimpleNamespace(replies=[], calls=[], sleeps=[], now=1000.0)

    def post(url, headers, json, timeout):
        state.calls.append(json)
        reply = state.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds

    monkeypatch.setattr(gen, "requests", types.SimpleNamespace(
        post=post, RequestException=requests.RequestException))
    monkeypatch.setattr(gen, "time", types.SimpleNamespace(sleep=sleep, monotonic=lambda: state.now))
    monkeypatch.setattr(gen, "MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr(gen, "_last_call", 0.0)
    return state


def test_the_sql_comes_back_without_markdown_fences(server):
    server.replies = [Reply(content="```sql\nSELECT COUNT(*) FROM customers\n```")]
    assert gen._mistral_generate("How many customers?", "schema") == "SELECT COUNT(*) FROM customers"
    assert server.calls[0]["temperature"] == 0.0


def test_cannot_answer_means_no_query(server):
    server.replies = [Reply(content="CANNOT_ANSWER")]
    assert gen.generate_sql("What is Customer 12's email?", [], mode="mistral") is None


def test_rate_limits_and_server_errors_are_retried_with_growing_waits(server):
    server.replies = [Reply(429), Reply(503), Reply(content="SELECT 2")]
    assert gen._mistral_generate("q", "schema") == "SELECT 2"
    assert len(server.calls) == 3
    assert 1 in server.sleeps and 2 in server.sleeps  # 2**0, then 2**1 seconds


def test_the_retry_after_header_is_respected(server):
    server.replies = [Reply(429, headers={"Retry-After": "7"}), Reply()]
    gen._mistral_generate("q", "schema")
    assert 7 in server.sleeps


def test_a_dropped_connection_is_retried(server):
    server.replies = [requests.ConnectionError("reset"), Reply()]
    assert gen._mistral_generate("q", "schema") == "SELECT 1"


def test_it_gives_up_after_the_last_try(server):
    server.replies = [Reply(503)] * (LLM_RETRIES + 1)
    with pytest.raises(gen.LLMError, match=f"still failing after {LLM_RETRIES + 1} tries"):
        gen._mistral_generate("q", "schema")
    assert len(server.calls) == LLM_RETRIES + 1


def test_a_rejected_key_stops_at_once(server):
    server.replies = [Reply(401)]
    with pytest.raises(gen.LLMAuthError, match="rejected the API key"):
        gen._mistral_generate("q", "schema")
    assert len(server.calls) == 1 and server.sleeps == []


def test_a_missing_key_stops_before_any_request(server, monkeypatch):
    monkeypatch.setattr(gen, "MISTRAL_API_KEY", "")
    with pytest.raises(gen.LLMAuthError, match="not set"):
        gen._mistral_generate("q", "schema")
    assert server.calls == []


def test_another_client_error_is_reported_not_retried(server):
    server.replies = [Reply(400, content="Invalid model: mistral-tiny-9000")]
    with pytest.raises(gen.LLMError, match="Invalid model"):
        gen._mistral_generate("q", "schema")
    assert len(server.calls) == 1


def test_back_to_back_requests_are_spaced_out(server):
    server.replies = [Reply(), Reply()]
    gen._mistral_generate("q1", "schema")
    gen._mistral_generate("q2", "schema")
    assert server.sleeps == [pytest.approx(LLM_MIN_INTERVAL)]
