"""Azure Fast Transcription config refusals (T2a-azure). Default off."""

from __future__ import annotations

from cosmas_os.config import Settings

VALID = "https://eastus.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def test_azure_switch_defaults_false():
    configured = _settings()
    assert configured.independent_recording_transcription_azure_enabled is False
    assert configured.azure_fast_transcription_endpoint is None
    assert configured.azure_fast_transcription_auth == "entra"


def test_azure_on_without_main_switch_refuses():
    configured = _settings(
        independent_recording_transcription_enabled=False,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint=VALID,
    )
    errors = configured.runtime_configuration_errors()
    assert any("INDEPENDENT_RECORDING_TRANSCRIPTION_ENABLED" in item for item in errors)
    assert not any("eastus" in item for item in errors)


def test_azure_on_without_endpoint_refuses():
    configured = _settings(
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint=None,
    )
    errors = configured.runtime_configuration_errors()
    assert any("AZURE_FAST_TRANSCRIPTION_ENDPOINT" in item for item in errors)


def test_azure_on_with_non_us_host_refuses():
    configured = _settings(
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint=(
            "https://westeurope.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe"
        ),
    )
    errors = configured.runtime_configuration_errors()
    assert any("AZURE_FAST_TRANSCRIPTION_ENDPOINT" in item for item in errors)
    assert not any("westeurope" in item for item in errors)


def test_azure_valid_config_passes_when_main_on():
    configured = _settings(
        cosmas_env="synth_os",
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint=VALID,
    )
    errors = [e for e in configured.runtime_configuration_errors() if "TRANSCRIPTION" in e or "AZURE_FAST" in e]
    assert errors == []


def test_standalone_accepts_switch_when_azure_configured():
    configured = _settings(
        cosmas_env="standalone_clerk_synthetic",
        independent_recording_transcription_enabled=True,
        independent_recording_transcription_azure_enabled=True,
        azure_fast_transcription_endpoint=VALID,
    )
    errors = [
        e
        for e in configured.runtime_configuration_errors()
        if "real transcription processor" in e
    ]
    assert errors == []
