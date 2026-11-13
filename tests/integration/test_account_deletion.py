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
        self.looked_up: list[str] = []
        self.get_status: dict[str, int] = {}
        self.delete_status: dict[str, int] = {}
        self.block_network = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.block_network:
            raise httpx.ConnectError("invented-clerk-egress-blocked", request=request)
        if not request.url.path.startswith("/v1/users/"):
            return httpx.Response(500, json={"error": "unexpected"})
        subject = request.url.path.rsplit("/", 1)[-1]
        if request.method == "GET":
            self.looked_up.append(subject)
            status = self.get_status.get(subject, 200)
            if status == 404:
                return httpx.Response(404, json={"error": "not_found"})
            return httpx.Response(200, json={"id": subject, "object": "user"})
        if request.method == "DELETE":
            status = self.delete_status.get(subject, 200)
            if status == 404:
                return httpx.Response(404, json={"error": "not_found"})
            if status >= 400:
                return httpx.Response(status, json={"error": "invented_clerk_failure"})
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
        account_delete_clerk_secret_key="sk_test_invented_account_deletion",
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
    assert deletion.clerk_transport.looked_up == ["user_delete_peer"]
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
    [None, "", "   ", "\t\n"],
    ids=[
        "account_delete_clerk_secret_unset",
        "account_delete_clerk_secret_empty_string",
        "account_delete_clerk_secret_spaces",
        "account_delete_clerk_secret_tabs_newlines",
    ],
)
def test_hosted_delete_fails_closed_without_clerk_secret(
    deletion, session, monkeypatch, secret_value
):
    """Absent or whitespace-only ACCOUNT_DELETE_CLERK_SECRET_KEY fails closed.

    Profile-agnostic: staging and production-review may allow the secret *name*,
    but with the key unset/empty/whitespace delete still returns exactly
    "account deletion is not configured" and mutates nothing.
    """

    api.app.dependency_overrides.pop(api._clerk_user_deletion_port, None)
    monkeypatch.setattr(
        api.settings,
        "account_delete_clerk_secret_key",
        None if secret_value is None else SecretStr(secret_value),
    )
    # CLERK_SECRET_KEY must not unlock delete; only the dedicated account-delete name does.
    monkeypatch.setattr(
        api.settings,
        "clerk_secret_key",
        SecretStr("sk_test_must_not_be_used_for_account_delete"),
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
    assert NOT_CONFIGURED == "account deletion is not configured"
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


def test_staging_delete_succeeds_when_account_delete_clerk_secret_present(
    deletion, session, monkeypatch
):
    """Staging with ACCOUNT_DELETE_CLERK_SECRET_KEY deletes and calls Clerk once."""

    api.app.dependency_overrides.pop(api._clerk_user_deletion_port, None)
    fake_secret = "sk_test_invented_account_delete_present"
    monkeypatch.setattr(
        api.settings,
        "account_delete_clerk_secret_key",
        SecretStr(fake_secret),
    )
    monkeypatch.setattr(api.settings, "clerk_secret_key", None)

    constructions: list[str] = []
    real_init = ClerkProvisioningPort.__init__

    def tracking_init(self, secret: str, *, client=None):  # noqa: ANN001
        constructions.append(secret)
        return real_init(
            self,
            secret,
            client=httpx.Client(transport=httpx.MockTransport(deletion.clerk_transport)),
        )

    monkeypatch.setattr(ClerkProvisioningPort, "__init__", tracking_init)

    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("cache-control") == "no-store"
    assert response.json() == {"status": "deleted"}
    assert constructions == [fake_secret]
    assert deletion.clerk_transport.looked_up == ["user_delete_peer"]
    assert deletion.clerk_transport.deleted == ["user_delete_peer"]

    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.TOMBSTONED.value


def test_clerk_404_on_require_user_does_not_tombstone_locally(deletion, session):
    """Wrong-instance / missing Clerk user must not report deleted or wipe local rows."""
    deletion.clerk_transport.get_status["user_delete_peer"] = 404
    before = _snapshot_account_rows(
        session, deletion.box, deletion.people["peer"], deletion.bindings["peer"].id
    )
    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 503
    assert response.headers.get("cache-control") == "no-store"
    assert response.json() == {"detail": "account deletion is temporarily unavailable"}
    assert deletion.clerk_transport.looked_up == ["user_delete_peer"]
    assert deletion.clerk_transport.deleted == []
    after = _snapshot_account_rows(
        session, deletion.box, deletion.people["peer"], deletion.bindings["peer"].id
    )
    assert after == before
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.ACTIVE.value


def test_clerk_egress_blocked_leaves_local_account_rows_unchanged(deletion, session):
    """Egress-blocked Clerk call must roll back; no half-changed local rows."""
    deletion.clerk_transport.block_network = True
    before = _snapshot_account_rows(
        session, deletion.box, deletion.people["peer"], deletion.bindings["peer"].id
    )
    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 503
    assert response.headers.get("cache-control") == "no-store"
    assert response.json() == {"detail": "account deletion is temporarily unavailable"}
    assert deletion.clerk_transport.deleted == []
    after = _snapshot_account_rows(
        session, deletion.box, deletion.people["peer"], deletion.bindings["peer"].id
    )
    assert after == before
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.ACTIVE.value
    still_signed_in = deletion.client.get("/account/identity", headers=deletion.headers("peer"))
    assert still_signed_in.status_code == 200
    assert still_signed_in.json()["state"] == "allowed"


def test_retry_succeeds_after_clerk_delete_then_commit_failure(deletion, session, monkeypatch):
    """Intent survives wipe rollback; retry accepts Clerk 404 and finishes locally."""
    from cosmas_os.models import AccountDeleteIntent

    commits = {"n": 0}
    real_commit = session.commit

    def flaky_commit():
        commits["n"] += 1
        # 1 = durable intent; 2 = wipe/tombstone commit after Clerk delete.
        if commits["n"] == 2:
            raise RuntimeError("invented-db-commit-failure")
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    first = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert first.status_code >= 400
    assert deletion.clerk_transport.deleted == ["user_delete_peer"]
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.ACTIVE.value
    intent = session.scalar(
        select(AccountDeleteIntent).where(
            AccountDeleteIntent.box_id == deletion.box,
            AccountDeleteIntent.principal_id == deletion.people["peer"],
            AccountDeleteIntent.subject == "user_delete_peer",
        )
    )
    assert intent is not None

    deletion.clerk_transport.get_status["user_delete_peer"] = 404
    monkeypatch.setattr(session, "commit", real_commit)
    second = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"status": "deleted"}
    session.refresh(peer)
    assert peer.state == PrincipalState.TOMBSTONED.value


def test_retry_succeeds_after_second_subject_clerk_5xx(deletion, session):
    """Two Clerk subjects: first deleted, second 5xx; retry finishes both."""
    from cosmas_os.models import AccountDeleteIntent

    second_binding = ExternalIdentity(
        box_id=deletion.box,
        principal_id=deletion.people["peer"],
        provider="clerk",
        issuer="https://identity.example.invalid",
        subject="user_delete_peer_b",
        # Distinct org so uq_external_identity_org_principal allows a second row.
        organization_id="org_identity_invented_b",
        reviewed_by="Invented reviewer",
        evidence_ref="test:account-deletion-second-subject",
    )
    session.add(second_binding)
    session.commit()

    deletion.clerk_transport.delete_status["user_delete_peer_b"] = 500
    first = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert first.status_code == 503
    assert "user_delete_peer" in deletion.clerk_transport.deleted
    assert "user_delete_peer_b" not in deletion.clerk_transport.deleted
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.ACTIVE.value
    intents = list(
        session.scalars(
            select(AccountDeleteIntent).where(
                AccountDeleteIntent.box_id == deletion.box,
                AccountDeleteIntent.principal_id == deletion.people["peer"],
            )
        )
    )
    assert {row.subject for row in intents} >= {"user_delete_peer", "user_delete_peer_b"}

    deletion.clerk_transport.get_status["user_delete_peer"] = 404
    deletion.clerk_transport.delete_status.pop("user_delete_peer_b", None)
    deletion.clerk_transport.deleted.clear()
    deletion.clerk_transport.looked_up.clear()
    second = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert second.status_code == 200, second.text
    assert second.json() == {"status": "deleted"}
    session.refresh(peer)
    assert peer.state == PrincipalState.TOMBSTONED.value
    assert "user_delete_peer_b" in deletion.clerk_transport.deleted


def _active_owners(session, box_id: str) -> list[Principal]:
    return list(
        session.scalars(
            select(Principal).where(
                Principal.box_id == box_id,
                Principal.principal_type == "human",
                Principal.state == PrincipalState.ACTIVE.value,
                Principal.tombstoned_at.is_(None),
                Principal.is_owner.is_(True),
            )
        )
    )


def test_delete_refuses_when_new_member_enrolls_after_intent_commit(
    deletion, session, monkeypatch
):
    """Sole-owner delete racing enrolment: post-intent owner guard refuses; practice keeps an owner."""
    from cosmas_os.application import account_deletion as deletion_app
    from cosmas_os.models import AccountDeleteIntent

    # Make owner the sole active human so the first lock admits the delete.
    peer = session.get(Principal, deletion.people["peer"])
    peer.state = PrincipalState.TOMBSTONED.value
    peer.tombstoned_at = datetime.now(UTC)
    peer.is_owner = False
    session.commit()

    real_commit = session.commit

    def enroll_member_during_intent_commit():
        # Intent commit drops the box FOR UPDATE lock; enrolment takes it next.
        new_member = Principal(
            box_id=deletion.box,
            principal_type="human",
            display_name="Invented New Enrollee",
            state="active",
            is_owner=False,
        )
        session.add(new_member)
        return real_commit()

    commits = {"n": 0}

    def flaky_commit():
        commits["n"] += 1
        if commits["n"] == 1:
            return enroll_member_during_intent_commit()
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    response = deletion.client.post(
        PATH, headers=deletion.headers("owner"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 400, response.text
    assert response.json() == {
        "detail": deletion_app.OWNER_TRANSFER_REQUIRED,
    }
    assert deletion.clerk_transport.deleted == []
    owner = session.get(Principal, deletion.people["owner"])
    session.refresh(owner)
    assert owner.state == PrincipalState.ACTIVE.value
    assert owner.is_owner is True
    assert len(_active_owners(session, deletion.box)) == 1
    intent = session.scalar(
        select(AccountDeleteIntent).where(
            AccountDeleteIntent.box_id == deletion.box,
            AccountDeleteIntent.principal_id == deletion.people["owner"],
            AccountDeleteIntent.subject == "user_delete_owner",
        )
    )
    assert intent is not None


def test_delete_refuses_when_ownership_transfers_after_intent_commit(
    deletion, session, monkeypatch
):
    """Member delete racing ownership transfer: re-lock owner guard refuses; no Clerk delete."""
    from cosmas_os.application import account_deletion as deletion_app

    real_commit = session.commit

    def transfer_ownership_during_intent_commit():
        owner = session.get(Principal, deletion.people["owner"])
        peer = session.get(Principal, deletion.people["peer"])
        owner.is_owner = False
        peer.is_owner = True
        return real_commit()

    commits = {"n": 0}

    def flaky_commit():
        commits["n"] += 1
        if commits["n"] == 1:
            return transfer_ownership_during_intent_commit()
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": deletion_app.OWNER_TRANSFER_REQUIRED}
    assert deletion.clerk_transport.deleted == []
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.ACTIVE.value
    assert peer.is_owner is True
    assert len(_active_owners(session, deletion.box)) == 1


def test_without_post_intent_owner_guard_transfer_race_leaves_practice_ownerless(
    deletion, session, monkeypatch
):
    """Negative control: skipping the post-intent owner refuse leaves no owner.

    Proves the re-lock guard is load-bearing: invert/remove it and this test fails
    the final owner assertion (practice would be ownerless).
    """
    from cosmas_os.application import account_deletion as deletion_app

    refuse_calls = {"n": 0}
    real_refuse = deletion_app._refuse_if_owner_with_teammates

    def selective_refuse(session_arg, *, box_id, actor):
        refuse_calls["n"] += 1
        # First lock: peer is not owner — real check is a no-op return.
        # Second lock (after transfer): skip so the mutation wins.
        if refuse_calls["n"] <= 1:
            return real_refuse(session_arg, box_id=box_id, actor=actor)
        return None

    monkeypatch.setattr(deletion_app, "_refuse_if_owner_with_teammates", selective_refuse)

    real_commit = session.commit

    def transfer_ownership_during_intent_commit():
        owner = session.get(Principal, deletion.people["owner"])
        peer = session.get(Principal, deletion.people["peer"])
        owner.is_owner = False
        peer.is_owner = True
        return real_commit()

    commits = {"n": 0}

    def flaky_commit():
        commits["n"] += 1
        if commits["n"] == 1:
            return transfer_ownership_during_intent_commit()
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 200, response.text
    assert "user_delete_peer" in deletion.clerk_transport.deleted
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.TOMBSTONED.value
    assert peer.is_owner is False
    # Mutation proof: without the post-intent guard the practice has no owner.
    assert _active_owners(session, deletion.box) == []
    assert refuse_calls["n"] >= 2


def test_delete_refuses_when_clerk_subject_set_changes_after_intent(
    deletion, session, monkeypatch
):
    """Subject remapped in the intent-commit gap must refuse (no unconfirmed Clerk delete)."""
    from cosmas_os.application import account_deletion as deletion_app

    real_commit = session.commit

    def remap_clerk_subject_during_intent_commit():
        # One principal may only hold one issuer+org binding; remap subject instead
        # of inserting a second row (would hit uq_external_identity_org_principal).
        binding = session.get(ExternalIdentity, deletion.bindings["peer"].id)
        binding.subject = "user_delete_peer_remapped"
        return real_commit()

    commits = {"n": 0}

    def flaky_commit():
        commits["n"] += 1
        if commits["n"] == 1:
            return remap_clerk_subject_during_intent_commit()
        return real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    response = deletion.client.post(
        PATH, headers=deletion.headers("peer"), json={"confirm": CONFIRM_PHRASE}
    )
    assert response.status_code == 400, response.text
    assert response.json() == {"detail": deletion_app.SUBJECT_SET_CHANGED}
    assert deletion.clerk_transport.deleted == []
    peer = session.get(Principal, deletion.people["peer"])
    session.refresh(peer)
    assert peer.state == PrincipalState.ACTIVE.value


def test_confirm_without_lookup_user_never_treats_errors_as_success(deletion, session):
    """Fail-closed: ports without lookup_user must call require_user; no silent pass."""
    from cosmas_os.application import account_deletion as deletion_app
    from cosmas_os.enrollment.domain import EnrollmentError

    class RequireOnlyClerk:
        def __init__(self) -> None:
            self.required: list[str] = []
            self.deleted: list[str] = []

        def require_user(self, subject: str) -> dict:
            self.required.append(subject)
            raise EnrollmentError(
                "provisioning_identity_unavailable",
                "Practice identity setup can be retried safely.",
                503,
            )

        def delete_user(self, subject: str) -> None:
            self.deleted.append(subject)

    # Seed an intent so the old fail-open branch would have accepted any error.
    from cosmas_os.models import AccountDeleteIntent

    session.add(
        AccountDeleteIntent(
            box_id=deletion.box,
            principal_id=deletion.people["peer"],
            provider="clerk",
            subject="user_delete_peer",
        )
    )
    session.commit()

    clerk = RequireOnlyClerk()
    with pytest.raises(EnrollmentError):
        deletion_app._confirm_clerk_subjects(
            session,
            clerk,
            box_id=deletion.box,
            principal_id=deletion.people["peer"],
            subjects=["user_delete_peer"],
        )
    assert clerk.required == ["user_delete_peer"]
    assert clerk.deleted == []

