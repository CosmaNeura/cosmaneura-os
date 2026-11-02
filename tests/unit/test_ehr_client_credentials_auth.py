"""C2 2-legged OAuth client-credentials auth against a mock token server.

Synthetic only. Obvious fake placeholders for client id/secret and canary
tokens exist only in the test process via env monkeypatch — never as real
Key Vault values and never committed as production credentials.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from cosmas_os.adapters.ehr_auth import (
    ATHENA_FHIR_CLIENT_ID_REF,
    ATHENA_FHIR_CLIENT_SECRET_REF,
    AUTH_KIND_CLIENT_CREDENTIALS,
    ClientCredentialsAuthError,
    ClientCredentialsAuthProvider,
    ClientCredentialsConfig,
    ClientCredentialsTokenClient,
    ManagedSecretEnvResolver,
    normalize_system_read_scopes,
    validate_managed_secret_reference_name,
)
from cosmas_os.plugins.athena import EHR_CAPABILITY as ATHENA
from cosmas_os.plugins.ehr import DeclaredEhrConnector

TOKEN_URL = "http://127.0.0.1:9/oauth2/v1/token"
FAKE_CLIENT_ID = "fake-athena-fhir-client-id-PLACEHOLDER"
FAKE_CLIENT_SECRET = "fake-athena-fhir-client-secret-PLACEHOLDER"
CANARY_TOKEN = "CANARY_EHR_CC_ACCESS_TOKEN_9a1b2c3d_NEVER_LOG"
CANARY_SECRET = "CANARY_EHR_CC_CLIENT_SECRET_4e5f6a7b_NEVER_LOG"
REQUESTED_SCOPES = frozenset({
    "system/Patient.read",
    "system/Encounter.read",
    "system/AllergyIntolerance.read",
})


class _MockTokenServer:
    def __init__(
        self,
        *,
        mode: str = "success",
        expires_in: int = 3600,
        access_token: str = CANARY_TOKEN,
        expected_id: str = FAKE_CLIENT_ID,
        expected_secret: str = FAKE_CLIENT_SECRET,
    ) -> None:
        self.mode = mode
        self.expires_in = expires_in
        self.access_token = access_token
        self.expected_id = expected_id
        self.expected_secret = expected_secret
        self.calls = 0
        self.last_form: dict[str, str] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if request.method != "POST" or str(request.url) != TOKEN_URL:
            return httpx.Response(404, json={"error": "not_found"})
        form = {
            key: values[0]
            for key, values in parse_qs(
                request.content.decode(),
                keep_blank_values=True,
            ).items()
        }
        self.last_form = form
        if form.get("grant_type") != "client_credentials":
            return httpx.Response(400, json={"error": "invalid_request"})
        if self.mode == "invalid_client":
            return httpx.Response(401, json={"error": "invalid_client"})
        if (
            form.get("client_id") != self.expected_id
            or form.get("client_secret") != self.expected_secret
        ):
            return httpx.Response(401, json={"error": "invalid_client"})
        if self.mode == "unauthorized":
            return httpx.Response(401, json={"error": "invalid_client"})
        return httpx.Response(
            200,
            json={
                "access_token": self.access_token,
                "token_type": "Bearer",
                "expires_in": self.expires_in,
                "scope": " ".join(sorted(REQUESTED_SCOPES)),
            },
        )


def _bind_fakes(monkeypatch: pytest.MonkeyPatch, *, secret: str = FAKE_CLIENT_SECRET) -> None:
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_ID_REF, FAKE_CLIENT_ID)
    monkeypatch.setenv(ATHENA_FHIR_CLIENT_SECRET_REF, secret)


def _config() -> ClientCredentialsConfig:
    return ClientCredentialsConfig(
        client_id_ref=ATHENA_FHIR_CLIENT_ID_REF,
        client_secret_ref=ATHENA_FHIR_CLIENT_SECRET_REF,
        token_url=TOKEN_URL,
        scopes=REQUESTED_SCOPES,
    )


def _client(
    mock: _MockTokenServer,
    monkeypatch: pytest.MonkeyPatch,
    *,
    secret: str = FAKE_CLIENT_SECRET,
    monotonic=None,
) -> ClientCredentialsTokenClient:
    _bind_fakes(monkeypatch, secret=secret)
    mock.expected_secret = secret
    return ClientCredentialsTokenClient(
        config=_config(),
        secrets=ManagedSecretEnvResolver(),
        transport=httpx.MockTransport(mock.handler),
        monotonic=monotonic,
    )


def test_managed_secret_reference_names_follow_codex_scheme():
    assert validate_managed_secret_reference_name(ATHENA_FHIR_CLIENT_ID_REF) == (
        ATHENA_FHIR_CLIENT_ID_REF
    )
    assert ATHENA_FHIR_CLIENT_ID_REF.startswith("COSMAS_MANAGED_SECRET_")
    assert ATHENA_FHIR_CLIENT_SECRET_REF.startswith("COSMAS_MANAGED_SECRET_")
    with pytest.raises(ValueError, match="managed_secret_reference_invalid"):
        validate_managed_secret_reference_name("ATHENA_CLIENT_SECRET")


def test_normalize_scopes_refuse_wildcards():
    assert normalize_system_read_scopes(["system/Patient.read"]) == frozenset(
        {"system/Patient.read"}
    )
    with pytest.raises(ClientCredentialsAuthError) as raised:
        normalize_system_read_scopes(["system/*.read"])
    assert raised.value.code == "scope_wildcard_refused"


def test_success_token_exchange_and_memory_cache(monkeypatch):
    mock = _MockTokenServer()
    clock = {"mono": 1_000.0}
    client = _client(mock, monkeypatch, monotonic=lambda: clock["mono"])
    token = client.get_access_token()
    assert token.get_secret_value() == CANARY_TOKEN
    assert isinstance(token, SecretStr)
    assert mock.calls == 1
    assert mock.last_form is not None
    assert mock.last_form["client_id"] == FAKE_CLIENT_ID
    assert mock.last_form["grant_type"] == "client_credentials"
    assert "system/Patient.read" in mock.last_form["scope"]

    clock["mono"] = 1_000.0 + 3_500.0
    assert client.get_access_token().get_secret_value() == CANARY_TOKEN
    assert mock.calls == 1

    clock["mono"] = 1_000.0 + 3_540.0
    assert client.get_access_token().get_secret_value() == CANARY_TOKEN
    assert mock.calls == 2


def test_invalid_client_from_mock_token_server(monkeypatch):
    mock = _MockTokenServer(mode="invalid_client")
    client = _client(mock, monkeypatch)
    with pytest.raises(ClientCredentialsAuthError) as raised:
        client.get_access_token()
    assert raised.value.code == "invalid_client"


def test_401_refresh_clears_cache_and_fetches_new_token(monkeypatch):
    mock = _MockTokenServer(access_token=CANARY_TOKEN)
    clock = {"mono": 100.0}
    client = _client(mock, monkeypatch, monotonic=lambda: clock["mono"])
    first = client.get_access_token()
    assert first.get_secret_value() == CANARY_TOKEN
    assert mock.calls == 1

    mock.access_token = "CANARY_EHR_CC_ACCESS_TOKEN_REFRESHED_ONLY_IN_MEMORY"
    refreshed = client.refresh_after_unauthorized()
    assert refreshed.get_secret_value() == "CANARY_EHR_CC_ACCESS_TOKEN_REFRESHED_ONLY_IN_MEMORY"
    assert mock.calls == 2


def test_canary_token_and_secret_absent_from_captured_logs(monkeypatch, caplog):
    mock = _MockTokenServer(access_token=CANARY_TOKEN)
    client = _client(mock, monkeypatch, secret=CANARY_SECRET)
    with caplog.at_level(logging.DEBUG):
        token = client.get_access_token()
        logging.getLogger("cosmas_os.adapters.ehr_auth.client_credentials").debug(
            "client=%r resolver=%r token_type=%s",
            client,
            ManagedSecretEnvResolver(),
            type(token).__name__,
        )
    assert token.get_secret_value() == CANARY_TOKEN
    assert CANARY_TOKEN not in caplog.text
    assert CANARY_SECRET not in caplog.text
    assert FAKE_CLIENT_ID not in caplog.text
    assert "CANARY_EHR_CC_" not in caplog.text


def test_missing_vault_binding_is_not_configured(monkeypatch):
    monkeypatch.delenv(ATHENA_FHIR_CLIENT_ID_REF, raising=False)
    monkeypatch.delenv(ATHENA_FHIR_CLIENT_SECRET_REF, raising=False)
    mock = _MockTokenServer()
    client = ClientCredentialsTokenClient(
        config=_config(),
        secrets=ManagedSecretEnvResolver(),
        transport=httpx.MockTransport(mock.handler),
    )
    with pytest.raises(ClientCredentialsAuthError) as raised:
        client.get_access_token()
    assert raised.value.code == "not_configured"
    assert mock.calls == 0


def test_auth_provider_attaches_to_c1_connector_for_client_credentials(monkeypatch):
    assert AUTH_KIND_CLIENT_CREDENTIALS == "oauth2_client_credentials"
    assert "oauth2_client_credentials" in ATHENA.auth_styles
    assert "smart_backend_services" not in ATHENA.auth_styles

    mock = _MockTokenServer()
    token_client = _client(mock, monkeypatch)
    provider = ClientCredentialsAuthProvider({"athena": token_client})
    connector = DeclaredEhrConnector(ATHENA)
    provider.attach_to(connector)
    assert connector.auth_provider is provider
    value = provider.access_token(vendor_id="athena", audience=TOKEN_URL)
    assert value == CANARY_TOKEN
    with pytest.raises(ClientCredentialsAuthError) as raised:
        provider.access_token(vendor_id="athena", audience="https://example.invalid/token")
    assert raised.value.code == "invalid_request"


def test_repr_surfaces_never_include_secret_or_token_values(monkeypatch):
    mock = _MockTokenServer()
    client = _client(mock, monkeypatch, secret=CANARY_SECRET)
    token = client.get_access_token()
    text = " ".join([repr(client), repr(token), repr(ManagedSecretEnvResolver()), repr(_config())])
    assert CANARY_SECRET not in text
    assert CANARY_TOKEN not in text
    assert FAKE_CLIENT_SECRET not in text
    assert ATHENA_FHIR_CLIENT_ID_REF in repr(client)
