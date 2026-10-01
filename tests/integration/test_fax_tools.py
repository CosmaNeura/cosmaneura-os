"""Bots exercise each real fax boundary without access to human submission."""

import json
from uuid import uuid4

import pytest
from lab.fax_sandbox import bound
from lab.fax_tools import BROKER_AUTHORITY, FAX_SCHEMAS, FAX_TOOL_ROLES, FaxTools
from lab.store import LabError
from sqlalchemy import func, select
from tests.integration.test_virtual_clinic_lab import clinic as clinic

from cosmas_os.application import vendor_work, workspace
from cosmas_os.config import settings
from cosmas_os.models import Decision
from cosmas_os.ports.vendor_artifacts import ArtifactStoreError
from cosmas_os.vendor_models import VendorConnectionVersion, VendorCorrespondenceVersion

PROVIDERS = ("spruce", "srfax", "documo", "efax")


def prepare_args(readiness, provider, *, action="fax", upload=None):
    options = readiness["options"]
    result = {"provider": provider, "expected_workspace_revision": options["entry_revision"],
        "idempotency_key": "proposal-" + str(uuid4()), "proposed_operation_id": readiness["proposal_ids"][action],
        "source": options["source"], "connection": {k: options["connections"][0][k]
            for k in ("id", "revision", "public_sha256")}, "action": action}
    if action == "media_upload" or provider != "spruce":
        result["document"] = readiness["document"]
    if action == "fax":
        result["correspondence"] = {k: options["correspondences"][0][k]
            for k in ("id", "revision", "public_sha256")}
    if upload:
        result["uploaded_media_operation_id"] = upload["detail"]["summary"]["operation_id"]
    return result


def receipt_args(detail, provider, *, key="fax-receipt", refresh=False):
    return {"provider": provider, "ticket_id": detail["summary"]["ticket_id"],
            **bound(detail, key), "refresh": refresh}


def prepared_fax(tools, provider):
    readiness = tools.call("follow_up", "fax_readiness", {"provider": provider})
    upload = None
    if provider == "spruce":
        upload = tools.call("follow_up", "fax_prepare", prepare_args(readiness, provider, action="media_upload"))
        tools.human_submit(provider, upload["detail"]["summary"]["ticket_id"], authorized=True)
        readiness = tools.call("follow_up", "fax_readiness", {"provider": provider})
    return tools.call("follow_up", "fax_prepare", prepare_args(readiness, provider, upload=upload))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_bot_calls_each_persistent_boundary_and_human_send_is_separate(clinic, tmp_path, provider):
    app, _ = clinic
    prior = settings.vendor_work_enabled, settings.vendor_io_enabled
    tools = FaxTools(app, tmp_path / "fax-tools")
    assert (settings.vendor_work_enabled, settings.vendor_io_enabled) == prior
    readiness = tools.call("chief", "fax_readiness", {"provider": provider})
    assert readiness["ready_for_proposal"] and readiness["document_custody"] == "ready"
    assert tools.calls == []
    with tools.sessions() as s:
        assert s.scalar(select(func.count()).select_from(Decision).where(Decision.box_id == app.box)) == 0
    prepared = prepared_fax(tools, provider)
    detail, ticket_id = prepared["detail"], prepared["detail"]["summary"]["ticket_id"]
    assert prepared["broker"]["authority"] == BROKER_AUTHORITY
    assert detail["summary"]["state"] == "pending_approval"
    assert detail["summary"]["acceptance"] == "not_observed"
    before = list(tools.calls)
    observed = tools.call("follow_up", "fax_receipt", receipt_args(detail, provider))
    assert observed["detail"]["summary"]["operation_id"] == detail["summary"]["operation_id"]
    assert tools.calls == before
    with pytest.raises(LabError, match="scripted_human_authorization_required"):
        tools.human_submit(provider, ticket_id)
    assert tools.calls == before
    with pytest.raises(workspace.WorkspaceError, match="vendor_reference_unavailable"):
        tools.call("chief", "fax_receipt", receipt_args(detail, provider, refresh=True))
    submitted = tools.human_submit(provider, ticket_id, authorized=True)
    assert submitted["detail"]["summary"]["acceptance"] == "accepted"
    request = receipt_args(submitted["detail"], provider, refresh=True)
    observed = tools.call("follow_up", "fax_receipt", request)
    assert observed["detail"]["summary"]["transport"] == ("pending" if provider == "spruce" else "delivered")
    assert observed["detail"]["summary"]["state"] == "approved"
    assert sum(c["action"] == "submit" for c in tools.calls) == 1
    assert sum(c["action"] == "upload" for c in tools.calls) == (provider == "spruce")
    calls = list(tools.calls)
    repeated = tools.call("follow_up", "fax_receipt", request)
    assert repeated["receipt"]["effect"]["receipt_id"] == observed["receipt"]["effect"]["receipt_id"]
    assert tools.calls == calls
    app.engine.dispose()
    recovered = tools.call("chief", "fax_receipt", receipt_args(repeated["detail"], provider))
    for key in ("operation_id", "revision_id", "payload_hash", "observation_head", "evidence_sha256"):
        assert recovered["detail"]["summary"][key] == repeated["detail"]["summary"][key]
    assert (settings.vendor_work_enabled, settings.vendor_io_enabled) == prior
    assert "invented-fax-tool-secret" not in json.dumps(recovered)
    tools.close()


@pytest.mark.parametrize("provider", PROVIDERS)
def test_lost_submission_response_is_unconfirmed_and_never_resent(clinic, tmp_path, provider):
    tools = FaxTools(clinic[0], tmp_path / "lost-fax", "lost_reply")
    prepared = prepared_fax(tools, provider)
    ticket_id = prepared["detail"]["summary"]["ticket_id"]
    result = tools.human_submit(provider, ticket_id, authorized=True)
    assert result["detail"]["summary"]["acceptance"] == "unconfirmed"
    repeated = tools.human_submit(provider, ticket_id, authorized=True)
    assert repeated["receipt"]["effect"]["receipt_id"] == result["receipt"]["effect"]["receipt_id"]
    with pytest.raises(workspace.WorkspaceError, match="vendor_submit_already_claimed"):
        tools.human_submit(provider, ticket_id, authorized=True, idempotency_key="fresh-resend-key")
    with pytest.raises(workspace.WorkspaceError, match="vendor_reference_unavailable"):
        tools.call("follow_up", "fax_receipt", receipt_args(result["detail"], provider, refresh=True))
    assert sum(c["action"] == "submit" for c in tools.calls) == 1


def test_spruce_unknown_upload_cannot_authorize_a_fax(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "upload-lost", "upload_reply_lost")
    ready = tools.call("follow_up", "fax_readiness", {"provider": "spruce"})
    upload = tools.call("follow_up", "fax_prepare", prepare_args(ready, "spruce", action="media_upload"))
    submitted = tools.human_submit("spruce", upload["detail"]["summary"]["ticket_id"], authorized=True)
    assert submitted["detail"]["summary"]["acceptance"] == "unconfirmed"
    with pytest.raises(workspace.WorkspaceError, match="artifact_unavailable"):
        tools.call("follow_up", "fax_prepare", prepare_args(ready, "spruce", upload=upload))
    assert [c["action"] for c in tools.calls] == ["upload"]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_explicit_status_recovery_reuses_operation_without_resending(clinic, tmp_path, provider):
    tools = FaxTools(clinic[0], tmp_path / "read-lost", "read_timeout")
    prepared = prepared_fax(tools, provider)
    submitted = tools.human_submit(provider, prepared["detail"]["summary"]["ticket_id"], authorized=True)
    request = receipt_args(submitted["detail"], provider, key="first-status-read", refresh=True)
    first = tools.call("follow_up", "fax_receipt", request)
    assert first["detail"]["summary"]["transport"] == "unknown"
    assert sum(c["action"] == "read" for c in tools.calls) == 1
    tools.call("follow_up", "fax_receipt", request)
    assert sum(c["action"] == "read" for c in tools.calls) == 1
    recovered = tools.call("follow_up", "fax_receipt", receipt_args(first["detail"], provider,
        key="explicit-status-recovery", refresh=True))
    assert recovered["detail"]["summary"]["operation_id"] == submitted["detail"]["summary"]["operation_id"]
    # Spruce posting is nonterminal and cannot erase prior unknown evidence.
    assert recovered["detail"]["summary"]["transport"] == ("unknown" if provider == "spruce" else "delivered")
    assert sum(c["action"] == "read" for c in tools.calls) == 2
    assert sum(c["action"] == "submit" for c in tools.calls) == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_prepare_replay_recovers_exact_receipt_but_changed_key_intent_is_denied(clinic, tmp_path, provider):
    tools = FaxTools(clinic[0], tmp_path / "proposal-replay")
    ready = tools.call("follow_up", "fax_readiness", {"provider": provider})
    request = prepare_args(ready, provider, action="media_upload" if provider == "spruce" else "fax")
    first = tools.call("follow_up", "fax_prepare", request)
    assert tools.calls == []
    tools.change_source()
    tools.change_pdf()
    repeated = tools.call("chief", "fax_prepare", request)
    assert repeated["receipt"]["effect"] == first["receipt"]["effect"]
    changed = {**request, "proposed_operation_id": str(uuid4())}
    with pytest.raises(workspace.WorkspaceError, match="vendor_idempotency_conflict"):
        tools.call("follow_up", "fax_prepare", changed)
    assert tools.calls == []


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("fault", ["unavailable", "missing_recipient", "changed_source", "changed_pdf"])
def test_readiness_reports_unavailable_or_changed_bindings_without_sending(clinic, tmp_path, provider, fault):
    tools = FaxTools(clinic[0], tmp_path / fault, fault)
    ready = tools.call("follow_up", "fax_readiness", {"provider": provider})
    assert ready["ready_for_proposal"] is False
    assert tools.calls == []
    if fault == "changed_pdf":
        assert ready["document_custody"] == "changed"
    if fault == "changed_source":
        assert ready["options"]["source"] is None


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("fault,error", [("unavailable", "vendor_selection_changed"),
                                         ("missing_recipient", "vendor_permission_unavailable")])
def test_unavailable_connection_or_missing_recipient_refuses_preparation(clinic, tmp_path, provider, fault, error):
    tools = FaxTools(clinic[0], tmp_path / fault, fault)
    ready = tools.call("follow_up", "fax_readiness", {"provider": provider})
    fixture = tools.providers[provider]
    request = {"provider": provider, "expected_workspace_revision": ready["options"]["entry_revision"],
        "idempotency_key": "denied-proposal", "proposed_operation_id": ready["proposal_ids"]["fax"],
        "source": tools.source, "connection": {k: fixture["connection"][k] for k in ("id", "revision", "public_sha256")},
        "correspondence": {k: fixture["correspondence"][k] for k in ("id", "revision", "public_sha256")}}
    if provider == "spruce":
        request["uploaded_media_operation_id"] = str(uuid4())
    else:
        request["document"] = ready["document"]
    with pytest.raises(workspace.WorkspaceError, match=error):
        tools.call("follow_up", "fax_prepare", request)
    assert tools.calls == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_changed_source_or_pdf_fences_submission_before_provider_call(clinic, tmp_path, provider):
    tools = FaxTools(clinic[0], tmp_path / "changed-after-prepare")
    prepared = prepared_fax(tools, provider)
    ticket_id = prepared["detail"]["summary"]["ticket_id"]
    before = list(tools.calls)
    tools.change_source()
    with pytest.raises(workspace.WorkspaceError, match="vendor_source_changed"):
        tools.human_submit(provider, ticket_id, authorized=True)
    assert tools.calls == before


def test_changed_pdf_fences_a_reviewed_proposal_and_new_preparation(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "changed-pdf")
    ready = tools.call("follow_up", "fax_readiness", {"provider": "efax"})
    request = prepare_args(ready, "efax")
    prepared = tools.call("follow_up", "fax_prepare", request)
    tools.change_pdf()
    with pytest.raises(ArtifactStoreError, match="artifact_changed"):
        tools.call("follow_up", "fax_prepare", {**request, "idempotency_key": "new-proposal", "proposed_operation_id": str(uuid4())})
    submitted = tools.human_submit("efax", prepared["detail"]["summary"]["ticket_id"], authorized=True)
    assert submitted["detail"]["summary"]["acceptance"] != "accepted"
    assert tools.calls == []


def test_chief_discovers_exact_existing_proposal_without_duplicate_work_or_send(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "list-proposals")
    documo = prepared_fax(tools, "documo")
    srfax = prepared_fax(tools, "srfax")
    listed = tools.call("chief", "fax_list_proposals", {"provider": "documo"})
    assert listed["catalog"]["items"] == [documo["detail"]["summary"]]
    assert listed["catalog"]["items"][0]["ticket_id"] != srfax["detail"]["summary"]["ticket_id"]
    assert listed["source_bindings"] == [{"ticket_id": documo["detail"]["summary"]["ticket_id"],
        "source": documo["detail"]["review"]["source"], "review_sha256": documo["detail"]["review_sha256"]}]
    assert listed["broker"]["authority"] == BROKER_AUTHORITY
    assert listed["catalog"]["limit"] == 25 and listed["catalog"]["has_more"] is False
    observed = tools.call("chief", "fax_receipt", receipt_args({"summary": listed["catalog"]["items"][0]}, "documo"))
    assert observed["detail"]["summary"] == documo["detail"]["summary"]
    assert tools.calls == []
    with pytest.raises(LabError, match="fax_tool_role_denied"):
        tools.call("research", "fax_list_proposals", {"provider": "documo"})
    assert tools.call("follow_up", "fax_list_proposals", {"provider": "efax"})["catalog"]["items"] == []


def test_proposal_listing_is_bounded_and_reports_more_existing_work(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "bounded-list")
    ready = tools.call("follow_up", "fax_readiness", {"provider": "documo"})
    request = prepare_args(ready, "documo")
    for _ in range(26):
        tools.call("follow_up", "fax_prepare", {**request,
            "proposed_operation_id": str(uuid4()), "idempotency_key": "proposal-" + str(uuid4())})
    listed = tools.call("chief", "fax_list_proposals", {"provider": "documo"})
    assert len(listed["catalog"]["items"]) == len(listed["source_bindings"]) == listed["catalog"]["limit"] == 25
    assert listed["catalog"]["has_more"] is True
    assert len({item["ticket_id"] for item in listed["catalog"]["items"]}) == 25
    assert tools.calls == []


def test_fax_role_scope_fixed_arguments_and_agent_approval_denial(clinic, tmp_path, monkeypatch):
    tools = FaxTools(clinic[0], tmp_path / "role-scope")
    assert set(FAX_SCHEMAS) == {"fax_readiness", "fax_list_proposals", "fax_prepare", "fax_receipt",
                               "fax_prepare_ready", "fax_inspect_prepared"}
    assert all(roles == {"chief", "follow_up"} for roles in FAX_TOOL_ROLES.values())
    for role in ("scribe", "research", "visit_prep", "followup"):
        with pytest.raises(LabError, match="fax_tool_role_denied"):
            tools.call(role, "fax_readiness", {"provider": "documo"})
    with pytest.raises(LabError, match="unknown_tool"):
        tools.call("chief", "human_submit", {})
    with pytest.raises(LabError, match="invalid_tool_arguments"):
        tools.call("chief", "fax_readiness", {"provider": "documo", "actor_id": tools.app.owner})
    prepared = prepared_fax(tools, "documo")
    with tools.sessions() as s:
        with pytest.raises(workspace.WorkspaceError):
            vendor_work.decide(s, tools.app.box, tools.app.agent_id("follow_up"), tools.app.workspace,
                prepared["detail"]["summary"]["ticket_id"], {})
    monkeypatch.setattr(tools.app, "check_agent", lambda role: (_ for _ in ()).throw(LabError("agent_authority_unavailable")))
    with pytest.raises(LabError, match="agent_authority_unavailable"):
        tools.call("chief", "fax_readiness", {"provider": "documo"})
    assert tools.calls == []


@pytest.mark.parametrize("provider", PROVIDERS)
def test_compact_tools_keep_exact_bindings_and_recover_lost_preparation(clinic, tmp_path, provider):
    tools = FaxTools(clinic[0], tmp_path / "compact-tools")
    readiness = tools.call("follow_up", "fax_readiness", {"provider": provider})
    action = "media_upload" if provider == "spruce" else "fax"
    request = {"provider": provider, "idempotency_key": "compact-proposal",
        "expected_workspace_revision": readiness["options"]["entry_revision"], "action": action}
    result = tools.call("follow_up", "fax_prepare_ready", request)
    assert result["detail"]["summary"]["operation_id"] == readiness["proposal_ids"][action]
    tools.change_source()
    repeated = tools.call("follow_up", "fax_prepare_ready", request)
    assert repeated["receipt"]["effect"] == result["receipt"]["effect"]
    tools.call("chief", "fax_list_proposals", {"provider": provider})
    inspected = tools.call("chief", "fax_inspect_prepared", {"provider": provider, "action": action})
    assert inspected["detail"]["summary"] == repeated["detail"]["summary"]
    assert inspected["broker"]["authority"] == BROKER_AUTHORITY
    assert tools.calls == []
    with pytest.raises(LabError, match="fax_idempotency_conflict"):
        tools.call("follow_up", "fax_prepare_ready", {**request, "expected_workspace_revision": request["expected_workspace_revision"] + 1})


@pytest.mark.parametrize("fault", ["source", "pdf", "connection", "recipient"])
def test_compact_prepare_refuses_changed_readiness_without_picking_fresh_bindings(clinic, tmp_path, fault):
    tools = FaxTools(clinic[0], tmp_path / fault)
    readiness = tools.call("follow_up", "fax_readiness", {"provider": "documo"})
    if fault == "source":
        tools.change_source()
    elif fault == "pdf":
        tools.change_pdf()
    else:
        with tools.sessions() as s:
            fixture = tools.providers["documo"]
            if fault == "connection":
                row = s.get(VendorConnectionVersion, fixture["connection"]["id"])
                assert row is not None
                row.write_enabled = False
            else:
                row = s.get(VendorCorrespondenceVersion, fixture["correspondence"]["id"])
                assert row is not None
                row.is_current = False
            s.commit()
    with pytest.raises(LabError, match="fax_readiness_changed"):
        tools.call("follow_up", "fax_prepare_ready", {"provider": "documo", "idempotency_key": "compact-denied",
            "expected_workspace_revision": readiness["options"]["entry_revision"]})
    assert tools.call("chief", "fax_list_proposals", {"provider": "documo"})["catalog"]["items"] == []
    assert tools.calls == []


def test_compact_tools_require_each_roles_own_read_and_exact_fixture_operation(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "compact-scope")
    request = {"provider": "documo", "idempotency_key": "compact-scope", "expected_workspace_revision": 1}
    with pytest.raises(LabError, match="fax_readiness_not_read"):
        tools.call("follow_up", "fax_prepare_ready", request)
    with pytest.raises(LabError, match="fax_proposals_not_read"):
        tools.call("chief", "fax_inspect_prepared", {"provider": "documo"})
    readiness = tools.call("chief", "fax_readiness", {"provider": "documo"})
    request["expected_workspace_revision"] = readiness["options"]["entry_revision"]
    with pytest.raises(LabError, match="fax_readiness_not_read"):
        tools.call("follow_up", "fax_prepare_ready", request)
    arbitrary = prepare_args(readiness, "documo")
    arbitrary["proposed_operation_id"] = str(uuid4())
    tools.call("chief", "fax_prepare", arbitrary)
    tools.call("chief", "fax_list_proposals", {"provider": "documo"})
    with pytest.raises(LabError, match="fax_prepared_operation_not_seen"):
        tools.call("chief", "fax_inspect_prepared", {"provider": "documo"})
    for name, args in (("fax_prepare_ready", request), ("fax_inspect_prepared", {"provider": "documo"})):
        with pytest.raises(LabError, match="fax_tool_role_denied"):
            tools.call("research", name, args)
    assert tools.calls == []
