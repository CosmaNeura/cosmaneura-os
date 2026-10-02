"""Actual durable fax receipts, owner links and HTTP reads; provider twins only."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from lab.fax_tools import FaxTools
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from tests.integration.test_fax_tools import prepared_fax, receipt_args
from tests.integration.test_virtual_clinic_lab import clinic as clinic
from tests.integration.test_workspace_auth import signed_workspace as signed_workspace

from cosmas_os.api import app as api
from cosmas_os.api import fax_status_schemas as public
from cosmas_os.application import (
    conversation,
    fax_status,
    operations_status,
    provider_team,
    workspace,
)
from cosmas_os.models import Decision, ExternalIdentity, Operation, Principal
from cosmas_os.vendor_models import VendorConnectionVersion, VendorReadClaim, VendorSubmitClaim

PROVIDERS = ("spruce", "srfax", "documo", "efax")


def saved(tools, ticket):
    with tools.sessions() as s:
        return fax_status.read(s, tools.app.box, tools.app.owner, tools.app.workspace, ticket)


def counts(tools):
    with tools.sessions() as s:
        return [s.scalar(select(func.count()).select_from(model).where(model.box_id == tools.app.box))
                for model in (Decision, Operation, VendorSubmitClaim, VendorReadClaim)]


def linked(tools, ticket):
    with tools.sessions() as s:
        current = workspace.read(s, *tools.scope)
        workspace.append(s, *tools.scope, expected=current["revision"], key="fax-status-link-" + ticket,
                         kind="work_link", ticket_id=ticket)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_saved_receipts_and_linked_chief_status_never_send_or_check_provider(clinic, tmp_path, monkeypatch, provider):
    tools = FaxTools(clinic[0], tmp_path / provider)
    prepared = prepared_fax(tools, provider)
    ticket = prepared["detail"]["summary"]["ticket_id"]
    assert saved(tools, ticket)["next_step"]["code"] == "review_exact_proposal"
    submitted = tools.human_submit(provider, ticket, authorized=True)
    assert saved(tools, ticket)["external_outcome"] == ("spruce_posted_delivery_unconfirmed" if provider == "spruce" else "not_established")
    checked = tools.call("follow_up", "fax_receipt", receipt_args(submitted["detail"], provider, refresh=True))
    linked(tools, ticket)
    with tools.sessions() as s:
        note_before = workspace.read(s, *tools.scope)["note"]
    before, calls = counts(tools), list(tools.calls)
    value = saved(tools, ticket)
    assert value["external_outcome"] == ("spruce_posted_delivery_unconfirmed" if provider == "spruce" else "provider_transport_delivered")
    assert value["verification"] == "pending" and value["source_current"] is True
    assert value["observation_head"] == checked["detail"]["summary"]["observation_head"]
    if provider == "spruce":
        assert value["pages"] is None
    else:
        assert (value["pages"]["total"], value["pages"]["delivered"]) == (1, 1)
    assert public.FaxStatus.model_validate(value).public() == value
    tools.app.engine.dispose()
    reopened = saved(tools, ticket)
    assert reopened["sha256"] == value["sha256"]
    with tools.sessions() as s:
        status = operations_status.read(s, *tools.scope, kind="fax", record_id=ticket)
        assert status["evidence"]["commitment"] == value["sha256"]
        assert status["evidence"]["workflow_closed"] is False
        snapshot = workspace.read(s, *tools.scope)
        team = provider_team.current(s, tools.app.box, tools.app.owner)
        assert team is not None
        chief = next(bot for bot in team.configuration["bots"] if bot["role"] == "chief")
        observed = operations_status.linked(s, *tools.scope, snapshot, chief)
        assert next(row for row in observed if row["record_id"] == ticket)["evidence"]["external_outcome"] == value["external_outcome"]
        assert workspace.read(s, *tools.scope)["note"] == note_before
        monkeypatch.setattr(conversation.runtime_settings, "workspace_llm_backend", "disabled")
        reply = conversation.ask(s, *tools.scope, expected=snapshot["revision"], team_revision=team.revision,
            key="fax-native-chief-" + ticket, role="chief", content="What is the next action for this saved fax?")
        assert value["next_step"]["label"] in reply["workspace"]["entries"][-1]["reply"]["content"]
    assert counts(tools) == before and tools.calls == calls
    assert operations_status.KINDS == frozenset({"inbox", "follow_up", "scheduling", "membership", "payment"})
    encoded = json.dumps(value)
    assert all(term not in encoded for term in ("invented-fax-tool-secret", "12125550101", "administrative confirmation", "private_reference", "remote_account_id"))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_lost_submission_receipt_reopens_unconfirmed_without_resend(clinic, tmp_path, provider):
    tools = FaxTools(clinic[0], tmp_path / provider, "lost_reply")
    proposal = prepared_fax(tools, provider)
    ticket = proposal["detail"]["summary"]["ticket_id"]
    tools.human_submit(provider, ticket, authorized=True)
    calls, before = list(tools.calls), counts(tools)
    first, second = saved(tools, ticket), saved(tools, ticket)
    assert first["sha256"] == second["sha256"]
    assert first["external_outcome"] == "unconfirmed"
    assert first["next_step"]["code"] == "inspect_existing_operation"
    assert first["pages"] is None
    assert tools.calls == calls and counts(tools) == before


def test_partial_failed_receipt_retains_transmitted_pages(clinic, tmp_path, monkeypatch):
    tools = FaxTools(clinic[0], tmp_path / "partial")
    original = tools._respond

    def partial(provider, request):
        response = original(provider, request)
        if provider == "documo" and request.method == "GET":
            value = response.json()
            return httpx.Response(200, json={**value, "pagesCount": 3, "pagesComplete": 1,
                                            "status": "failed", "resultCode": "4000"})
        return response

    monkeypatch.setattr(tools, "_respond", partial)
    p = prepared_fax(tools, "documo")
    ticket = p["detail"]["summary"]["ticket_id"]
    submitted = tools.human_submit("documo", ticket, authorized=True)
    tools.call("follow_up", "fax_receipt", receipt_args(submitted["detail"], "documo", refresh=True))
    result = saved(tools, ticket)
    assert result["external_outcome"] == "provider_transport_failed"
    assert result["pages"]["total"] == 3 and result["pages"]["delivered"] == 1
    assert result["next_step"]["code"] == "review_fax_exception"


def test_conflicting_terminal_receipts_require_human_resolution_without_resend(clinic, tmp_path, monkeypatch):
    tools = FaxTools(clinic[0], tmp_path / "conflict")
    p = prepared_fax(tools, "documo")
    ticket = p["detail"]["summary"]["ticket_id"]
    submitted = tools.human_submit("documo", ticket, authorized=True)
    first = tools.call("follow_up", "fax_receipt", receipt_args(submitted["detail"], "documo", key="first-delivered", refresh=True))
    original = tools._respond

    def contradict(provider, request):
        response = original(provider, request)
        if provider == "documo" and request.method == "GET":
            return httpx.Response(200, json={**response.json(), "status": "failed", "resultCode": "4000"})
        return response

    monkeypatch.setattr(tools, "_respond", contradict)
    tools.call("follow_up", "fax_receipt", receipt_args(first["detail"], "documo", key="explicit-conflicting-check", refresh=True))
    calls = list(tools.calls)
    value = saved(tools, ticket)
    assert value["conflicting_evidence"] is True
    assert value["external_outcome"] == "unconfirmed" and value["next_step"]["code"] == "review_conflicting_receipts"
    assert tools.calls == calls and sum(call["action"] == "submit" for call in calls) == 1


def test_changed_source_and_revoked_account_preserve_receipt_without_current_permission(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "stale")
    p = prepared_fax(tools, "documo")
    ticket = p["detail"]["summary"]["ticket_id"]
    submitted = tools.human_submit("documo", ticket, authorized=True)
    tools.call("follow_up", "fax_receipt", receipt_args(submitted["detail"], "documo", refresh=True))
    old = saved(tools, ticket)
    tools.change_source()
    with tools.sessions() as s:
        config = s.get(VendorConnectionVersion, tools.providers["documo"]["connection"]["id"])
        assert config is not None
        config.revoked_at = datetime.now(UTC)
        config.read_enabled = config.write_enabled = False
        s.commit()
        note = workspace.read(s, *tools.scope)["note"]
    calls, before = list(tools.calls), counts(tools)
    changed = saved(tools, ticket)
    assert changed["external_outcome"] == old["external_outcome"] == "provider_transport_delivered"
    assert changed["observation_head"] == old["observation_head"]
    assert changed["source_current"] is False and changed["original_account_available"] is False
    assert changed["next_step"]["code"] == "review_current_source"
    with tools.sessions() as s:
        assert workspace.read(s, *tools.scope)["note"] == note
    assert counts(tools) == before and tools.calls == calls


def test_direct_chief_read_requires_explicit_encounter_link_and_current_human(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "scope")
    ticket = prepared_fax(tools, "documo")["detail"]["summary"]["ticket_id"]
    with tools.sessions() as s:
        with pytest.raises(workspace.WorkspaceError, match="vendor_work_unavailable"):
            operations_status.read(s, *tools.scope, kind="fax", record_id=ticket)
    linked(tools, ticket)
    for actor in (tools.app.agent_id("chief"), str(uuid4())):
        with tools.sessions() as s:
            with pytest.raises(workspace.WorkspaceError):
                fax_status.read(s, tools.app.box, actor, tools.app.workspace, ticket)
    with tools.sessions() as s:
        with pytest.raises(workspace.WorkspaceError):
            fax_status.read(s, str(uuid4()), tools.app.owner, tools.app.workspace, ticket)
    with tools.sessions() as s:
        s.info["vendor_final_authority"] = lambda: (_ for _ in ()).throw(workspace.WorkspaceError("access_revoked", 403))
        with pytest.raises(workspace.WorkspaceError, match="access_revoked"):
            fax_status.read(s, *tools.scope, ticket)


def test_two_saved_reads_share_account_without_lock_upgrade_or_provider_io(clinic, tmp_path):
    tools = FaxTools(clinic[0], tmp_path / "concurrent")
    ticket = prepared_fax(tools, "documo")["detail"]["summary"]["ticket_id"]
    calls = list(tools.calls)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: saved(tools, ticket), range(2)))
    assert results[0]["sha256"] == results[1]["sha256"] and tools.calls == calls


def test_signed_actual_saved_status_api_is_bounded_private_and_provider_free(clinic, signed_workspace, tmp_path, monkeypatch):
    tools = FaxTools(clinic[0], tmp_path / "signed")
    ticket = prepared_fax(tools, "documo")["detail"]["summary"]["ticket_id"]
    f = signed_workspace
    subject = "fax-status-" + str(uuid4())
    monkeypatch.setattr(f.configuration, "beta_box_id", tools.app.box)
    with tools.sessions() as s:
        identity = ExternalIdentity(box_id=tools.app.box, principal_id=tools.app.owner, provider="clerk",
            issuer=f.configuration.clerk_issuer, subject=subject, organization_id="org_invented",
            reviewed_by="Invented reviewer", evidence_ref="test:fax-status-signed")
        other = Principal(box_id=tools.app.box, principal_type="human", display_name="Invented other owner", state="active", is_owner=True)
        s.add_all([identity, other])
        s.flush()
        s.add(ExternalIdentity(box_id=tools.app.box, principal_id=other.id, provider="clerk",
            issuer=f.configuration.clerk_issuer, subject=subject + "-other", organization_id="org_invented",
            reviewed_by="Invented reviewer", evidence_ref="test:fax-status-other"))
        s.commit()
        identity_id = identity.id

    def requests():
        with Session(tools.app.engine, autoflush=False) as current:
            yield current

    previous = api.app.dependency_overrides[api.get_session]
    api.app.dependency_overrides[api.get_session] = requests
    api.app.dependency_overrides[api._vendor_execution_factory] = lambda: pytest.fail("Saved GET must not construct a provider runtime")
    endpoint = f"/workspaces/{tools.app.workspace}/vendor-work/{ticket}/status"
    h = {"Authorization": "Bearer " + f.token(sub=subject), "X-Cosmas-Vendor-Contract": "1"}
    before, calls = counts(tools), list(tools.calls)
    try:
        first = f.client.get(endpoint, headers=h)
        assert first.status_code == 200, first.text
        assert first.headers["cache-control"] == "no-store"
        value = public.FaxStatus.model_validate(first.json()).public()
        assert value["scope"] == {"box_id": tools.app.box, "owner_id": tools.app.owner, "workspace_id": tools.app.workspace}
        assert len(first.content) <= 8192
        assert f.client.get(endpoint, headers=h).json()["sha256"] == value["sha256"]
        assert f.client.get(endpoint + "?refresh=true", headers=h).status_code == 400
        assert f.client.get(endpoint, headers={**h, "X-Cosmas-Vendor-Contract": "2"}).status_code == 426
        other_h = {**h, "Authorization": "Bearer " + f.token(sub=subject + "-other")}
        assert f.client.get(endpoint, headers=other_h).status_code == 404
        with tools.sessions() as s:
            row = s.get(ExternalIdentity, identity_id)
            assert row is not None
            row.active = False
            s.commit()
        assert f.client.get(endpoint, headers=h).status_code == 403
    finally:
        api.app.dependency_overrides[api.get_session] = previous
        api.app.dependency_overrides.pop(api._vendor_execution_factory, None)
    assert tools.calls == calls and counts(tools) == before
