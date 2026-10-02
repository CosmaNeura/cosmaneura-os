"""Hosted proposal activation cannot reach any direct execution entry point."""

from unittest.mock import Mock

import pytest
from fastapi.routing import APIRoute
from tests.unit.test_hosted_workspace_config import hosted

from cosmas_os.api import app as api
from cosmas_os.application import appointment_execution as execution
from cosmas_os.application import workspace as ws


@pytest.mark.parametrize("mode", ["submit", "reconcile", "retry"])
@pytest.mark.parametrize("explicit", [True, False])
def test_hosted_direct_run_denied_before_database_or_reauthentication(monkeypatch, mode, explicit):
    configuration = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True)
    monkeypatch.setattr(execution.follow_up, "settings", configuration)
    s, reauthenticate, port = Mock(), Mock(), Mock()
    with pytest.raises(ws.WorkspaceError, match="appointment_execution_not_available") as refused:
        execution.run(s, "box", "owner", "workspace", "ticket", external_identity_id="identity",
            reauthenticate=reauthenticate, port=port, operation_id="operation", revision_id="revision",
            digest="a" * 64, mode=mode, configuration=configuration if explicit else None)
    assert refused.value.status == 403
    s.get_bind.assert_not_called()
    s.execute.assert_not_called()
    reauthenticate.assert_not_called()
    port.submit.assert_not_called()
    port.reconcile.assert_not_called()


def test_hosted_route_has_an_independent_execution_gate(monkeypatch):
    configuration = hosted(workspace_scheduling_enabled=True, workspace_appointments_enabled=True)
    monkeypatch.setattr(api, "settings", configuration)
    api._appointment_gate()
    with pytest.raises(ws.WorkspaceError, match="appointment_execution_not_available"):
        api._appointment_execution_gate()
    routes = [r for r in api.app.routes if isinstance(r, APIRoute) and r.path.endswith("/appointments/{ticket_id}/execute")]
    assert len(routes) == 1
    assert api._appointment_execution_gate in [dependency.call for dependency in routes[0].dependant.dependencies]
