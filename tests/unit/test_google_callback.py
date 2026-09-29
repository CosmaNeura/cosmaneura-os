import asyncio
from urllib.parse import urlencode

import httpx
import pytest

from cosmas_os.api.app import app


class GoogleService:
    return_origin = "https://os.example.invalid"

    def __init__(self):
        self.calls = []

    def callback(self, state, code, denied):
        self.calls.append((state, code, denied))
        return not denied


def get(monkeypatch, query):
    service = GoogleService()
    monkeypatch.setattr(app.state, "google_connection", service, raising=False)

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://owned"
        ) as client:
            return await client.get("/connections/google/callback?" + query)

    return asyncio.run(request()), service


@pytest.mark.parametrize("issuer", [None, "https://accounts.google.com"])
def test_google_callback_accepts_the_published_issuer(monkeypatch, issuer):
    fields = {
        "state": "s" * 43,
        "code": "synthetic_PRIVATE_code",
        "scope": "openid email https://www.googleapis.com/auth/gmail.metadata",
        "authuser": "0",
        "hd": "example.invalid",
        "prompt": "consent",
    }
    if issuer is not None:
        fields["iss"] = issuer
    response, service = get(monkeypatch, urlencode(fields))
    assert response.status_code == 303
    assert response.headers["location"] == service.return_origin + "/#google-connected"
    assert service.calls == [("s" * 43, "synthetic_PRIVATE_code", False)]
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize(
    "extra",
    [
        "&iss=https%3A%2Fother.example.invalid",
        "&iss=",
        "&iss=https%3A%2Faccounts.google.com%2Fevil",
        "&iss=https%3A%2Faccounts.google.com&iss=https%3A%2Faccounts.google.com",
        "&unknown=synthetic_PRIVATE_sentinel",
        "&error=access_denied",
    ],
)
def test_google_callback_rejects_ambiguous_or_foreign_responses(monkeypatch, caplog, extra):
    response, service = get(monkeypatch, "state=" + "s" * 43 + "&code=synthetic_PRIVATE_code" + extra)
    assert response.status_code == 303
    assert response.headers["location"] == service.return_origin + "/#google-sign-in"
    assert service.calls == []
    assert "PRIVATE" not in caplog.text and "s" * 43 not in caplog.text


def test_google_denial_with_valid_issuer_still_reaches_single_use_attempt(monkeypatch):
    response, service = get(monkeypatch, urlencode({
        "state": "s" * 43, "error": "access_denied", "iss": "https://accounts.google.com",
    }))
    assert response.status_code == 303
    assert response.headers["location"].endswith("/#google-sign-in")
    assert service.calls == [("s" * 43, None, True)]
