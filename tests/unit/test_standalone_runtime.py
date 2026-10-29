from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from cosmas_os.api.auth import AccessDenied, AuthenticationFailed, ClerkTokenVerifier
from cosmas_os.config import Settings
from cosmas_os.standalone_runtime import LocalPublicKeys


@pytest.fixture
def standalone(tmp_path):
    instance = uuid.uuid4()
    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    (root / "blobs").mkdir(mode=0o700)
    (root / "keys").mkdir(mode=0o700)
    marker = root / "instance.json"
    marker.write_text(json.dumps({"schema": "cosmabot-standalone-runtime/v1", "instance_id": str(instance)}))
    marker.chmod(0o600)
    issuer = f"https://{instance}.cosmabot.invalid"
    runtime = Settings(_env_file=None, cosmas_env="standalone_synthetic", data_mode="synthetic",
        standalone_instance_id=str(instance), standalone_root=str(root),
        standalone_jwks_path=str(root / "keys/jwks.json"),
        database_url="postgresql+psycopg://invented:invented@127.0.0.1:54321/cosmabot_standalone_unit",
        redis_url="", blob_backend="local", blob_root=str(root / "blobs"),
        auth_mode="clerk_jwt", synth_seed=False, sync_worker=False,
        workspace_enabled=True, workspace_authenticated_enabled=True,
        workspace_draft_recovery_required=True, workspace_llm_endpoint="",
        clerk_issuer=issuer, clerk_jwks_url=issuer + "/.well-known/jwks.json",
        clerk_audience=f"cosmabot-standalone:{instance}",
        clerk_organization_id="org_cosmabot_" + instance.hex,
        beta_box_id=str(uuid.uuid4()), cors_allowed_origins="http://127.0.0.1:5173",
        clerk_authorized_parties="http://127.0.0.1:5173")
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    public = {name: public[name] for name in ("kty", "n", "e")}
    public.update(kid=f"cosmabot-standalone:{instance}:key1", alg="RS256", use="sig")
    path = root / "keys/jwks.json"
    path.write_text(json.dumps({"keys": [public]}))
    path.chmod(0o600)
    return runtime, private, public


def test_standalone_profile_is_explicit_and_runtime_valid(standalone):
    runtime, _, _ = standalone
    runtime.validate_runtime_configuration()
    assert runtime.workspace_available
    assert not runtime.workspace_core_connection_available
    assert not runtime.workspace_llm_available
    assert not runtime.workspace_capture_available
    # The same local configuration is not quietly accepted as a hosted profile.
    assert runtime.model_copy(update={"cosmas_env": "early_adopter_beta"}).runtime_configuration_errors()
    assert runtime.model_copy(update={"cosmas_env": "synth_os"}).runtime_configuration_errors()


@pytest.mark.parametrize("changes", [
    {"database_url": "postgresql+psycopg://invented:invented@db.example.invalid/cosmabot_standalone_unit"},
    {"database_url": "postgresql+psycopg://invented:invented@127.0.0.1:54321/cosmas_os"},
    {"database_url": "postgresql+psycopg://invented:invented@127.0.0.1:54321/cosmabot_standalone_unit?host=db.invalid"},
    {"standalone_instance_id": str(uuid.UUID(int=1))},
    {"blob_root": "/tmp/shared"}, {"redis_url": "redis://127.0.0.1:6379/0"},
    {"core_capture_origin": "https://core.example.invalid"},
    {"workspace_core_connection_enabled": True}, {"workspace_routines_enabled": True},
    {"workspace_google_connection_enabled": True}, {"vendor_io_enabled": True},
    {"google_connection_client_secret": "invented"}, {"workspace_llm_api_key": "invented"},
    {"azure_storage_account_url": "https://storage.example.invalid"},
    {"workspace_hosted_enabled": True}, {"auth_mode": "synth_headers"},
    {"clerk_issuer": "https://other.example.invalid"}, {"clerk_audience": "shared"},
    {"clerk_organization_id": "org_shared"}, {"clerk_session_policy": "shared_staging"},
    {"workspace_llm_endpoint": "https://model.example.invalid"},
    {"cors_allowed_origins": "https://workspace.example.invalid"},
])
def test_standalone_rejects_mixed_resources_and_external_activation(standalone, changes):
    runtime, _, _ = standalone
    invalid = runtime.model_copy(update=changes)
    assert invalid.runtime_configuration_errors()
    assert not invalid.workspace_available


def test_local_signed_identity_verifies_without_network_or_refresh(standalone, monkeypatch):
    runtime, private, public = standalone
    def forbidden(*args, **kwargs):
        raise AssertionError("Network key discovery or refresh is forbidden")
    monkeypatch.setattr("cosmas_os.api.auth.PyJWKClient", forbidden)
    monkeypatch.setattr("cosmas_os.api.auth.Thread", forbidden)
    verifier = ClerkTokenVerifier(runtime, jwks_client=LocalPublicKeys(runtime), start_background_refresh=False)
    now = datetime.now(UTC)
    claims = {"iss": runtime.clerk_issuer, "aud": runtime.clerk_audience,
        "org_id": runtime.clerk_organization_id, "sub": "user_invented_owner",
        "sid": "session_invented", "azp": runtime.authorized_parties[0],
        "iat": now, "nbf": now, "exp": now + timedelta(minutes=5)}
    def token(updates):
        return jwt.encode(claims | updates, private, algorithm="RS256", headers={"kid": public["kid"]})
    assert verifier.verify(token({}))["sub"] == "user_invented_owner"
    for changed in ({"iss": "https://other.example.invalid"}, {"aud": "shared"},
                    {"org_id": "org_other"}, {"azp": "https://other.example.invalid"},
                    {"exp": now - timedelta(minutes=1)}):
        with pytest.raises((AuthenticationFailed, AccessDenied)):
            verifier.verify(token(changed))


@pytest.mark.parametrize("fault", ["marker", "public_permissions", "key_namespace", "private_key", "symlink"])
def test_local_keys_reject_shared_or_unowned_state(standalone, fault):
    runtime, _, public = standalone
    from pathlib import Path
    root = Path(runtime.standalone_root)
    path = root / "keys/jwks.json"
    if fault == "marker":
        (root / "instance.json").write_text("{}")
    elif fault == "public_permissions":
        path.chmod(0o644)
    elif fault == "key_namespace":
        path.write_text(json.dumps({"keys": [public | {"kid": "shared:key1"}]}))
    elif fault == "private_key":
        path.write_text(json.dumps({"keys": [public | {"d": "private-part"}]}))
    else:
        target = root / "keys/elsewhere.json"
        path.rename(target)
        path.symlink_to(target)
    with pytest.raises(RuntimeError):
        LocalPublicKeys(runtime)


@pytest.mark.parametrize("path", [
    "/schedule/import", "/patient-links/attest", "/chase/open", "/synth/seed",
    "/synth/demo-queue", "/tickets/invented/edit", "/tickets/invented/decide",
    "/tickets/invented/upload-verify", "/tickets/invented/close", "/retention/purge",
    "/admin/identities/bind", "/admin/owner/transfer", "/capabilities/invented/invoke",
    "/provider-team/rehearsal", "/workspaces/00000000-0000-4000-8000-000000000001/conversation",
    "/workspaces/00000000-0000-4000-8000-000000000001/appointments/invented/execute",
    "/workspaces/00000000-0000-4000-8000-000000000001/notes/invented/review",
])
def test_standalone_api_refuses_legacy_mutations_before_database_or_dispatch(standalone, monkeypatch, path):
    from fastapi.testclient import TestClient

    from cosmas_os.api import app as api
    from cosmas_os.application import services
    runtime, _, _ = standalone
    def forbidden(*args, **kwargs):
        raise AssertionError("Forbidden standalone route reached database or dispatch")
    monkeypatch.setattr(api, "settings", runtime)
    monkeypatch.setattr(services, "_dispatch_operation", forbidden)
    previous = api.app.dependency_overrides.copy()
    api.app.dependency_overrides[api.get_session] = forbidden
    try:
        # In-process request routing only; lifespan/listener is intentionally not started.
        response = TestClient(api.app).post(path, json={}, headers={"X-Cosmas-Workspace-Protocol": "1"})
        assert response.status_code == 403
        assert response.json() == {"detail": "standalone_operation_unavailable"}
    finally:
        api.app.dependency_overrides = previous


def test_standalone_local_surface_is_explicit_and_dispatch_is_closed(standalone, monkeypatch):
    from cosmas_os.application import services
    from cosmas_os.domain.rules import PolicyDenied
    from cosmas_os.standalone_runtime import standalone_request_allowed
    runtime, _, _ = standalone
    for path in ("/practice-access/setup/complete", "/provider-team", "/workspaces", "/workspaces/private-drafts",
                 "/workspaces/00000000-0000-4000-8000-000000000001/entries",
                 "/workspaces/00000000-0000-4000-8000-000000000001/notes",
                 "/workspaces/00000000-0000-4000-8000-000000000001/conversations/chief/read"):
        assert standalone_request_allowed("POST", path)
        assert not standalone_request_allowed("DELETE", path)
    monkeypatch.setattr(services, "settings", runtime)
    with pytest.raises(PolicyDenied, match="standalone_operation_unavailable"):
        services._dispatch_operation(None, None)


def test_static_offline_keys_outlive_remote_cache_ttl_but_not_jwt_lifetimes(standalone, monkeypatch):
    from cosmas_os.standalone_runtime import StandaloneTokenVerifier
    runtime, private, public = standalone
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline identity must not discover keys or start refresh threads")
    monkeypatch.setattr("cosmas_os.api.auth.PyJWKClient", forbidden)
    monkeypatch.setattr("cosmas_os.api.auth.Thread", forbidden)
    verifier = StandaloneTokenVerifier(runtime)
    now = datetime.now(UTC)
    claims = {"iss": runtime.clerk_issuer, "aud": runtime.clerk_audience,
        "org_id": runtime.clerk_organization_id, "sub": "user_invented_owner",
        "sid": "session_invented", "azp": runtime.authorized_parties[0],
        "iat": now, "nbf": now, "exp": now + timedelta(minutes=5)}
    def token(updates):
        return jwt.encode(claims | updates, private, algorithm="RS256", headers={"kid": public["kid"]})
    monkeypatch.setattr("cosmas_os.api.auth.monotonic", lambda: float("inf"))
    assert verifier.verify(token({}))["sub"] == "user_invented_owner"
    for changes in ({"exp": now - timedelta(minutes=1)}, {"nbf": now + timedelta(minutes=1)},
                    {"aud": "other"}, {"iss": "https://other.example.invalid"}, {"org_id": "org_other"}):
        with pytest.raises((AuthenticationFailed, AccessDenied)):
            verifier.verify(token(changes))
    unknown = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "untrusted:key"})
    with pytest.raises(AuthenticationFailed):
        verifier.verify(unknown)
