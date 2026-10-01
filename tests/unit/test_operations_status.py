"""Regression checks for false completion and unsafe next-action suggestions."""

from types import SimpleNamespace

import pytest

from cosmas_os.application import operations_status as operations
from cosmas_os.application.operations_status import project


@pytest.mark.parametrize("kind,facts,code,outcome", [
    ("follow_up", {"state": "pending_approval"}, "review_and_approve", "not_established"),
    ("follow_up", {"state": "sent", "receipt_kinds": ["local_delivery"]}, "record_human_outcome", "synthetic_only"),
    ("follow_up", {"state": "closed", "receipt_kinds": ["local_delivery", "human_completion"]}, "review_complete", "synthetic_only"),
    ("scheduling", {"state": "approved", "appointment_saved": False, "dispatch_started": True}, "check_existing_operation", "unconfirmed"),
    ("scheduling", {"state": "sent", "appointment_saved": True, "calendar_state": "pending"}, "check_calendar_sync", "appointment_saved_calendar_unconfirmed"),
    ("scheduling", {"state": "sent", "appointment_saved": True, "calendar_state": "synced"}, "review_receipt", "calendar_synced"),
    ("membership", {"state": "closed", "evidence_current": "current"}, "review_complete", "membership_not_established"),
    ("membership", {"state": "approved", "evidence_current": "changed"}, "review_changed_evidence", "membership_not_established"),
    ("inbox", {"state": "closed_local_review"}, "review_complete", "no_external_action"),
    ("inbox", {"state": "needs_human"}, "provider_review", "no_external_action"),
    ("payment", {"state": "approved", "conflicting_evidence": False, "payment_state": "succeeded"}, "review_payment_receipt", "payment_recorded_membership_not_established"),
    ("payment", {"state": "approved", "conflicting_evidence": False, "payment_state": "not_observed", "submit_claimed": True}, "check_existing_payment", "unconfirmed"),
    ("payment", {"state": "closed", "conflicting_evidence": True}, "resolve_payment_evidence", "unconfirmed"),
])
def test_exact_receipt_meaning_controls_next_step(kind, facts, code, outcome):
    next_step, external = project(kind, facts)
    assert next_step["code"] == code and external == outcome
    assert set(next_step) == {"code", "label", "requires_human"}


@pytest.mark.parametrize("kind", ["inbox", "follow_up", "scheduling", "membership", "payment"])
def test_stale_source_overrides_a_previously_closed_status(kind):
    action, external = project(kind, {"state": "closed", "source_current": False})
    assert action["code"] == "review_updated_source" and action["requires_human"]
    assert external == "unconfirmed"


@pytest.fixture
def linked_scope(monkeypatch):
    w = SimpleNamespace(id="invented-workspace", revision=4)
    monkeypatch.setattr(operations.ws, "_workspace", lambda *args: w)
    return {"id": w.id, "revision": w.revision, "entries": [], "follow_ups": []}


def link(record_id, lane="scheduling_appointment", *, kind="work_link"):
    return {"id": "entry-" + record_id, "kind": kind,
            "ticket": {"id": record_id, "lane": lane, "state": "approved"}}


def test_native_selection_uses_only_bound_links_deduplicated_and_bounded(monkeypatch, linked_scope):
    linked_scope["entries"] = [link(str(i)) for i in range(15)]
    linked_scope["entries"] += [link("14"), link("unrelated", "unrecognized_lane"), link("not-a-link", kind="evidence")]
    linked_scope["follow_ups"] = [{"ticket_id": "14"}]
    linked_scope["work_candidates"] = [link("unselected-candidate")]
    calls = []

    def read(_s, box, owner, workspace_id, **selection):
        calls.append((box, owner, workspace_id, selection["record_id"], selection["kind"]))
        return {"record_id": selection["record_id"]}

    monkeypatch.setattr(operations, "read", read)
    rows = operations.linked(None, "box", "owner", linked_scope["id"], linked_scope, {"role": "chief"})
    assert [r["record_id"] for r in rows] == [str(i) for i in range(14, 2, -1)]
    assert calls == [("box", "owner", linked_scope["id"], str(i), "scheduling") for i in range(14, 2, -1)]


def test_saved_follow_up_is_selected_without_scanning_inbox(monkeypatch, linked_scope):
    linked_scope["follow_ups"] = [{"ticket_id": "saved-follow-up"}]
    seen = []
    def read(*args, **selection):
        seen.append(selection)
        return {"kind": selection["kind"]}
    monkeypatch.setattr(operations, "read", read)
    rows = operations.linked(None, "box", "owner", linked_scope["id"], linked_scope, {"role": "chief"})
    assert rows == ({"kind": "follow_up"},)
    assert seen[0]["record_id"] == "saved-follow-up"


def test_missing_and_unreadable_links_remain_visible_without_private_details(monkeypatch, linked_scope):
    linked_scope["entries"] = [link("stale"), {"id": "revoked-link", "kind": "work_link", "ticket": None}]
    def unavailable(*args, **kwargs):
        assert kwargs["record_id"] == "stale"
        raise operations.ws.WorkspaceError("private-account-detail-must-not-escape", 404)
    monkeypatch.setattr(operations, "read", unavailable)
    rows = operations.linked(None, "box", "owner", linked_scope["id"], linked_scope, {"role": "chief"})
    assert len(rows) == 2 and all(r["state"] == "unavailable" for r in rows)
    assert rows[0]["record_id"] is None and rows[0]["source_entry_id"] == "revoked-link"
    assert rows[1]["record_id"] == "stale"
    assert all(r["evidence"]["external_outcome"] == "unconfirmed" for r in rows)
    assert all(r["evidence"]["commitment"] is None for r in rows)
    assert "private-account-detail" not in repr(rows)


def test_stale_snapshot_is_rejected_before_any_record_read(monkeypatch, linked_scope):
    linked_scope["revision"] -= 1
    monkeypatch.setattr(operations, "read", lambda *args, **kwargs: pytest.fail("record read before snapshot check"))
    with pytest.raises(operations.ws.WorkspaceError, match="workspace_revision_conflict"):
        operations.linked(None, "box", "owner", linked_scope["id"], linked_scope, {"role": "chief"})


def test_other_roles_do_not_gain_automatic_operation_reads(monkeypatch):
    monkeypatch.setattr(operations.ws, "_workspace", lambda *args: pytest.fail("unexpected workspace query"))
    for role in ("scribe", "research", "custom"):
        assert operations.linked(None, "box", "owner", "wid", {}, {"role": role, "skills": ["work_status"]}) == ()


def test_lost_owner_scope_aborts_projection_instead_of_returning_cached_rows(monkeypatch, linked_scope):
    calls = 0
    def workspace(*args):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise operations.ws.WorkspaceError("workspace_unavailable", 404)
        return SimpleNamespace(id=linked_scope["id"], revision=linked_scope["revision"])
    monkeypatch.setattr(operations.ws, "_workspace", workspace)
    with pytest.raises(operations.ws.WorkspaceError, match="workspace_unavailable"):
        operations.linked(None, "box", "owner", linked_scope["id"], linked_scope, {"role": "chief"})
