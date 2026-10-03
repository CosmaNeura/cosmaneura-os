"""Optional real-browser coverage of the signed synthetic operational fixture."""
import os

import pytest

from tests.integration import test_scribe_to_specialists_ui_server_lab as fixture


@pytest.mark.skipif(
    not all(os.environ.get(key) for key in (
        "COSMAS_PLAYWRIGHT_MODULE_URL", "COSMAS_CHROMIUM_EXECUTABLE"
    )),
    reason="Explicit local Playwright and Chromium paths required; no automatic downloads",
)
def test_actual_browser_recording_to_reviewed_specialist_graphs(engine, monkeypatch, tmp_path):
    monkeypatch.setenv(
        "COSMAS_SCRIBE_BROWSER_DRIVER",
        str(fixture.REPO / "web/browser-operational-lab/run.mjs"),
    )
    if not os.environ.get("COSMAS_SCRIBE_SPECIALIST_EVIDENCE_DIR"):
        monkeypatch.setenv("COSMAS_SCRIBE_SPECIALIST_EVIDENCE_DIR", str(tmp_path))
    fixture.test_actual_recording_to_reviewed_source_and_four_specialist_ui_graphs(
        engine, monkeypatch, tmp_path
    )

@pytest.mark.skipif(
    not all(os.environ.get(key) for key in ("COSMAS_PLAYWRIGHT_MODULE_URL", "COSMAS_CHROMIUM_EXECUTABLE")),
    reason="Explicit local browser tooling required; no downloads",
)
def test_actual_browser_postcommit_response_loss_recovers_exact_result(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("COSMAS_SCRIBE_BROWSER_SCENARIO", "postcommit")
    monkeypatch.setenv("COSMAS_SCRIBE_LAB_TEST_NAME", "postcommit one case")
    test_actual_browser_recording_to_reviewed_specialist_graphs(engine, monkeypatch, tmp_path)

@pytest.mark.skipif(
    not all(os.environ.get(key) for key in ("COSMAS_PLAYWRIGHT_MODULE_URL", "COSMAS_CHROMIUM_EXECUTABLE")),
    reason="Explicit local browser tooling required; no downloads",
)
def test_actual_browser_process_restart_recovers_encrypted_request(engine, monkeypatch, tmp_path):
    monkeypatch.setenv("COSMAS_SCRIBE_BROWSER_SCENARIO", "process")
    monkeypatch.setenv("COSMAS_SCRIBE_LAB_TEST_NAME", "process restart one case")
    test_actual_browser_recording_to_reviewed_specialist_graphs(engine, monkeypatch, tmp_path)
