"""Actual signed process proof of unsent editing, recovery and one later creation."""

import json

from sqlalchemy.orm import Session
from tests.integration.test_finance_process import lines, prepare
from tests.integration.test_finance_process import processes as processes
from tests.integration.test_finance_work import bound, proposal

from cosmas_os.finance_models import FinanceSubmitClaim
from cosmas_os.models import Operation


def test_signed_process_unsent_revision_recovers_then_creates_only_new_intent(processes, engine):
    case, http = processes, processes["client"]
    url, prior = prepare(case)
    collection, tid = url.rsplit("/", 1)
    request = proposal(
        case["case"],
        due_date="2026-10-04",
        expected_outcome="Invented revised due date after human review.",
        revises={
            "ticket_id": tid,
            "expected_version": prior["summary"]["version"],
            "revision_id": prior["summary"]["revision_id"],
            "payload_hash": prior["summary"]["payload_hash"],
        },
    ).public()
    changed = http.post(collection, json=request)
    assert changed.status_code == 200, changed.text
    current = http.get(url).json()
    assert current["summary"]["state"] == "pending_approval"
    assert current["summary"]["operation_id"] != prior["summary"]["operation_id"]
    assert lines(case["root"] / "receiver.jsonl") == []
    assert lines(case["root"] / "credentials.jsonl") == []
    with Session(engine) as s:
        old_op = s.get(Operation, prior["summary"]["operation_id"])
        assert old_op.status == "cancelled" and old_op.attempt_count == 0
        assert s.get(FinanceSubmitClaim, old_op.id) is None
    # A real restart must preserve exact old/new history and never revive approval.
    case["app"].kill()
    case["app"].wait(timeout=3)
    case["start"]("os")
    replay = http.post(collection, json=request)
    assert replay.status_code == 200 and replay.json()["effect"] == changed.json()["effect"]
    assert http.post(url + "/submit", json=bound(prior)).status_code == 409
    assert http.post(url + "/submit", json=bound(current)).status_code == 409
    assert lines(case["root"] / "receiver.jsonl") == []
    assert lines(case["root"] / "credentials.jsonl") == []
    approve = http.post(
        url + "/decide",
        json=bound(current, review_sha256=current["review_sha256"], choice="approve"),
    )
    assert approve.status_code == 200, approve.text
    approved = http.get(url).json()
    submit = bound(approved)
    sent = http.post(url + "/submit", json=submit)
    assert sent.status_code == 200, sent.text
    assert http.post(url + "/submit", json=submit).json()["effect"] == sent.json()["effect"]
    assert http.post(url + "/submit", json=bound(prior)).status_code == 409
    effects = lines(case["root"] / "receiver.jsonl")
    assert len(effects) == 1 and effects[0]["method"] == "POST"
    assert effects[0]["operation"] == approved["summary"]["operation_id"]
    assert effects[0]["body"]["confirm"] == ["false"]
    assert len(lines(case["root"] / "credentials.jsonl")) == 1
    final = http.get(url).json()
    assert final["summary"]["creation"] == "accepted"
    assert final["summary"]["payment_state"] == "not_observed"
    (case["root"] / "actual-finance-revision-process.json").write_text(
        json.dumps(
            {
                "prior": prior,
                "request": request,
                "receipt": changed.json(),
                "replay": replay.json(),
                "pending": current,
                "approved": approved,
                "submitted": final,
                "effects": effects,
            },
            indent=2,
        )
        + "\n"
    )
