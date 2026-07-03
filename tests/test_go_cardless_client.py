import logging

import pytest

import go_cardless_client
from go_cardless_client import Client


class FakeResponse:
    """Mimics a requests.Response for an error page that isn't JSON (e.g. HTML 502)."""

    def __init__(self, status_code=502, text="<html>Bad Gateway</html>"):
        self.status_code = status_code
        self.text = text

    def json(self):
        raise ValueError("No JSON object could be decoded")


@pytest.fixture
def client():
    """A Client with a token, bypassing __init__ (no network, no .env)."""
    c = Client.__new__(Client)
    c.token = {"access": "fake-access", "refresh": "fake-refresh"}
    return c


def test_get_returns_none_on_non_json_error_body(client, monkeypatch):
    monkeypatch.setattr(
        go_cardless_client.requests, "get", lambda *a, **kw: FakeResponse()
    )
    assert client.get("accounts/x/transactions/") is None


def test_get_logs_failure_at_error_level(client, monkeypatch, caplog):
    monkeypatch.setattr(
        go_cardless_client.requests, "get", lambda *a, **kw: FakeResponse()
    )
    with caplog.at_level(logging.ERROR):
        client.get("accounts/x/transactions/")
    assert any(
        r.levelno == logging.ERROR and "502" in r.message for r in caplog.records
    )


def test_post_returns_none_and_logs_error_on_non_json_body(client, monkeypatch, caplog):
    monkeypatch.setattr(
        go_cardless_client.requests, "post", lambda *a, **kw: FakeResponse()
    )
    with caplog.at_level(logging.ERROR):
        assert client.post("token/refresh/", {"refresh": "x"}) is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_delete_returns_none_and_logs_error_on_non_json_body(
    client, monkeypatch, caplog
):
    monkeypatch.setattr(
        go_cardless_client.requests, "delete", lambda *a, **kw: FakeResponse()
    )
    with caplog.at_level(logging.ERROR):
        assert client.delete("requisitions/x/") is None
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_get_new_token_failure_logs_error_without_crashing(client, monkeypatch, caplog):
    client._secret_id = "id"
    client._secret_key = "key"
    monkeypatch.setattr(
        go_cardless_client.requests, "post", lambda *a, **kw: FakeResponse(401, "nope")
    )
    with caplog.at_level(logging.ERROR):
        assert client.try_get_new_token() is False
    assert any(
        r.levelno == logging.ERROR and "401" in r.message for r in caplog.records
    )
