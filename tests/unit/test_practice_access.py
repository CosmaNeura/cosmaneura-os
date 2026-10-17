"""Owned PostgreSQL enrollment checks. No actual identity, service or patient data."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from cosmas_os.api.auth import AccessDenied, ClerkTokenVerifier, authenticate_request
from cosmas_os.api.practice_access_routes import register
from cosmas_os.api.practice_access_schemas import (
    CreateInvitation,
    DecideAccess,
    JoinInvitation,
    ReviewAccess,
    RevokeInvitation,
    SubmitAccess,
)
from cosmas_os.application import beta_identity_admin as admin
from cosmas_os.application import practice_access as access
from cosmas_os.application import practice_invites as invites
from cosmas_os.config import Settings
from cosmas_os.db import Base
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_access_models import (
    PracticeAccessRequest,
    PracticeInvitation,
    PracticeInviteRevocation,
    PracticeInviteUse,
)
from cosmas_os.practice_setup_models import PracticeOwnerReservation, PracticeSetupProfile


@pytest.fixture
def case(engine):
    # Use the test runner's database, with a private schema for committed and
    # concurrent sessions. No workstation-specific settings file is required.
    root = engine
    schema = "practice_access_" + uuid4().hex
    with root.begin() as c:
        c.execute(text('CREATE SCHEMA "' + schema + '"'))
    isolated = create_engine(root.url, connect_args={"options": "-c search_path=" + schema})
    try:
        yield _practice_access_case(isolated)
    finally:
        isolated.dispose()
        with root.begin() as c:
            c.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))


def _practice_access_case(engine):
    tables = [BoxContext.__table__, Principal.__table__, ExternalIdentity.__table__,
              AuditEvent.__table__, PracticeAccessRequest.__table__, PracticeOwnerReservation.__table__, PracticeSetupProfile.__table__, PracticeInvitation.__table__, PracticeInviteRevocation.__table__, PracticeInviteUse.__table__]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(engine, autoflush=False)
    values = json.loads((Path(__file__).parents[1] / "fixtures/hosted-workspace-settings.json").read_text())
    values["beta_box_id"] = str(uuid4())
    config = Settings(_env_file=None, **values)
    config.validate_runtime_configuration()
    owner_id = str(uuid4())
    with factory() as s:
        s.add(BoxContext(id=config.beta_box_id, display_name="Invented practice"))
        s.flush()
        s.add(Principal(id=owner_id, box_id=config.beta_box_id, display_name="Invented owner",
                        principal_type="human", state="active", is_owner=True))
        s.flush()
        s.add(ExternalIdentity(box_id=config.beta_box_id, principal_id=owner_id, provider="clerk",
            issuer=config.clerk_issuer, organization_id=config.clerk_organization_id,
            subject="user_w81owner", active=True, reviewed_by="invented", evidence_ref="invented:owner"))
        s.commit()
    def member(subject):
        return access.VerifiedMember(config.beta_box_id, config.clerk_issuer, config.clerk_organization_id, subject)
    return SimpleNamespace(factory=factory, engine=engine, config=config, owner_id=owner_id,
                          owner=member("user_w81owner"), applicant=member("user_w81member"), member=member)


def invoke(c, operation, member=None, command=None, fence=lambda: None):
    with c.factory() as s:
        return operation(s, c.config, member or c.applicant, *([] if command is None else [command]), fence=fence)


def request(c):
    return invoke(c, access.submit, command=SubmitAccess(idempotency_key=uuid4(), display_name="Invented teammate"))["request"]


def decision(row, **changes):
    return DecideAccess(request_id=row["request_id"], review_sha256=row["review_sha256"],
                        confirm=True, decision=changes.get("decision", "approve"))


def count(c, model):
    with c.factory() as s:
        return s.scalar(select(func.count()).select_from(model))


def verifier(c):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    class Keys:
        def get_signing_keys(self, **_):
            return [SimpleNamespace(key_id="w81", key=private.public_key())]
    checked = ClerkTokenVerifier(c.config, jwks_client=Keys(), start_background_refresh=False)
    def token(member, **changes):
        now = int(time.time())
        claims = {"iss": c.config.clerk_issuer, "sub": member.subject, "org_id": member.organization_id,
                  "aud": c.config.clerk_audience, "iat": now, "nbf": now, "exp": now + 120,
                  "sid": "sess_invented_w81", "azp": c.config.authorized_parties[0], **changes}
        return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "w81"})
    return checked, token


def test_request_is_not_a_grant_and_review_uses_existing_once_only_binding(case):
    c = case
    command = SubmitAccess(idempotency_key=uuid4(), display_name="Invented teammate")
    first = invoke(c, access.submit, command=command)
    assert first == invoke(c, access.submit, command=command)
    assert first["state"] == "pending" and count(c, Principal) == 1 and count(c, ExternalIdentity) == 1
    owner_view = invoke(c, access.pending, c.owner)
    assert owner_view["requests"] == [first["request"]]
    assert c.applicant.subject not in json.dumps(owner_view)
    result = invoke(c, access.decide, c.owner, decision(first["request"]))
    assert result["request"]["state"] == "approved"
    assert result == invoke(c, access.decide, c.owner, decision(first["request"]))
    assert invoke(c, access.status) == {"contract_version": 1, "state": "connected", "role": "member", "request": None}
    assert count(c, ExternalIdentity) == 2 and count(c, Principal) == 2
    with c.factory() as s:
        assert s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "external_identity.bound")) == 1
        assert s.scalar(select(func.count()).select_from(Principal).where(Principal.is_owner.is_(True))) == 1
    checked, token = verifier(c)
    with c.factory() as s:
        identity = authenticate_request(s, c.config, authorization="Bearer " + token(c.applicant),
                                        box_header=None, actor_header=None, verifier=checked)
        assert identity.box_id == c.config.beta_box_id and identity.external_identity_id


def test_owner_scope_exact_review_and_request_privacy(case):
    c = case
    row = request(c)
    for op, command in [(access.pending, None), (access.decide, decision(row))]:
        with pytest.raises(access.PracticeAccessError, match="practice_access_denied"):
            invoke(c, op, command=command)
    bad = decision(row).model_copy(update={"review_sha256": "0" * 64})
    with pytest.raises(access.PracticeAccessError, match="practice_access_conflict"):
        invoke(c, access.decide, c.owner, bad)
    other = c.member("user_someoneelse")
    with pytest.raises(access.PracticeAccessError, match="practice_access_not_found"):
        invoke(c, access.cancel, other, ReviewAccess(request_id=row["request_id"], review_sha256=row["review_sha256"], confirm=True))
    assert count(c, Principal) == 1


def test_revoked_subject_cannot_request_or_be_reactivated_by_pending_approval(case):
    c = case
    row = request(c)
    with c.factory() as s:
        admin.bind_beta_identity(s, c.config, actor_principal_id=c.owner_id, clerk_subject=c.applicant.subject,
                                display_name="Invented prior member", evidence_ref="invented:prior")
        admin.deactivate_beta_identity(s, c.config, actor_principal_id=c.owner_id,
                                       clerk_subject=c.applicant.subject, evidence_ref="invented:revoked")
    with pytest.raises(access.PracticeAccessError, match="practice_access_denied"):
        request(c)
    with pytest.raises(admin.BetaIdentityAdminError):
        invoke(c, access.decide, c.owner, decision(row))
    with c.factory() as s:
        assert s.get(PracticeAccessRequest, row["request_id"]).state == "pending"
        assert not s.scalar(select(ExternalIdentity).where(ExternalIdentity.subject == c.applicant.subject)).active


def test_expired_cancelled_and_declined_requests_do_not_grant_access(case, monkeypatch):
    c = case
    row = request(c)
    cancel = ReviewAccess(request_id=row["request_id"], review_sha256=row["review_sha256"], confirm=True)
    assert invoke(c, access.cancel, command=cancel)["state"] == "cancelled"
    assert invoke(c, access.cancel, command=cancel)["state"] == "cancelled"
    with pytest.raises(access.PracticeAccessError):
        invoke(c, access.decide, c.owner, decision(row))
    row = request(c)
    assert invoke(c, access.decide, c.owner, decision(row, decision="decline"))["request"]["state"] == "declined"
    assert invoke(c, access.status)["state"] == "declined"
    row = request(c)
    with c.factory() as s:
        deadline = s.get(PracticeAccessRequest, row["request_id"]).expires_at
    monkeypatch.setattr(access, "_now", lambda s: deadline)
    assert invoke(c, access.status)["state"] == "expired"
    with pytest.raises(access.PracticeAccessError):
        invoke(c, access.decide, c.owner, decision(row))
    assert count(c, Principal) == 1


def test_concurrent_submits_and_approvals_create_one_binding(case):
    c = case
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda _: request(c), range(3)))
    assert rows[0] == rows[1] == rows[2] and count(c, PracticeAccessRequest) == 1
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: invoke(c, access.decide, c.owner, decision(rows[0])), range(3)))
    assert results[0] == results[1] == results[2]
    assert count(c, ExternalIdentity) == 2
    with c.factory() as s:
        assert s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "practice_access.approved")) == 1


def test_late_verification_failure_rolls_back_decision_and_binding(case):
    c = case
    row = request(c)
    calls = []
    def fence():
        calls.append(True)
        if len(calls) == 2:
            raise AccessDenied("invented revoked session")
    with pytest.raises(AccessDenied):
        invoke(c, access.decide, c.owner, decision(row), fence=fence)
    assert count(c, ExternalIdentity) == 1
    assert invoke(c, access.status)["state"] == "pending"


def test_cached_owner_authority_is_refreshed_after_ownership_changes(case):
    c = case
    row = request(c)
    with c.factory() as cached:
        owner = cached.get(Principal, c.owner_id)
        assert owner.is_owner
        with c.factory() as other:
            other.get(Principal, c.owner_id).is_owner = False
            other.commit()
        with pytest.raises(access.PracticeAccessError, match="practice_access_denied"):
            access.decide(cached, c.config, c.owner, decision(row), fence=lambda: None)
    assert count(c, ExternalIdentity) == 1


def test_changed_saved_request_cannot_be_approved(case):
    c = case
    row = request(c)
    with c.factory() as s:
        s.get(PracticeAccessRequest, row["request_id"]).display_name = "Changed invented name"
        s.commit()
    with pytest.raises(access.PracticeAccessError, match="practice_access_conflict"):
        invoke(c, access.decide, c.owner, decision(row))
    assert count(c, ExternalIdentity) == 1


def test_real_signed_http_request_owner_decision_and_recovery(case):
    c = case
    checked, token = verifier(c)
    app = FastAPI()
    register(app, runtime=lambda: c.config, verifier=lambda _origins: checked, session_factory=c.factory)
    def headers(member):
        return {"Authorization": "Bearer " + token(member), "X-Cosmas-Practice-Access-Contract": "1"}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            h = headers(c.applicant)
            response = await client.get("/practice-access", headers=h)
            assert response.status_code == 200 and response.json()["state"] == "request_required"
            assert response.headers["cache-control"] == "no-store"
            response = await client.post("/practice-access/request", headers=h,
                json={"idempotency_key": str(uuid4()), "display_name": "Invented HTTP teammate"})
            assert response.status_code == 200, response.text
            row = response.json()["request"]
            assert (await client.get("/practice-access/requests", headers=h)).status_code == 403
            owner = headers(c.owner)
            response = await client.post("/practice-access/decide", headers=owner,
                                        json=decision(row).model_dump(mode="json"))
            assert response.status_code == 200, response.text
            assert (await client.get("/practice-access", headers=h)).json()["state"] == "connected"
            bad = {**h, "Authorization": "Bearer " + token(c.applicant, org_id="org_other")}
            assert (await client.get("/practice-access", headers=bad)).status_code == 403
            bad = {**h, "Authorization": "Bearer invalid"}
            assert (await client.get("/practice-access", headers=bad)).status_code == 401
            assert (await client.get("/practice-access?subject=outside", headers=h)).status_code == 422
            assert (await client.post("/practice-access/request", headers=h,
                json={"idempotency_key": str(uuid4()), "display_name": "Name", "subject": c.owner.subject})).status_code == 422
    asyncio.run(exercise())

# Invitation links are synthetic credentials, never identity-matching codes.


def invite_command(**changes):
    return CreateInvitation(idempotency_key=uuid4(), label="Invented onboarding", token=uuid4().hex + uuid4().hex,
                            expires_in_hours=72, **changes)


def test_invitation_exact_recovery_hash_only_storage_and_reviewed_join(case):
    c, command = case, invite_command()
    absent = invoke(c, invites.resolve_create, c.owner, command)
    assert absent == {"contract_version": 1, "outcome": "not_found", "invitation": None}
    first = invoke(c, invites.create, c.owner, command)
    assert first == invoke(c, invites.create, c.owner, command)
    resolved = invoke(c, invites.resolve_create, c.owner, command)
    assert resolved["outcome"] == "recorded" and resolved["invitation"] == first["invitation"]
    assert command.token not in json.dumps(first)
    assert command.token not in json.dumps(invoke(c, invites.list_invitations, c.owner))
    with c.factory() as s:
        row = s.get(PracticeInvitation, first["invitation"]["invitation_id"])
        assert row.token_sha256 == sha256(command.token.encode()).hexdigest()
        assert command.token not in json.dumps({column.key: str(getattr(row, column.key)) for column in row.__table__.columns})
    join = JoinInvitation(idempotency_key=uuid4(), display_name="Invented invited teammate", token=command.token)
    result = invoke(c, invites.join, command=join)
    assert result == invoke(c, invites.join, command=join)
    assert result["state"] == "pending" and count(c, Principal) == 1 and count(c, ExternalIdentity) == 1
    assert count(c, PracticeInviteUse) == 1
    assert invoke(c, invites.list_invitations, c.owner)["invitations"][0]["requests"] == 1
    invoke(c, access.decide, c.owner, decision(result["request"]))
    assert invoke(c, access.status)["state"] == "connected" and count(c, ExternalIdentity) == 2


def test_invitation_scope_non_owner_wrong_org_expiry_revocation_and_no_grant(case, monkeypatch):
    c, command = case, invite_command()
    with pytest.raises(access.PracticeAccessError, match="practice_access_denied"):
        invoke(c, invites.create, command=command)
    first = invoke(c, invites.create, c.owner, command)["invitation"]
    bad = access.VerifiedMember(c.config.beta_box_id, c.config.clerk_issuer, "org_invented_wrong", c.applicant.subject)
    join = JoinInvitation(idempotency_key=uuid4(), display_name="Invented teammate", token=command.token)
    with pytest.raises(access.PracticeAccessError):
        invoke(c, invites.join, bad, join)
    with c.factory() as s:
        expires = s.get(PracticeInvitation, first["invitation_id"]).expires_at
    with monkeypatch.context() as patch:
        patch.setattr(access, "_now", lambda s: expires)
        with pytest.raises(access.PracticeAccessError, match="practice_invitation_unavailable"):
            invoke(c, invites.join, command=join)
        assert invoke(c, invites.list_invitations, c.owner)["invitations"][0]["state"] == "expired"
    revoke = RevokeInvitation(idempotency_key=uuid4(), invitation_id=first["invitation_id"])
    assert invoke(c, invites.resolve_revoke, c.owner, revoke)["outcome"] == "not_found"
    changed = invoke(c, invites.revoke, c.owner, revoke)
    assert changed == invoke(c, invites.revoke, c.owner, revoke)
    assert invoke(c, invites.resolve_revoke, c.owner, revoke)["invitation"]["state"] == "revoked"
    with pytest.raises(access.PracticeAccessError, match="practice_invitation_unavailable"):
        invoke(c, invites.join, command=join)
    assert count(c, Principal) == 1 and count(c, PracticeAccessRequest) == 0 and count(c, PracticeInviteRevocation) == 1


def test_invitation_conflicting_retries_concurrent_create_and_late_authority_rollback(case):
    c, command = case, invite_command()
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda _: invoke(c, invites.create, c.owner, command), range(3)))
    assert rows[0] == rows[1] == rows[2] and count(c, PracticeInvitation) == 1
    for changed in [command.model_copy(update={"label": "Other invented label"}), command.model_copy(update={"token": "a"*64})]:
        with pytest.raises(access.PracticeAccessError, match="practice_access_conflict"):
            invoke(c, invites.create, c.owner, changed)
    same_token = command.model_copy(update={"idempotency_key": uuid4()})
    with pytest.raises(access.PracticeAccessError, match="practice_access_conflict"):
        invoke(c, invites.create, c.owner, same_token)
    calls = []
    def fence():
        calls.append(True)
        if len(calls) == 2:
            raise AccessDenied()
    with pytest.raises(AccessDenied):
        invoke(c, invites.create, c.owner, invite_command(), fence=fence)
    assert count(c, PracticeInvitation) == 1


@pytest.mark.parametrize("changes", [{"token": "matching-code"}, {"expires_in_hours": True}, {"expires_in_hours": 1}, {"expires_in_hours": 169}, {"label": "bad\nname"}, {"unexpected": True}])
def test_invitation_closed_bounded_requests(changes):
    from pydantic import ValidationError
    value = invite_command().model_dump(mode="json")
    with pytest.raises(ValidationError):
        CreateInvitation.model_validate({**value, **changes})


def test_signed_http_invitation_resolve_join_and_revoke(case):
    c = case
    checked, token = verifier(c)
    app = FastAPI()
    register(app, runtime=lambda: c.config, verifier=lambda _origins: checked, session_factory=c.factory)
    command = invite_command().model_dump(mode="json")
    def headers(member):
        return {"Authorization": "Bearer " + token(member), "X-Cosmas-Practice-Access-Contract": "1"}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            owner, applicant = headers(c.owner), headers(c.applicant)
            assert (await client.get('/practice-access/invitations', headers=applicant)).status_code == 403
            response = await client.post('/practice-access/invitation/create', json=command, headers=owner)
            assert response.status_code == 200, response.text
            assert response.headers['cache-control'] == 'no-store' and command['token'] not in response.text
            row = response.json()['invitation']
            assert (await client.post('/practice-access/invitation/create/resolve', json=command, headers=owner)).json()['outcome'] == 'recorded'
            join = {"idempotency_key": str(uuid4()), "display_name": "Invented invited HTTP member", "token": command['token']}
            result = await client.post('/practice-access/invitation/join', json=join, headers=applicant)
            assert result.status_code == 200 and result.json()['state'] == 'pending', result.text
            revoke = {"idempotency_key": str(uuid4()), "invitation_id": row['invitation_id']}
            assert (await client.post('/practice-access/invitation/revoke', json=revoke, headers=owner)).json()['invitation']['state'] == 'revoked'
            assert (await client.post('/practice-access/invitation/join', json=join, headers=applicant)).status_code == 409
            assert (await client.post('/practice-access/invitation/create?token=outside', json=command, headers=owner)).status_code == 422
    asyncio.run(exercise())
