"""Artifact intent/generation recovery against actual PostgreSQL and local files."""

import hashlib
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from cosmas_os.adapters.local import FakeNotifyAdapter, InjectableClock, LocalBlobAdapter
from cosmas_os.adapters.vendor_artifacts import LocalVendorArtifactStore
from cosmas_os.api import vendor_work_schemas as p
from cosmas_os.application import note_review as notes
from cosmas_os.application import services
from cosmas_os.application import vendor_artifacts as flow
from cosmas_os.application import workspace as ws
from cosmas_os.config import settings
from cosmas_os.db import make_session_factory
from cosmas_os.models import AppointmentObservation, PatientLink, Principal
from cosmas_os.vendor_models import VendorArtifact, VendorArtifactAttempt, VendorCommandReceipt

PDF = b"%PDF-1.7\nInvented W36 local custody fixture\n%%EOF"


@pytest.fixture(autouse=True)
def gates(monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)


def _case(session, seeded):
    box, owner = seeded["box_id"], seeded["owner_id"]
    link = PatientLink(box_id=box, source_pair_key=str(uuid4()), label="Invented artifact patient",
        state="confirmed", confirmed_by_principal_id=owner, attested_at=datetime.now(UTC))
    session.add(link)
    session.flush()
    visit = AppointmentObservation(box_id=box, patient_link_id=link.id, external_id=str(uuid4()),
        source="synthetic", start_at=datetime.now(UTC), patient_label="Invented artifact encounter")
    session.add(visit)
    session.commit()
    w = ws.create(session, box, owner, visit.id, "create-artifact-encounter")
    w = notes.save(session, box, owner, w["id"], expected=1, key="artifact-note-source",
        base_note_id=None, source_reply_id=None, content="Invented reviewed source.")["workspace"]
    n = w["note"]["latest"]
    notes.review(session, box, owner, w["id"], n["id"], expected=2, key="artifact-note-review",
        content_hash=n["content_hash"], source_hash=n["source_fingerprint"])
    return {"box": box, "owner": owner, "wid": w["id"], "link": link.id,
        "source": {"kind": "reviewed_note", "note_id": n["id"],
            "content_sha256": n["content_hash"], "source_fingerprint": n["source_fingerprint"]}}


@pytest.fixture
def artifact_case(session, seeded):
    return _case(session, seeded)


def call(s, c, function, *args, **kwargs):
    return function(s, c["box"], c["owner"], c["wid"], *args, **kwargs)


def request(c, **changes):
    return p.VendorArtifactIntent.model_validate({"artifact_id": str(uuid4()),
        "idempotency_key": "intent-" + str(uuid4()), "source": c["source"],
        "sha256": hashlib.sha256(PDF).hexdigest(), "byte_length": len(PDF),
        "media_type": "application/pdf", **changes})


def resolver(response):
    return p.VendorArtifactResolve(artifact_id=response["effect"]["artifact_id"],
        command_kind=response["command_kind"], idempotency_key=response["idempotency_key"],
        request_sha256=response["request_sha256"])


def claim(admission: flow.ContentAdmission) -> flow.ContentToken:
    assert admission.token is not None
    return admission.token


def admitted(s, c):
    initial = call(s, c, flow.intent, request(c))
    admission = call(s, c, flow.begin_content, initial["effect"]["artifact_id"], "content-" + str(uuid4()))
    assert claim(admission) is not None
    return initial, admission


def settle(s, admission, outcome):
    result = flow.settle_in_session(s, claim(admission), outcome)
    s.commit()
    return result


def assert_error(code, call):
    with pytest.raises(ws.WorkspaceError) as error:
        call()
    assert error.value.code == code


def test_content_inherits_outer_deadline_and_expiry_keeps_durable_intent(session, artifact_case, tmp_path):
    initial, admission = admitted(session, artifact_case)
    deadlines = []

    class RecordingLocal(LocalVendorArtifactStore):
        def put_verified(self, scope, data, *, deadline=None):
            deadlines.append(deadline)
            super().put_verified(scope, data, deadline=deadline)

    store = RecordingLocal(tmp_path / "deadline-custody")
    assert flow.write_content(store, claim(admission), PDF, deadline=time.monotonic() - 1) == "unknown"
    assert deadlines == []
    current = call(session, artifact_case, flow.resolve, resolver(initial))
    assert current["artifact"]["state"] == "receiving"
    deadline = time.monotonic() + 30
    assert flow.write_content(store, claim(admission), PDF, deadline=deadline) == "ready"
    assert deadlines == [deadline]
    settle(session, admission, "ready")
    assert call(session, artifact_case, flow.resolve, resolver(initial))["artifact"]["state"] == "ready"


def test_intent_is_durable_zero_io_and_exact_effect_has_fresh_metadata(session, artifact_case, tmp_path):
    c = artifact_case
    req = request(c)
    first = call(session, c, flow.intent, req)
    assert first["artifact"]["state"] == "empty" and first["artifact"]["generation"] == 0
    assert session.scalar(select(func.count()).select_from(VendorArtifactAttempt)
        .where(VendorArtifactAttempt.workspace_id == c["wid"])) == 0
    again = call(session, c, flow.intent, req)
    assert again["effect"] == first["effect"]
    admission = call(session, c, flow.begin_content, req.artifact_id, "write-artifact-exact")
    assert admission.response["outcome"] == "recorded"
    assert admission.response["artifact"]["state"] == "receiving"
    custody_root = tmp_path / "artifact-custody"
    assert not custody_root.exists()
    store = LocalVendorArtifactStore(custody_root)
    assert flow.write_content(store, claim(admission), PDF) == "ready"
    settle(session, admission, "ready")
    recovered = call(session, c, flow.resolve, resolver(first))
    assert recovered["effect"] == first["effect"]
    assert recovered["artifact"]["state"] == "ready"
    assert recovered["artifact"]["version"] > first["artifact"]["version"]


def test_repeated_exact_request_has_one_generation_and_new_key_cannot_take_over(session, artifact_case):
    c = artifact_case
    _, first = admitted(session, c)
    replay = call(session, c, flow.begin_content, claim(first).artifact_id, first.response["idempotency_key"])
    assert replay.token is None and replay.response["effect"] == first.response["effect"]
    assert session.scalar(select(func.count()).select_from(VendorArtifactAttempt)
        .where(VendorArtifactAttempt.workspace_id == c["wid"])) == 1
    assert_error("vendor_idempotency_conflict", lambda: call(session, c, flow.begin_content,
        claim(first).artifact_id, "different-write-key"))


def _store_then_exit(root, token):
    outcome = flow.write_content(LocalVendorArtifactStore(root), token, PDF)
    os._exit(77 if outcome == "ready" else 78)


def test_actual_process_loss_after_exclusive_storage_resumes_same_identity(session, artifact_case, tmp_path, monkeypatch):
    c = artifact_case
    _, first = admitted(session, c)
    child = multiprocessing.get_context("fork").Process(target=_store_then_exit, args=(str(tmp_path), claim(first)))
    child.start()
    child.join(timeout=10)
    if child.is_alive():
        child.kill()
        child.join()
        pytest.fail("artifact child did not reach the injected loss")
    assert child.exitcode == 77
    target = tmp_path.joinpath(*first.scope.storage_segments())
    inode = target.stat().st_ino
    before = call(session, c, flow.resolve, resolver(first.response))
    assert before["artifact"]["state"] == "receiving"
    later = flow.work._clock(session) + timedelta(seconds=100)
    monkeypatch.setattr(flow.work, "_clock", lambda _: later)
    second = call(session, c, flow.begin_content, claim(first).artifact_id, first.response["idempotency_key"])
    assert claim(second).generation == 2
    assert second.response["effect"] == first.response["effect"]
    assert flow.write_content(LocalVendorArtifactStore(tmp_path), claim(second), PDF) == "ready"
    settle(session, second, "ready")
    assert target.stat().st_ino == inode
    assert call(session, c, flow.resolve, resolver(first.response))["artifact"]["state"] == "ready"


def test_expired_old_generation_cannot_replace_newer_result(session, artifact_case, monkeypatch):
    c = artifact_case
    _, first = admitted(session, c)
    later = flow.work._clock(session) + timedelta(seconds=100)
    monkeypatch.setattr(flow.work, "_clock", lambda _: later)
    second = call(session, c, flow.begin_content, claim(first).artifact_id, first.response["idempotency_key"])
    assert settle(session, first, "stored_corrupt") == "already_settled"
    assert session.get(VendorArtifact, claim(first).artifact_id).state == "receiving"
    settle(session, second, "ready")
    assert settle(session, first, "ready") == "already_settled"
    assert session.get(VendorArtifact, claim(first).artifact_id).active_generation == 2


def test_expired_sole_generation_cannot_publish_late_success(session, artifact_case, monkeypatch):
    _, first = admitted(session, artifact_case)
    later = flow.work._clock(session) + timedelta(seconds=100)
    monkeypatch.setattr(flow.work, "_clock", lambda _: later)
    assert settle(session, first, "ready") == "expired"
    assert session.get(VendorArtifact, claim(first).artifact_id).state == "receiving"
    assert session.get(VendorArtifactAttempt, claim(first).attempt_id).state == "unknown"


def test_historical_local_intent_survives_new_note_but_new_intent_requires_current_review(session, artifact_case):
    c = artifact_case
    req = request(c)
    first = call(session, c, flow.intent, req)
    notes.save(session, c["box"], c["owner"], c["wid"], expected=3, key="new-artifact-source",
        base_note_id=c["source"]["note_id"], source_reply_id=None, content="New unreviewed source.")
    admission = call(session, c, flow.begin_content, req.artifact_id, "historical-local-write")
    assert claim(admission) is not None
    assert call(session, c, flow.intent, req)["effect"] == first["effect"]
    assert_error("vendor_source_changed", lambda: call(session, c, flow.intent, request(c)))


def test_disabled_feature_resolves_old_receipt_and_blocks_new_generation(session, artifact_case, monkeypatch):
    c = artifact_case
    first, admission = admitted(session, c)
    monkeypatch.setattr(settings, "vendor_work_enabled", False)
    assert call(session, c, flow.resolve, resolver(first))["effect"] == first["effect"]
    assert call(session, c, flow.begin_content, claim(admission).artifact_id,
        admission.response["idempotency_key"]).token is None
    later = flow.work._clock(session) + timedelta(seconds=100)
    monkeypatch.setattr(flow.work, "_clock", lambda _: later)
    assert_error("vendor_feature_disabled", lambda: call(session, c, flow.begin_content,
        claim(admission).artifact_id, admission.response["idempotency_key"]))


def test_revocation_allows_private_settlement_but_no_metadata_disclosure(session, artifact_case):
    c = artifact_case
    first, admission = admitted(session, c)
    actor = session.get(Principal, c["owner"])
    actor.state = "disabled"
    session.commit()
    settle(session, admission, "ready")
    assert session.get(VendorArtifact, claim(admission).artifact_id).state == "ready"
    assert_error("workspace_access_denied", lambda: call(session, c, flow.resolve, resolver(first)))


def test_bad_input_never_touches_store_or_quarantines_good_bytes(session, artifact_case, tmp_path):
    c = artifact_case
    _, admission = admitted(session, c)
    store = LocalVendorArtifactStore(tmp_path)
    assert flow.write_content(store, claim(admission), PDF) == "ready"
    assert flow.write_content(store, claim(admission), b"wrong input") == "input_invalid"
    assert store.read_verified(admission.scope) == PDF
    settle(session, admission, "input_invalid")
    assert session.get(VendorArtifact, claim(admission).artifact_id).state == "receiving"


def test_stored_corruption_is_quarantined_without_overwrite(session, artifact_case, tmp_path):
    _, admission = admitted(session, artifact_case)
    store = LocalVendorArtifactStore(tmp_path)
    target = tmp_path.joinpath(*admission.scope.storage_segments())
    target.parent.mkdir(parents=True)
    target.write_bytes(b"%PDF-different stored object")
    outcome = flow.write_content(store, claim(admission), PDF)
    assert outcome == "stored_corrupt"
    settle(session, admission, outcome)
    assert session.get(VendorArtifact, claim(admission).artifact_id).state == "quarantined"
    assert target.read_bytes() == b"%PDF-different stored object"


def test_preview_checks_full_bytes_current_access_and_deadline(session, artifact_case, tmp_path):
    c = artifact_case
    _, admission = admitted(session, c)
    store = LocalVendorArtifactStore(tmp_path)
    flow.write_content(store, claim(admission), PDF)
    settle(session, admission, "ready")
    token = call(session, c, flow.preview, claim(admission).artifact_id)
    assert call(session, c, flow.finish_preview, token, store.read_verified(token.scope),
        deadline=time.monotonic() + 60) == PDF
    assert_error("artifact_changed", lambda: call(session, c, flow.finish_preview,
        token, PDF[:-1], deadline=time.monotonic() + 60))
    assert_error("artifact_unavailable", lambda: call(session, c, flow.finish_preview,
        token, PDF, deadline=time.monotonic() - 1))
    session.get(PatientLink, c["link"]).revoked_at = datetime.now(UTC)
    session.commit()
    assert_error("encounter_unavailable", lambda: call(session, c, flow.finish_preview,
        token, PDF, deadline=time.monotonic() + 60))


def test_cross_kind_key_and_direct_identity_mutation_are_rejected(session, artifact_case):
    c = artifact_case
    req = request(c)
    call(session, c, flow.intent, req)
    assert_error("vendor_idempotency_conflict", lambda: call(session, c, flow.begin_content,
        req.artifact_id, req.idempotency_key))
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(text("UPDATE vendor_artifacts SET sha256=:sha, version=version+1 WHERE artifact_id=:aid"),
            {"sha": "f" * 64, "aid": req.artifact_id})
    assert session.scalar(select(func.count()).select_from(VendorCommandReceipt)
        .where(VendorCommandReceipt.workspace_id == c["wid"])) == 1


def test_preview_corruption_quarantines_only_same_version_and_never_promotes(session, artifact_case):
    c = artifact_case
    _, admission = admitted(session, c)
    assert_error("artifact_unavailable", lambda: call(session, c, flow.preview, claim(admission).artifact_id))
    settle(session, admission, "ready")
    token = call(session, c, flow.preview, claim(admission).artifact_id)
    assert flow.quarantine_in_session(session, token)
    session.commit()
    assert not flow.quarantine_in_session(session, token)
    assert session.get(VendorArtifact, claim(admission).artifact_id).state == "quarantined"
    assert_error("artifact_changed", lambda: call(session, c, flow.finish_preview,
        token, PDF, deadline=time.monotonic() + 60))


def test_actual_two_connection_admission_has_one_writer(engine, tmp_path):
    """A separate invented Box is committed and retained for real concurrent connections."""
    factory = make_session_factory(engine)
    with factory() as s:
        container = services.Container(s, clock=InjectableClock(datetime.now(UTC)),
            blob=LocalBlobAdapter(tmp_path / "race-seed"), notify=FakeNotifyAdapter())
        case = _case(s, services.provision_box(container, "Invented artifact concurrency"))
        initial = call(s, case, flow.intent, request(case))
    aid = initial["effect"]["artifact_id"]
    barrier = threading.Barrier(2)

    def admit():
        with factory() as s:
            barrier.wait(timeout=5)
            result = call(s, case, flow.begin_content, aid, "concurrent-exact-write")
            assert not s.in_transaction()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(admit) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert sum(result.token is not None for result in results) == 1
    assert results[0].response["effect"] == results[1].response["effect"]
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(VendorArtifactAttempt)
            .where(VendorArtifactAttempt.artifact_id == aid)) == 1


@pytest.mark.parametrize("kind", ["intent", "content"])
def test_final_identity_fence_prevents_admission_commit(session, artifact_case, kind):
    c = artifact_case
    req = request(c)
    if kind == "content":
        call(session, c, flow.intent, req)

    def expired_identity():
        raise ws.WorkspaceError("workspace_access_denied", 403)

    session.info["vendor_final_authority"] = expired_identity
    try:
        if kind == "intent":
            assert_error("workspace_access_denied", lambda: call(session, c, flow.intent, req))
        else:
            assert_error("workspace_access_denied", lambda: call(session, c, flow.begin_content,
                req.artifact_id, "expired-identity-write"))
        session.rollback()
        assert session.scalar(select(func.count()).select_from(VendorArtifactAttempt)
            .where(VendorArtifactAttempt.artifact_id == req.artifact_id)) == 0
        if kind == "intent":
            assert session.get(VendorArtifact, req.artifact_id) is None
        else:
            assert session.get(VendorArtifact, req.artifact_id).state == "empty"
    finally:
        session.info.pop("vendor_final_authority", None)
