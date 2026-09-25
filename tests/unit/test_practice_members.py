"""Actual PostgreSQL member lifecycle, existing writer and authenticated routes."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from tests.unit import test_practice_access as existing
from tests.unit.test_practice_access import decision, invoke, request, verifier

from cosmas_os.api.auth import AccessDenied, authenticate_request
from cosmas_os.api.practice_access_routes import register
from cosmas_os.api.practice_access_schemas import MemberChange, MembersPage, SubmitAccess
from cosmas_os.application import practice_access as access
from cosmas_os.application import practice_members as members
from cosmas_os.models import AuditEvent, ExternalIdentity, Principal

case = existing.case

def enrolled(c):
    row = request(c)
    invoke(c, access.decide, c.owner, decision(row))
    return next(row for row in page(c)["members"] if row["role"] == "member")


def page(c, after=None):
    return invoke(c, members.members, c.owner, MembersPage(after_id=after))


def command(row, **overrides):
    return MemberChange(idempotency_key=uuid4(), member_id=row["member_id"], action=row["action"],
        reviewed_at=row["reviewed_at"], review_sha256=row["review_sha256"], confirm=True).model_copy(update=overrides)


def selected(c, identity_id):
    return next(row for row in page(c)["members"] if row["member_id"] == identity_id)


def receipt_count(c):
    with c.factory() as s:
        return s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == members.RECORDED))


def test_existing_member_pause_restore_and_authentication(case):
    c = case
    row = enrolled(c)
    assert c.applicant.subject not in json.dumps(page(c))
    cmd = command(row)
    result = invoke(c, members.change, c.owner, cmd)
    assert result["receipt"]["recorded_state"] == "inactive" and result["replayed"] is False
    assert selected(c, row["member_id"])["action"] == "reactivate"
    with pytest.raises(access.PracticeAccessError, match="denied"):
        invoke(c, access.submit, command=SubmitAccess(idempotency_key=uuid4(), display_name="Cannot self-restore"))
    checked, token = verifier(c)
    with c.factory() as s, pytest.raises(AccessDenied):
        authenticate_request(s, c.config, authorization="Bearer " + token(c.applicant),
                             box_header=None, actor_header=None, verifier=checked)
    repeated = invoke(c, members.change, c.owner, cmd)
    assert repeated["replayed"] and repeated["receipt"] == result["receipt"] and receipt_count(c) == 1
    restore = command(selected(c, row["member_id"]))
    assert invoke(c, members.change, c.owner, restore)["receipt"]["recorded_state"] == "active"
    with c.factory() as s:
        assert authenticate_request(s, c.config, authorization="Bearer " + token(c.applicant),
                                    box_header=None, actor_header=None, verifier=checked).external_identity_id == row["member_id"]
        assert s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type.in_(
            ["external_identity.deactivated", "external_identity.reactivated"]))) == 2


def test_lost_reply_never_reapplies_a_change_after_later_access_changes(case):
    c = case
    row = enrolled(c)
    pause = command(row)
    first = invoke(c, members.change, c.owner, pause)
    restore = command(selected(c, row["member_id"]))
    second = invoke(c, members.change, c.owner, restore)
    assert invoke(c, members.change, c.owner, pause)["receipt"] == first["receipt"]
    assert selected(c, row["member_id"])["state"] == "active"
    with pytest.raises(access.PracticeAccessError, match="conflict"):
        invoke(c, members.change, c.owner, command(row))
    invoke(c, members.change, c.owner, command(selected(c, row["member_id"])))
    assert invoke(c, members.change, c.owner, restore)["receipt"] == second["receipt"]
    assert selected(c, row["member_id"])["state"] == "inactive" and receipt_count(c) == 3


def test_stale_cached_target_and_remapped_receipt_are_rejected(case):
    c = case
    row = enrolled(c)
    pause = command(row)
    with c.factory() as stale:
        binding = stale.get(ExternalIdentity, row["member_id"])
        stale.get(Principal, binding.principal_id)
        invoke(c, members.change, c.owner, pause)
        with pytest.raises(access.PracticeAccessError, match="conflict"):
            members.change(stale, c.config, c.owner, command(row), fence=lambda: None)
    with c.factory() as s:
        replacement = Principal(box_id=c.config.beta_box_id, principal_type="human", display_name="Replacement",
                                state="active", is_owner=False)
        s.add(replacement)
        s.flush()
        s.get(ExternalIdentity, row["member_id"]).principal_id = replacement.id
        s.commit()
    with pytest.raises(access.PracticeAccessError, match="conflict"):
        invoke(c, members.change, c.owner, pause)
    assert receipt_count(c) == 1


def test_commit_fence_rolls_back_real_flushed_state_and_both_audits(case):
    c = case
    row = enrolled(c)
    cmd = command(row)
    with c.factory() as s:
        def fence():
            if s.get(ExternalIdentity, row["member_id"]).active is False:
                assert s.scalar(select(AuditEvent.id).where(AuditEvent.id == str(cmd.idempotency_key))) is not None
                raise AccessDenied()
        with pytest.raises(AccessDenied):
            members.change(s, c.config, c.owner, cmd, fence=fence)
    assert selected(c, row["member_id"])["state"] == "active" and receipt_count(c) == 0
    with c.factory() as s:
        assert s.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.event_type == "external_identity.deactivated")) == 0


def test_owner_self_tombstone_and_nonowner_boundaries(case):
    c = case
    row = enrolled(c)
    own = next(item for item in page(c)["members"] if item["role"] == "owner")
    with pytest.raises(access.PracticeAccessError, match="conflict"):
        invoke(c, members.change, c.owner, command({**own, "action": "deactivate"}))
    with pytest.raises(access.PracticeAccessError, match="denied"):
        invoke(c, members.members, c.applicant, MembersPage(after_id=None))
    with pytest.raises(access.PracticeAccessError, match="denied"):
        invoke(c, members.change, c.applicant, command(row))
    with c.factory() as s:
        binding = s.get(ExternalIdentity, row["member_id"])
        principal = s.get(Principal, binding.principal_id)
        principal.state, principal.tombstoned_at = "tombstoned", datetime.now(UTC)
        binding.active = False
        s.commit()
    unavailable = selected(c, row["member_id"])
    assert unavailable["state"] == "unavailable" and unavailable["action"] is None
    with pytest.raises(access.PracticeAccessError, match="conflict"):
        invoke(c, members.change, c.owner, command({**unavailable, "action": "reactivate"}))
    assert receipt_count(c) == 0


def test_expired_review_is_not_a_write_and_completed_receipt_survives_expiry(case, monkeypatch):
    c = case
    row = enrolled(c)
    with c.factory() as s:
        binding, principal = members._target(s, c.owner, row["member_id"])
        expired = members._view(binding, principal, access._now(s) - timedelta(minutes=11), members._context(s, [principal.id]))
    with pytest.raises(access.PracticeAccessError, match="conflict"):
        invoke(c, members.change, c.owner, command(expired))
    assert receipt_count(c) == 0
    cmd = command(row)
    first = invoke(c, members.change, c.owner, cmd)
    monkeypatch.setattr(access, "_now", lambda _s: datetime.now(UTC) + timedelta(minutes=11))
    recovered = invoke(c, members.change, c.owner, cmd)
    assert recovered["replayed"] and recovered["receipt"] == first["receipt"]


def test_concurrent_same_key_commits_one_change(case):
    c = case
    row = enrolled(c)
    cmd = command(row)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: invoke(c, members.change, c.owner, cmd), range(4)))
    assert sum(not result["replayed"] for result in results) == 1
    assert all(result["receipt"] == results[0]["receipt"] for result in results)
    assert receipt_count(c) == 1


def test_receipt_tamper_and_nonce_reuse_cannot_change_access(case):
    c = case
    row = enrolled(c)
    cmd = command(row)
    invoke(c, members.change, c.owner, cmd)
    with pytest.raises(access.PracticeAccessError, match="conflict"):
        invoke(c, members.change, c.owner, command(selected(c, row["member_id"]), idempotency_key=cmd.idempotency_key))
    with c.factory() as s:
        audit = s.get(AuditEvent, str(cmd.idempotency_key))
        audit.payload_hash = "0" * 64
        s.commit()
    with pytest.raises(access.PracticeAccessError, match="unavailable"):
        invoke(c, members.change, c.owner, cmd)
    assert selected(c, row["member_id"])["state"] == "inactive" and receipt_count(c) == 1


def test_roster_keyset_pagination_never_omits_members_after_the_first_page(case):
    c = case
    with c.factory() as s:
        for i in range(102):
            person = Principal(box_id=c.config.beta_box_id, principal_type="human", display_name=f"Member {i}", state="active", is_owner=False)
            s.add(person)
            s.flush()
            s.add(ExternalIdentity(box_id=c.config.beta_box_id, principal_id=person.id, provider="clerk",
                issuer=c.config.clerk_issuer, organization_id=c.config.clerk_organization_id,
                subject=f"user_member_{i}", active=True, reviewed_by="invented", evidence_ref="invented:pagination"))
        s.commit()
    first = page(c)
    assert len(first["members"]) == 100 and first["next_after_id"] == first["members"][-1]["member_id"]
    second = page(c, first["next_after_id"])
    assert len(second["members"]) == 3 and second["next_after_id"] is None
    assert len({row["member_id"] for row in first["members"] + second["members"]}) == 103


def test_real_signed_http_member_routes_and_closed_commands(case):
    c = case
    row = enrolled(c)
    checked, token = verifier(c)
    app = FastAPI()
    register(app, runtime=lambda: c.config, verifier=lambda: checked, session_factory=c.factory)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": "Bearer " + token(c.owner), "X-Cosmas-Practice-Access-Contract": "1"}
            reply = await client.post("/practice-access/members", headers=headers, json={"after_id": None})
            assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store"
            current = next(item for item in reply.json()["members"] if item["member_id"] == row["member_id"])
            body = command(current).model_dump(mode="json")
            assert (await client.post("/practice-access/member-change", headers=headers, json={**body, "subject": c.applicant.subject})).status_code == 422
            reply = await client.post("/practice-access/member-change", headers=headers, json=body)
            assert reply.status_code == 200 and reply.json()["receipt"]["recorded_state"] == "inactive"
            assert c.applicant.subject not in reply.text
            headers["Authorization"] = "Bearer " + token(c.applicant)
            assert (await client.post("/practice-access/members", headers=headers, json={"after_id": None})).status_code == 403
    asyncio.run(scenario())
