"""Signed private review and F-8 require the exact current capture-gap evidence."""

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from tests.integration.test_core_note_review import (
    capture_case,
    case,
    count,
    decide,
    link,
    post,
    proposal,
)

from cosmas_os.models import (
    FollowUpReceipt,
    Operation,
    WorkspaceCoreNoteSource,
    WorkspaceNoteReview,
)
from cosmas_os.ports.core_notes import CoreDraftReceipt, CoreDraftReference

__all__ = ["capture_case", "case"]
FIXTURE = Path(__file__).parents[1] / "fixtures/capture_gap_draft.json"


@pytest.fixture
def gap_case(case):
    f = case
    f.configuration.workspace_capture_source_enabled = True
    f.configuration.workspace_capture_corrections_enabled = True
    f.draft = json.loads(FIXTURE.read_text())["draft"]
    f.draft["session_id"] = str(f.port.saved.session_id)
    f.source = CoreDraftReference.from_draft(CoreDraftReceipt.model_validate(f.draft)).model_dump(
        mode="json"
    )
    return f


def linked(f):
    response = link(f)
    assert response.status_code == 200, response.text
    f.note = response.json()["workspace"]["note"]["latest"]
    f.review_body = {
        "expected_revision": 2,
        "idempotency_key": "gap-review",
        "content_hash": f.note["content_hash"],
        "source_fingerprint": f.note["source_fingerprint"],
        "gap_acknowledgment": {
            "acknowledged": True,
            "recovery_sha256": f.draft["capture_gap_review"]["recovery_sha256"],
        },
    }
    return f.note


def review(f, body=None):
    return post(f, f"/notes/{f.note['id']}/review", f.review_body if body is None else body)


def reviewed(f):
    linked(f)
    response = review(f)
    assert response.status_code == 200, response.text
    return response.json()["workspace"]


def test_gap_review_proposal_authorization_and_verified_completion(gap_case):
    f = gap_case
    state = reviewed(f)
    digest = f.draft["capture_gap_review"]["recovery_sha256"]
    assert state["note"]["latest"]["review"]["capture_gap_review_sha256"] == digest
    assert f.note["core_source"]["capture_gap_review"] == f.source["capture_gap_review"]
    assert review(f).status_code == 200 and link(f).status_code == 200
    with Session(f.engine) as session:
        source = session.get(WorkspaceCoreNoteSource, f.note["id"])
        assert source.capture_gap_review == f.source["capture_gap_review"]
    response = proposal(f)
    assert response.status_code == 200, response.text
    f.item = response.json()["workspace"]["follow_ups"][0]
    assert count(f, Operation) == 0
    response = decide(f)
    assert response.status_code == 200, response.text
    assert response.json()["workspace"]["follow_ups"][0]["state"] == "sent"
    assert decide(f).status_code == 200
    assert count(f, Operation) == count(f, FollowUpReceipt) == 1
    response = post(
        f,
        f"/follow-ups/{f.item['ticket_id']}/complete",
        {
            "revision_id": f.item["revision_id"],
            "payload_hash": f.item["payload_hash"],
            "idempotency_key": "gap-completion",
            "evidence": "Invented confirmation during rehearsal.",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["workspace"]["follow_ups"][0]["state"] == "closed"
    assert count(f, FollowUpReceipt) == 2


@pytest.mark.parametrize("fault", ["missing", "null", "false", "integer", "string", "hash"])
def test_only_explicit_exact_acknowledgment_can_review(gap_case, fault):
    f = gap_case
    linked(f)
    body = copy.deepcopy(f.review_body)
    if fault == "missing":
        del body["gap_acknowledgment"]
    elif fault == "null":
        body["gap_acknowledgment"] = None
    elif fault == "hash":
        body["gap_acknowledgment"]["recovery_sha256"] = "0" * 64
    else:
        body["gap_acknowledgment"]["acknowledged"] = {
            "false": False,
            "integer": 1,
            "string": "true",
        }[fault]
    response = review(f, body)
    assert response.status_code == (422 if fault in {"false", "integer", "string"} else 409), (
        response.text
    )
    assert count(f, WorkspaceNoteReview) == count(f, Operation) == 0
    assert proposal(f).status_code == 409
    assert review(f).status_code == 200
    assert review(f, body).status_code in {409, 422}


@pytest.mark.parametrize("phase", ["link", "review", "propose", "approve"])
@pytest.mark.parametrize("mutation", ["manifest", "observation", "source"])
def test_changed_gap_evidence_or_source_blocks_every_follow_up_boundary(gap_case, phase, mutation):
    f = gap_case
    if phase == "review":
        linked(f)
    elif phase in {"propose", "approve"}:
        reviewed(f)
    if phase == "approve":
        response = proposal(f)
        assert response.status_code == 200, response.text
        f.item = response.json()["workspace"]["follow_ups"][0]
    if mutation == "manifest":
        f.draft["capture_gap_review"]["recovery_sha256"] = "b" * 64
    elif mutation == "observation":
        f.draft["capture_gap_review"]["observations"][0]["reason_code"] = "capture_source_failed"
    else:
        f.draft["source_sha256"] = "c" * 64
    response = {"link": link, "review": review, "propose": proposal, "approve": decide}[phase](f)
    assert response.status_code == 409, response.text
    assert count(f, Operation) == count(f, FollowUpReceipt) == 0


@pytest.mark.parametrize(
    "flag", ["workspace_capture_source_enabled", "workspace_capture_corrections_enabled"]
)
def test_gap_receipt_and_review_remain_closed_when_qualified_path_is_disabled(gap_case, flag):
    f = gap_case
    reviewed(f)
    setattr(f.configuration, flag, False)
    assert link(f).status_code == 503
    assert review(f).status_code == 503
    assert proposal(f).status_code == 503
    assert count(f, Operation) == 0


@pytest.mark.parametrize("digest", [None, "0" * 64])
def test_database_rejects_review_without_matching_gap_hash(gap_case, digest):
    f = gap_case
    linked(f)
    with (
        Session(f.engine) as session,
        pytest.raises(DBAPIError, match="exact capture gap acknowledgment required"),
    ):
        session.add(
            WorkspaceNoteReview(
                workspace_id=f.workspace["id"],
                box_id=f.box,
                owner_id=f.actor,
                note_id=f.note["id"],
                workspace_revision=3,
                content_hash=f.note["content_hash"],
                source_fingerprint=f.note["source_fingerprint"],
                idempotency_key="direct-gap-review",
                request_hash="a" * 64,
                capture_gap_review_sha256=digest,
            )
        )
        session.commit()
    assert count(f, WorkspaceNoteReview) == 0
    assert review(f).status_code == 200


def test_database_cannot_attach_gap_source_to_already_reviewed_private_note(gap_case):
    f = gap_case
    response = post(
        f,
        "/notes",
        {
            "expected_revision": 1,
            "idempotency_key": "invented-private-note",
            "content": "Invented independently saved note.",
        },
    )
    assert response.status_code == 200, response.text
    note = response.json()["workspace"]["note"]["latest"]
    response = post(
        f,
        f"/notes/{note['id']}/review",
        {
            "expected_revision": 2,
            "idempotency_key": "invented-private-review",
            "content_hash": note["content_hash"],
            "source_fingerprint": note["source_fingerprint"],
        },
    )
    assert response.status_code == 200, response.text
    assert count(f, WorkspaceCoreNoteSource) == 0
    with (
        Session(f.engine) as session,
        pytest.raises(DBAPIError, match="reviewed note source cannot change"),
    ):
        session.add(
            WorkspaceCoreNoteSource(
                note_id=note["id"],
                workspace_id=f.workspace["id"],
                box_id=f.box,
                owner_id=f.actor,
                content_hash=note["content_hash"],
                source_fingerprint=note["source_fingerprint"],
                note_type=f.draft["note_type"],
                **f.source,
            )
        )
        session.commit()
    assert count(f, WorkspaceCoreNoteSource) == 0 and count(f, WorkspaceNoteReview) == 1
