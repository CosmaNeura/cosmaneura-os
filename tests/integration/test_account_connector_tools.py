"""Real account custody, workspace evidence and draft handoffs; offline I/O only."""

import hashlib
import json
from datetime import timedelta

import httpx
import pytest
from lab.account_tools import ACCOUNT_SCHEMAS, execute, prepared_account_sandboxes
from lab.application import Application
from lab.cases import CLINIC
from lab.journey import run_journey
from lab.store import Store, digest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cosmas_os.application import provider_team, workspace
from cosmas_os.models import Decision, ExternalIdentity, Operation, Principal, WorkspaceEntry


@pytest.fixture
def account_clinic(engine, tmp_path):
    store = Store(tmp_path)
    app = Application(engine, CLINIC, lambda role, kind, **v: store.event("account", role, kind, **v))
    with prepared_account_sandboxes(app) as boxes:
        yield app, store, boxes


def call(fixture, name, args, role="visit_prep", episode="account"):
    app, store, _ = fixture
    return execute(app, store, episode, role, name, args)


def read(fixture, provider="google", kind="mail", key="read-one", role="visit_prep"):
    name = "account_read_mail_headers" if kind == "mail" else "account_read_calendar"
    return call(fixture, name, {"provider": provider, "idempotency_key": key}, role=role)


def save_args(receipt, key="save-one"):
    return {"observation_id": receipt["observation_id"],
        "observation_sha256": receipt["observation_sha256"],
        "item_ids": [item["id"] for item in receipt["observation"]["items"]],
        "expected_workspace_revision": receipt["workspace_revision"], "idempotency_key": key}


def evidence_entries(app):
    with Session(app.engine) as session:
        return workspace.read(session, app.box, app.owner, app.workspace)["entries"]


@pytest.mark.parametrize("provider", ["google", "microsoft"])
@pytest.mark.parametrize("kind", ["mail", "calendar"])
def test_lost_read_reply_reuses_exact_observation_then_saves_real_evidence(account_clinic, provider, kind):
    app, store, boxes = account_clinic
    before = len(boxes[provider].calls)
    first = read(account_clinic, provider, kind)
    assert first["status"] == "ready", first
    calls_after_read = len(boxes[provider].calls)
    assert calls_after_read - before == (2 if (provider, kind) == ("google", "mail") else 1)
    assert first["saved_to_workspace"] is False
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)
    # Simulate lost delivery of the successful read, reopen the durable journal,
    # and repeat the exact request. Provider I/O and source bytes must not change.
    reopened = Store(store.root)
    second = execute(app, reopened, "account", "visit_prep",
        "account_read_mail_headers" if kind == "mail" else "account_read_calendar",
        {"provider": provider, "idempotency_key": "read-one"})
    assert second["idempotent_replay"] is True
    assert second["observation_id"] == first["observation_id"]
    assert second["observation_sha256"] == first["observation_sha256"]
    assert second["observation"] == first["observation"]
    assert len(boxes[provider].calls) == calls_after_read

    args = save_args(first)
    saved = call(account_clinic, "account_save_selected_observations", args)
    replay = execute(app, reopened, "account", "visit_prep", "account_save_selected_observations", args)
    assert saved["status"] == replay["status"] == "saved", (saved, replay)
    assert saved["entry_id"] == replay["entry_id"]
    assert replay["idempotent_replay"] is True
    entries = evidence_entries(app)
    assert len(entries) == (len(CLINIC.inputs) or 1) + 1
    entry = next(e for e in entries if e["id"] == saved["entry_id"])
    payload = json.loads(entry["content"])
    assert entry["revision"] == saved["entry_revision"] == first["workspace_revision"] + 1
    assert hashlib.sha256(entry["content"].encode()).hexdigest() == saved["content_sha256"]
    assert payload["items"] == first["observation"]["items"]
    assert payload["source_observation_sha256"] == first["observation_sha256"]
    assert payload["source_sha256"] == digest(first["observation"])
    assert payload["requester_agent_id"] == app.agent_id("visit_prep")
    assert payload["kind"] == kind and payload["provider"] == provider
    assert all(row["method"] == "GET" or "token" in row["path"] for row in boxes[provider].calls)
    assert "invented-access" not in json.dumps([first, saved, replay, entries])


@pytest.mark.parametrize("provider", ["google", "microsoft"])
def test_changed_read_intent_same_key_does_not_make_another_provider_request(account_clinic, provider):
    _, _, boxes = account_clinic
    initial = read(account_clinic, provider)
    assert initial["status"] == "ready"
    calls_before = len(boxes[provider].calls)
    changed_kind = read(account_clinic, provider, "calendar")
    assert changed_kind["error"] == "account_read_idempotency_conflict"
    other = "microsoft" if provider == "google" else "google"
    changed_provider = read(account_clinic, other)
    assert changed_provider["error"] == "account_read_idempotency_conflict"
    assert len(boxes[provider].calls) == calls_before
    assert "observation" not in changed_kind and "observation" not in changed_provider


@pytest.mark.parametrize("provider", ["google", "microsoft"])
@pytest.mark.parametrize("fault", ["read_timeout", "revoked_during_read", "oversized", "long_retry_after_429"])
def test_failed_or_revoked_read_has_no_partial_result_or_workspace_save(account_clinic, provider, fault):
    app, _, boxes = account_clinic
    box = boxes[provider]
    box.fault = fault
    before = len(box.calls)
    result = read(account_clinic, provider)
    assert result["status"] == "failed", result
    assert "observation" not in result and "observation_id" not in result
    assert result["saved_to_workspace"] is False
    assert len(box.calls) == before + 1
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)
    assert "synthetic_provider_fault_body" not in json.dumps(result)
    if fault == "read_timeout":
        recovered = read(account_clinic, provider)
        assert recovered["status"] == "ready"
    if fault == "revoked_during_read":
        calls = len(box.calls)
        failed_again = read(account_clinic, provider)
        assert failed_again["status"] == "failed" and len(box.calls) == calls


@pytest.mark.parametrize("provider", ["google", "microsoft"])
def test_explicit_read_handles_credential_refresh_but_tool_surface_never_grants(account_clinic, provider):
    _, _, boxes = account_clinic
    box = boxes[provider]
    before = len(box.calls)
    box.now += timedelta(hours=2)
    result = read(account_clinic, provider)
    assert result["status"] == "ready", result
    assert sum(row["method"] == "POST" for row in box.calls[before:]) == 1
    assert not any("connect" in name or "disconnect" in name or "send" in name for name in ACCOUNT_SCHEMAS
        if name != "account_connection_status")


@pytest.mark.parametrize("provider", ["google", "microsoft"])
@pytest.mark.parametrize("kind", ["mail", "calendar"])
def test_empty_response_is_empty_and_is_not_an_automatic_workspace_write(account_clinic, provider, kind):
    app, _, boxes = account_clinic
    box = boxes[provider]
    transport_owner = box.service if provider == "google" else box.service._client
    original = transport_owner._transport

    def empty(request):
        box.respond(request)  # Retain route/bounds checks and request receipt.
        payload = ({"messages": []} if kind == "mail" else {"items": []}) if provider == "google" else {"value": []}
        return httpx.Response(200, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps(payload).encode()))

    transport_owner._transport = httpx.MockTransport(empty)
    try:
        result = read(account_clinic, provider, kind)
    finally:
        transport_owner._transport = original
    assert result["status"] == "empty", result
    assert result["observation"]["items"] == [] and result["saved_to_workspace"] is False
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)
    args = save_args(result)
    denied = call(account_clinic, "account_save_selected_observations", args)
    assert denied["error"] == "invalid_account_tool_arguments"


@pytest.mark.parametrize("role", ["scribe", "research", "unconfigured", "prep", "followup"])
def test_wrong_role_denied_before_provider_or_evidence_access(account_clinic, role):
    app, _, boxes = account_clinic
    before = {provider: len(box.calls) for provider, box in boxes.items()}
    result = read(account_clinic, role=role)
    assert result["error"] == "account_tool_role_denied"
    assert {provider: len(box.calls) for provider, box in boxes.items()} == before
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)


def test_unconfigured_inbox_requires_actual_agent_and_unknown_action_is_denied(account_clinic):
    _, _, boxes = account_clinic
    before = len(boxes["google"].calls)
    denied = read(account_clinic, role="inbox")
    assert denied["status"] == "failed" and "observation" not in denied
    assert len(boxes["google"].calls) == before
    assert call(account_clinic, "account_send_email", {})["error"] == "unknown_account_tool"
    assert call(account_clinic, "account_read_mail_headers", {"provider": "google", "idempotency_key": "x",
        "account_id": "foreign"})["error"] == "invalid_account_tool_arguments"


@pytest.mark.parametrize("change", ["revoked", "different_account", "disconnected", "changed_identity", "disabled_agent"])
def test_old_read_cannot_be_saved_after_authority_or_account_selection_changes(account_clinic, change):
    app, _, boxes = account_clinic
    receipt = read(account_clinic)
    box = boxes["google"]
    if change == "different_account":
        box.identity = box.unconnected_identity()
    elif change == "disconnected":
        box.service.disconnect(box.identity)
    else:
        with Session(app.engine) as session:
            if change == "disabled_agent":
                principal = session.get(Principal, app.agent_id("visit_prep"))
                assert principal is not None
                principal.state = "disabled"
            else:
                row = session.get(ExternalIdentity, box.account)
                assert row is not None
                if change == "revoked":
                    row.active = False
                else:
                    row.subject = "synthetic_changed_subject"
            session.commit()
    calls_before = len(box.calls)
    result = call(account_clinic, "account_save_selected_observations", save_args(receipt))
    assert result["status"] == "failed", result
    assert "entry_id" not in result and len(box.calls) == calls_before
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)
    retry = read(account_clinic)
    assert retry["status"] == "failed" and "observation" not in retry


def test_selected_items_and_revision_are_bound_to_one_durable_save(account_clinic):
    app, _, boxes = account_clinic
    box = boxes["microsoft"]
    original = box.service._client._transport

    def two_messages(request):
        response = box.respond(request)
        data = json.loads(response.read())
        if "messages" in request.url.path:
            other = {**data["value"][0], "id": "lab-mail-two", "subject": "Synthetic request two"}
            data["value"].append(other)
        return httpx.Response(200, headers={"content-type": "application/json"},
            stream=httpx.ByteStream(json.dumps(data).encode()))

    box.service._client._transport = httpx.MockTransport(two_messages)
    try:
        receipt = read(account_clinic, "microsoft")
    finally:
        box.service._client._transport = original
    assert receipt["status"] == "ready"
    args = save_args(receipt)
    args["item_ids"] = ["lab-mail"]
    first = call(account_clinic, "account_save_selected_observations", args)
    assert first["status"] == "saved", first
    changed = call(account_clinic, "account_save_selected_observations", {**args, "item_ids": ["lab-mail-two"]})
    assert changed["error"] == "idempotency_conflict"
    bad_hash = call(account_clinic, "account_save_selected_observations", {**args, "observation_sha256": "0" * 64})
    assert bad_hash["error"] == "artifact_revision_mismatch"
    foreign = call(account_clinic, "account_save_selected_observations", {**args, "item_ids": ["foreign"]})
    assert foreign["error"] == "invalid_observation_selection"
    duplicate = call(account_clinic, "account_save_selected_observations", {**args, "item_ids": ["lab-mail", "lab-mail"]})
    assert duplicate["error"] == "invalid_observation_selection"
    stale = call(account_clinic, "account_save_selected_observations", {**args, "idempotency_key": "fresh-key"})
    assert stale["error"] == "workspace_revision_conflict"
    denied_other_role = call(account_clinic, "account_save_selected_observations", args, role="chief")
    assert denied_other_role["status"] == "failed" and "entry_id" not in denied_other_role
    entries = evidence_entries(app)
    assert len(entries) == (len(CLINIC.inputs) or 1) + 1
    payload = json.loads(next(e for e in entries if e["id"] == first["entry_id"])["content"])
    assert [item["id"] for item in payload["items"]] == ["lab-mail"]


def test_saved_account_evidence_reaches_actual_chief_and_recipient_handoffs(account_clinic):
    app, store, _ = account_clinic
    saved_ids = set()
    for role, kind in (("visit_prep", "calendar"), ("follow_up", "mail")):
        receipt = read(account_clinic, "microsoft", kind, key="read-" + role, role=role)
        saved = call(account_clinic, "account_save_selected_observations", save_args(receipt, "save-" + role), role=role)
        assert saved["status"] == "saved", saved
        saved_ids.add(saved["entry_id"])
    assert saved_ids <= {source["id"] for source in app.sources()}
    result = run_journey(app, store, "account-handoffs", None, "none", concurrency=1)
    assert result["passed"], result["failures"]
    assert len(result["handoff_receipts"]) == 3
    for artifact in result["artifacts"]:
        assert saved_ids <= set(artifact["source_ids"])
    with Session(app.engine) as session:
        # Exact source-entry lineage is committed in real application handoffs,
        # then observed again through a new workspace session.
        reopened = workspace.read(session, app.box, app.owner, app.workspace)
        for handoff in reopened["handoffs"]:
            assert saved_ids <= set(json.loads(handoff["brief"])["source_ids"])
        assert session.scalar(select(func.count()).select_from(Decision).where(Decision.box_id == app.box)) == 0
        assert session.scalar(select(func.count()).select_from(Operation).where(Operation.box_id == app.box)) == 0
        assert session.scalar(select(func.count()).select_from(WorkspaceEntry).where(
            WorkspaceEntry.workspace_id == app.workspace, WorkspaceEntry.kind == "evidence")) == (len(CLINIC.inputs) or 1) + 2


def test_account_health_is_not_a_data_read_or_permission_grant(account_clinic):
    _, _, boxes = account_clinic
    before = {provider: len(box.calls) for provider, box in boxes.items()}
    ready = call(account_clinic, "account_connection_status", {"provider": "google"})
    assert ready["status"] == "ready" and ready["data_read"] is False
    assert {provider: len(box.calls) for provider, box in boxes.items()} == before
    boxes["google"].service.disconnect(boxes["google"].identity)
    unavailable = call(account_clinic, "account_connection_status", {"provider": "google"})
    assert unavailable["status"] == "unavailable"
    assert unavailable["connection"]["state"] == "sign_in_required"


def test_new_team_revision_invalidates_old_role_observation(account_clinic):
    app, _, boxes = account_clinic
    receipt = read(account_clinic)
    with Session(app.engine) as session:
        current = provider_team.read(session, app.box, app.owner)
        saved = provider_team.save(session, app.box, app.owner, expected=current["revision"],
            key="synthetic-team-update", configuration=current["configuration"])
        app.team_revision = saved["revision"]
    calls = len(boxes["google"].calls)
    replay = read(account_clinic)
    assert replay["error"] == "account_observation_role_changed"
    denied = call(account_clinic, "account_save_selected_observations", save_args(receipt))
    assert denied["error"] == "account_observation_scope_mismatch"
    assert len(boxes["google"].calls) == calls
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)


@pytest.mark.parametrize("provider,kind", [("google", "mail"), ("microsoft", "calendar")])
def test_compact_selection_resolves_exact_read_without_hash_transcription_or_new_io(account_clinic, provider, kind):
    app, _, boxes = account_clinic
    receipt = read(account_clinic, provider, kind, key="original-read-key")
    assert receipt["read_key"] == "original-read-key"
    args = {"read_key": receipt["read_key"], "item_ids": [receipt["observation"]["items"][0]["id"]],
        "expected_workspace_revision": receipt["workspace_revision"], "idempotency_key": "compact-selection-one"}
    calls_before = len(boxes[provider].calls)
    saved = call(account_clinic, "account_select_observed_items", args)
    replay = call(account_clinic, "account_select_observed_items", args)
    assert saved["status"] == replay["status"] == "saved", (saved, replay)
    assert replay["idempotent_replay"] and replay["entry_id"] == saved["entry_id"]
    assert saved["source_observation_sha256"] == receipt["observation_sha256"]
    assert saved["source_observation_id"] == receipt["observation_id"]
    assert saved["read_key"] == "original-read-key"
    assert len(boxes[provider].calls) == calls_before
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1) + 1
    entry = next(item for item in evidence_entries(app) if item["id"] == saved["entry_id"])
    assert json.loads(entry["content"])["source_observation_sha256"] == receipt["observation_sha256"]


def test_compact_selection_rejects_bad_key_role_selection_revision_and_revocation(account_clinic):
    app, _, boxes = account_clinic
    receipt = read(account_clinic, key="stable-read")
    args = {"read_key": receipt["read_key"], "item_ids": [receipt["observation"]["items"][0]["id"]],
        "expected_workspace_revision": receipt["workspace_revision"], "idempotency_key": "stable-selection"}
    calls_before = len(boxes["google"].calls)
    malformed = call(account_clinic, "account_select_observed_items", {**args, "read_key": "bad key"})
    assert malformed["error"] == "invalid_account_tool_arguments"
    missing = call(account_clinic, "account_select_observed_items", {**args, "read_key": "changed-read"})
    assert missing["error"] == "artifact_not_found"
    wrong_role = call(account_clinic, "account_select_observed_items", args, role="chief")
    assert wrong_role["error"] == "artifact_not_found"
    denied_role = call(account_clinic, "account_select_observed_items", args, role="scribe")
    assert denied_role["error"] == "account_tool_role_denied"
    changed = call(account_clinic, "account_select_observed_items", {**args, "item_ids": ["foreign"]})
    assert changed["error"] == "invalid_observation_selection"
    stale = call(account_clinic, "account_select_observed_items", {**args, "expected_workspace_revision": 1})
    assert stale["error"] == "workspace_revision_conflict"
    with Session(app.engine) as session:
        identity = session.get(ExternalIdentity, boxes["google"].account)
        assert identity is not None
        identity.active = False
        session.commit()
    revoked = call(account_clinic, "account_select_observed_items", args)
    assert revoked["status"] == "failed" and "entry_id" not in revoked
    assert len(boxes["google"].calls) == calls_before
    assert len(evidence_entries(app)) == (len(CLINIC.inputs) or 1)
