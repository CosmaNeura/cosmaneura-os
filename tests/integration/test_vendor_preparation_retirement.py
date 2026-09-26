"""Unadmitted preparation recovery with real API/SQL receipts and custody fences."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session
from tests.integration.test_vendor_retirement import blocked, row_copy
from tests.integration.test_vendor_work import call, immediate, proposal
from tests.integration.test_vendor_work import gates as gates
from tests.integration.test_vendor_work import vendor_case as vendor_case
from tests.integration.test_vendor_work_api import headers, root

from cosmas_os.adapters.local import LocalBlobAdapter
from cosmas_os.api import app as api
from cosmas_os.api import vendor_retirement_schemas as schema
from cosmas_os.api import vendor_work_schemas as public
from cosmas_os.application import note_review, services, vendor_artifacts, vendor_retirement
from cosmas_os.application import vendor_preparation_retirement as flow
from cosmas_os.application import vendor_work as work
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.vendor_models import VendorArtifact, VendorArtifactAttempt, VendorCommandReceipt
from cosmas_os.vendor_retirement_models import VendorCommandRetirement, VendorPreparationRetirement

PDF = b"%PDF-1.7\nInvented preparation retirement document\n%%EOF"
KINDS = ["propose", "artifact_intent", "artifact_content"]


@pytest.fixture
def client(session):
    # Every HTTP request owns its Session, as the production dependency does.
    # Share only the isolated test connection, not a previous request's budget.
    def request_session():
        with Session(bind=session.get_bind(), join_transaction_mode="create_savepoint") as request:
            yield request
    api.app.dependency_overrides[api.get_session] = request_session
    try:
        with TestClient(api.app) as client:
            yield client
    finally:
        api.app.dependency_overrides.clear()


def original(s, c, kind):
    if kind == "propose":
        return proposal(c)
    q = public.VendorArtifactIntent(artifact_id=str(uuid4()), idempotency_key="intent-" + str(uuid4()),
        source=c["source"], sha256=hashlib.sha256(PDF).hexdigest(), byte_length=len(PDF),
        media_type="application/pdf")
    if kind == "artifact_intent":
        return q
    saved = call(s, c, vendor_artifacts.intent, q)
    return public.VendorArtifactContent(artifact_id=q.artifact_id,
        intent_sha256=saved["request_sha256"], idempotency_key="content-" + str(uuid4()),
        sha256=q.sha256, byte_length=q.byte_length, media_type=q.media_type)


def retirement(c, kind, q):
    return schema.VendorPreparationRetire(command_kind=kind, request=q,
        request_sha256=public.request_digest(kind, {"kind": "workspace", "id": c["wid"]}, q))


def resolve_body(c, kind, q):
    return {"command_kind": kind, "idempotency_key": q.idempotency_key,
        "request_sha256": retirement(c, kind, q).request_sha256,
        **({} if kind == "propose" else {"artifact_id": q.artifact_id})}


def invoke(s, c, kind, q):
    if kind == "propose":
        return call(s, c, work.propose, q)
    if kind == "artifact_intent":
        return call(s, c, vendor_artifacts.intent, q)
    return call(s, c, vendor_artifacts.begin_content, q.artifact_id, q.idempotency_key).response


def http_original(client, c, kind, q):
    if kind == "propose":
        return client.post(root(c), headers=headers(c), json=q.public())
    url = f"/workspaces/{c['wid']}/vendor-artifacts"
    if kind == "artifact_intent":
        return client.post(url, headers=headers(c), json=q.public())
    return client.put(url + f"/{q.artifact_id}/content", content=PDF,
        headers={**headers(c), "Content-Type": "application/pdf",
                 "X-Cosmas-Artifact-Write-Key": q.idempotency_key})


@pytest.mark.parametrize("kind", KINDS)
def test_actual_api_recovery_retires_without_work_and_old_request_cannot_admit(
    session, client, vendor_case, monkeypatch, tmp_path, kind
):
    c = vendor_case
    q = original(session, c, kind)
    # A changed note makes these two exact source requests permanently stale.
    if kind != "artifact_content":
        note_review.save(session, c["box"], c["actor"], c["wid"], expected=3,
            key="new-source-" + str(uuid4()), base_note_id=c["source"]["note_id"],
            source_reply_id=None, content="Invented corrected source requiring new review.")
        denied = http_original(client, c, kind, q)
        assert denied.status_code == 409 and denied.json()["error"]["code"] == "vendor_source_changed"
    request = retirement(c, kind, q)
    base = root(c) if kind == "propose" else f"/workspaces/{c['wid']}/vendor-artifacts"
    before = client.post(base + "/resolve", headers=headers(c), json=resolve_body(c, kind, q))
    assert before.status_code == 200 and before.json()["outcome"] == "not_found"
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    url = f"/workspaces/{c['wid']}/vendor-preparations/retire"
    saved = client.post(url, headers=headers(c), json=request.public())
    assert saved.status_code == 200, saved.text
    model = schema.PreparationCommandRetirementResponse if kind == "propose" else schema.PreparationArtifactRetirementResponse
    proof = model.model_validate(saved.json()).public()
    assert proof["outcome"] == "retired" and proof["effect"] is None
    assert saved.headers["cache-control"] == "no-store"
    resolved = client.post(base + "/resolve", headers=headers(c), json=resolve_body(c, kind, q))
    replay = http_original(client, c, kind, q)
    again = client.post(url, headers=headers(c), json=request.public())
    assert resolved.status_code == replay.status_code == again.status_code == 200
    assert resolved.json()["retirement"] == replay.json()["retirement"] == again.json()["retirement"] == proof["retirement"]
    assert session.scalar(select(func.count()).select_from(VendorCommandReceipt).where(
        VendorCommandReceipt.workspace_id == c["wid"], VendorCommandReceipt.idempotency_key == q.idempotency_key)) == 0
    assert session.scalar(select(func.count()).select_from(VendorArtifactAttempt).where(
        VendorArtifactAttempt.workspace_id == c["wid"])) == 0
    if kind == "artifact_content":
        artifact = session.get(VendorArtifact, q.artifact_id)
        assert artifact.state == "empty" and artifact.active_generation == 0
    immediate(session)
    (tmp_path / f"actual-preparation-{kind}.json").write_text(json.dumps({
        "request": request.public(), "not_found": before.json(), "retired": proof,
        "resolved": resolved.json(), "late_original": replay.json()}, indent=2) + "\n")


@pytest.mark.parametrize("kind", KINDS)
def test_admitted_original_wins_retirement_including_unfinished_content(session, vendor_case, monkeypatch, tmp_path, kind):
    c = vendor_case
    q = original(session, c, kind)
    admitted = invoke(session, c, kind, q)
    if kind == "artifact_content":
        attempts = [row_copy(row) for row in session.scalars(select(VendorArtifactAttempt).where(
            VendorArtifactAttempt.artifact_id == q.artifact_id))]
        assert len(attempts) == 1 and attempts[0]["completed_at"] is None
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    saved = call(session, c, flow.retire, retirement(c, kind, q))
    assert saved["outcome"] == "recorded" and saved["effect"] == admitted["effect"]
    assert session.scalar(select(func.count()).select_from(VendorPreparationRetirement).where(
        VendorPreparationRetirement.workspace_id == c["wid"])) == 0
    if kind == "artifact_content":
        (tmp_path / "actual-preparation-content-winner.json").write_text(json.dumps({
            "request": retirement(c, kind, q).public(), "recorded": saved}, indent=2) + "\n")
        assert saved["artifact"]["state"] == "receiving"
        assert [row_copy(row) for row in session.scalars(select(VendorArtifactAttempt).where(
            VendorArtifactAttempt.artifact_id == q.artifact_id))] == attempts


@pytest.mark.parametrize("kind", KINDS)
def test_exact_request_key_scope_and_final_authority_are_required(session, vendor_case, kind):
    c = vendor_case
    q = original(session, c, kind)
    r = retirement(c, kind, q)
    wrong = r.model_copy(update={"request_sha256": "f" * 64})
    with pytest.raises(ws.WorkspaceError, match="vendor_idempotency_conflict"):
        call(session, c, flow.retire, wrong)
    with pytest.raises(ws.WorkspaceError):
        flow.retire(session, c["box"], str(uuid4()), c["wid"], r)
    with pytest.raises(ws.WorkspaceError):
        flow.retire(session, c["box"], c["actor"], str(uuid4()), r)
    def lost():
        raise ws.WorkspaceError("vendor_work_unavailable", 403)
    session.info["vendor_final_authority"] = lost
    with pytest.raises(ws.WorkspaceError):
        call(session, c, flow.retire, r)
    session.rollback()
    session.info.pop("vendor_final_authority")
    assert session.scalar(select(func.count()).select_from(VendorPreparationRetirement).where(
        VendorPreparationRetirement.workspace_id == c["wid"])) == 0


@pytest.mark.parametrize("kind", KINDS)
def test_retired_key_and_digest_cannot_change_or_cross_command_kinds(session, vendor_case, kind):
    c = vendor_case
    q = original(session, c, kind)
    call(session, c, flow.retire, retirement(c, kind, q))
    changed = q.model_copy(update={"message": "Changed immutable request."}) if kind == "propose" else q.model_copy(update={"sha256": "e" * 64})
    with pytest.raises(ws.WorkspaceError, match="vendor_idempotency_conflict"):
        call(session, c, flow.retire, retirement(c, kind, changed))
    other = proposal(c, idempotency_key=q.idempotency_key)
    if kind == "propose":
        other = original(session, c, "artifact_intent").model_copy(update={"idempotency_key": q.idempotency_key})
    with pytest.raises(ws.WorkspaceError, match="vendor_idempotency_conflict"):
        invoke(session, c, "artifact_intent" if kind == "propose" else "propose", other)


def raw_retirement(c, kind, q):
    from datetime import UTC, datetime
    now, rid = datetime.now(UTC), str(uuid4())
    r = retirement(c, kind, q)
    meta = {"receipt_id": rid, "retired_at": public.timestamp(now)}
    sha = public.public_digest(flow.DOMAIN, {"scope": {"kind": "workspace", "id": c["wid"]},
        "command_kind": kind, "idempotency_key": q.idempotency_key,
        "request_sha256": r.request_sha256, "retirement": meta})
    return {"id": rid, "box_id": c["box"], "workspace_id": c["wid"], "owner_id": c["actor"],
        "actor_id": c["actor"], "command_kind": kind, "idempotency_key": q.idempotency_key,
        "request_sha256": r.request_sha256, "public_request": q.public(),
        "public_retirement": {**meta, "receipt_sha256": sha}, "receipt_sha256": sha, "retired_at": now}


@pytest.mark.parametrize("kind", KINDS)
def test_sql_immutable_proof_and_both_admission_directions(session, vendor_case, kind):
    c = vendor_case
    q = original(session, c, kind)
    saved = call(session, c, flow.retire, retirement(c, kind, q))
    for sql in ["DELETE FROM vendor_preparation_retirements WHERE id=:id",
                "UPDATE vendor_preparation_retirements SET request_sha256=:hash WHERE id=:id"]:
        blocked(session, lambda sql=sql: session.execute(text(sql), {
            "id": saved["retirement"]["receipt_id"], "hash": "0" * 64}), "immutable")
    next_q = original(session, c, kind)
    invoke(session, c, kind, next_q)
    immediate(session)
    admitted = session.scalar(select(VendorCommandReceipt).where(
        VendorCommandReceipt.workspace_id == c["wid"], VendorCommandReceipt.idempotency_key == next_q.idempotency_key))
    copy = row_copy(admitted)
    copy.update(id=str(uuid4()), idempotency_key=q.idempotency_key)
    blocked(session, lambda: session.execute(insert(VendorCommandReceipt).values(**copy)), "retired vendor preparation key")
    blocked(session, lambda: session.execute(insert(VendorPreparationRetirement).values(**raw_retirement(c, kind, next_q))), "admitted vendor preparation")
    if kind == "artifact_content":
        attempt = session.scalar(select(VendorArtifactAttempt).where(VendorArtifactAttempt.artifact_id == next_q.artifact_id))
        copy = row_copy(attempt)
        copy.update(id=str(uuid4()), idempotency_key=q.idempotency_key)
        blocked(session, lambda: session.execute(insert(VendorArtifactAttempt).values(**copy)), "retired vendor preparation key")


def test_existing_work_retirement_and_preparation_namespace_are_reciprocal(session, vendor_case):
    from tests.integration.test_vendor_retirement import retirement as work_retirement
    from tests.integration.test_vendor_work import bound
    c = vendor_case
    admitted = invoke(session, c, "propose", proposal(c))
    tid = admitted["effect"]["ticket_id"]
    d = call(session, c, work.detail, tid)
    decision = public.VendorDecision(**bound(d, review_sha256=d["review_sha256"], choice="approve"))
    call(session, c, vendor_retirement.retire, tid, work_retirement(c, decision, "decide"))
    q = proposal(c, idempotency_key=decision.idempotency_key)
    blocked(session, lambda: session.execute(insert(VendorPreparationRetirement).values(**raw_retirement(c, "propose", q))), "retirement key already reserved")
    q = proposal(c)
    call(session, c, flow.retire, retirement(c, "propose", q))
    # The legacy trigger must reject cross-kind reuse before its own exact-shape check.
    attempt = row_copy(session.scalar(select(VendorCommandRetirement).where(
        VendorCommandRetirement.workspace_id == c["wid"], VendorCommandRetirement.idempotency_key == decision.idempotency_key)))
    attempt["id"] = str(uuid4())
    attempt["idempotency_key"] = q.idempotency_key
    blocked(session, lambda: session.execute(insert(VendorCommandRetirement).values(**attempt)), "retired vendor preparation key")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("winner", ["original", "retire"])
def test_independent_transactions_serialize_admission_and_retirement(engine, tmp_path, kind, winner):
    with Session(engine, expire_on_commit=False) as s:
        seed = services.provision_box(services.Container(s, blob=LocalBlobAdapter(tmp_path / "seed")),
            "Invented preparation retirement race")
        c = globals()["vendor_case"].__wrapped__(s, seed)
        q = original(s, c, kind)
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
            return call(s, c, flow.retire, retirement(c, kind, q)) if action == "retire" else invoke(s, c, kind, q)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(apply, winner, True)
        assert paused.wait(5)
        second = pool.submit(apply, "retire" if winner == "original" else "original")
        assert second_started.wait(5)
        release.set()
        a, b = first.result(timeout=5), second.result(timeout=5)
    assert a["outcome"] == b["outcome"] == ("recorded" if winner == "original" else "retired")
    assert a.get("effect") == b.get("effect") and a.get("retirement") == b.get("retirement")


def test_api_closed_types_bounds_and_artifact_anchor(client, session, vendor_case):
    c = vendor_case
    url = f"/workspaces/{c['wid']}/vendor-preparations/retire"
    q = proposal(c, message="界" * 4000)
    body = retirement(c, "propose", q).public()
    assert len(public.canonical(body)) > 4096
    saved = client.post(url, headers=headers(c), json=body)
    assert saved.status_code == 200
    for change in [{"command_kind": "artifact_content"}, {"force": True}, {"request_sha256": "bad"}]:
        assert client.post(url, headers=headers(c), json={**body, **change}).status_code == 400
    h = headers(c)
    h.pop("X-Cosmas-Vendor-Contract")
    assert client.post(url, headers=h, json=body).status_code == 426
    assert client.post(url, headers={**headers(c), "Content-Type": "application/json"}, content=b" " * 33793).status_code == 413
    missing = public.VendorArtifactContent(artifact_id=str(uuid4()), idempotency_key="missing-content",
        intent_sha256="a" * 64, sha256=hashlib.sha256(PDF).hexdigest(), byte_length=len(PDF), media_type="application/pdf")
    assert client.post(url, headers=headers(c), json=retirement(c, "artifact_content", missing).public()).status_code == 404
    valid = original(session, c, "artifact_content")
    wrong = valid.model_copy(update={"intent_sha256": "b" * 64})
    assert client.post(url, headers=headers(c), json=retirement(c, "artifact_content", wrong).public()).status_code == 409
