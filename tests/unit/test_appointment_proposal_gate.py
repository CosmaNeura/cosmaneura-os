"""Explicit hosted preparation is independent of local delivery admission."""

from unittest.mock import Mock

import pytest
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.application import appointment_work as work
from cosmas_os.application import workspace as ws


def test_explicit_signed_hosted_proposals_do_not_inspect_or_connect_database(monkeypatch):
    configuration = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True)
    assert configuration.workspace_scheduling_available
    session = Mock()
    monkeypatch.setattr(work.follow_up, "_local", lambda _: pytest.fail("Synthetic delivery gate borrowed"))
    work._proposal_gate(session, configuration)
    session.get_bind.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"workspace_scheduling_enabled": False}, {"workspace_appointments_enabled": False},
    {"workspace_authenticated_enabled": False}, {"auth_mode": "synth_headers"},
    {"synth_seed": True}, {"human_deploy_evidence_ref": None},
])
def test_incomplete_or_disabled_explicit_profile_cannot_fall_back_to_local(monkeypatch, changes):
    configuration = hosted(**{"workspace_scheduling_enabled": True,
        "workspace_appointments_enabled": True, **changes})
    local = Mock()
    monkeypatch.setattr(work.follow_up, "_local", local)
    session = Mock()
    with pytest.raises(ws.WorkspaceError, match="appointment_proposals_unavailable") as refused:
        work._proposal_gate(session, configuration)
    assert refused.value.status == 403
    local.assert_not_called()
    session.get_bind.assert_not_called()


def test_omitting_explicit_profile_keeps_legacy_local_delivery_gate(monkeypatch):
    session, local = Mock(), Mock()
    monkeypatch.setattr(work.follow_up, "_local", local)
    work._proposal_gate(session, None)
    local.assert_called_once_with(session)


def test_live_configuration_is_checked_each_time(monkeypatch):
    configuration = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True)
    monkeypatch.setattr(work.follow_up, "_local", lambda _: pytest.fail("Local fallback admitted"))
    work._proposal_gate(Mock(), configuration)
    configuration.workspace_appointments_enabled = False
    with pytest.raises(ws.WorkspaceError, match="appointment_proposals_unavailable"):
        work._proposal_gate(Mock(), configuration)


@pytest.mark.parametrize("operation", ["read", "catalog", "propose", "decide"])
def test_every_preparation_entrypoint_checks_gate_before_workspace_access(monkeypatch, operation):
    configuration = hosted(workspace_scheduling_enabled=True)
    monkeypatch.setattr(work.ws, "_workspace", lambda *_args, **_kwargs: pytest.fail("Workspace accessed"))
    arguments = [Mock(), "invented-box", "invented-human", "invented-workspace"]
    keywords: dict[str, object] = {"configuration": configuration}
    if operation in {"read", "decide"}:
        arguments.append("invented-ticket")
    if operation == "propose":
        keywords.update(external_identity_id="invented-identity", intent=None, key="invented-key", share=True)
    elif operation == "decide":
        keywords.update(external_identity_id="invented-identity", revision_id="invented-revision",
                        digest="a" * 64, choice="approve")
    with pytest.raises(ws.WorkspaceError, match="appointment_proposals_unavailable"):
        getattr(work, operation)(*arguments, **keywords)
