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


def test_enabled_true_is_accepted_outside_standalone():
    configured = _settings(independent_recording_transcription_enabled=True)
    errors = [e for e in configured.runtime_configuration_errors() if "TRANSCRIPTION" in e]
    assert errors == []
