"""Additive standalone Clerk preparation; all keys/accounts are invented and offline."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from tests.unit import test_standalone_runtime as offline_tests

from cosmas_os.api.auth import (
    AccessDenied,
    AuthenticationFailed,
    ClerkTokenVerifier,
    native_clerk_origin,
)
from cosmas_os.api.practice_access_routes import PATHS
from cosmas_os.config import Settings
from cosmas_os.standalone_runtime import LocalPublicKeys, StandaloneTokenVerifier

standalone = offline_tests.standalone


@pytest.fixture(params=["audience", "shared_staging"])
def clerk_standalone(standalone, request):
    offline, private, _ = standalone
    policy = request.param
    issuer = ("https://identity.invented-cosmabot.test" if policy == "audience"
              else "https://invented-cosmabot.clerk.accounts.dev")
    runtime = offline.model_copy(update={
        "cosmas_env": "standalone_clerk_synthetic", "standalone_jwks_path": "",
        "standalone_clerk_issuer_allowlist": issuer, "workspace_hosted_enabled": True,
        "clerk_issuer": issuer, "clerk_jwks_url": issuer + "/.well-known/jwks.json",
        "clerk_session_policy": policy,
        "clerk_audience": "invented-practice-app-api" if policy == "audience" else "",
        "clerk_organization_id": "org_invented_separate_practice",
        "clerk_authorized_parties": "https://workspace.invented-cosmabot.test",
        "cors_allowed_origins": "https://workspace.invented-cosmabot.test",
        "human_deploy_evidence_ref": "invented:reviewed-clerk-preparation",
    })
    runtime.validate_runtime_configuration()
    calls = []

    class Keys:
        def get_signing_keys(self, **_):
            calls.append("selected-issuer-fixture")
            return [SimpleNamespace(key_id="clerk-invented-fixture", key=private.public_key())]

    def token(updates=None, *, omit=(), kid="clerk-invented-fixture"):
        now = datetime.now(UTC)
        claims = {"iss": runtime.clerk_issuer, "sub": "user_invented_clerk_owner",
            "org_id": runtime.clerk_organization_id, "sid": "sess_invented_clerk",
            "azp": runtime.authorized_parties[0], "iat": now, "nbf": now,
            "exp": now + timedelta(minutes=5)}
        if policy == "audience":
            claims["aud"] = runtime.clerk_audience
        claims.update(updates or {})
        for key in omit:
            claims.pop(key, None)
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": kid})

    return SimpleNamespace(runtime=runtime, offline=offline, private=private,
                           keys=Keys, token=token, calls=calls, policy=policy)


def test_explicit_clerk_profile_keeps_owned_resources_and_external_work_disabled(clerk_standalone):
    c = clerk_standalone
    assert c.runtime.workspace_available
    assert not c.runtime.workspace_core_connection_available
    assert not c.runtime.workspace_capture_available
    assert not c.runtime.workspace_llm_available
    assert c.runtime.database_url == c.offline.database_url
    assert c.runtime.blob_root == c.offline.blob_root
    assert c.runtime.standalone_jwks_path == ""
    # Even if an old offline key file exists, it cannot supply real Clerk keys.
    with pytest.raises(RuntimeError, match="offline standalone"):
        LocalPublicKeys(c.runtime)
    with pytest.raises(RuntimeError, match="offline standalone"):
        StandaloneTokenVerifier(c.runtime)
    assert c.offline.workspace_available


@pytest.mark.parametrize("change", [
    {"standalone_clerk_issuer_allowlist": ""},
    {"standalone_clerk_issuer_allowlist": "https://other.clerk.accounts.dev"},
    {"clerk_organization_id": ""}, {"clerk_organization_id": "org_"},
    {"human_deploy_evidence_ref": ""}, {"clerk_session_policy": "missing"},
    {"clerk_jwks_url": "https://other.clerk.accounts.dev/.well-known/jwks.json"},
    {"standalone_jwks_path": "/private/tmp/forbidden-local-keys.json"},
    {"workspace_hosted_enabled": False}, {"workspace_apple_local_transport_enabled": True},
    {"data_mode": "authorized_beta"}, {"core_capture_origin": "https://core.example.invalid"},
    {"workspace_google_connection_enabled": True}, {"workspace_llm_backend": "azure_gpt41"},
    {"cors_allowed_origins": "http://127.0.0.1:5173"},
    {"clerk_authorized_parties": "https://another.invented-cosmabot.test"},
])
def test_real_clerk_profile_refuses_unreviewed_or_mixed_configuration(clerk_standalone, change):
    assert clerk_standalone.runtime.model_copy(update=change).runtime_configuration_errors()


def test_policy_is_explicit_and_never_falls_back(clerk_standalone):
    c = clerk_standalone
    values = c.runtime.model_dump()
    values.pop("clerk_session_policy")
    assert Settings(**{"_env_file": None, **values}).runtime_configuration_errors()
    assert c.runtime.model_copy(update={"clerk_session_policy": "shared_staging" if c.policy == "audience" else "audience"}).runtime_configuration_errors()
    assert c.runtime.model_copy(update={"clerk_audience": None}).runtime_configuration_errors()
    doubled = c.runtime.clerk_issuer + "," + c.runtime.clerk_issuer
    assert c.runtime.model_copy(update={"standalone_clerk_issuer_allowlist": doubled}).runtime_configuration_errors()


def test_application_audience_requires_exact_explicit_session_contract(clerk_standalone):
    c = clerk_standalone
    # This is the existing application's signed session audience, independent
    # of the dedicated storage UUID. Offline fixtures keep their UUID audience.
    assert c.offline.model_copy(update={"clerk_audience": "invented-practice-app-api"}).runtime_configuration_errors()
    if c.policy == "shared_staging":
        assert c.runtime.model_copy(update={"clerk_audience": "invented-practice-app-api"}).runtime_configuration_errors()
        return
    assert c.runtime.clerk_audience == "invented-practice-app-api"
    values = c.runtime.model_dump()
    values.pop("clerk_audience")
    assert Settings(**{"_env_file": None, **values}).runtime_configuration_errors()
    for audience in (None, "", " app", "app ", "two audiences", "app\n", "é", "a" * 256):
        assert c.runtime.model_copy(update={"clerk_audience": audience}).runtime_configuration_errors()
    selected_other = c.runtime.model_copy(update={"clerk_audience": "invented-other-api"})
    selected_other.validate_runtime_configuration()
    checked = ClerkTokenVerifier(selected_other, jwks_client=c.keys(), start_background_refresh=False)
    with pytest.raises(AuthenticationFailed):
        checked.verify(c.token())
    assert checked.verify(c.token({"aud": selected_other.clerk_audience}))["sub"] == "user_invented_clerk_owner"


def test_known_separate_platform_origins_are_never_standalone_inputs(clerk_standalone):
    c = clerk_standalone
    issuer = "https://clerk.cosmaneura.com"
    assert c.runtime.model_copy(update={"clerk_issuer": issuer,
        "clerk_jwks_url": issuer + "/.well-known/jwks.json",
        "standalone_clerk_issuer_allowlist": issuer}).runtime_configuration_errors()
    assert c.runtime.model_copy(update={"cors_allowed_origins": "https://app.cosmaneura.com",
        "clerk_authorized_parties": "https://app.cosmaneura.com"}).runtime_configuration_errors()


def test_existing_verifier_enforces_exact_selected_session_claims(clerk_standalone):
    c = clerk_standalone
    checked = ClerkTokenVerifier(c.runtime, jwks_client=c.keys(), start_background_refresh=False)
    assert checked.verify(c.token())["sub"] == "user_invented_clerk_owner"
    for change in ({"iss": "https://other.clerk.accounts.dev"}, {"org_id": "org_other"},
                   {"azp": "https://other.invented-cosmabot.test"},
                   {"aud": None}, {"aud": ""}, {"aud": "wrong-instance"},
                   {"exp": datetime.now(UTC) - timedelta(minutes=1)}):
        with pytest.raises((AuthenticationFailed, AccessDenied)):
            checked.verify(c.token(change))
    with pytest.raises(AuthenticationFailed):
        checked.verify(c.token(kid="unreviewed-key"))
    if c.policy == "audience":
        with pytest.raises(AuthenticationFailed):
            checked.verify(c.token(omit=("aud",)))
    assert c.calls == ["selected-issuer-fixture"]


@pytest.mark.parametrize("origin", ["capacitor://localhost", "app://cosmas"])
def test_native_session_transport_reuses_exact_origin_and_azp_defenses(clerk_standalone, origin):
    c = clerk_standalone
    assert native_clerk_origin(c.runtime, [origin]) is None
    runtime = c.runtime.model_copy(update={
        "workspace_apple_hosted_transport_enabled": origin == "capacitor://localhost",
        "workspace_desktop_hosted_transport_enabled": origin == "app://cosmas",
        "cors_allowed_origins": c.runtime.cors_allowed_origins + "," + origin,
        "clerk_authorized_parties": c.runtime.clerk_authorized_parties + "," + origin,
    })
    runtime.validate_runtime_configuration()
    assert native_clerk_origin(runtime, [origin]) == origin
    assert native_clerk_origin(runtime, [origin, origin]) is None
    checked = ClerkTokenVerifier(runtime, jwks_client=c.keys(), start_background_refresh=False, native_origin=origin)
    assert checked.verify(c.token(omit=("azp",)))["sub"] == "user_invented_clerk_owner"
    assert checked.verify(c.token({"azp": origin}))["sub"] == "user_invented_clerk_owner"
    for claim in (None, "null", c.runtime.authorized_parties[0]):
        with pytest.raises(AuthenticationFailed):
            checked.verify(c.token({"azp": claim}))
    web = ClerkTokenVerifier(runtime, jwks_client=c.keys(), start_background_refresh=False)
    with pytest.raises(AuthenticationFailed):
        web.verify(c.token(omit=("azp",)))


def test_app_selects_existing_clerk_verifier_without_offline_key_fallback(clerk_standalone, monkeypatch):
    from cosmas_os.api import app as api

    c = clerk_standalone
    selected = []

    def factory(runtime, *, native_origin=None):
        selected.append((runtime, native_origin))
        return object()

    monkeypatch.setattr(api, "settings", c.runtime)
    monkeypatch.setattr(api, "ClerkTokenVerifier", factory)
    api._clerk_verifier.__wrapped__()
    assert selected == [(c.runtime, None)]


@pytest.mark.parametrize("path", [path for path, value in PATHS.items()
                                  if value[0] == "POST" and path != "/practice-access/setup/complete"])
def test_actual_middleware_stack_blocks_direct_practice_access_dispatch(clerk_standalone, monkeypatch, path):
    from cosmas_os.api import app as api

    monkeypatch.setattr(api, "settings", clerk_standalone.runtime)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("forbidden practice mutation reached identity or database")

    monkeypatch.setattr(api, "_request_clerk_verifier", forbidden)
    monkeypatch.setattr(api, "new_capture_session", forbidden)
    response = TestClient(api.app).post(path, content=b"not JSON; must not be read", headers={
        "X-Cosmas-Workspace-Protocol": "1", "X-Cosmas-Practice-Access-Contract": "1",
        "Content-Type": "application/json", "Authorization": "Bearer invented"})
    assert response.status_code == 403
    assert response.json() == {"detail": "standalone_operation_unavailable"}
    assert response.headers["x-cosmas-workspace-protocol"] == "1"


def test_existing_offline_stack_also_blocks_previously_outer_practice_mutations(standalone, monkeypatch):
    from cosmas_os.api import app as api

    runtime, _, _ = standalone
    monkeypatch.setattr(api, "settings", runtime)
    response = TestClient(api.app).post("/practice-access/invitations", content=b"unread", headers={
        "X-Cosmas-Workspace-Protocol": "1", "Content-Type": "application/json"})
    assert response.status_code == 403
    assert response.json() == {"detail": "standalone_operation_unavailable"}


@pytest.mark.parametrize("fault", [None, "redirect", "oversize", "private", "duplicate", "wrong_algorithm", "encoding", "deadline"])
def test_remote_key_transport_is_bounded_and_never_redirects(clerk_standalone, monkeypatch, fault):
    from cosmas_os.adapters import standalone_clerk_jwks as transport

    c = clerk_standalone
    public = json.loads(RSAAlgorithm.to_jwk(c.private.public_key()))
    public.update(kid="clerk-invented-fixture", alg="RS256", use="sig")
    if fault == "private":
        public["d"] = "forbidden-private-material"
    if fault == "wrong_algorithm":
        public["alg"] = "HS256"
    raw = json.dumps({"keys": [public]}).encode()
    if fault == "oversize":
        raw = b" " * 65537
    elif fault == "duplicate":
        raw = b'{"keys":[],"keys":[]}'
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if fault == "redirect":
            return httpx.Response(302, headers={"Location": "https://app.cosmaneura.com/.well-known/jwks.json"})
        return httpx.Response(200, stream=httpx.ByteStream(raw),
                              headers={"Content-Encoding": "gzip"} if fault == "encoding" else {})

    real_client = httpx.Client

    def client(**options):
        assert options == {"timeout": 5.0, "follow_redirects": False, "trust_env": False}
        return real_client(transport=httpx.MockTransport(handler), **options)

    monkeypatch.setattr(transport.httpx, "Client", client)
    if fault == "deadline":
        ticks = iter([0.0, 0.1, 5.1])
        monkeypatch.setattr(transport, "monotonic", lambda: next(ticks))
    selected = transport.StandaloneClerkKeys(c.runtime)
    if fault is None:
        keys = selected.get_signing_keys()
        assert len(keys) == 1 and keys[0].key_id == "clerk-invented-fixture"
    else:
        with pytest.raises(jwt.PyJWKClientError):
            selected.get_signing_keys()
    assert calls == [c.runtime.clerk_jwks_url]


def test_only_new_profile_selects_closed_remote_key_transport(clerk_standalone, monkeypatch):
    from cosmas_os.adapters.standalone_clerk_jwks import StandaloneClerkKeys
    from cosmas_os.api import auth

    c = clerk_standalone
    assert isinstance(ClerkTokenVerifier._key_client(c.runtime), StandaloneClerkKeys)
    calls = []
    monkeypatch.setattr(auth, "PyJWKClient", lambda *args, **kwargs: calls.append((args, kwargs)))
    ClerkTokenVerifier._key_client(c.offline)
    assert calls == [((c.offline.clerk_jwks_url,), {"cache_jwk_set": True, "timeout": 5})]
