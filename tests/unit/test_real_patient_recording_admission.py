"""Capture admission honors the real-patient recording gate (synthetic only)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from tests.unit import test_workspace_capture_failure as capture_failure

from cosmas_os.application import real_patient_recording as rpr
from cosmas_os.application import workspace as ws
from cosmas_os.application import workspace_capture as capture
from cosmas_os.models import BoxContext

# Re-export fixture for pytest discovery without shadowing the parameter name.
graph = capture_failure.graph


def _patch_encounter(monkeypatch, case, recording_class: str):
    selected = case.selected
    monkeypatch.setattr(
        capture.ws,
        "_encounter",
        lambda *args, **kwargs: SimpleNamespace(
            source="cosmaneura_core",
            external_id=selected.appointment_ref,
            recording_class=recording_class,
        ),
    )
    monkeypatch.setattr(
        "cosmas_os.config.settings",
        SimpleNamespace(
            clinic_approval_ref=None,
            baa_evidence_ref=None,
            phi_authorization_ref=None,
        ),
    )


def test_admit_refuses_real_patient_when_switch_off(graph, monkeypatch):
    box_row = BoxContext(
        id=str(uuid4()),
        display_name="Invented",
        real_patient_recording_enabled=False,
        real_patient_recording_kill_engaged=True,
    )
    _patch_encounter(monkeypatch, graph, "real")
    graph.session.get = lambda model, key: box_row if model is BoxContext else None
    graph.session.refresh = lambda row: None
    with pytest.raises(ws.WorkspaceError, match=rpr.REFUSED) as caught:
        capture_failure.read(graph)
    assert caught.value.code == rpr.REFUSED
    assert graph.calls == []


def test_admit_allows_synthetic_patient_with_switch_off(graph, monkeypatch):
    box_row = BoxContext(
        id=str(uuid4()),
        display_name="Invented",
        real_patient_recording_enabled=False,
        real_patient_recording_kill_engaged=True,
    )
    _patch_encounter(monkeypatch, graph, "synthetic")
    graph.session.get = lambda model, key: box_row if model is BoxContext else None
    graph.session.refresh = lambda row: None
    capture_failure.read(graph)
    assert "session_verification" in graph.calls or "review" in graph.calls
