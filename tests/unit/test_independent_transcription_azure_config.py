"""Azure Fast Transcription config refusals (T2a-azure). Default off."""

from __future__ import annotations

from cosmas_os.config import Settings


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def test_azure_switch_defaults_false():
    configured = _settings()
    assert configured.independent_recording_transcription_azure_enabled is False
    assert configured.azure_fast_transcription_endpoint is None
    assert configured.azure_fast_transcription_key_env_name is None


def test_azure_on_without_main_switch_refuses():
    configured = _settings(
        independent_recording_transcription_enabled=False,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint="https://speech.example.invalid/speechtotext/transcriptions:transcribe",
    )
    errors = configured.runtime_configuration_errors()
    assert any("INDEPENDENT_RECORDING_TRANSCRIPTION_ENABLED" in item for item in errors)
    assert not any("speech.example.invalid" in item for item in errors)


def test_azure_on_without_endpoint_refuses():
    configured = _settings(
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint=None,
    )
    errors = configured.runtime_configuration_errors()
    assert any("AZURE_FAST_TRANSCRIPTION_ENDPOINT" in item for item in errors)


def test_azure_on_with_query_endpoint_refuses():
    configured = _settings(
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint="https://speech.example.invalid/path?api-version=1",
    )
    errors = configured.runtime_configuration_errors()
    assert any("AZURE_FAST_TRANSCRIPTION_ENDPOINT" in item for item in errors)
    assert not any("api-version" in item for item in errors)


def test_azure_valid_config_passes_when_main_on():
    configured = _settings(
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint="https://speech.example.invalid/speechtotext/transcriptions:transcribe",
    )
    errors = [e for e in configured.runtime_configuration_errors() if "TRANSCRIPTION" in e or "AZURE_FAST" in e]
    assert errors == []
