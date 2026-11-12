"""Non-standalone managed enrollment stays valid; defaults stay off."""

from __future__ import annotations

from tests.unit.test_clerk_verifier import _settings

from cosmas_os.config import Settings


def test_non_standalone_enrollment_managed_true_still_accepted_when_complete():
    settings = _settings(
        _env_file=None,
        clerk_session_policy="enrollment_default",
        clerk_audience="",
        workspace_enrollment_managed=True,
        workspace_enrollment_practice_id="00000000-0000-4000-8000-000000000002",
        workspace_enrollment_api_origin="https://enrollment.example.invalid",
        workspace_enrollment_account_origin="https://beta.example.invalid",
        workspace_enrollment_origin_allowlist=(
            "https://enrollment.example.invalid,https://beta.example.invalid"
        ),
        workspace_enrollment_admission_secret="e" * 64,
    )
    assert settings.cosmas_env == "early_adopter_beta"
    assert settings.workspace_enrollment_managed is True
    assert settings.runtime_configuration_errors() == []
    settings.validate_runtime_configuration()


def test_default_settings_keep_enrollment_managed_off():
    assert Settings(_env_file=None).workspace_enrollment_managed is False
