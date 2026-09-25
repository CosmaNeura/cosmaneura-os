"""Exact rejected verification recovery, races and immutable no-admission proof."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_vendor_work import acceptance, approved, bound, call, immediate
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case
from tests.integration.test_vendor_work_api import client as client
from tests.integration.test_vendor_work_api import headers, root

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import vendor_retirement_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import services, vendor_execution, vendor_retirement
from cosmas_os.application import vendor_work as work
from cosmas_os.config import settings
from cosmas_os.vendor_models import VendorCommandReceipt
from cosmas_os.vendor_retirement_models import VendorCommandRetirement


def verification(s, c, tid, *, manual=False):
    d = call(s, c, work.detail, tid)
    result = call(
        s,
        c,
        work.record_result,
        tid,
        public.VendorResult(
            **bound(
                d,
                observation_head=d["summary"]["observation_head"],
                evidence_sha256=d["summary"]["evidence_sha256"],
                disposition="verified_in_vendor" if manual else "reported_success",
                evidence="Invented human reviewed the outcome.",
            )
        ),
    )
    d = call(s, c, work.detail, tid)
    request = public.VendorVerify(
        **bound(
            d,
            result_receipt_id=result["effect"]["receipt_id"],
            result_receipt_sha256=result["effect"]["receipt_sha256"],
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            reviewed_result=True,
            reviewed_observations=True,
            outcome_confirmed=True,
            reviewed_conflicting_evidence=False,
        )
    )
    return request, d


def ready(s, c, *, manual=False):
    tid, d = approved(s, c)
    _, invocation = call(s, c, vendor_execution.claim_submit, tid, public.BoundCommand(**bound(d)))
    vendor_execution.settle(s, invocation, observation=acceptance(invocation))
    request, d = verification(s, c, tid, manual=manual)
    return tid, request, d


def retirement(c, request, kind="verify"):
    return schema.VendorRetire(
        command_kind=kind,
        request=request,
        request_sha256=public.request_digest(
            kind, {"kind": "workspace", "id": c["wid"]}, request
        ),
    )


def test_actual_rejected_verification_retires_then_new_manual_result_can_complete(
    session, client, vendor_case, monkeypatch, tmp_path
):
    import json

    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, d = ready(session, c)
    url = root(c) + "/" + tid
    h = headers(c)
    assert d["availability"]["verify"] == {
        "allowed": False,
        "reason": "manual_verification_required",
    }
    denied = client.post(url + "/verify", headers=h, json=request.public())
    assert (
        denied.status_code == 409
        and denied.json()["error"]["code"] == "vendor_exception_unresolved"
    )
    retired_request = retirement(c, request)
    resolve = public.VendorResolve(
        command_kind="verify",
        idempotency_key=request.idempotency_key,
        request_sha256=retired_request.request_sha256,
    )
    assert (
        client.post(root(c) + "/resolve", headers=h, json=resolve.public()).json()["outcome"]
        == "not_found"
    )
    saved = client.post(url + "/retire", headers=h, json=retired_request.public())
    assert saved.status_code == 200, saved.text
    proof = schema.RetirementResponse.model_validate(saved.json()).public()
    assert proof["outcome"] == "retired"
    assert client.get(url, headers=h).json()["summary"] == d["summary"]
    replay = client.post(url + "/verify", headers=h, json=request.public())
    assert replay.status_code == 200 and replay.json()["retirement"] == proof["retirement"]
    resolved = client.post(root(c) + "/resolve", headers=h, json=resolve.public())
    assert resolved.json()["retirement"] == proof["retirement"]
    next_request, next_detail = verification(session, c, tid, manual=True)
    assert next_detail["availability"]["verify"] == {"allowed": True, "reason": "available"}
    completed = client.post(url + "/verify", headers=h, json=next_request.public())
    assert completed.status_code == 200 and completed.json()["outcome"] == "recorded"
    again = client.post(url + "/retire", headers=h, json=retired_request.public())
    assert again.json()["retirement"] == proof["retirement"]
    assert client.get(url, headers=h).json()["summary"]["state"] == "closed"
    immediate(session)
    (tmp_path / "actual-retirement-fixtures.json").write_text(
        json.dumps(
            {
                "request": retired_request.public(),
                "retired": proof,
                "resolved": resolved.json(),
                "late_verify": replay.json(),
                "manual_detail": next_detail,
                "completed": completed.json(),
            },
            indent=2,
        )
        + "\n"
    )


def test_recorded_original_wins_retirement_and_disabled_recovery_is_exact(
    session, vendor_case, monkeypatch
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, _ = ready(session, c, manual=True)
    saved = call(session, c, work.verify, tid, request)
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    monkeypatch.setattr(settings, "vendor_io_enabled", False)
    again = call(session, c, vendor_retirement.retire, tid, retirement(c, request))
    assert again["effect"] == saved["effect"] and again["outcome"] == "recorded"
    assert (
        session.scalar(
            select(VendorCommandRetirement).where(VendorCommandRetirement.workspace_id == c["wid"])
        )
        is None
    )


@pytest.mark.parametrize("changed", ["digest", "body", "ticket", "actor"])
def test_retirement_cannot_change_exact_command_or_scope(
    session, client, vendor_case, monkeypatch, changed
):
    from cosmas_os.models import Principal

    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, _ = ready(session, c)
    call(session, c, vendor_retirement.retire, tid, retirement(c, request))
    body = retirement(c, request).public()
    h = headers(c)
    if changed == "digest":
        body["request_sha256"] = "0" * 64
    elif changed == "body":
        body["request"]["reviewed_conflicting_evidence"] = True
    elif changed == "ticket":
        tid = str(uuid4())
    else:
        other = Principal(
            box_id=c["box"],
            principal_type="human",
            display_name="Invented colleague",
            state="active",
        )
        session.add(other)
        session.commit()
        h["X-Actor-Principal-Id"] = other.id
    response = client.post(root(c) + "/" + tid + "/retire", headers=h, json=body)
    assert response.status_code in {403, 404, 409}, response.text


def row_copy(row):
    return {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}


def blocked(s, action, reason):
    with s.begin_nested() as nested:
        with pytest.raises(DBAPIError) as caught:
            action()
            immediate(s)
        assert caught.value.orig.sqlstate in {"23514", "P0001"} and reason in str(caught.value.orig)
        nested.rollback()


def raw_retirement(c, tid, request):
    body = retirement(c, request)
    rid = str(uuid4())
    now = datetime.now(UTC)
    metadata = {
        "receipt_id": rid,
        "ticket_id": tid,
        "revision_id": request.revision_id,
        "operation_id": request.operation_id,
        "payload_hash": request.payload_hash,
        "retired_at": public.timestamp(now),
    }
    sha = public.public_digest(
        "cosmas-vendor-public-retirement.v1",
        {
            "scope": {"kind": "workspace", "id": c["wid"]},
            "command_kind": "verify",
            "idempotency_key": request.idempotency_key,
            "request_sha256": body.request_sha256,
            "retirement": metadata,
        },
    )
    return {
        "id": rid,
        "box_id": c["box"],
        "owner_id": c["actor"],
        "actor_id": c["actor"],
        "workspace_id": c["wid"],
        "ticket_id": tid,
        "action_revision_id": request.revision_id,
        "operation_id": request.operation_id,
        "payload_hash": request.payload_hash,
        "command_kind": "verify",
        "idempotency_key": request.idempotency_key,
        "public_request": request.public(),
        "request_sha256": body.request_sha256,
        "receipt_sha256": sha,
        "public_retirement": {**metadata, "receipt_sha256": sha},
        "retired_at": now,
    }


def test_sql_reciprocal_fences_and_immutable_retirement(session, vendor_case, monkeypatch):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, _ = ready(session, c)
    saved = call(session, c, vendor_retirement.retire, tid, retirement(c, request))
    immediate(session)
    original = session.scalar(
        select(VendorCommandReceipt).where(VendorCommandReceipt.ticket_id == tid)
    )
    attempted = row_copy(original)
    attempted["id"] = str(uuid4())
    attempted["idempotency_key"] = request.idempotency_key
    blocked(
        session,
        lambda: session.execute(insert(VendorCommandReceipt).values(**attempted)),
        "retired vendor command cannot be admitted",
    )
    retired_id = saved["retirement"]["receipt_id"]
    for sql in [
        "DELETE FROM vendor_command_retirements WHERE id=:id",
        "UPDATE vendor_command_retirements SET request_sha256=:hash WHERE id=:id",
    ]:
        blocked(
            session,
            lambda sql=sql: session.execute(text(sql), {"id": retired_id, "hash": "0" * 64}),
            "immutable",
        )
    next_request, _ = verification(session, c, tid, manual=True)
    call(session, c, work.verify, tid, next_request)
    immediate(session)
    attempted = raw_retirement(c, tid, next_request)
    blocked(
        session,
        lambda: session.execute(insert(VendorCommandRetirement).values(**attempted)),
        "recorded vendor command cannot be retired",
    )


@pytest.mark.parametrize("winner", ["verify", "retire"])
def test_independent_transactions_serialize_original_and_retirement(
    engine, tmp_path, monkeypatch, winner
):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(
            services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented retirement race",
        )
        c = globals()["vendor_case"].__wrapped__(s, seed)
        tid, request, _ = ready(s, c, manual=True)
        s.commit()
    paused, release, second_started = Event(), Event(), Event()

    def apply(kind, first=False):
        with Session(engine, expire_on_commit=False) as s:
            if first:

                def fence():
                    paused.set()
                    assert release.wait(5)

                s.info["vendor_final_authority"] = fence
            else:
                second_started.set()
            return (
                call(s, c, work.verify, tid, request)
                if kind == "verify"
                else call(s, c, vendor_retirement.retire, tid, retirement(c, request))
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, winner, True)
        assert paused.wait(5)
        second = pool.submit(apply, "retire" if winner == "verify" else "verify")
        assert second_started.wait(5)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a["outcome"] == b["outcome"] == ("recorded" if winner == "verify" else "retired")
    with Session(engine) as s:
        final = call(s, c, work.detail, tid)
        assert final["summary"]["state"] == ("closed" if winner == "verify" else "approved")


def test_disabled_feature_and_stale_version_can_retire_exact_owned_request(
    session, client, vendor_case, monkeypatch
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, _ = ready(session, c)
    newer, _ = verification(session, c, tid, manual=True)
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    monkeypatch.setattr(settings, "vendor_io_enabled", False)
    before = call(session, c, work.detail, tid)["summary"]
    result = client.post(
        root(c) + "/" + tid + "/retire", headers=headers(c), json=retirement(c, request).public()
    )
    assert result.status_code == 200 and result.json()["outcome"] == "retired"
    assert call(session, c, work.detail, tid)["summary"] == before
    assert call(session, c, work.verify, tid, request)["outcome"] == "retired"
    # A different key still requires a separately bound real verification.
    assert call(session, c, work.verify, tid, newer)["outcome"] == "recorded"


def test_retirement_kind_must_match_exact_request_and_bytes_are_bounded(
    session, client, vendor_case, monkeypatch
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, _ = ready(session, c)
    url = root(c) + "/" + tid + "/retire"
    h = headers(c)
    body = retirement(c, request).public()
    body["command_kind"] = "submit"
    assert client.post(url, headers=h, json=body).status_code == 400
    assert (
        client.post(
            url,
            headers={**h, "Content-Type": "application/json", "Content-Length": "1"},
            content=b" " * 4097,
        ).status_code
        == 413
    )
    assert (
        client.post(
            url, headers=h, json={**retirement(c, request).public(), "force": True}
        ).status_code
        == 400
    )
    assert (
        session.scalar(
            select(VendorCommandRetirement).where(VendorCommandRetirement.workspace_id == c["wid"])
        )
        is None
    )


def test_retirement_rolls_back_when_final_authority_is_lost(session, vendor_case, monkeypatch):
    from cosmas_os.application import workspace as ws

    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, d = ready(session, c)
    calls = 0

    def deny_second_fence():
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise ws.WorkspaceError("vendor_work_unavailable", 403)

    session.info["vendor_final_authority"] = deny_second_fence
    try:
        with pytest.raises(ws.WorkspaceError):
            call(session, c, vendor_retirement.retire, tid, retirement(c, request))
        session.rollback()
    finally:
        session.info.pop("vendor_final_authority", None)
    assert (
        session.scalar(
            select(VendorCommandRetirement).where(VendorCommandRetirement.workspace_id == c["wid"])
        )
        is None
    )
    assert call(session, c, work.detail, tid)["summary"] == d["summary"]


def test_retired_key_cannot_be_repurposed_for_another_command(session, vendor_case, monkeypatch):
    from cosmas_os.application import workspace as ws

    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, request, d = ready(session, c)
    call(session, c, vendor_retirement.retire, tid, retirement(c, request))
    result = public.VendorResult(
        **bound(
            d,
            idempotency_key=request.idempotency_key,
            observation_head=d["summary"]["observation_head"],
            evidence_sha256=d["summary"]["evidence_sha256"],
            disposition="verified_in_vendor",
            evidence="Invented different command using a retired key.",
        )
    )
    with pytest.raises(ws.WorkspaceError, match="vendor_idempotency_conflict"):
        call(session, c, work.record_result, tid, result)


@pytest.mark.parametrize("kind", ["decide", "submit"])
@pytest.mark.parametrize("winner", ["original", "retire"])
def test_decision_and_send_retirement_preserves_winning_exact_admission(
    session, vendor_case, monkeypatch, kind, winner
):
    c = vendor_case
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    tid, d = approved(session, c)
    # A rejection remains possible for an approved ticket only via retirement;
    # use a fresh proposal for the decision admission itself.
    if kind == "decide":
        from tests.integration.test_vendor_work import proposal
        tid = call(session, c, work.propose, proposal(c))["effect"]["ticket_id"]
        d = call(session, c, work.detail, tid)
    request = (public.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve"))
               if kind == "decide" else public.BoundCommand(**bound(d)))
    retire_request = retirement(c, request, kind)

    def original():
        if kind == "decide":
            return call(session, c, work.decide, tid, request), None
        return call(session, c, vendor_execution.claim_submit, tid, request)

    before = call(session, c, work.detail, tid)["summary"]
    if winner == "original":
        receipt, invocation = original()
        assert (invocation is not None) == (kind == "submit")
        retired = call(session, c, vendor_retirement.retire, tid, retire_request)
        assert retired["outcome"] == "recorded" and retired["effect"] == receipt["effect"]
    else:
        retired = call(session, c, vendor_retirement.retire, tid, retire_request)
        assert retired["outcome"] == "retired" and retired["command_kind"] == kind
        receipt, invocation = original()
        assert invocation is None and receipt["retirement"] == retired["retirement"]
        assert call(session, c, work.detail, tid)["summary"] == before
    assert call(session, c, vendor_retirement.retire, tid, retire_request)["outcome"] == retired["outcome"]
    resolved = call(session, c, work.resolve, public.VendorResolve(command_kind=kind,
        idempotency_key=request.idempotency_key, request_sha256=retire_request.request_sha256))
    assert resolved["outcome"] == retired["outcome"]
    immediate(session)


@pytest.mark.parametrize("kind", ["decide", "submit"])
@pytest.mark.parametrize("winner", ["original", "retire"])
def test_decision_and_send_race_with_retirement(engine, tmp_path, monkeypatch, kind, winner):
    from tests.integration.test_vendor_work import proposal
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    monkeypatch.setattr(settings, "vendor_io_enabled", True)
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
                                      "Invented command retirement race")
        c = globals()["vendor_case"].__wrapped__(s, seed)
        if kind == "decide":
            tid = call(s, c, work.propose, proposal(c))["effect"]["ticket_id"]
            d = call(s, c, work.detail, tid)
            request = public.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve"))
        else:
            tid, d = approved(s, c)
            request = public.BoundCommand(**bound(d))
        s.commit()
    paused, release, second_started = Event(), Event(), Event()
    def apply(action, first=False):
        with Session(engine, expire_on_commit=False) as s:
            if first:
                def fence():
                    paused.set()
                    assert release.wait(5)
                s.info["vendor_final_authority"] = fence
            else:
                second_started.set()
            if action == "retire":
                return call(s, c, vendor_retirement.retire, tid, retirement(c, request, kind))
            if kind == "decide":
                return call(s, c, work.decide, tid, request)
            return call(s, c, vendor_execution.claim_submit, tid, request)[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, winner, True)
        assert paused.wait(5)
        second = pool.submit(apply, "retire" if winner == "original" else "original")
        assert second_started.wait(5)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a["outcome"] == b["outcome"] == ("recorded" if winner == "original" else "retired")
    with Session(engine) as s:
        summary = call(s, c, work.detail, tid)["summary"]
        assert summary["submit_claimed"] == (kind == "submit" and winner == "original")
        if kind == "decide":
            assert summary["state"] == ("approved" if winner == "original" else "pending_approval")
