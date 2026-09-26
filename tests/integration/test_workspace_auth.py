"""Signed requests exercise the real auth and private-workspace API boundaries offline."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from cosmas_os.api import app as api_module
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application import workspace as ws
from cosmas_os.config import Settings
from cosmas_os.models import AppointmentObservation, ExternalIdentity, PatientLink, Principal


@pytest.fixture
def signed_workspace(session, seeded, monkeypatch, request):
    box, actor = seeded["box_id"], seeded["owner_id"]
    platform = getattr(request, "param", "browser")
    apple, desktop = platform == "apple", platform == "desktop"
    origin = "capacitor://localhost" if apple else "app://cosmas" if desktop else "http://localhost:5173"
    issuer = seeded.get("clerk_issuer", "https://clerk.example.invalid")
    configuration = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue] -- BaseSettings runtime-only option.
        workspace_enabled=True, workspace_authenticated_enabled=True,
        database_url="postgresql+psycopg://w1a_synth@127.0.0.1:55439/w1a_w1b_test",
        auth_mode="clerk_jwt", synth_seed=False,
        clerk_issuer=issuer,
        clerk_jwks_url=issuer + "/.well-known/jwks.json",
        clerk_audience="cosmas-workspace-local", clerk_organization_id="org_invented",
        clerk_authorized_parties=origin, beta_box_id=box,
        cors_allowed_origins=origin,
        workspace_apple_local_transport_enabled=apple,
        workspace_desktop_local_transport_enabled=desktop,
    )
    assert configuration.runtime_configuration_errors() == []
    monkeypatch.setattr(api_module, "settings", configuration)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class LocalJwks:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="invented-key", key=key.public_key())]

    verifier = ClerkTokenVerifier(configuration, jwks_client=LocalJwks(), start_background_refresh=False)
    monkeypatch.setattr(api_module, "_clerk_verifier", lambda: verifier)
    binding = ExternalIdentity(
        box_id=box, principal_id=actor, provider="clerk",
        issuer=configuration.clerk_issuer, subject="user_invented",
        organization_id="org_invented", reviewed_by="Invented reviewer",
        evidence_ref="test:offline-binding",
    )
    link = PatientLink(box_id=box, source_pair_key="invented:" + str(uuid4()),
                       label="Invented encounter", state="confirmed",
                       confirmed_by_principal_id=actor, attested_at=datetime.now(UTC))
    session.add_all([binding, link])
    session.flush()
    appointment = AppointmentObservation(box_id=box, external_id="invented-" + str(uuid4()),
        source="synthetic", start_at=datetime.now(UTC), patient_label="Invented encounter",
        patient_link_id=link.id)
    session.add(appointment)
    session.commit()
    workspace = ws.create(session, box, actor, appointment.id, "authenticated-create")

    def token(**changes):
        now = datetime.now(UTC)
        claims = dict(sub="user_invented", iss=configuration.clerk_issuer,
            aud=configuration.clerk_audience, sid="session_invented",
            azp=origin, org_id="org_invented",
            iat=now, nbf=now, exp=now + timedelta(minutes=5))
        return jwt.encode({**claims, **changes}, key, algorithm="RS256", headers={"kid": "invented-key"})

    def get_session():
        yield session

    api_module.app.dependency_overrides[api_module.get_session] = get_session
    try:
        with TestClient(api_module.app) as client:
            yield SimpleNamespace(client=client, token=token, workspace=workspace, box=box,
                actor=actor, binding=binding, appointment=appointment, configuration=configuration)
    finally:
        api_module.app.dependency_overrides.pop(api_module.get_session, None)


def test_two_signed_sessions_reopen_the_same_private_history(signed_workspace):
    case = signed_workspace
    first = {"Authorization": "Bearer " + case.token(sid="session_mac")}
    second = {"Authorization": "Bearer " + case.token(sid="session_phone")}
    catalog = case.client.get("/workspaces", headers=first)
    assert catalog.status_code == 200
    assert catalog.json()[0]["workspace_id"] == case.workspace["id"]
    endpoint = f"/workspaces/{case.workspace['id']}"
    saved = case.client.post(endpoint + "/entries", headers=first, json={
        "expected_revision": 1, "idempotency_key": "signed-note",
        "kind": "scratchpad", "content": "Invented shared-device note",
    })
    assert saved.status_code == 200
    reopened = case.client.get(endpoint, headers=second)
    assert reopened.status_code == 200
    assert reopened.json()["entries"][-1]["content"] == "Invented shared-device note"
    assert reopened.headers["cache-control"] == "no-store"
    assert case.client.get("/provider-team", headers=second).status_code == 200


def test_draft_recovery_scope_is_stable_per_human_and_requires_current_access(signed_workspace, session):
    case = signed_workspace
    first = {"Authorization": "Bearer " + case.token(sid="session_before_restart")}
    second = {"Authorization": "Bearer " + case.token(sid="session_after_restart")}
    initial = case.client.get("/provider-team", headers=first)
    scope = initial.json()["recovery_scope"]
    assert len(scope) == 64 and all(char in "0123456789abcdef" for char in scope)
    assert case.client.get("/provider-team", headers=second).json()["recovery_scope"] == scope
    assert initial.headers["cache-control"] == "no-store"
    saved = case.client.post("/provider-team", headers=first, json={"expected_revision": 0,
        "idempotency_key": "invented-recovery-team-save", "configuration": initial.json()["configuration"]})
    assert saved.status_code == 200 and saved.json()["recovery_scope"] == scope
    other = Principal(box_id=case.box, principal_type="human", display_name="Invented recovery peer",
                      state="active", is_owner=True)
    session.add(other)
    session.flush()
    session.add(ExternalIdentity(box_id=case.box, principal_id=other.id, provider="clerk",
        issuer=case.configuration.clerk_issuer, subject="user_recovery_peer", organization_id="org_invented",
        reviewed_by="Invented reviewer", evidence_ref="test:recovery-peer-binding"))
    session.commit()
    peer = case.client.get("/provider-team", headers={"Authorization": "Bearer " + case.token(sub="user_recovery_peer")})
    assert peer.status_code == 200 and peer.json()["recovery_scope"] != scope
    case.binding.active = False
    session.commit()
    revoked = case.client.get("/provider-team", headers=second)
    assert revoked.status_code == 403 and "recovery_scope" not in revoked.json()


def test_required_recovery_generation_blocks_old_clients_before_reads_or_writes(signed_workspace, monkeypatch):
    case = signed_workspace
    monkeypatch.setattr(case.configuration, "workspace_draft_recovery_required", True)
    headers = {"Authorization": "Bearer " + case.token()}
    for path in ["/provider-team", "/workspaces", f"/workspaces/{case.workspace['id']}", "/practice-work"]:
        rejected = case.client.get(path, headers=headers)
        assert rejected.status_code == 426
        assert rejected.json() == {"detail": "workspace_client_update_required"}
        assert rejected.headers["cache-control"] == "no-store"
    rejected = case.client.post(f"/workspaces/{case.workspace['id']}/entries", headers=headers, json={
        "expected_revision": 1, "idempotency_key": "old-client-must-not-write", "kind": "scratchpad", "content": "Not admitted"})
    assert rejected.status_code == 426
    assert case.client.get("/provider-team", headers={**headers, "X-Cosmas-Draft-Recovery": "1"}).status_code == 426
    accepted = {**headers, "X-Cosmas-Draft-Recovery": "2"}
    assert case.client.get("/provider-team", headers=accepted).status_code == 200
    current = case.client.get(f"/workspaces/{case.workspace['id']}", headers=accepted)
    assert current.status_code == 200 and all(row["content"] != "Not admitted" for row in current.json()["entries"])
    assert case.client.get("/provider-team", headers={"X-Cosmas-Draft-Recovery": "2"}).status_code == 401


@pytest.mark.parametrize("claims,expected", [
    ({"sub": "user_unbound"}, 403), ({"org_id": "org_foreign"}, 403),
    ({"azp": "http://other.invalid"}, 401), ({"aud": "different-api"}, 401),
    ({"exp": datetime(2020, 1, 1, tzinfo=UTC)}, 401),
])
def test_invalid_or_unbound_signed_requests_cannot_read(signed_workspace, claims, expected):
    case = signed_workspace
    result = case.client.get(f"/workspaces/{case.workspace['id']}",
                            headers={"Authorization": "Bearer " + case.token(**claims)})
    assert result.status_code == expected
    assert result.headers["cache-control"] == "no-store"
    assert "Invented encounter" not in result.text


def test_identity_headers_and_unsigned_seeding_are_rejected(signed_workspace):
    case = signed_workspace
    for headers in [{}, {"X-Box-Id": case.box, "X-Actor-Principal-Id": case.actor},
        {"Authorization": "Bearer " + case.token(), "X-Box-Id": case.box}]:
        assert case.client.get("/workspaces", headers=headers).status_code == 401
    # Even an accidental seed toggle cannot open the unauthenticated seed route.
    case.configuration.synth_seed = True
    for path in ["/synth/seed", "/synth/demo-queue"]:
        assert case.client.post(path).status_code == 404


@pytest.mark.parametrize("revocation", ["binding", "human", "patient"])
def test_revocation_blocks_the_next_request(signed_workspace, session, revocation):
    case = signed_workspace
    headers = {"Authorization": "Bearer " + case.token()}
    endpoint = f"/workspaces/{case.workspace['id']}"
    assert case.client.get(endpoint, headers=headers).status_code == 200
    if revocation == "binding":
        case.binding.active = False
    elif revocation == "human":
        session.get(Principal, case.actor).state = "disabled"
    else:
        session.get(PatientLink, case.appointment.patient_link_id).revoked_at = datetime.now(UTC)
    session.commit()
    result = case.client.get(endpoint, headers=headers)
    assert result.status_code in {403, 404}
    assert result.headers["cache-control"] == "no-store"


def test_another_signed_human_cannot_open_the_private_notebook(signed_workspace, session):
    case = signed_workspace
    other = Principal(box_id=case.box, principal_type="human", display_name="Other invented user",
                      state="active", is_owner=True)
    session.add(other)
    session.flush()
    session.add(ExternalIdentity(box_id=case.box, principal_id=other.id, provider="clerk",
        issuer=case.configuration.clerk_issuer, subject="user_other", organization_id="org_invented",
        reviewed_by="Invented reviewer", evidence_ref="test:second-binding"))
    session.commit()
    headers = {"Authorization": "Bearer " + case.token(sub="user_other")}
    catalog = case.client.get("/workspaces", headers=headers)
    assert catalog.status_code == 200
    assert all(item["workspace_id"] != case.workspace["id"] for item in catalog.json())
    assert case.client.get(f"/workspaces/{case.workspace['id']}", headers=headers).status_code == 404
