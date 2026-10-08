"""Private audio metadata refuses invented completion and consent."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cosmas_os.ports.private_recording import AttachRecording, FinishRecording


def test_actual_app_browser_preflight_allows_exact_private_metadata_headers_only():
    from cosmas_os.api import app as api
    from cosmas_os.api.workspace_protocol import CONTRACTS

    assert CONTRACTS["private_recording"] == 1
    client = TestClient(api.app)
    origin = api.settings.allowed_origins[0]
    for header in ("X-Cosmas-Private-Draft", "X-Cosmas-Private-Recording"):
        response = client.options("/workspaces/private-drafts", headers={"Origin": origin,
            "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": header})
        assert response.status_code == 200
        assert header.lower() in response.headers["access-control-allow-headers"].lower()
    rejected = client.options("/workspaces/private-drafts", headers={"Origin": origin,
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "X-Unreviewed-Custody"})
    assert rejected.status_code == 400


def attach():
    now = datetime.now(UTC)
    return {"idempotency_key": str(uuid4()), "local_recording_id": str(uuid4()),
        "expected_workspace_revision": 1, "bot": {"address": "scribe", "team_revision": 1},
        "started_at": now.isoformat(), "consent": {"modality": "in_person", "participant_regions": [],
        "method": "verbal_attestation", "all_parties_consented": True,
        "granted_at": (now - timedelta(seconds=1)).isoformat()}}


@pytest.mark.parametrize("field,value", [("patient_id", str(uuid4())), ("wrapped_dek", "secret"),
                                         ("audio", "untrusted"), ("tenant_id", str(uuid4()))])
def test_private_attach_never_accepts_patient_key_or_audio(field, value):
    with pytest.raises(ValidationError):
        AttachRecording.model_validate({**attach(), field: value})


@pytest.mark.parametrize("value", [False, "true", 1])
def test_consent_requires_actual_boolean(value):
    body = attach()
    body["consent"]["all_parties_consented"] = value
    with pytest.raises(ValidationError):
        AttachRecording.model_validate(body)


def test_consent_cannot_be_after_local_capture():
    body = attach()
    body["consent"]["granted_at"] = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValidationError):
        AttachRecording.model_validate(body)


@pytest.mark.parametrize("value", [
    {"capture_state": "finished"},
    {"capture_state": "unknown", "manifest_sha256": "a" * 64},
    {"capture_state": "finished", "manifest_sha256": "a" * 64, "chunks": True,
     "frames": 16000, "ended_at": datetime.now(UTC).isoformat()},
])
def test_finish_requires_exact_complete_or_explicit_unknown(value):
    with pytest.raises(ValidationError):
        FinishRecording.model_validate({"idempotency_key": str(uuid4()), **value})


def test_unknown_has_no_invented_audio_completion():
    value = FinishRecording(idempotency_key=uuid4(), capture_state="unknown")
    assert value.manifest_sha256 is None and value.frames is None and value.ended_at is None
