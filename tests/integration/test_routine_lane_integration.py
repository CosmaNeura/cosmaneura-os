"""Actual signed API/PostgreSQL reports; Core prep and vendor outcomes are invented fixtures."""
import json
import os
from copy import deepcopy
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import select
from tests.integration.test_preparation_work import (
    approve,
    assign,
    create,
    ready,
    verify,
)
from tests.integration.test_preparation_work import (
    capture_case as capture_case,
)
from tests.integration.test_preparation_work import case as _prep_case
from tests.integration.test_routines import configuration
from tests.integration.test_vendor_work import bound, call, proposal, vendor_case

from cosmas_os.api import vendor_work_schemas as p
from cosmas_os.application import provider_team, routines, shared_work, vendor_shared, vendor_work
from cosmas_os.config import settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import EncounterWorkspace, PatientLink, RoutineRevision, RoutineRun

prep_case = _prep_case


def approved_vendor(f, c, label):
    request = proposal(c, share_to_practice=True, expected_outcome=label)
    created = call(f.session, c, vendor_work.propose, request)
    tid = created["effect"]["ticket_id"]
    detail = call(f.session, c, vendor_work.detail, tid)
    call(f.session, c, vendor_work.decide, tid, p.VendorDecision(
        **bound(detail, choice="approve", review_sha256=detail["review_sha256"])))
    return tid, call(f.session, c, vendor_work.detail, tid)


def vendor_result(f, c, tid, detail):
    result = call(f.session, c, vendor_work.record_result, tid, p.VendorResult(**bound(detail,
        observation_head=detail["summary"]["observation_head"],
        evidence_sha256=detail["summary"]["evidence_sha256"],
        disposition="verified_in_vendor", evidence="Invented manual outcome evidence; no service accessed.")))
    return result, call(f.session, c, vendor_work.detail, tid)


@pytest.fixture
def lanes(prep_case, monkeypatch):
    f = prep_case
    f.configuration.workspace_routines_enabled = True
    monkeypatch.setattr(routines, "settings", f.configuration)
    monkeypatch.setattr(settings, "vendor_work_enabled", True)
    ids = {}
    for label in ("prep_active", "prep_ready", "prep_closed"):
        revision = f.session.get(EncounterWorkspace, f.workspace["id"]).revision
        response, _ = create(f, idempotency_key=label, expected_entry_revision=revision,
                             body="Invented routine " + label)
        assert response.status_code == 200, response.text
        response, _ = approve(f, response.json()["item"])
        assert response.status_code == 200, response.text
        item = response.json()["item"]
        ids[label] = item["ticket_id"]
        if label == "prep_active":
            item, f.staff, f.staff_headers, f.staff_binding = assign(f, item)
        if label != "prep_active":
            response, _ = ready(f, item, idempotency_key=label + "_ready")
            assert response.status_code == 200, response.text
            if label == "prep_closed":
                response, _ = verify(f, response.json(), idempotency_key=label + "_verify")
                assert response.status_code == 200, response.text
    c = cast(Any, vendor_case).__wrapped__(f.session, {"box_id": f.box, "owner_id": f.actor})
    for label in ("vendor_active", "vendor_ready", "vendor_closed", "vendor_withdrawn", "vendor_superseded"):
        tid, detail = approved_vendor(f, c, "Invented routine " + label)
        ids[label] = tid
        if label in {"vendor_active", "vendor_superseded"}:
            vendor_shared.handoff(f.session, f.box, f.actor, tid, p.VendorHandoff(
                expected_version=detail["summary"]["version"], revision_id=detail["summary"]["revision_id"],
                payload_hash=detail["summary"]["payload_hash"], idempotency_key=str(uuid4()),
                kind="offer", recipient_id=f.staff))
            detail = call(f.session, c, vendor_work.detail, tid)
        if label in {"vendor_ready", "vendor_closed"}:
            result, detail = vendor_result(f, c, tid, detail)
            if label == "vendor_closed":
                call(f.session, c, vendor_work.verify, tid, p.VendorVerify(**bound(detail,
                    result_receipt_id=result["effect"]["receipt_id"],
                    result_receipt_sha256=result["effect"]["receipt_sha256"],
                    observation_head=detail["summary"]["observation_head"],
                    evidence_sha256=detail["summary"]["evidence_sha256"], reviewed_result=True,
                    reviewed_observations=True, outcome_confirmed=True, reviewed_conflicting_evidence=False)))
        elif label == "vendor_withdrawn":
            call(f.session, c, vendor_work.withdraw, tid, p.BoundCommand(**bound(detail)))
        elif label == "vendor_superseded":
            call(f.session, c, vendor_work.propose, proposal(c, message="Later private revision must stay withheld.",
                revises={"ticket_id": tid, "expected_version": detail["summary"]["version"],
                         "revision_id": detail["summary"]["revision_id"], "payload_hash": detail["summary"]["payload_hash"]}))
    provider_team.save(f.session, f.box, f.staff, expected=0, key="staff-routine-team",
                       configuration=provider_team.default_configuration())
    # Release the setup read lock before HTTP opens its own write transaction.
    f.session.commit()
    for headers in (f.headers, f.staff_headers):
        response = f.client.post("/provider-team/routines/chief", headers=headers, json={
            "expected_revision": 0, "team_revision": 1, "idempotency_key": "routine-lane-schedule",
            "configuration": configuration()})
        assert response.status_code == 200, response.text
    latest = f.session.scalar(select(RoutineRevision.created_at).where(RoutineRevision.box_id == f.box)
                              .order_by(RoutineRevision.created_at.desc()).limit(1))
    f.clock = [latest.astimezone(UTC).replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=1)]
    monkeypatch.setattr(routines, "_now", lambda _s: f.clock[0])
    f.ids, f.vendor = ids, c
    return f


def run(f, actor=None, headers=None):
    outcome = routines.run_once(f.session, f.box, actor or f.actor, "chief")
    assert outcome["status"] == "completed", outcome
    rid = cast(dict[str, Any], outcome["run"])["id"]
    response = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=headers or f.headers)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json(), rid


def export(name, value):
    root = Path(os.environ["ROUTINE_EVIDENCE_ROOT"])
    label = os.environ["ROUTINE_EVIDENCE_LABEL"]
    folder = root / ("evidence-" + label)
    folder.mkdir(exist_ok=True)
    with (folder / name).open("x") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write("\n")


def test_actual_signed_mixed_lane_report_contract(lanes):
    f = lanes
    source = shared_work.catalog(f.session, f.box, f.actor, vendor=True)["items"]
    report, rid = run(f)
    staff_report, _ = run(f, f.staff, f.staff_headers)
    saved = f.client.get("/provider-team/routines/chief", headers=f.headers).json()
    export("actual-routine-lanes.json", {"kind": "actual_signed_synthetic_postgresql", "ids": f.ids,
        "routine": saved, "report": report, "staff_report": staff_report,
        "source_states": [{"ticket_id": item["ticket_id"], "work_kind": item["work_kind"], "state": item["state"]} for item in source]})
    assert report["matching_items"] == 8
    assert report["counts"]["open"] == 4
    assert report["counts"]["verified_complete"] == 2
    assert staff_report["counts"]["open"] == 2
    assert staff_report["counts"]["verified_complete"] == 0
    by_id = {item["ticket_id"]: item for item in report["items"]}
    for label in ("vendor_withdrawn", "vendor_superseded"):
        assert not by_id[f.ids[label]]["human_completion"]
        assert not by_id[f.ids[label]]["ready_for_review"]
    assert by_id[f.ids["prep_ready"]]["ready_for_review"]
    assert by_id[f.ids["vendor_ready"]]["ready_for_review"]
    assert "Later private revision" not in json.dumps(report)
    assert "clinical source" not in json.dumps(report)
    row = f.session.get(RoutineRun, rid)
    assert payload_hash(row.snapshot) == row.snapshot_hash


def test_legacy_snapshot_keeps_exact_bytes_and_current_disclosure(lanes, monkeypatch):
    f = lanes
    original = routines._snapshot
    def legacy(*args):
        value = original(*args)
        for item in value["items"]:
            item.pop("work_kind", None)
            item.pop("ready_for_review", None)
        return value
    monkeypatch.setattr(routines, "_snapshot", legacy)
    report, rid = run(f)
    row = f.session.get(RoutineRun, rid)
    before, digest = deepcopy(row.snapshot), row.snapshot_hash
    assert report["counts"]["open"] == 4
    assert all("work_kind" not in item and "ready_for_review" not in item for item in report["items"])
    export("actual-legacy-routine.json", {"report": report})
    # Publishing a changed revision removes the prior owner projection from this
    # historical report; staff still require their own exact publication grant.
    tid = f.ids["vendor_superseded"]
    detail = call(f.session, f.vendor, vendor_work.detail, tid)
    call(f.session, f.vendor, vendor_work.decide, tid, p.VendorDecision(
        **bound(detail, choice="approve", review_sha256=detail["review_sha256"])))
    detail = call(f.session, f.vendor, vendor_work.detail, tid)
    call(f.session, f.vendor, vendor_work.publish, tid, p.VendorPublication(
        **bound(detail, review_sha256=detail["review_sha256"], share_to_practice=True)))
    response = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=f.headers)
    assert response.status_code == 200, response.text
    revised = response.json()
    assert revised["withheld_sources"] and tid not in {item["ticket_id"] for item in revised["items"]}
    link = f.session.get(PatientLink, f.patient_link_id)
    link.revoked_at = f.clock[0]
    f.session.commit()
    response = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=f.headers)
    assert response.status_code == 200, response.text
    withheld = response.json()
    assert not ({f.ids[n] for n in ("prep_active", "prep_ready", "prep_closed")} & {item["ticket_id"] for item in withheld["items"]})
    assert withheld["withheld_sources"]
    f.session.refresh(row)
    assert row.snapshot == before and row.snapshot_hash == digest == payload_hash(before)
    export("actual-withheld-routine.json", {"report": withheld})
    f.binding.active = False
    f.session.commit()
    denied = f.client.get("/provider-team/routines/chief/runs/" + rid, headers=f.headers)
    assert denied.status_code == 403 and "items" not in denied.json()
    export("actual-revoked-routine.json", {"status": denied.status_code, "body": denied.json()})


def test_withdrawn_vendor_result_is_neither_ready_nor_complete(lanes):
    f = lanes
    tid, detail = approved_vendor(f, f.vendor, "Invented routine withdrawn with result")
    _, detail = vendor_result(f, f.vendor, tid, detail)
    call(f.session, f.vendor, vendor_work.withdraw, tid, p.BoundCommand(**bound(detail)))
    source = shared_work.read(f.session, f.box, f.actor, tid, vendor=True)
    # The shared source retains prior result evidence after withdrawal; the
    # routine must not turn that evidence into active review or completion.
    assert source["state"] == "withdrawn" and source["ready_for_review"]
    report, _ = run(f)
    item = next(item for item in report["items"] if item["ticket_id"] == tid)
    assert item["state"] == "withdrawn" and not item["ready_for_review"] and not item["human_completion"]
    assert report["counts"]["open"] == 4 and report["counts"]["verified_complete"] == 2
    export("actual-withdrawn-result-routine.json", {"report": report, "withdrawn_ticket_id": tid})
