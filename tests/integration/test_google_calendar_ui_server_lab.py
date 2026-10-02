"""Calendar → Chief → specialist edits → human acceptance, through mounted controls."""

from tests.integration.test_google_message_ui_server_lab import run_signed_selected_source_ui_lab


def test_actual_signed_calendar_ui_runs_six_reviewed_handoff_loops_with_email_and_note_preserved(
    engine, monkeypatch, tmp_path
):
    run_signed_selected_source_ui_lab(engine, monkeypatch, tmp_path, source_kind="calendar")
