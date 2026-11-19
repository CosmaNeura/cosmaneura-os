"""Independent transcription process switch: default off; invalid bool refuses."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cosmas_os.config import Settings

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/c68f2a91b053_independent_recording_transcription.py"


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


def test_migration_upgrade_sets_lock_timeout_first():
    source = MIGRATION.read_text(encoding="utf-8")
    upgrade = source.split("UPGRADE = r\"\"\"", 1)[1].split("\"\"\"", 1)[0]
    first_stmt = next(line.strip() for line in upgrade.splitlines() if line.strip())
    assert first_stmt == "SET LOCAL lock_timeout = '5s';"


def test_synthetic_environment_reads_settings_data_mode_directly(monkeypatch):
    from cosmas_os.application import independent_transcription as tx

    assert "data_mode" in Settings.model_fields
    monkeypatch.setattr(tx, "settings", _settings(data_mode="synthetic"))
    assert tx._synthetic_environment() is True
    monkeypatch.setattr(tx, "settings", _settings(data_mode="authorized_beta"))
    assert tx._synthetic_environment() is False
