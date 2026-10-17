"""Signed private notebooks, actual PostgreSQL custody and denied patient actions."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from tests.helpers.task_brief import REQUIREMENTS
from tests.integration.test_workspace_auth import signed_workspace as _signed_workspace

from cosmas_os.application import agent_tools, model_work, provider_team
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    AppointmentObservation,
    ExternalIdentity,
    PatientLink,
    Principal,
    WorkspaceAppointmentLink,
)
from cosmas_os.ports.bot_capabilities import BotReply, DraftBrief, ModelCallFailure

signed_workspace = _signed_workspace


def headers(f):
    return {"Authorization": "Bearer " + f.token(), "X-Cosmas-Private-Draft": "1"}


def create(f):
    body = {"title": "Private preparation", "idempotency_key": "private-draft-create"}
    result = f.client.post("/workspaces/private-drafts", headers=headers(f), json=body)
    assert result.status_code == 200, result.text
    return body, result.json()


def appointment(s, f):
    link = PatientLink(box_id=f.box, source_pair_key="draft-test:" + str(uuid4()), label="Invented later visit",
        state="confirmed", confirmed_by_principal_id=f.actor, attested_at=datetime.now(UTC))
    s.add(link)
    s.flush()
    row = AppointmentObservation(box_id=f.box, external_id="invented:" + str(uuid4()), source="synthetic",
        start_at=datetime.now(UTC), patient_label="Invented later visit", patient_link_id=link.id)
    s.add(row)
    s.commit()
    return row


def test_empty_draft_save_reopen_exact_create_recovery_and_team(signed_workspace):
    f = signed_workspace
    body, draft = create(f)
    assert draft["appointment_id"] is None and draft["entries"] == []
    assert draft["private_draft"] == {"title": body["title"], "state": "unlinked", "link_receipt_id": None, "linked_at": None}
    path = f"/workspaces/{draft['id']}"
    saved = f.client.post(path + "/entries", headers=headers(f), json={
        "expected_revision": 1, "idempotency_key": "private-draft-note", "kind": "scratchpad", "content": "Invented private agenda"})
    assert saved.status_code == 200 and saved.json()["entry_revision"] == 2
    second_session = {**headers(f), "Authorization": "Bearer " + f.token(sid="invented-second-device")}
    reopened = f.client.get(path, headers=second_session)
    assert reopened.status_code == 200 and reopened.json()["entries"][0]["content"] == "Invented private agenda"
    resolved = f.client.post("/workspaces/private-drafts/resolve", headers=second_session, json=body)
    assert resolved.status_code == 200 and resolved.json()["workspace"]["revision"] == 2
    replay = f.client.post("/workspaces/private-drafts", headers=headers(f), json=body)
    assert replay.json()["id"] == draft["id"] and replay.json()["revision"] == 2
    listed = f.client.get("/workspaces/private-drafts", headers=headers(f))
    assert listed.json()["drafts"][0]["workspace_id"] == draft["id"] and listed.json()["has_more"] is False
    assert f.client.get("/provider-team", headers=second_session).status_code == 200
    conflict = f.client.post("/workspaces/private-drafts", headers=headers(f), json={**body, "title": "Different"})
    assert conflict.status_code == 409


def test_team_and_visit_storage_failures_are_bounded_safe_and_do_not_create_a_link(signed_workspace, session, monkeypatch):
    f = signed_workspace
    _, draft = create(f)
    selected = appointment(session, f)
    command = {"expected_revision": 1, "idempotency_key": "synthetic-storage-fault", "appointment_id": selected.id, "appointment_link_confirmed": True}

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("PRIVATE DATABASE PARAMETER")

    with monkeypatch.context() as fault:
        fault.setattr(provider_team, "read", unavailable)
        response = f.client.get("/provider-team", headers=headers(f))
        assert response.status_code == 503 and "PRIVATE" not in response.text
        assert response.headers["cache-control"] == "no-store"
    with monkeypatch.context() as fault:
        fault.setattr(ws, "link_appointment", unavailable)
        response = f.client.post(f"/workspaces/{draft['id']}/appointment-link", headers=headers(f), json=command)
        assert response.status_code == 503 and "PRIVATE" not in response.text
    response = f.client.post(f"/workspaces/{draft['id']}/appointment-link/resolve", headers=headers(f), json=command)
    assert response.status_code == 200 and response.json()["outcome"] == "not_found"
    assert session.scalar(select(func.count()).select_from(WorkspaceAppointmentLink).where(WorkspaceAppointmentLink.workspace_id == draft["id"])) == 0


@pytest.mark.parametrize("bad", [{"patient_id": str(uuid4())}, {"appointment_id": str(uuid4())}, {"title": " "}])
def test_create_rejects_client_patient_authority_and_empty_title(signed_workspace, bad):
    f = signed_workspace
    result = f.client.post("/workspaces/private-drafts", headers=headers(f),
        json={"title": "Private note", "idempotency_key": "draft-invalid-key", **bad})
    assert result.status_code == 422


@pytest.mark.parametrize("raw", [
    '{"title":"first","title":"second","idempotency_key":"draft-duplicate-key"}',
    '{"title":"Private note","idempotency_key":"draft-large-key","extra":"' + "x" * 4096 + '"}',
])
def test_signed_request_byte_bound_and_duplicate_fields_reject_before_create(signed_workspace, raw):
    f = signed_workspace
    result = f.client.post("/workspaces/private-drafts", headers={**headers(f), "Content-Type": "application/json"}, content=raw)
    assert result.status_code == 422 and result.json() == {"detail": "invalid_private_draft_request"}
    assert f.client.get("/workspaces/private-drafts", headers=headers(f)).json()["drafts"] == []


def test_private_draft_contract_identity_owner_and_revocation(signed_workspace, session):
    f = signed_workspace
    body, draft = create(f)
    assert f.client.post("/workspaces/private-drafts", headers={"Authorization": "Bearer " + f.token()}, json=body).status_code == 426
    assert f.client.get("/workspaces/private-drafts?owner=other", headers=headers(f)).status_code == 422
    other = Principal(box_id=f.box, principal_type="human", display_name="Invented peer", state="active", is_owner=True)
    session.add(other)
    session.flush()
    session.add(ExternalIdentity(box_id=f.box, principal_id=other.id, provider="clerk", issuer=f.configuration.clerk_issuer,
        subject="user_private_peer", organization_id="org_invented", reviewed_by="Invented", evidence_ref="test:peer"))
    session.commit()
    peer = {**headers(f), "Authorization": "Bearer " + f.token(sub="user_private_peer")}
    assert f.client.get(f"/workspaces/{draft['id']}", headers=peer).status_code == 404
    assert f.client.get("/workspaces/private-drafts", headers=peer).json()["drafts"] == []
    assert f.client.post("/workspaces/private-drafts/resolve", headers=peer, json=body).json()["outcome"] == "not_found"
    f.binding.active = False
    session.commit()
    assert f.client.get(f"/workspaces/{draft['id']}", headers=headers(f)).status_code == 403


def test_link_existing_visible_appointment_preserves_history_and_resolves_without_resubmit(signed_workspace, session):
    f = signed_workspace
    _, draft = create(f)
    saved = ws.append(session, f.box, f.actor, draft["id"], expected=1, key="private-pre-link",
        kind="scratchpad", content="Invented original private agenda")
    selected = appointment(session, f)
    body = {"expected_revision": 2, "idempotency_key": "private-link-key", "appointment_id": selected.id, "appointment_link_confirmed": True}
    path = f"/workspaces/{draft['id']}/appointment-link"
    assert f.client.post(path + "/resolve", headers=headers(f), json=body).json()["outcome"] == "not_found"
    result = f.client.post(path, headers=headers(f), json=body)
    assert result.status_code == 200, result.text
    value = result.json()
    assert value["workspace"]["appointment_id"] == selected.id and value["workspace"]["revision"] == 3
    assert value["workspace"]["entries"] == saved["workspace"]["entries"]
    assert value["workspace"]["private_draft"]["title"] == "Private preparation"
    assert f.client.post(path, headers=headers(f), json=body).json() == value
    resolved = f.client.post(path + "/resolve", headers=headers(f), json=body)
    assert resolved.json()["link_receipt_id"] == value["link_receipt_id"]
    assert session.scalar(select(func.count()).select_from(WorkspaceAppointmentLink).where(WorkspaceAppointmentLink.workspace_id == draft["id"])) == 1
    receipt = session.get(WorkspaceAppointmentLink, value["link_receipt_id"])
    assert receipt and len(receipt.draft_sha256) == 64 and len(receipt.appointment_sha256) == 64
    with pytest.raises(DBAPIError), session.begin_nested():
        session.execute(text("UPDATE workspace_appointment_links SET request_hash=:hash WHERE id=:id"), {"id": receipt.id, "hash": "a" * 64})
    assert f.client.post(path + "/resolve", headers=headers(f), json={**body, "idempotency_key": "different-key"}).status_code == 409
    session.get(PatientLink, selected.patient_link_id).revoked_at = datetime.now(UTC)
    session.commit()
    assert f.client.get(f"/workspaces/{draft['id']}", headers=headers(f)).status_code == 404
    assert f.client.get("/workspaces/private-drafts", headers=headers(f)).json()["drafts"] == []


@pytest.mark.parametrize("fault", ["missing", "unconfirmed", "already_owned", "not_human", "stale"])
def test_bad_link_never_creates_association_or_receipt(signed_workspace, session, fault):
    f = signed_workspace
    _, draft = create(f)
    selected = appointment(session, f)
    body = {"expected_revision": 1, "idempotency_key": "private-invalid-link", "appointment_id": selected.id, "appointment_link_confirmed": True}
    if fault == "missing":
        body["appointment_id"] = str(uuid4())
    if fault == "unconfirmed":
        session.get(PatientLink, selected.patient_link_id).state = "unconfirmed"
        session.commit()
    if fault == "already_owned":
        body["appointment_id"] = f.appointment.id
    if fault == "not_human":
        body["appointment_link_confirmed"] = 1
    if fault == "stale":
        body["expected_revision"] = 2
    result = f.client.post(f"/workspaces/{draft['id']}/appointment-link", headers=headers(f), json=body)
    assert result.status_code in {404, 409, 422}
    assert ws.read(session, f.box, f.actor, draft["id"])["appointment_id"] is None
    assert session.scalar(select(func.count()).select_from(WorkspaceAppointmentLink).where(WorkspaceAppointmentLink.workspace_id == draft["id"])) == 0


def test_sql_rejects_half_pair_owner_takeover_and_receiptless_association(signed_workspace, session):
    f = signed_workspace
    _, draft = create(f)
    for statement, args in [
        ("UPDATE encounter_workspaces SET appointment_id=:value WHERE id=:id", {"value": f.appointment.id}),
        ("UPDATE encounter_workspaces SET owner_id=:value WHERE id=:id", {"value": str(uuid4())}),
        ("UPDATE encounter_workspaces SET appointment_id=:value,patient_link_id=:patient,revision=revision+1 WHERE id=:id",
            {"value": f.appointment.id, "patient": f.appointment.patient_link_id}),
    ]:
        with pytest.raises((DBAPIError, IntegrityError)), session.begin_nested():
            session.execute(text(statement), {"id": draft["id"], **args})


def test_unlinked_draft_rejects_patient_handlers_and_keeps_internal_source_tools(signed_workspace, session, monkeypatch):
    f = signed_workspace
    _, draft = create(f)
    with pytest.raises(ws.WorkspaceError, match="workspace_appointment_required"):
        ws._workspace(session, f.box, f.actor, draft["id"])
    with pytest.raises(ws.WorkspaceError, match="work_unavailable"):
        ws.append(session, f.box, f.actor, draft["id"], expected=1, key="private-ticket-link", kind="work_link", ticket_id=str(uuid4()))
    ws.append(session, f.box, f.actor, draft["id"], expected=1, key="private-tool-source", kind="scratchpad", content="Invented private preparation facts")
    configuration = f.configuration
    configuration.workspace_agent_tools_enabled = True
    configuration.workspace_llm_backend = "azure_gpt41"
    configuration.workspace_llm_api_key = SecretStr("invented-not-dispatched")
    monkeypatch.setattr(provider_team, "runtime_settings", configuration)
    version = provider_team.save(session, f.box, f.actor, expected=0, key="private-team-defaults", configuration=provider_team.default_configuration())
    admission, _ = model_work.reserve_conversation(session, f.box, f.actor, draft["id"], expected=2,
        team_revision=version["revision"], key="private-chief-request", role="chief", content="Prepare my private agenda.", external_identity_id=f.binding.id)
    claim = model_work.claim(session, f.box, f.actor, admission)
    assert claim and claim.envelope["contract"] == "cosmas-gpt41-prepared.v6"
    executor = agent_tools.AgentToolExecutor(session, claim)
    listed = executor.execute({"tool": "list_selected_sources"})["data"]
    assert listed["sources"]
    handle = listed["sources"][0]
    result = executor.execute({"tool": "read_selected_source", **{key: handle[key] for key in ("entry_id", "revision", "sha256")}})
    assert "Invented private preparation facts" in str(result)
    assert claim.envelope["tool_selection"]["operations"] == []
    with pytest.raises(ws.WorkspaceError, match="agent_tool_request_invalid"):
        executor.execute({"tool": "propose_research_query", "topic": "literature", "sources": ["pubmed"], "query": "ankle injury"})
    model_work.settle(session, claim, ModelCallFailure(dispatch="not_dispatched"))
    assert f.client.get(f"/workspaces/{draft['id']}", headers={**headers(f), "X-Cosmas-Model-Contract": "1"}).status_code == 200


def test_signed_chat_private_handoff_saved_reply_reopens_without_patient(signed_workspace, session, monkeypatch):
    from cosmas_os.application import conversation

    f = signed_workspace
    _, draft = create(f)
    configuration = f.configuration
    configuration.workspace_agent_tools_enabled = True
    configuration.workspace_llm_backend = "azure_gpt41"
    configuration.workspace_llm_api_key = SecretStr("invented-no-model-network")
    monkeypatch.setattr(provider_team, "runtime_settings", configuration)
    monkeypatch.setattr(conversation, "runtime_settings", configuration)
    provider_team.save(session, f.box, f.actor, expected=0, key="private-handoff-team", configuration=provider_team.default_configuration())
    actual_ask = conversation.ask

    def authored_dispatch(claim):
        assert claim.envelope["contract"] == "cosmas-gpt41-prepared.v6"
        return BotReply("Private agenda draft prepared for review.", (), "azure_gpt41", 20, 8,
            (DraftBrief("scribe", "Organize the invented private agenda; patient remains unselected.", REQUIREMENTS),))

    def local_ask(*args, **kwargs):
        return actual_ask(*args, **{**kwargs, "dispatch": authored_dispatch})

    monkeypatch.setattr(conversation, "ask", local_ask)
    body = {"expected_revision": 1, "team_revision": 1, "idempotency_key": "private-chief-handoff",
        "role": "chief", "content": "Prepare my private agenda without a selected patient."}
    path = f"/workspaces/{draft['id']}"
    auth = {**headers(f), "X-Cosmas-Model-Contract": "1"}
    result = f.client.post(path + "/conversation", headers=auth, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["outcome"] == "saved"
    reopened = f.client.get(path, headers=auth)
    assert reopened.status_code == 200
    value = reopened.json()
    saved = next(entry for entry in value["entries"] if entry["id"] == result.json()["saved_entry"]["id"])
    assert value["appointment_id"] is None and saved["reply"]["content"] == "Private draft requests: 1 queued; 0 not started. Review each teammate’s recorded status below."
    assert value["handoffs"] and value["handoffs"][0]["recipient_role"] == "scribe"
    assert value["work_candidates"] == []
    replay = f.client.post(path + "/conversation/resolve", headers=auth, json=body)
    assert replay.status_code == 200 and replay.json()["saved_entry"] == result.json()["saved_entry"]
