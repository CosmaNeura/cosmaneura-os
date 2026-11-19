"""Independent transcription process switch: default off; invalid bool refuses."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cosmas_os.config import Settings


def _settings(**values) -> Settings:
    return Settings(_env_file=None, **values)  # pyright: ignore[reportCallIssue]


def test_switch_default_false():
    configured = _settings()
    assert configured.independent_recording_transcription_enabled is False


def test_invalid_bool_refuses_to_construct(monkeypatch):
    monkeypatch.setenv("INDEPENDENT_RECORDING_TRANSCRIPTION_ENABLED", "not-a-bool")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_enabled_true_is_accepted_on_synth_os():
    configured = _settings(
        cosmas_env="synth_os",
        independent_recording_transcription_enabled=True,
    )
    errors = [e for e in configured.runtime_configuration_errors() if "TRANSCRIPTION" in e]
    assert errors == []


def test_standalone_refuses_switch_without_real_processor():
    configured = _settings(
        cosmas_env="standalone_clerk_synthetic",
        independent_recording_transcription_enabled=True,
    )
    errors = configured.runtime_configuration_errors()
    assert any(
        "requires a configured real transcription processor" in item for item in errors
    )


def test_production_refuses_switch_without_real_processor():
    configured = _settings(
        cosmas_env="early_adopter_beta",
        independent_recording_transcription_enabled=True,
    )
    errors = configured.runtime_configuration_errors()
    assert any(
        "requires a configured real transcription processor" in item for item in errors
    )
