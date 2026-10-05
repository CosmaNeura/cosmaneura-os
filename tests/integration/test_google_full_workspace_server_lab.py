"""Full EncounterWorkspace Google email/calendar, actual encrypted journal, signed synthetic API."""
import pytest
from tests.integration.test_google_message_ui_server_lab import run_signed_selected_source_ui_lab


@pytest.mark.parametrize("source_kind", ["email", "calendar"])
def test_actual_full_encounter_google_source_revision_acceptance_and_private_recovery(engine, monkeypatch, tmp_path, source_kind):
    run_signed_selected_source_ui_lab(engine, monkeypatch, tmp_path, source_kind=source_kind, full_workspace=True)
