"""Self-serve account deletion: confirm deletes caller only; peers stay intact."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from cosmas_os.api import app as api
from cosmas_os.api.auth import ClerkTokenVerifier
from cosmas_os.application.account_deletion import CONFIRM_PHRASE, NOT_CONFIGURED
from cosmas_os.config import Settings
from cosmas_os.domain.enums import PrincipalState
from cosmas_os.enrollment.provisioning import ClerkProvisioningPort
from cosmas_os.google_connection_models import GoogleConnectionCredential
from cosmas_os.models import (
    AuditEvent,
    ExternalIdentity,
    PatientLink,
    Principal,
    Ticket,
    WorkspaceNote,
)

ORIGIN = "http://localhost:5173"
PATH = "/account/delete"


class FakeClerkUsers:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" and request.url.path.startswith("/v1/users/"):
            subject = request.url.path.rsplit("/", 1)[-1]
            self.deleted.append(subject)
            return httpx.Response(200, json={"id": subject, "deleted": True})
        return httpx.Response(500, json={"error": "unexpected"})


@pytest.fixture
def deletion(session, seeded, monkeypatch):
    box, owner = seeded["box_id"], seeded["owner_id"]
    conf = Settings(
        _env_file=None,
        workspace_enabled=True,
        workspace_authenticated_enabled=True,
        workspace_draft_recovery_required=True,
        auth_mode="clerk_jwt",
        synth_seed=False,
        clerk_issuer="https://identity.example.invalid",
        clerk_jwks_url="https://identity.example.invalid/.well-known/jwks.json",
        clerk_audience="cosmas-identity-local",
        clerk_organization_id="org_identity_invented",
        clerk_authorized_parties=ORIGIN,
        clerk_secret_key="sk_test_invented_account_deletion",
        beta_box_id=box,
        cors_allowed_origins=ORIGIN,
    )
    monkeypatch.setattr(api, "settings", conf)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    class OfflineKeys:
        def get_signing_keys(self, *, refresh):
            return [SimpleNamespace(key_id="deletion-test-key", key=key.public_key())]

    verifier = ClerkTokenVerifier(conf, jwks_client=OfflineKeys(), start_background_refresh=False)
    monkeypatch.setattr(api, "_clerk_verifier", lambda: verifier)

    peer = Principal(
        box_id=box,
        principal_type="human",
        display_name="Invented Peer",
        state="active",
        is_owner=False,
    )
    session.add(peer)
    session.flush()
    people = {"owner": owner, "peer": peer.id}
    bindings = {}
    for label, actor in people.items():
        binding = ExternalIdentity(
            box_id=box,
            principal_id=actor,
            provider="clerk",
            issuer=conf.clerk_issuer,
            subject="user_delete_" + label,
            organization_id=conf.clerk_organization_id,
            reviewed_by="Invented reviewer",
            evidence_ref="test:account-deletion",
        )
        session.add(binding)
        bindings[label] = binding
    session.flush()
    session.add(
        GoogleConnectionCredential(
            account_id=bindings["peer"].id,
            binding_digest="a" * 64,
            status="ready",
            sealed=b"\x00" * 28,
            refresh_id=str(uuid4()),
            connected_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.add(
        GoogleConnectionCredential(
            account_id=bindings["owner"].id,
            binding_digest="b" * 64,
            status="ready",
            sealed=b"\x01" * 28,
            refresh_id=str(uuid4()),
            connected_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    session.add(
        PatientLink(
            box_id=box,
            source_pair_key="invented-delete:" + str(uuid4()),
            label="Invented Patient",
            state="confirmed",
        )
    )
    session.commit()

    clerk_transport = FakeClerkUsers()
    clerk = ClerkProvisioningPort(
        "sk_test_invented_account_deletion",
        client=httpx.Client(transport=httpx.MockTransport(clerk_transport)),
    )

    def token(label="peer", **changes):
        now = datetime.now(UTC)
        claims = dict(
            sub="user_delete_" + label,
            iss=conf.clerk_issuer,
            aud=conf.clerk_audience,
            sid="session_delete",
            azp=ORIGIN,
            org_id=conf.clerk_organization_id,
            iat=now,
            nbf=now,
            exp=now + timedelta(minutes=5),
        )
        return jwt.encode(
            {**claims, **changes}, key, algorithm="RS256", headers={"kid": "deletion-test-key"}
        )

    def headers(label="peer", **changes):
        return {
            "Authorization": "Bearer " + token(label, **changes),
            "Origin": ORIGIN,
        }

    def get_session():
        yield session

    api.app.dependency_overrides[api.get_session] = get_session
    api.app.dependency_overrides[api._clerk_user_deletion_port] = lambda: clerk
    try:
        with TestClient(api.app) as client:
            yield SimpleNamespace(
                client=client,
                box=box,
                people=people,
                bindings=bindings,
                headers=headers,
                clerk_transport=clerk_transport,
                session=session,
            )
    finally:
        api.app.dependency_overrides.pop(api.get_session, None)
        api.app.dependency_overrides.pop(api._clerk_user_deletion_port, None)


def test_cancel_phrase_deletes_nothing(deletion, session):
    response = deletion.client.post(PATH, headers=deletion.headers("peer"), json={"confirm": "cancel"})
    assert response.status_code == 400
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "account deletion requires explicit confirmation"}
    peer = session.get(Principal, deletion.people["peer"])
    binding = deletion.bindings["peer"]
    session.refresh(peer)
    session.refresh(binding)
    assert peer.state == PrincipalState.ACTIVE.value
    assert binding.active
    assert deletion.clerk_transport.deleted == []
    credential = session.get(GoogleConnectionCredential, binding.id)
    assert credential is not None and credential.status == "ready" and credential.sealed is not None


def test_confirm_deletes_caller_clerk_and_personal_data_without_touching_peer(deletion, session):
    before_patients = session.scalar(
        select(func.count()).select_from(PatientLink).where(PatientLink.box_id == deletion.box)
    )
    before_tickets = session.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.box_id == deletion.box)
    )
    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "deleted"}
    assert deletion.clerk_transport.deleted == ["user_delete_peer"]

    peer = session.get(Principal, deletion.people["peer"])
    owner = session.get(Principal, deletion.people["owner"])
    peer_binding = deletion.bindings["peer"]
    owner_binding = deletion.bindings["owner"]
    session.refresh(peer)
    session.refresh(owner)
    session.refresh(peer_binding)
    session.refresh(owner_binding)

    assert peer.state == PrincipalState.TOMBSTONED.value
    assert peer.tombstoned_at is not None
    assert peer.display_name == "Deleted account"
    assert not peer_binding.active
    peer_credential = session.get(GoogleConnectionCredential, peer_binding.id)
    assert peer_credential is not None
    assert peer_credential.status == "disconnected"
    assert peer_credential.sealed is None

    assert owner.state == PrincipalState.ACTIVE.value
    assert owner.display_name != "Deleted account"
    assert owner_binding.active
    owner_credential = session.get(GoogleConnectionCredential, owner_binding.id)
    assert owner_credential is not None
    assert owner_credential.status == "ready"
    assert owner_credential.sealed is not None

    assert (
        session.scalar(
            select(func.count()).select_from(PatientLink).where(PatientLink.box_id == deletion.box)
        )
        == before_patients
    )
    assert (
        session.scalar(select(func.count()).select_from(Ticket).where(Ticket.box_id == deletion.box))
        == before_tickets
    )
    audit = session.scalar(
        select(AuditEvent).where(
            AuditEvent.box_id == deletion.box,
            AuditEvent.event_type == "account.deleted",
            AuditEvent.aggregate_id == peer.id,
        )
    )
    assert audit is not None and audit.outcome == "deleted"

    denied = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert denied.status_code == 403


def test_owner_with_active_teammate_must_transfer_first(deletion):
    response = deletion.client.post(
        PATH, headers=deletion.headers("owner"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "transfer ownership before deleting this owner account"}
    assert deletion.clerk_transport.deleted == []


def _snapshot_account_rows(session, box_id: str, principal_id: str, binding_id: str) -> dict:
    peer = session.get(Principal, principal_id)
    binding = session.get(ExternalIdentity, binding_id)
    credential = session.get(GoogleConnectionCredential, binding_id)
    session.refresh(peer)
    session.refresh(binding)
    if credential is not None:
        session.refresh(credential)
    return {
        "principal_state": peer.state,
        "tombstoned_at": peer.tombstoned_at,
        "display_name": peer.display_name,
        "is_owner": peer.is_owner,
        "binding_active": binding.active,
        "credential_status": None if credential is None else credential.status,
        "credential_sealed": None if credential is None else credential.sealed,
        "credential_refresh_id": None if credential is None else credential.refresh_id,
        "patients": session.scalar(
            select(func.count()).select_from(PatientLink).where(PatientLink.box_id == box_id)
        ),
        "tickets": session.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.box_id == box_id)
        ),
        "notes": session.scalar(
            select(func.count()).select_from(WorkspaceNote).where(WorkspaceNote.box_id == box_id)
        ),
        "principals": session.scalar(
            select(func.count()).select_from(Principal).where(Principal.box_id == box_id)
        ),
        "bindings": session.scalar(
            select(func.count())
            .select_from(ExternalIdentity)
            .where(ExternalIdentity.box_id == box_id)
        ),
        "deleted_audits": session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.box_id == box_id,
                AuditEvent.event_type == "account.deleted",
            )
        ),
    }


@pytest.mark.parametrize(
    "secret_value",
    [None, ""],
    ids=["clerk_secret_unset", "clerk_secret_empty_string"],
)
def test_hosted_delete_fails_closed_without_clerk_secret(
    deletion, session, monkeypatch, secret_value
):
    """Staging without CLERK_SECRET_KEY must refuse delete without mutating anything."""

    api.app.dependency_overrides.pop(api._clerk_user_deletion_port, None)
    monkeypatch.setattr(
        api.settings,
        "clerk_secret_key",
        None if secret_value is None else SecretStr(secret_value),
    )

    clerk_constructions: list[str] = []

    def refuse_construction(self, secret: str, *, client=None):  # noqa: ANN001
        clerk_constructions.append(secret)
        raise AssertionError("Clerk Backend client must not be constructed without a secret")

    monkeypatch.setattr(ClerkProvisioningPort, "__init__", refuse_construction)

    before = _snapshot_account_rows(
        session, deletion.box, deletion.people["peer"], deletion.bindings["peer"].id
    )

    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )

    assert response.status_code == 400
    assert response.status_code != 500
    assert response.headers.get("cache-control") == "no-store"
    body = response.json()
    assert body == {"detail": NOT_CONFIGURED}
    assert body["detail"] == "account deletion is not configured"
    text = response.text.lower()
    assert "traceback" not in text
    assert "secret" not in text
    assert "sk_" not in text
    assert clerk_constructions == []
    assert deletion.clerk_transport.deleted == []

    after = _snapshot_account_rows(
        session, deletion.box, deletion.people["peer"], deletion.bindings["peer"].id
    )
    assert after == before

    still_signed_in = deletion.client.get("/account/identity", headers=deletion.headers("peer"))
    assert still_signed_in.status_code == 200, still_signed_in.text
    assert still_signed_in.headers.get("cache-control") == "no-store"
    identity = still_signed_in.json()
    assert identity["state"] == "allowed"
    assert identity["box_id"] == deletion.box
