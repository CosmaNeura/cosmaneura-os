"""C2 SMART backend-services JWT auth against a mock token server.

Synthetic only. Local signing keys and canary tokens exist in memory for the
duration of each test and are never written to the repository.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from pydantic import SecretStr

from cosmas_os.adapters.ehr_auth import (
    AUTH_KIND_BACKEND_JWT,
    BackendJwtAuthError,
    BackendJwtConfig,
    BackendJwtTokenClient,
    KeyVaultRemoteKeySigner,
    LocalTestKeySigner,
    ManagedSecretKeyReference,
    SmartBackendJwtAuthProvider,
    normalize_system_read_scopes,
    validate_managed_secret_reference_name,
)
from cosmas_os.plugins.athena import EHR_CAPABILITY as ATHENA
from cosmas_os.plugins.ehr import DeclaredEhrConnector

TOKEN_URL = "http://127.0.0.1:9/oauth2/v1/token"
CLIENT_ID = "synth-athena-preview-client"
CANARY_TOKEN = "CANARY_EHR_BACKEND_JWT_TOKEN_7f3a9c2e1b88_NEVER_LOG"
REQUESTED_SCOPES = frozenset({
    "system/Patient.read",
    "system/Encounter.read",
    "system/AllergyIntolerance.read",
})


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class _MockTokenServer:
    """In-process OAuth token endpoint for synthetic assertion exchange."""

    def __init__(
        self,
        *,
        signer: LocalTestKeySigner,
        mode: str = "success",
        granted_scopes: frozenset[str] | None = None,
        expires_in: int = 3600,
        access_token: str = CANARY_TOKEN,
        max_clock_skew: int = 60,
        wall_time: Any = None,
    ) -> None:
        self.signer = signer
        self.mode = mode
        self.granted_scopes = granted_scopes
        self.expires_in = expires_in
        self.access_token = access_token
        self.max_clock_skew = max_clock_skew
        self.wall_time = wall_time or time.time
        self.calls = 0
        self.last_assertion: str | None = None
        self.last_form: dict[str, str] | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if request.method != "POST" or str(request.url) != TOKEN_URL:
            return httpx.Response(404, json={"error": "not_found"})
        from urllib.parse import parse_qs

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
        if form.get("client_assertion_type") != (
            "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
        ):
            return httpx.Response(400, json={"error": "invalid_request"})
        assertion = form.get("client_assertion", "")
        self.last_assertion = assertion
        if self.mode == "invalid_client":
            return httpx.Response(401, json={"error": "invalid_client"})
        try:
            header, payload = self._verify_assertion(assertion)
        except BackendJwtAuthError as exc:
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": exc.code},
            )
        if self.mode == "expired_assertion":
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "client assertion expired"},
            )
        if self.mode == "clock_skew":
            return httpx.Response(
                400,
                json={"error": "invalid_grant", "error_description": "clock skew too large"},
            )
        if self.mode == "unauthorized":
            return httpx.Response(401, json={"error": "invalid_client"})
        scopes = self.granted_scopes if self.granted_scopes is not None else REQUESTED_SCOPES
        body = {
            "access_token": self.access_token,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
            "scope": " ".join(sorted(scopes)),
        }
        # Keep header/payload referenced so verification side effects stay obvious in tests.
        assert header["kid"] == self.signer.kid
        assert payload["iss"] == CLIENT_ID
        return httpx.Response(200, json=body)

    def _verify_assertion(self, assertion: str) -> tuple[dict, dict]:
        parts = assertion.split(".")
        if len(parts) != 3:
            raise BackendJwtAuthError("invalid_request")
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
        if header.get("alg") not in {"RS384", "RS256"}:
            raise BackendJwtAuthError("invalid_request")
        if header.get("kid") != self.signer.kid:
            raise BackendJwtAuthError("invalid_client")
        if payload.get("iss") != CLIENT_ID or payload.get("sub") != CLIENT_ID:
            raise BackendJwtAuthError("invalid_client")
        if payload.get("aud") != TOKEN_URL:
            raise BackendJwtAuthError("invalid_request")
        now = int(self.wall_time())
        exp = payload.get("exp")
        iat = payload.get("iat")
        if type(exp) is not int or type(iat) is not int:
            raise BackendJwtAuthError("invalid_request")
        if exp - iat > 300:
            raise BackendJwtAuthError("invalid_request")
        if exp < now:
            raise BackendJwtAuthError("expired_assertion")
        if abs(iat - now) > self.max_clock_skew + 120:
            # Outside any reasonable skew window the client might apply.
            raise BackendJwtAuthError("clock_skew")
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        signature = _b64url_decode(parts[2])
        algorithm = header["alg"]
        hash_alg = hashes.SHA384() if algorithm == "RS384" else hashes.SHA256()
        digest = hashes.Hash(hash_alg)
        digest.update(signing_input)
        public = self._public_key()
        try:
            public.verify(signature, digest.finalize(), padding.PKCS1v15(), Prehashed(hash_alg))
        except Exception as exc:
            raise BackendJwtAuthError("invalid_client") from exc
        return header, payload

    def _public_key(self):
        # LocalTestKeySigner keeps the private key; export public for verify.
        private = self.signer._private
        return private.public_key()


def _config(**overrides) -> BackendJwtConfig:
    values = dict(
        client_id=CLIENT_ID,
        token_url=TOKEN_URL,
        scopes=REQUESTED_SCOPES,
        algorithm="RS384",
        assertion_lifetime_seconds=300,
        clock_skew_seconds=30,
    )
    values.update(overrides)
    return BackendJwtConfig(**values)


def _client(
    mock: _MockTokenServer,
    *,
    signer: LocalTestKeySigner | None = None,
    config: BackendJwtConfig | None = None,
    monotonic=None,
    wall_time=None,
) -> BackendJwtTokenClient:
    signer = signer or mock.signer
    return BackendJwtTokenClient(
        config=config or _config(),
        signer=signer,
        transport=httpx.MockTransport(mock.handler),
        monotonic=monotonic,
        wall_time=wall_time,
    )


def test_managed_secret_reference_names_follow_codex_scheme():
    assert (
        validate_managed_secret_reference_name("COSMAS_MANAGED_SECRET_EHR_ATHENA_JWT_KEY")
        == "COSMAS_MANAGED_SECRET_EHR_ATHENA_JWT_KEY"
    )
    with pytest.raises(ValueError, match="managed_secret_reference_invalid"):
        validate_managed_secret_reference_name("ATHENA_JWT_KEY")
    with pytest.raises(ValueError, match="managed_secret_reference_invalid"):
        validate_managed_secret_reference_name("COSMAS_MANAGED_SECRET_")


def test_normalize_scopes_refuse_wildcards_and_writes():
    assert normalize_system_read_scopes(["system/Patient.read"]) == frozenset(
        {"system/Patient.read"}
    )
    with pytest.raises(BackendJwtAuthError) as raised:
        normalize_system_read_scopes(["system/*.read"])
    assert raised.value.code == "scope_wildcard_refused"
    with pytest.raises(BackendJwtAuthError) as raised:
        normalize_system_read_scopes(["system/Patient.write"])
    assert raised.value.code == "invalid_request"


def test_success_token_exchange_and_memory_cache():
    signer = LocalTestKeySigner(kid="synth-kid-1")
    clock = {"mono": 1_000.0, "wall": 1_700_000_000.0}
    mock = _MockTokenServer(signer=signer, wall_time=lambda: clock["wall"])

    client = _client(
        mock,
        signer=signer,
        monotonic=lambda: clock["mono"],
        wall_time=lambda: clock["wall"],
    )
    token = client.get_access_token()
    assert token.get_secret_value() == CANARY_TOKEN
    assert mock.calls == 1
    assert mock.last_form is not None
    assert mock.last_form["grant_type"] == "client_credentials"
    assert "system/Patient.read" in mock.last_form["scope"]
    header = json.loads(_b64url_decode(mock.last_assertion.split(".")[0]))
    payload = json.loads(_b64url_decode(mock.last_assertion.split(".")[1]))
    assert header["kid"] == "synth-kid-1"
    assert header["alg"] == "RS384"
    assert payload["iss"] == payload["sub"] == CLIENT_ID
    assert payload["aud"] == TOKEN_URL
    assert payload["exp"] - payload["iat"] <= 300

    # Cached until 60s before expiry (expires_in=3600 → skew 60).
    clock["mono"] = 1_000.0 + 3_500.0
    assert client.get_access_token().get_secret_value() == CANARY_TOKEN
    assert mock.calls == 1

    clock["mono"] = 1_000.0 + 3_540.0
    assert client.get_access_token().get_secret_value() == CANARY_TOKEN
    assert mock.calls == 2


def test_invalid_client_from_mock_token_server():
    signer = LocalTestKeySigner(kid="synth-kid-2")
    mock = _MockTokenServer(signer=signer, mode="invalid_client")
    client = _client(mock, signer=signer)
    with pytest.raises(BackendJwtAuthError) as raised:
        client.get_access_token()
    assert raised.value.code == "invalid_client"


def test_expired_assertion_mapped_from_token_server():
    signer = LocalTestKeySigner(kid="synth-kid-3")
    mock = _MockTokenServer(signer=signer, mode="expired_assertion")
    client = _client(mock, signer=signer)
    with pytest.raises(BackendJwtAuthError) as raised:
        client.get_access_token()
    assert raised.value.code == "expired_assertion"


def test_clock_skew_mapped_from_token_server():
    signer = LocalTestKeySigner(kid="synth-kid-4")
    mock = _MockTokenServer(signer=signer, mode="clock_skew")
    client = _client(mock, signer=signer)
    with pytest.raises(BackendJwtAuthError) as raised:
        client.get_access_token()
    assert raised.value.code == "clock_skew"


def test_scope_narrower_than_requested_is_unsupported_for_missing_resources():
    signer = LocalTestKeySigner(kid="synth-kid-5")
    mock = _MockTokenServer(
        signer=signer,
        granted_scopes=frozenset({"system/Patient.read"}),
    )
    client = _client(mock, signer=signer)
    token = client.get_access_token()
    assert token.get_secret_value() == CANARY_TOKEN
    assert client.unsupported_resources_for_grant() == frozenset(
        {"Encounter", "AllergyIntolerance"}
    )
    with pytest.raises(BackendJwtAuthError) as raised:
        client.access_token_for_resource()
    assert raised.value.code == "unsupported_scope"


def test_401_refresh_clears_cache_and_fetches_new_token():
    signer = LocalTestKeySigner(kid="synth-kid-6")
    clock = {"mono": 100.0, "wall": 1_700_000_100.0}
    mock = _MockTokenServer(
        signer=signer,
        access_token=CANARY_TOKEN,
        wall_time=lambda: clock["wall"],
    )
    client = _client(
        mock,
        signer=signer,
        monotonic=lambda: clock["mono"],
        wall_time=lambda: clock["wall"],
    )
    first = client.get_access_token()
    assert first.get_secret_value() == CANARY_TOKEN
    assert mock.calls == 1

    mock.access_token = "CANARY_EHR_BACKEND_JWT_TOKEN_REFRESHED_ONLY_IN_MEMORY"
    refreshed = client.refresh_after_unauthorized()
    assert refreshed.get_secret_value() == "CANARY_EHR_BACKEND_JWT_TOKEN_REFRESHED_ONLY_IN_MEMORY"
    assert mock.calls == 2


def test_canary_token_absent_from_captured_logs(caplog):
    signer = LocalTestKeySigner(kid="synth-kid-7")
    mock = _MockTokenServer(signer=signer, access_token=CANARY_TOKEN)
    client = _client(mock, signer=signer)
    with caplog.at_level(logging.DEBUG):
        token = client.get_access_token()
        # Force logging of repr surfaces that must stay free of the canary.
        logging.getLogger("cosmas_os.adapters.ehr_auth.backend_jwt").debug(
            "client=%r token_type=%s", client, type(token).__name__
        )
    assert token.get_secret_value() == CANARY_TOKEN
    assert CANARY_TOKEN not in caplog.text
    assert "CANARY_EHR_BACKEND_JWT_TOKEN" not in caplog.text
    assert isinstance(token, SecretStr)


def test_key_vault_remote_signer_never_holds_private_key():
    local = LocalTestKeySigner(kid="vault-mirrored-kid")

    class _VaultDouble:
        def sign_digest(self, *, algorithm: str, digest: bytes) -> bytes:
            assert algorithm == "RS384"
            return local._private.sign(digest, padding.PKCS1v15(), Prehashed(hashes.SHA384()))

    reference = ManagedSecretKeyReference(
        reference_name="COSMAS_MANAGED_SECRET_EHR_ATHENA_JWT_KEY",
        kid="vault-mirrored-kid",
    )
    vault_signer = KeyVaultRemoteKeySigner(reference=reference, remote=_VaultDouble())
    assert vault_signer.reference_name == "COSMAS_MANAGED_SECRET_EHR_ATHENA_JWT_KEY"
    assert "private" not in repr(vault_signer).lower()
    assert not hasattr(vault_signer, "_private")

    mock = _MockTokenServer(signer=local)
    # Verify path uses local's public key; vault_signer produces matching signatures.
    client = BackendJwtTokenClient(
        config=_config(),
        signer=vault_signer,
        transport=httpx.MockTransport(mock.handler),
    )
    token = client.get_access_token()
    assert token.get_secret_value() == CANARY_TOKEN
    assert mock.calls == 1


def test_auth_provider_attaches_to_c1_connector_for_backend_jwt_kind():
    assert AUTH_KIND_BACKEND_JWT == "smart_backend_services"
    assert "smart_backend_services" in ATHENA.auth_styles

    signer = LocalTestKeySigner(kid="synth-kid-attach")
    mock = _MockTokenServer(signer=signer)
    token_client = _client(mock, signer=signer)
    provider = SmartBackendJwtAuthProvider({"athena": token_client})
    connector = DeclaredEhrConnector(ATHENA)
    provider.attach_to(connector)
    assert connector.auth_provider is provider

    value = provider.access_token(vendor_id="athena", audience=TOKEN_URL)
    assert value == CANARY_TOKEN
    with pytest.raises(BackendJwtAuthError) as raised:
        provider.access_token(vendor_id="athena", audience="https://example.invalid/token")
    assert raised.value.code == "invalid_request"


def test_local_test_signer_key_not_serializable_to_pem_in_repr_or_exports():
    signer = LocalTestKeySigner(kid="ephemeral-only")
    text = repr(signer)
    assert "BEGIN" not in text
    assert "PRIVATE" not in text
    # Ensure the in-memory key object is not accidentally a PEM string attribute.
    pem = signer._private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    assert b"BEGIN PRIVATE KEY" in pem
    # The PEM exists only in this test's memory for the assertion above; it is
    # not written to disk and is discarded when the test ends.
