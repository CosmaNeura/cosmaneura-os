"""Scheduling tools retain exact observation, authority and durable recovery."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from lab.scheduling_tools import (
    BROKER_AUTHORITY,
    SCHEDULING_SCHEMAS,
    SCHEDULING_TOOL_ROLES,
    SchedulingTools,
)
from lab.store import LabError
from sqlalchemy import func, select
from tests.integration.test_virtual_clinic_lab import clinic as clinic

from cosmas_os.application import appointment_work, workspace
from cosmas_os.config import settings
from cosmas_os.models import AppointmentWork, Decision, SchedulingAccount, SchedulingPatientAccount


def observed(tools, role="follow_up", timezone="America/New_York"):
    return tools.call(role, "scheduling_read_availability", {"timezone": timezone})


def prepare_args(read, index=0, key="observed-appointment"):
    return {"slot_ref": read["availability"]["slots"][index]["slot_ref"],
        "idempotency_key": key, "expected_workspace_revision": read["workspace_revision"]}


def prepare(tools, role="follow_up"):
    return tools.call(role, "scheduling_prepare_observed", prepare_args(observed(tools, role)))


def inspect(tools, role, ref):
    tools.call(role, "scheduling_list_proposals", {})
    return tools.call(role, "scheduling_inspect_prepared", {"proposal_ref": ref})


def count(tools, model):
    with tools.sessions() as s:
        return s.scalar(select(func.count()).select_from(model).where(model.box_id == tools.app.box))


def test_actual_boundaries_keep_approval_and_calendar_effect_separate(clinic, tmp_path):
    app, _ = clinic
    before_gate, before_roles = settings.workspace_team_setup_enabled, dict(app.agents)
    tools = SchedulingTools(app, tmp_path, "calendar_pending")
    try:
        assert settings.workspace_team_setup_enabled == before_gate
        assert app.agents == before_roles
        assert app.team_revision == 2
        read = observed(tools)
        assert read["broker"]["authority"] == BROKER_AUTHORITY
        assert read["broker"]["grant_role"] == "follow_up"
        assert read["source_bindings"]["selection"]["patient_id"] == tools.remote["patient_id"]
        assert len(tools.calls) == 1 and tools.calls[0]["method"] == "GET"
        prepared = tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read))
        detail = prepared["detail"]
        assert detail["state"] == "pending_approval" and detail["operation_id"] is None
        assert detail["appointment_saved"] is False and detail["calendar_state"] == "unconfirmed"
        assert count(tools, Decision) == 0
        before = list(tools.calls)
        listed = tools.call("chief", "scheduling_list_proposals", {})
        item = listed["catalog"]["items"][0]
        assert item["ticket_id"] == detail["ticket_id"]
        assert item["proposal_ref"] == prepared["proposal_ref"]
        assert item["payload_hash"] == detail["payload_hash"]
        assert listed["catalog"]["has_more"] is False
        inspected = tools.call("chief", "scheduling_inspect_prepared", {"proposal_ref": prepared["proposal_ref"]})
        assert inspected["detail"] == detail and tools.calls == before
        with pytest.raises(LabError, match="scripted_human_authorization_required"):
            tools.human_execute(detail["ticket_id"])
        assert count(tools, Decision) == 0 and tools.calls == before
        saved = tools.human_execute(detail["ticket_id"], authorized=True)
        assert saved["detail"]["appointment_saved"] is True
        assert saved["detail"]["calendar_state"] == "pending"
        assert saved["detail"]["operation_status"] == "succeeded"
        assert sum(call["method"] == "POST" for call in tools.calls) == 1
        assert tools.human_execute(detail["ticket_id"], authorized=True)["detail"] == saved["detail"]
        assert sum(call["method"] == "POST" for call in tools.calls) == 1
        app.engine.dispose()
        recovered = inspect(tools, "chief", prepared["proposal_ref"])
        assert recovered["detail"] == saved["detail"]
        assert "invented-scheduling-staff-token" not in json.dumps(recovered)
    finally:
        tools.close()


def test_dst_fold_is_two_exact_utc_slots_and_timezone_cannot_select_new_resource(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        read = observed(tools)
        first, second = read["availability"]["slots"]
        assert first["local_starts_at"] == "2026-11-01T01:30:00-04:00"
        assert second["local_starts_at"] == "2026-11-01T01:30:00-05:00"
        assert first["starts_at"] != second["starts_at"]
        prepared = tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read, index=1))
        assert prepared["detail"]["intent"]["slot"]["starts_at"] == second["starts_at"]
        read_utc = observed(tools, "visit_prep", "UTC")
        assert read_utc["availability"]["slots"][0]["local_starts_at"] == "2026-11-01T05:30:00+00:00"
        assert read_utc["source_bindings"] == read["source_bindings"]
        before = list(tools.calls)
        for args in ({"timezone": "US/Eastern"}, {"timezone": "UTC", "resource_id": str(uuid4())}):
            with pytest.raises(LabError, match="invalid_tool_arguments"):
                tools.call("follow_up", "scheduling_read_availability", args)
        assert tools.calls == before
    finally:
        tools.close()


@pytest.mark.parametrize("scenario,error", [("unavailable", "scheduling_unavailable"), ("grant_unavailable", "bot_resource_restricted")])
def test_unavailable_connection_or_current_grant_yields_no_proposal(clinic, tmp_path, scenario, error):
    tools = SchedulingTools(clinic[0], tmp_path, scenario)
    try:
        with pytest.raises(workspace.WorkspaceError, match=error):
            observed(tools)
        assert count(tools, AppointmentWork) == count(tools, Decision) == 0
        assert len(tools.calls) == (1 if scenario == "unavailable" else 0)
        with pytest.raises(LabError, match="scheduling_observed_slot_required"):
            tools.call("follow_up", "scheduling_prepare_observed", {"slot_ref": "slot-ny-1", "idempotency_key": "unobserved-slot", "expected_workspace_revision": 2})
    finally:
        tools.close()


def test_expired_or_receiver_removed_slot_never_autoselects_replacement(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path, "stale_slot")
    try:
        read = observed(tools)
        with pytest.raises(workspace.WorkspaceError, match="scheduling_unavailable"):
            tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read))
        assert count(tools, AppointmentWork) == 0 and len(tools.calls) == 2
        tools.observations["follow_up"]["valid_until"] = datetime.now(UTC) - timedelta(seconds=1)
        before = list(tools.calls)
        with pytest.raises(LabError, match="scheduling_observed_slot_expired"):
            tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read))
        assert tools.calls == before
    finally:
        tools.close()


def test_changed_google_connection_cannot_replace_observed_coverage(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        read = observed(tools)
        assert len(read["availability_receipt_sha256"]) == 64
        tools.remote["connection_id"] = str(uuid4())
        with pytest.raises(workspace.WorkspaceError, match="scheduling_unavailable"):
            tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read))
        assert count(tools, AppointmentWork) == 0 and count(tools, Decision) == 0
        assert len(tools.calls) == 2
    finally:
        tools.close()


@pytest.mark.parametrize("changed", ["patient", "resource", "grant", "revision"])
def test_changed_current_patient_resource_grant_or_revision_invalidates_observation(clinic, tmp_path, changed):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        read = observed(tools)
        if changed == "grant":
            tools.set_fixture_grant(False)
        else:
            with tools.sessions() as s:
                if changed == "patient":
                    mapping = s.get(SchedulingPatientAccount, tools.patient_mapping_id)
                    assert mapping is not None
                    mapping.revoked_at = datetime.now(UTC)
                    s.flush()
                    s.add(SchedulingPatientAccount(box_id=mapping.box_id, patient_link_id=mapping.patient_link_id,
                        practice_id=mapping.practice_id, patient_id=str(uuid4()), reviewed_by="synthetic_test_driver",
                        evidence_ref="lab:changed-patient", reviewed_at=datetime.now(UTC)))
                elif changed == "resource":
                    account = s.get(SchedulingAccount, tools.account_id)
                    assert account is not None
                    account.revoked_at = datetime.now(UTC)
                    s.flush()
                    s.add(SchedulingAccount(external_identity_id=account.external_identity_id,
                        **{name: getattr(account, name) for name in ("practice_id", "actor_id", "practitioner_id", "appointment_type_id")},
                        location_id=str(uuid4()), label="Changed invented resource", reviewed_by="synthetic_test_driver",
                        evidence_ref="lab:changed-resource", reviewed_at=datetime.now(UTC)))
                else:
                    workspace.append(s, *tools.scope, expected=read["workspace_revision"], key="changed-workspace", kind="scratchpad", content="Synthetic change")
                s.commit()
        before = list(tools.calls)
        with pytest.raises((LabError, workspace.WorkspaceError), match="scheduling_observation_changed|bot_resource_restricted|revision_conflict"):
            tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read))
        assert tools.calls == before and count(tools, AppointmentWork) == 0
    finally:
        tools.close()


def test_lost_preparation_reply_reuses_exact_key_and_durable_proposal(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path, "lost_prepare_reply")
    try:
        read = observed(tools)
        args = prepare_args(read)
        with pytest.raises(LabError, match="injected_lost_scheduling_prepare_reply"):
            tools.call("follow_up", "scheduling_prepare_observed", args)
        assert count(tools, AppointmentWork) == 1
        before = list(tools.calls)
        repeated = tools.call("follow_up", "scheduling_prepare_observed", args)
        assert tools.calls == before and count(tools, AppointmentWork) == 1
        with pytest.raises(workspace.WorkspaceError, match="idempotency_conflict"):
            tools.call("follow_up", "scheduling_prepare_observed", {**args, "slot_ref": "slot-ny-2"})
        assert tools.calls == before
        tools.app.engine.dispose()
        recovered = inspect(tools, "chief", repeated["proposal_ref"])
        for key in ("ticket_id", "revision_id", "payload_hash", "operation_id"):
            assert recovered["detail"][key] == repeated["detail"][key]
        assert recovered["detail"]["appointment_saved"] is False and count(tools, Decision) == 0
    finally:
        tools.close()


def test_lost_saved_reply_requires_explicit_reconcile_and_never_resubmits(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path, "lost_submit_reply")
    try:
        prepared = prepare(tools)
        ticket = prepared["detail"]["ticket_id"]
        uncertain = tools.human_execute(ticket, authorized=True)
        assert uncertain["detail"]["appointment_saved"] is False
        assert uncertain["detail"]["operation_status"] == "unknown"
        assert uncertain["detail"]["calendar_state"] == "unconfirmed"
        before = list(tools.calls)
        assert tools.human_execute(ticket, authorized=True)["detail"] == uncertain["detail"]
        assert inspect(tools, "chief", prepared["proposal_ref"])["detail"] == uncertain["detail"]
        assert tools.calls == before
        recovered = tools.human_execute(ticket, authorized=True, mode="reconcile")
        assert recovered["detail"]["appointment_saved"] is True
        assert recovered["detail"]["operation_id"] == uncertain["detail"]["operation_id"]
        assert sum(call["method"] == "POST" for call in tools.calls) == 1
        assert sum("appointment-operations/" in call["path"] and call["method"] == "GET" for call in tools.calls) == 1
        assert count(tools, Decision) == 1
    finally:
        tools.close()


@pytest.mark.parametrize("approved", [False, True])
def test_rejected_or_withdrawn_proposal_never_recommends_review_or_submission(clinic, tmp_path, approved):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        prepared = prepare(tools)
        detail = prepared["detail"]
        with tools.sessions() as s:
            if approved:
                detail = appointment_work.decide(s, *tools.scope, detail["ticket_id"], external_identity_id=tools.identity_id,
                    revision_id=detail["revision_id"], digest=detail["payload_hash"], choice="approve")
            rejected = appointment_work.decide(s, *tools.scope, detail["ticket_id"], external_identity_id=tools.identity_id,
                revision_id=detail["revision_id"], digest=detail["payload_hash"], choice="reject")
        before = list(tools.calls)
        result = inspect(tools, "chief", prepared["proposal_ref"])
        assert result["detail"] == rejected
        assert result["detail"]["state"] == "rejected"
        assert result["next_action"] == "retain rejected proposal; no approval or submission is permitted"
        assert result["detail"]["operation_status"] == ("failed" if approved else None)
        with pytest.raises(workspace.WorkspaceError, match="appointment_not_pending|appointment_approval_required"):
            tools.human_execute(detail["ticket_id"], authorized=True)
        assert tools.calls == before
    finally:
        tools.close()


def test_expired_saved_proposal_guidance_matches_service_and_keeps_unknown_recovery(clinic, tmp_path, monkeypatch):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        prepared = prepare(tools)
        expiry = datetime.fromisoformat(prepared["detail"]["intent"]["expires_at"])
        clock = expiry + timedelta(seconds=1)
        class AfterExpiry(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.astimezone(tz or UTC)
        monkeypatch.setattr("lab.scheduling_tools.datetime", AfterExpiry)
        before = list(tools.calls)
        result = inspect(tools, "chief", prepared["proposal_ref"])
        assert result["detail"]["state"] == "pending_approval"
        assert result["next_action"] == "retain expired proposal; read fresh availability before preparing a new exact intent with a new key"
        with tools.sessions() as s:
            with pytest.raises(workspace.WorkspaceError, match="appointment_proposal_expired"):
                appointment_work.decide(s, *tools.scope, prepared["detail"]["ticket_id"], external_identity_id=tools.identity_id,
                    revision_id=prepared["detail"]["revision_id"], digest=prepared["detail"]["payload_hash"], choice="approve", now=clock)
        unknown = deepcopy(prepared["detail"])
        unknown.update(state="approved", operation_id=str(uuid4()), operation_status="unknown", dispatch_started=True)
        assert tools._prepared(unknown)["next_action"] == "human explicitly reconciles the same operation; do not resubmit"
        approved = deepcopy(unknown)
        approved.update(operation_status="pending", dispatch_started=False)
        assert tools._prepared(approved)["next_action"].startswith("retain expired proposal")
        assert tools.calls == before
    finally:
        tools.close()


def test_role_and_prior_read_list_and_exact_ref_are_required(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        assert set(SCHEDULING_SCHEMAS) == {"scheduling_read_availability", "scheduling_prepare_observed", "scheduling_list_proposals", "scheduling_inspect_prepared"}
        assert all(roles == frozenset({"chief", "visit_prep", "follow_up"}) for roles in SCHEDULING_TOOL_ROLES.values())
        for role in ("scribe", "research", "followup"):
            with pytest.raises(LabError, match="scheduling_tool_role_denied"):
                observed(tools, role)
        for name in ("scheduling_approve", "scheduling_execute", "human_execute"):
            with pytest.raises(LabError, match="unknown_tool"):
                tools.call("chief", name, {})
        read = observed(tools, "follow_up")
        with pytest.raises(LabError, match="scheduling_observed_slot_required"):
            tools.call("chief", "scheduling_prepare_observed", prepare_args(read))
        prepared = tools.call("follow_up", "scheduling_prepare_observed", prepare_args(read))
        ref = prepared["proposal_ref"]
        with pytest.raises(LabError, match="scheduling_listed_proposal_required"):
            tools.call("chief", "scheduling_inspect_prepared", {"proposal_ref": ref})
        tools.call("chief", "scheduling_list_proposals", {})
        with pytest.raises(LabError, match="scheduling_listed_proposal_required"):
            tools.call("chief", "scheduling_inspect_prepared", {"proposal_ref": "appointment-" + "0" * 16})
        tools.catalog_reads["chief"]["observed_at"] -= timedelta(seconds=61)
        with pytest.raises(LabError, match="scheduling_proposal_list_expired"):
            tools.call("chief", "scheduling_inspect_prepared", {"proposal_ref": ref})
        before = list(tools.calls)
        original = tools.app.check_agent
        tools.app.check_agent = lambda role: (_ for _ in ()).throw(LabError("agent_authority_unavailable"))
        try:
            with pytest.raises(LabError, match="agent_authority_unavailable"):
                tools.call("chief", "scheduling_list_proposals", {})
        finally:
            tools.app.check_agent = original
        assert tools.calls == before
    finally:
        tools.close()


def test_receiver_reply_is_withheld_when_agent_revoked_during_read(clinic, tmp_path):
    tools = SchedulingTools(clinic[0], tmp_path)
    try:
        original, received = tools.app.check_agent, {"done": False}
        def current(role):
            if received["done"]:
                raise LabError("agent_authority_unavailable")
            return original(role)
        responder = tools._respond
        def reply(request):
            result = responder(request)
            received["done"] = True
            return result
        tools.port.close()
        import httpx
        from lab.scheduling_tools import _ObservedAppointments
        from pydantic import SecretStr
        tools.port = _ObservedAppointments("https://scheduling.example.invalid", lambda _: SecretStr("invented-scheduling-staff-token"), transport=httpx.MockTransport(reply))
        tools.app.check_agent = current
        try:
            with pytest.raises(LabError, match="agent_authority_unavailable"):
                observed(tools)
        finally:
            tools.app.check_agent = original
        assert len(tools.calls) == 1 and tools.observations == {}
        assert count(tools, AppointmentWork) == count(tools, Decision) == 0
    finally:
        tools.close()
