"""T1: recording_audio_48h_retention_enabled process switch defaults and parsing."""
from typing import Any

import pytest
from pydantic import ValidationError

from cosmas_os.config import Settings


def _settings(**values: Any) -> Settings:
    options: dict[str, Any] = {"_env_file": None, **values}
    return Settings(**options)  # pyright: ignore[reportCallIssue]


def test_recording_audio_48h_retention_defaults_false():
    settings = _settings()
    assert settings.recording_audio_48h_retention_enabled is False


@pytest.mark.parametrize("value", [True, False])
def test_recording_audio_48h_retention_accepts_bool(value):
    settings = _settings(recording_audio_48h_retention_enabled=value)
    assert settings.recording_audio_48h_retention_enabled is value


@pytest.mark.parametrize(
    "value",
    ["not-a-bool", "2", 2, {}, []],
)
def test_recording_audio_48h_retention_invalid_refuses_to_start(value):
    with pytest.raises(ValidationError):
        _settings(recording_audio_48h_retention_enabled=value)
