"""Explicit workspace profile for isolated synthetic integration checks."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from tests.integration.test_private_recordings import attached
from tests.integration.test_private_recordings import recording as private_recording_fixture
from tests.integration.test_private_recordings import signed_workspace as private_signed_workspace

from cosmas_os.adapters.local import InjectableClock, LocalBlobAdapter
from cosmas_os.application import independent_transcription as tx
from cosmas_os.application import services as svc
from cosmas_os.config import settings
from cosmas_os.models import BoxContext
from cosmas_os.ports.recording_transcription import FakeTranscriptionProcessor

# Re-export private-recording fixtures for T2a modules that moved off local aliases.
recording = private_recording_fixture
signed_workspace = private_signed_workspace


@pytest.fixture(autouse=True)
def local_workspace_profile(monkeypatch):
    # Application modules retain this singleton. Changing only api.settings in
    # signed-request fixtures leaves their local workflow gates disconnected.
    # Keep the environment and new Settings() defaults unchanged so default-off
    # configuration checks and explicit per-test overrides remain meaningful.
    monkeypatch.setattr(settings, "workspace_enabled", True)


@pytest.fixture
def enabled_case(recording, session, monkeypatch, tmp_path):
    f, draft, body, row = attached(recording)
    box = session.get(BoxContext, f.box)
    assert box is not None
    box.independent_recording_transcription_enabled = True
    session.commit()
    configuration = f.configuration.model_copy(
        update={"independent_recording_transcription_enabled": True, "blob_root": str(tmp_path / "blobs")}
    )
    monkeypatch.setattr(tx, "settings", configuration)
    monkeypatch.setattr(svc, "settings", configuration)
    from cosmas_os.api import app as api_module

    monkeypatch.setattr(api_module, "settings", configuration)
    clock = InjectableClock(datetime(2026, 11, 19, 12, 0, tzinfo=UTC))
    blob = LocalBlobAdapter(tmp_path / "blobs")
    tx.set_processor_override(FakeTranscriptionProcessor())
    try:
        yield {
            "f": f,
            "draft": draft,
            "row": row,
            "session": session,
            "clock": clock,
            "blob": blob,
            "external": f.binding.id,
        }
    finally:
        tx.set_processor_override(None)


def independent_consent(now: datetime) -> dict:
    return {
        "modality": "in_person",
        "participant_regions": [],
        "method": "verbal_attestation",
        "all_parties_consented": True,
        "granted_at": (now - timedelta(seconds=1)).isoformat(),
    }


def independent_payload(now: datetime, audio: bytes = b"tone-synth", **changes) -> dict:
    body = {
        "operation_id": str(uuid4()),
        "sha256": sha256(audio).hexdigest(),
        "duration_ms": 1000,
        "language": "en-US",
        "lease_expires_at": (now + timedelta(hours=1)).isoformat(),
        "consent": independent_consent(now),
        "audio": audio,
    }
    body.update(changes)
    return body
