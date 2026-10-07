"""Real PostgreSQL/JWT setup qualification; invented identities only."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker
from tests.unit.test_practice_access import verifier

from cosmas_os.api.practice_access_routes import register
from cosmas_os.api.practice_access_schemas import CompletePracticeSetup
from cosmas_os.application import practice_access as access
from cosmas_os.application import practice_setup as setup
from cosmas_os.application.beta_bootstrap import BetaBootstrapError, BetaBootstrapManifest
from cosmas_os.config import Settings
from cosmas_os.db import Base
from cosmas_os.models import AuditEvent, BoxContext, ExternalIdentity, Principal
from cosmas_os.practice_access_models import PracticeAccessRequest
from cosmas_os.practice_setup_models import PracticeOwnerReservation, PracticeSetupProfile


@pytest.fixture
def solo(engine):
    schema = "solo_setup_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA "' + schema + '"'))
    isolated = create_engine(engine.url, connect_args={"options": "-c search_path=" + schema})
    Base.metadata.create_all(isolated, tables=[BoxContext.__table__, Principal.__table__,
        ExternalIdentity.__table__, AuditEvent.__table__, PracticeAccessRequest.__table__,
        PracticeOwnerReservation.__table__, PracticeSetupProfile.__table__])
    values = json.loads((Path(__file__).parents[1] / "fixtures/hosted-workspace-settings.json").read_text())
    values["beta_box_id"] = str(uuid4())
    runtime = Settings(_env_file=None, **values)
    manifest = BetaBootstrapManifest(schema_version="cosmas-os/d3-beta-bootstrap/v1",
        box_id=runtime.beta_box_id, clinic_display_name="Invented reserved practice",
        owner_display_name="Invented clinician", clerk_issuer=runtime.clerk_issuer,
        clerk_subject="user_invented_solo_owner", clerk_organization_id=runtime.clerk_organization_id,
        reviewed_by="Invented deployer", evidence_ref=runtime.human_deploy_evidence_ref)
    factory = sessionmaker(isolated, autoflush=False)
    member = access.VerifiedMember(runtime.beta_box_id, runtime.clerk_issuer,
        runtime.clerk_organization_id, manifest.clerk_subject)
    command = CompletePracticeSetup(idempotency_key=uuid4(), practice_name="Invented solo practice",
        display_name="Invented clinician", specialty=None, confirm=True)
    try:
        yield SimpleNamespace(factory=factory, runtime=runtime, manifest=manifest, member=member, command=command)
    finally:
        isolated.dispose()
        with engine.begin() as connection:
            connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))


def invoke(case, operation, member=None, command=None, fence=lambda: None):
    with case.factory() as session:
        return operation(session, case.runtime, member or case.member,
            *([] if command is None else [command]), fence=fence)


def reserve(case):
    with case.factory() as session:
        setup.reserve_first_owner(session, case.runtime, case.manifest)


def test_reserved_owner_completes_without_another_approver_once(solo):
    reserve(solo)
    reserve(solo)
    assert invoke(solo, setup.status)["state"] == "solo_setup_available"
    assert invoke(solo, access.status)["state"] == "request_required"
    result = invoke(solo, setup.complete, command=solo.command)
    assert result["state"] == "owner_ready" and not result["can_start_practice"]
    assert result == invoke(solo, setup.complete, command=solo.command)
    assert invoke(solo, access.status)["role"] == "owner"
    with solo.factory() as session:
        assert session.scalar(select(func.count()).select_from(Principal)) == 1
        assert session.scalar(select(func.count()).select_from(ExternalIdentity)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
        assert session.get(BoxContext, solo.member.box_id).display_name == solo.manifest.clinic_display_name
        assert session.get(PracticeOwnerReservation, solo.member.box_id).consumed_at is not None


def test_unreserved_subject_cannot_claim_existing_practice_or_grant_itself_owner(solo):
    reserve(solo)
    other = access.VerifiedMember(solo.member.box_id, solo.member.issuer,
        solo.member.organization_id, "user_invented_other")
    assert invoke(solo, setup.status, other)["state"] == "join_existing"
    with pytest.raises(access.PracticeAccessError, match="practice_access_denied"):
        invoke(solo, setup.complete, other, solo.command)
    invoke(solo, setup.complete, command=solo.command)
    with pytest.raises(BetaBootstrapError, match="reservation differs"):
        with solo.factory() as session:
            setup.reserve_first_owner(session, solo.runtime,
                solo.manifest.model_copy(update={"clerk_subject": other.subject}))


def test_revocation_expiry_conflict_and_last_fence_do_not_create_owner(solo):
    reserve(solo)
    with solo.factory() as session:
        reservation = session.get(PracticeOwnerReservation, solo.member.box_id)
        reservation.expires_at = access._now(session) - timedelta(seconds=1)
        session.commit()
    assert not invoke(solo, setup.status)["can_start_practice"]
    with pytest.raises(access.PracticeAccessError):
        invoke(solo, setup.complete, command=solo.command)
    with solo.factory() as session:
        session.get(PracticeOwnerReservation, solo.member.box_id).expires_at = access._now(session) + timedelta(days=1)
        session.commit()
    calls = 0
    def fail_final_fence():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise access.PracticeAccessError("practice_access_denied", 403)
    with pytest.raises(access.PracticeAccessError):
        invoke(solo, setup.complete, command=solo.command, fence=fail_final_fence)
    assert invoke(solo, setup.status)["state"] == "solo_setup_available"
    invoke(solo, setup.complete, command=solo.command)
    with pytest.raises(access.PracticeAccessError, match="practice_access_conflict"):
        invoke(solo, setup.complete, command=solo.command.model_copy(update={"specialty": "Other"}))
    with solo.factory() as session:
        session.scalar(select(ExternalIdentity)).active = False
        session.commit()
    with pytest.raises(access.PracticeAccessError, match="practice_access_denied"):
        invoke(solo, setup.status)


def test_setup_http_contract_does_not_accept_identity_or_reservation_from_caller(solo):
    reserve(solo)
    app = FastAPI()
    checked, signed_token = verifier(SimpleNamespace(config=solo.runtime))
    register(app, runtime=lambda: solo.runtime, verifier=lambda origins: checked, session_factory=solo.factory)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": "Bearer " + signed_token(solo.member), "X-Cosmas-Practice-Access-Contract": "1"}
            assert (await client.get("/practice-access/setup", headers=headers)).json()["can_start_practice"]
            body = solo.command.model_dump(mode="json")
            assert (await client.post("/practice-access/setup/complete", headers=headers,
                json={**body, "is_owner": True})).status_code == 422
            first = await client.post("/practice-access/setup/complete", headers=headers, json=body)
            assert first.status_code == 200 and first.json()["state"] == "owner_ready"
            assert first.headers["cache-control"] == "no-store"
            assert (await client.get("/practice-access/setup", headers=headers)).json() == first.json()
            assert (await client.get("/practice-access/setup?subject=user_other", headers=headers)).status_code == 422
    asyncio.run(exercise())


def test_setup_confirmation_and_text_are_closed():
    values = {"idempotency_key": str(uuid4()), "practice_name": "Invented practice",
              "display_name": "Invented clinician", "specialty": None, "confirm": True}
    for changes in ({"confirm": 1}, {"confirm": False}, {"practice_name": " Bad "}, {"specialty": ""}):
        with pytest.raises(ValidationError):
            CompletePracticeSetup.model_validate({**values, **changes})
