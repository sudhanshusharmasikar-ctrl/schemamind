"""The web page starts at the server's generation mode, since it sends the
chosen mode with every question, and shows why a request failed."""
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

UI = str(Path(__file__).resolve().parent.parent / "ui" / "streamlit_app.py")


def health(gen_mode):
    reply = mock.Mock(json=lambda: {"status": "ok", "gen_mode": gen_mode, "tables": ["customers", "orders"]})
    return mock.Mock(return_value=reply)


def start(health_check):
    with mock.patch("requests.get", health_check):
        at = AppTest.from_file(UI, default_timeout=30).run()
    assert not at.exception
    return at


def test_the_mode_starts_at_the_servers_setting():
    at = start(health("mistral"))
    assert at.sidebar.radio[0].value == "mistral"
    assert at.sidebar.success[0].value == "API up"


def test_the_mode_falls_back_to_template_when_the_api_is_down():
    at = start(mock.Mock(side_effect=ConnectionError("no server")))
    assert at.sidebar.radio[0].value == "template"
    assert "unreachable" in at.sidebar.error[0].value


def test_a_failed_request_shows_the_reason():
    refused = mock.Mock(ok=False, status_code=502,
                        json=lambda: {"detail": "MISTRAL_API_KEY is not set. Put it in .env (see README)."})
    with mock.patch("requests.get", health("mistral")), mock.patch("requests.post", return_value=refused):
        at = AppTest.from_file(UI, default_timeout=30).run()
        at.text_input[0].input("How many customers are there?")
        at.button[0].click().run()
    assert not at.exception
    assert at.error[0].value == "Request failed (502): MISTRAL_API_KEY is not set. Put it in .env (see README)."
