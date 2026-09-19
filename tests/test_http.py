"""A kulcsot nem szivárogtató HTTP-burkoló (a publikus Actions-napló miatt)."""

import pytest
import requests

from pipeline.http import RequestFailed, get_json


def test_network_error_message_contains_neither_url_nor_key(monkeypatch):
    def boom(*_args, **_kwargs):
        raise requests.ConnectionError("failed to connect to https://api.example.com/x?api_key=SECRET123")

    monkeypatch.setattr(requests, "get", boom)
    with pytest.raises(RequestFailed) as err:
        get_json("https://api.example.com/x", {"api_key": "SECRET123"})
    assert "SECRET123" not in str(err.value)
    assert "api.example.com" not in str(err.value)
    assert "ConnectionError" in str(err.value)


def test_non_json_response_does_not_raise(monkeypatch):
    class Response:
        status_code = 500

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(requests, "get", lambda *a, **k: Response())
    status, body = get_json("https://x", {})
    assert status == 500
    assert body is None
