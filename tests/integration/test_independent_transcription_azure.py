"""Azure adapter stays dark when its switch is off (T2a-azure)."""

from __future__ import annotations

from tests.integration.test_independent_transcription import _payload
from tests.integration.test_independent_transcription import enabled_case as _enabled_case
from tests.integration.test_independent_transcription import recording as _recording
from tests.integration.test_independent_transcription import signed_workspace as _signed_workspace

from cosmas_os.application import independent_transcription as tx

enabled_case = _enabled_case
recording = _recording
signed_workspace = _signed_workspace


def test_azure_never_constructed_when_off(enabled_case, monkeypatch):
    c = enabled_case
    calls: list[str] = []

    def boom(*args, **kwargs):
        calls.append("constructed")
        raise AssertionError("Azure adapter must not be constructed when off")

    monkeypatch.setattr(
        tx, "AzureFastTranscriptionProcessor", type("X", (), {"from_settings": staticmethod(boom)})
    )
    monkeypatch.setattr(
        c["f"].configuration,
        "independent_recording_transcription_azure_enabled",
        False,
    )
    now = c["clock"].now()
    payload = _payload(now, b"tone-no-azure")
    tx.upload_audio(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        payload, external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    tx.start_transcription(
        c["session"], c["f"].box, c["f"].actor, c["draft"]["id"], c["row"]["recording_id"],
        {"operation_id": payload["operation_id"]},
        external=c["external"], blob=c["blob"], clock=c["clock"],
    )
    assert calls == []
