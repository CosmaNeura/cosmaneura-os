"""Real PostgreSQL: fresh owner review sees only the current private proposal."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from tests.integration.test_inbox_handoff import (
    ON,
    accepted,
    command,
    constraints,
    ingest,
    propose,
    read,
    review,
    snapshot,
)
from tests.integration.test_inbox_handoff import (
    case as case,
)
from tests.integration.test_inbox_handoff import (
    gates as gates,
)
from tests.integration.test_inbox_handoff import (
    inbox_case as inbox_case,
)
from tests.integration.test_inbox_handoff import (
    vendor_case as vendor_case,
)

from cosmas_os.api import inbox_handoff_routes as routes
from cosmas_os.api import inbox_handoff_schemas as p
from cosmas_os.application import inbox_handoff as flow
from cosmas_os.application import inbox_work as inbox
from cosmas_os.application import workspace
from cosmas_os.inbox_handoff_models import InboxHandoffReceipt
from cosmas_os.models import ActionRevision, EncounterWorkspace, Operation, Principal, Ticket

HEADERS = {"X-Cosmas-Inbox-Handoff-Contract": "1"}


@contextmanager
def client(s, c, actor=None):
    app = FastAPI()
    identity = SimpleNamespace(box_id=c["box"], principal_id=actor or c["actor"])

    def db():
        yield s

    routes.register(
        app,
        db,
        lambda: identity,
        policy_dependency=lambda: ON,
        registry_dependency=lambda: c["registry"],
        reauthenticate=lambda request, session, current: None,
    )
    with TestClient(app) as value:
        yield value


def counts(s, tid):
    return {
        "operations": s.scalar(
            select(func.count()).select_from(Operation).where(Operation.ticket_id == tid)
        ),
        "commands": s.scalar(
            select(func.count())
            .select_from(InboxHandoffReceipt)
            .where(InboxHandoffReceipt.ticket_id == tid)
        ),
        "version": s.get(Ticket, tid).version,
    }


def test_fresh_http_owner_review_includes_exact_persisted_due_and_outcome(session, case, tmp_path):
    c = case
    original = c["q"].public()
    with client(session, c) as http:
        response = http.post(
            f"/workspaces/{c['wid']}/inbox-handoffs/propose", headers=HEADERS, json=original
        )
        assert response.status_code == 200
        receipt = response.json()
        tid = receipt["effect"]["ticket_id"]
        before = counts(session, tid)
        # A later unsent local edit must never become the server's review source.
        c["q"] = c["q"].model_copy(
            update={"due_date": "2026-12-31", "expected_outcome": "Unsent local draft"}
        )
        session.expire_all()
        saved = session.get(ActionRevision, receipt["effect"]["revision_id"])
        observed = http.get("/inbox-handoffs/" + tid, headers=HEADERS)
        assert observed.status_code == 200 and observed.headers["cache-control"] == "no-store"
        detail = p.Detail.model_validate(observed.json()).public()
        assert detail["state"] == "pending_approval" and detail["publication_active"] is False
        assert detail["due_date"] == saved.payload["due_date"] == original["due_date"]
        assert (
            detail["expected_outcome"]
            == saved.payload["expected_outcome"]
            == original["expected_outcome"]
        )
        assert detail["instructions"] == original["instructions"]
        assert detail["selected_context"] == original["selected_context"]
        assert detail["private_source"]["unavailability"] is None
        assert detail["result"] is None and detail["verified_current"] is False
        assert counts(session, tid) == before == {"operations": 0, "commands": 1, "version": 1}
        (tmp_path / "actual-owner-proposal-review-http.json").write_text(
            json.dumps({"request": original, "receipt": receipt, "detail": detail}, indent=2) + "\n"
        )
    constraints(session)


def build_state(s, c, state):
    if state in {"published", "closed"}:
        tid = accepted(s, c)
        if state == "closed":
            command(
                s,
                c,
                tid,
                "result",
                actor=c["staff"],
                evidence="Reviewed local administrative task; no outgoing message.",
                no_external_action_claimed=True,
            )
            result = read(s, c, tid)["result"]
            command(
                s,
                c,
                tid,
                "verify",
                result_receipt_id=result["receipt_id"],
                result_request_sha256=result["request_sha256"],
                reviewed_current_source=True,
                reviewed_result=True,
                local_handoff_only=True,
            )
    else:
        tid = propose(s, c)["effect"]["ticket_id"]
        if state == "rejected":
            command(s, c, tid, "decide", choice="reject", publish_selected_context=True)
    return tid


@pytest.mark.parametrize("state", ["pending", "published", "closed", "rejected"])
def test_owner_staff_peer_visibility_across_private_public_and_terminal_states(
    session, case, state
):
    c = case
    tid = build_state(session, c, state)
    before = counts(session, tid)
    owner = read(session, c, tid)
    if state == "rejected":
        assert owner["state"] == "rejected" and not owner["publication_active"]
        assert owner["due_date"] is None and owner["expected_outcome"] is None
    else:
        assert owner["due_date"] == c["q"].due_date
        assert owner["expected_outcome"] == c["q"].expected_outcome
        assert owner["publication_active"] is (state in {"published", "closed"})
    for actor in (c["staff"], c["peer"]):
        if actor == c["staff"] and state in {"published", "closed"}:
            visible = read(session, c, tid, actor)
            assert visible["due_date"] == c["q"].due_date
            assert visible["expected_outcome"] == c["q"].expected_outcome
            assert "private_source" not in visible
            assert visible["verified_current"] is (state == "closed")
        else:
            with client(session, c, actor) as http:
                denied = http.get("/inbox-handoffs/" + tid, headers=HEADERS)
            assert denied.status_code == 404 and denied.headers["cache-control"] == "no-store"
            assert c["q"].due_date not in denied.text and c["q"].expected_outcome not in denied.text
    assert counts(session, tid) == before
    constraints(session)


@pytest.mark.parametrize("state", ["pending", "published", "closed"])
@pytest.mark.parametrize("change", ["source", "review", "workspace", "grant", "policy"])
def test_stale_source_review_or_authority_never_exposes_due_outcome_for_new_review(
    session, case, state, change
):
    c = case
    tid = build_state(session, c, state)
    before = counts(session, tid)
    if change == "source":
        ingest(session, c, snapshot(c, 10, text_="Changed incoming question"))
    elif change == "review":
        review(session, c, c["iid"])
    elif change == "workspace":
        session.get(EncounterWorkspace, c["wid"]).revision += 1
        session.commit()
    elif change == "grant":
        c["registry_state"]["registry"] = inbox.InboxRegistry([])
    policy = flow.Policy(False) if change == "policy" else ON
    owner = flow.read(session, c["box"], c["actor"], tid, registry=c["registry"], policy=policy)
    assert owner["state"] == "source_unavailable" and owner["requires_owner_attention"]
    assert owner["due_date"] is None and owner["expected_outcome"] is None
    assert owner["result"] is None and owner["verified_current"] is False
    # Retained owner-only history is unchanged from R9; it is not current review.
    assert owner["instructions"] == c["q"].instructions
    assert owner["selected_context"] == c["q"].selected_context
    assert owner["private_source"]["unavailability"] is not None
    if state == "pending":
        with pytest.raises(workspace.WorkspaceError):
            flow.read(session, c["box"], c["staff"], tid, registry=c["registry"], policy=policy)
    else:
        staff = flow.read(session, c["box"], c["staff"], tid, registry=c["registry"], policy=policy)
        assert staff["instructions"] is None and staff["selected_context"] is None
        assert staff["due_date"] is None and staff["expected_outcome"] is None
        assert staff["responsible_id"] == c["staff"] and staff["requires_owner_attention"]
        assert "private_source" not in staff
    assert counts(session, tid) == before
    constraints(session)


def test_disabled_owner_cannot_use_pending_review_visibility(session, case):
    c = case
    tid = propose(session, c)["effect"]["ticket_id"]
    session.get(Principal, c["actor"]).state = "disabled"
    session.commit()
    with client(session, c) as http:
        denied = http.get("/inbox-handoffs/" + tid, headers=HEADERS)
    assert denied.status_code in {403, 404}
    assert c["q"].due_date not in denied.text and c["q"].expected_outcome not in denied.text
    assert counts(session, tid)["operations"] == 0
