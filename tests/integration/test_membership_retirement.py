"""Actual PG/HTTP exact negative admission; no service or membership action."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_membership_work import (
    OFF,
    POLICY,
    approve,
    bound,
    call,
    detail,
    proposal,
    result,
    verification,
)
from tests.integration.test_membership_work import (
    client as client,
)
from tests.integration.test_membership_work import (
    gates as gates,
)
from tests.integration.test_membership_work import (
    vendor_case as vendor_case,
)

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import membership_work_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.api.membership_retirement_schemas import MembershipRetire
from cosmas_os.application import membership_retirement as retirement
from cosmas_os.application import membership_work as flow
from cosmas_os.application import note_review as notes
from cosmas_os.application import services
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.membership_models import MembershipCommandRetirement, MembershipReceipt
from cosmas_os.models import Operation, Ticket


def envelope(c, kind, request):
    scope = {"box_id": c["box"], "owner_id": c["actor"], "workspace_id": c["wid"]}
    return MembershipRetire(
        command_kind=kind,
        request=request,
        request_sha256=schema.request_digest(kind, scope, request),
    )


def advance_note(s, c, old):
    changed = notes.save(
        s,
        c["box"],
        c["actor"],
        c["wid"],
        expected=old.expected_workspace_revision,
        key="retirement-note-" + str(uuid4()),
        base_note_id=old.source.note_id,
        source_reply_id=None,
        content="Invented current note after the local membership request was saved.",
    )["workspace"]
    n = changed["note"]["latest"]
    notes.review(
        s,
        c["box"],
        c["actor"],
        c["wid"],
        n["id"],
        expected=changed["revision"],
        key="retirement-review-" + str(uuid4()),
        content_hash=n["content_hash"],
        source_hash=n["source_fingerprint"],
    )


def test_stale_proposal_retirement_is_exact_terminal_and_fresh_request_works(
    client, session, vendor_case, tmp_path
):
    c = vendor_case
    root = f"/workspaces/{c['wid']}/membership-work"
    old_options = client.get(root + "/options").json()
    old = proposal(session, c)
    request = envelope(c, "propose", old)
    advance_note(session, c, old)
    rejected = client.post(root, json=old.public())
    assert (
        rejected.status_code == 409
        and rejected.json()["error"]["code"] == "membership_source_changed"
    )
    query = {
        "command_kind": "propose",
        "idempotency_key": old.idempotency_key,
        "request_sha256": request.request_sha256,
    }
    missing = client.post(root + "/resolve", json=query).json()
    assert missing["outcome"] == "not_found"
    response = client.post(root + "/retire", json=request.public())
    assert response.status_code == 200, response.text
    retired = response.json()
    assert retired["outcome"] == "retired" and retired["effect"] is None
    assert retired["retirement"]["reason"] == "membership_source_changed"
    assert client.post(root + "/resolve", json=query).json() == retired
    assert client.post(root + "/retire", json=request.public()).json() == retired
    assert client.post(root, json=old.public()).json() == retired
    row = session.scalar(
        select(MembershipCommandRetirement).where(
            MembershipCommandRetirement.workspace_id == c["wid"]
        )
    )
    assert row.request == old.public()
    fresh_options = client.get(root + "/options").json()
    fresh = proposal(session, c)
    accepted = client.post(root, json=fresh.public())
    assert accepted.status_code == 200 and accepted.json()["outcome"] == "recorded"
    assert client.post(root, json=old.public()).json() == retired
    assert (
        session.scalar(
            select(func.count())
            .select_from(Operation)
            .join(Ticket, Operation.ticket_id == Ticket.id)
            .where(Ticket.box_id == c["box"], Ticket.created_by_principal_id == c["actor"])
        )
        == 0
    )
    assert (
        session.scalar(
            select(func.count())
            .select_from(MembershipReceipt)
            .where(MembershipReceipt.workspace_id == c["wid"])
        )
        == 1
    )
    (tmp_path / "actual-membership-retirement-http.json").write_text(
        json.dumps(
            {
                "scope": old_options["scope"],
                "old_options": old_options,
                "old_request": old.public(),
                "retire_request": request.public(),
                "rejection": {"status": rejected.status_code, "body": rejected.json()},
                "missing": missing,
                "retired": retired,
                "resolved": client.post(root + "/resolve", json=query).json(),
                "late_original": client.post(root, json=old.public()).json(),
                "current_options": fresh_options,
                "fresh_request": fresh.public(),
                "fresh_receipt": accepted.json(),
                "external_operations_created": 0,
            },
            indent=2,
        )
        + "\n"
    )


def test_currently_admissible_or_unknown_request_cannot_be_retired(session, vendor_case):
    c = vendor_case
    original = proposal(session, c)
    with pytest.raises(WorkspaceError, match="membership_retirement_unavailable"):
        call(session, c, retirement.retire, envelope(c, "propose", original))
    assert (
        session.scalar(
            select(func.count())
            .select_from(MembershipCommandRetirement)
            .where(MembershipCommandRetirement.workspace_id == c["wid"])
        )
        == 0
    )
    receipt = call(session, c, flow.propose, original)
    assert call(session, c, retirement.retire, envelope(c, "propose", original)) == receipt
    assert (
        call(session, c, retirement.retire, envelope(c, "propose", original), policy=OFF) == receipt
    )


@pytest.mark.parametrize("kind", ["decide", "result", "verify", "withdraw"])
def test_bound_rejected_commands_retire_without_reversing_prior_effects(session, vendor_case, kind):
    c = vendor_case
    initial = call(session, c, flow.propose, proposal(session, c))
    tid = initial["effect"]["ticket_id"]
    if kind == "decide":
        d = detail(session, c, tid)
        old = schema.Decision(
            **bound(d),
            review_sha256=d["review_sha256"],
            choice="approve",
            reviewed_patient=True,
            reviewed_local_only_authority=True,
        )
        approve(session, c, tid)
    else:
        approve(session, c, tid)
        if kind == "verify":
            result(session, c, tid, disposition="needs_human")
            old = verification(session, c, tid)
        elif kind == "result":
            old = schema.Result(
                **bound(detail(session, c, tid)),
                disposition="local_preparation_ready",
                evidence="Invented old result.",
            )
            result(session, c, tid)
        else:
            old = schema.Withdraw(**bound(detail(session, c, tid)), confirm_withdraw=True)
            result(session, c, tid)
    before = detail(session, c, tid)
    with pytest.raises(WorkspaceError):
        call(session, c, flow.command, tid, kind, old)
    retired = call(session, c, retirement.retire, envelope(c, kind, old))
    assert retired["outcome"] == "retired"
    assert call(session, c, flow.command, tid, kind, old, policy=OFF) == retired
    assert detail(session, c, tid) == before
    assert (
        session.scalar(
            select(func.count())
            .select_from(Operation)
            .join(Ticket, Operation.ticket_id == Ticket.id)
            .where(Ticket.box_id == c["box"], Ticket.created_by_principal_id == c["actor"])
        )
        == 0
    )


def test_retirement_conflicts_privacy_and_atomic_final_authority(session, vendor_case):
    c = vendor_case
    old = proposal(session, c)
    advance_note(session, c, old)
    request = envelope(c, "propose", old)
    wrong = request.model_copy(update={"request_sha256": "a" * 64})
    with pytest.raises(WorkspaceError, match="membership_idempotency_conflict"):
        call(session, c, retirement.retire, wrong)

    fences = 0

    def reject():
        nonlocal fences
        fences += 1
        if fences >= 2:
            raise WorkspaceError("membership_unavailable", 503)

    with session.begin_nested() as tx:
        session.info["membership_final_authority"] = reject
        with pytest.raises(WorkspaceError, match="membership_unavailable"):
            call(session, c, retirement.retire, request)
        tx.rollback()
        session.info.pop("membership_final_authority")
    assert (
        session.scalar(
            select(func.count())
            .select_from(MembershipCommandRetirement)
            .where(MembershipCommandRetirement.workspace_id == c["wid"])
        )
        == 0
    )
    with pytest.raises(WorkspaceError, match="membership_work_unavailable"):
        retirement.retire(session, c["box"], str(uuid4()), c["wid"], request, policy=POLICY)
    retired = call(session, c, retirement.retire, request, policy=OFF)
    assert retired["outcome"] == "retired"
    modified = old.model_copy(update={"instructions": "Changed exact content."})
    with pytest.raises(WorkspaceError, match="membership_idempotency_conflict"):
        call(session, c, retirement.retire, envelope(c, "propose", modified))
    with session.begin_nested():
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    "UPDATE membership_command_retirements SET reason='membership_revision_changed' WHERE workspace_id=:wid"
                ),
                {"wid": c["wid"]},
            )
        session.rollback()


def sql_blocked(s, action, reason):
    with pytest.raises(DBAPIError, match=reason):
        with s.begin_nested():
            action()


def test_reciprocal_sql_fences_exact_proof_and_immutability(session, vendor_case):
    c = vendor_case
    old = proposal(session, c)
    advance_note(session, c, old)
    proof = call(session, c, retirement.retire, envelope(c, "propose", old))
    recorded = call(session, c, flow.propose, proposal(session, c))
    row = session.get(MembershipReceipt, recorded["effect"]["receipt_id"])
    raw = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    raw.update(id=str(uuid4()), idempotency_key=old.idempotency_key)
    sql_blocked(
        session,
        lambda: session.execute(insert(MembershipReceipt).values(**raw)),
        "retired membership command cannot be admitted",
    )
    retired = session.get(MembershipCommandRetirement, proof["retirement"]["receipt_id"])
    raw_retired = {
        column.name: getattr(retired, column.name) for column in retired.__table__.columns
    }
    raw_retired.update(
        id=str(uuid4()),
        idempotency_key=row.idempotency_key,
        request=row.request,
        request_sha256=row.request_sha256,
    )
    sql_blocked(
        session,
        lambda: session.execute(insert(MembershipCommandRetirement).values(**raw_retired)),
        "recorded membership command cannot be retired",
    )
    for statement in [
        "DELETE FROM membership_command_retirements WHERE id=:id",
        "UPDATE membership_command_retirements SET request_sha256=:hash WHERE id=:id",
    ]:
        sql_blocked(
            session,
            lambda statement=statement: session.execute(
                text(statement), {"id": retired.id, "hash": "0" * 64}
            ),
            "immutable",
        )
    forged = dict(raw_retired, id=str(uuid4()), idempotency_key="forged-retirement-key")
    sql_blocked(
        session,
        lambda: session.execute(insert(MembershipCommandRetirement).values(**forged)),
        "exact identity mismatch",
    )


@pytest.mark.parametrize("winner", ["original", "retire"])
def test_independent_transactions_serialize_admission_and_retirement(engine, tmp_path, winner):
    with Session(engine, expire_on_commit=False) as s:
        seeded = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented membership retirement race",
        )
        c = globals()["vendor_case"].__wrapped__(s, seeded)
        original = proposal(s, c)
        if winner == "retire":
            advance_note(s, c, original)
        s.commit()
    paused, release, second_started = Event(), Event(), Event()

    def apply(kind, first=False):
        with Session(engine, expire_on_commit=False) as s:
            if first:

                def fence():
                    paused.set()
                    assert release.wait(5)

                s.info["membership_final_authority"] = fence
            else:
                second_started.set()
            return (
                call(s, c, flow.propose, original)
                if kind == "original"
                else call(s, c, retirement.retire, envelope(c, "propose", original))
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, winner, True)
        assert paused.wait(5)
        second = pool.submit(apply, "original" if winner == "retire" else "retire")
        assert second_started.wait(5)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a == b and a["outcome"] == ("recorded" if winner == "original" else "retired")
    with Session(engine) as s:
        assert s.scalar(
            select(func.count())
            .select_from(MembershipCommandRetirement)
            .where(MembershipCommandRetirement.workspace_id == c["wid"])
        ) == (winner == "retire")
        assert s.scalar(
            select(func.count())
            .select_from(MembershipReceipt)
            .where(MembershipReceipt.workspace_id == c["wid"])
        ) == (winner == "original")


def test_retirement_route_rejects_unknown_kinds_extra_fields_and_oversize(
    client, session, vendor_case
):
    c = vendor_case
    path = f"/workspaces/{c['wid']}/membership-work/retire"
    q = envelope(c, "propose", proposal(session, c)).public()
    for body in [
        {**q, "command_kind": "submit"},
        {**q, "force": True},
        {**q, "command_kind": "withdraw"},
    ]:
        assert client.post(path, json=body).status_code == 400
    assert (
        client.post(
            path,
            content=b" " * 16385,
            headers={"Content-Type": "application/json", "Content-Length": "1"},
        ).status_code
        == 413
    )
    assert client.post(path + "?force=true", json=q).status_code == 426
    assert (
        session.scalar(
            select(func.count())
            .select_from(MembershipCommandRetirement)
            .where(MembershipCommandRetirement.workspace_id == c["wid"])
        )
        == 0
    )


def test_full_valid_unicode_request_fits_retirement_wrapper_and_oversize_original_is_rejected(
    client, session, vendor_case
):
    c = vendor_case
    original = proposal(session, c)
    advance_note(session, c, original)
    count = 2000
    while True:
        old = original.model_copy(update={"instructions": "🧪" * count})
        if len(public.canonical(old.public())) <= 8192:
            break
        count -= 1
    request = envelope(c, "propose", old)
    assert len(public.canonical(request.public())) > 8192
    root = f"/workspaces/{c['wid']}/membership-work"
    good = client.post(
        root + "/retire",
        content=public.canonical(request.public()),
        headers={"Content-Type": "application/json"},
    )
    assert good.status_code == 200 and good.json()["outcome"] == "retired", good.text
    saved = session.get(MembershipCommandRetirement, good.json()["retirement"]["receipt_id"])
    assert saved.request == old.public()
    excessive = original.model_copy(
        update={"idempotency_key": "retirement-large-" + str(uuid4()), "instructions": "🧪" * 2000}
    )
    assert len(public.canonical(excessive.public())) > 8192
    bad = client.post(
        root + "/retire",
        content=public.canonical(envelope(c, "propose", excessive).public()),
        headers={"Content-Type": "application/json"},
    )
    assert bad.status_code == 413 and bad.json()["error"]["code"] == "invalid_membership_request"
