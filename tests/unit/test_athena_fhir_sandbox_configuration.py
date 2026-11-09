"""C8 dual-flag gates for athena FHIR Preview. Defaults off; hosted refuses."""

from __future__ import annotations

import pytest

from cosmas_os.adapters.athena_fhir_r4 import (
    ATHENA_FHIR_EXTRA_SANDBOX_HOSTS,
    ATHENA_FHIR_R4_BASE_URL,
    ATHENA_FHIR_RESOURCES,
    ATHENA_FHIR_SYSTEM_READ_SCOPES,
    ATHENA_PREVIEW_HOST,
    FORBIDDEN_FHIR_RESOURCES,
)
from cosmas_os.config import Settings
from cosmas_os.plugins.ehr_fhir import READABLE_RESOURCES, FhirR4ReadClient


def test_athena_fhir_sandbox_flags_default_off():
    settings = Settings()
    assert settings.workspace_ehr_read_enabled is False
    assert settings.workspace_athena_fhir_sandbox_enabled is False
    assert settings.workspace_athena_fhir_sandbox_available is False
    assert settings.cosmas_ehr_real_data_enabled is False


def test_hosted_refuses_athena_fhir_sandbox_flag():
    settings = Settings(
        workspace_hosted_enabled=True,
        workspace_athena_fhir_sandbox_enabled=True,
    )
    assert any(
        "WORKSPACE_ATHENA_FHIR_SANDBOX_ENABLED must remain false" in error
        for error in settings.runtime_configuration_errors()
    )


def test_shared_c4_allowlists_not_widened_for_athena():
    assert ATHENA_PREVIEW_HOST not in {
        "fhir.sandbox.example.com",
        "sandbox.fhir.example.org",
        "synthetic.invalid",
        "mock.example.com",
        "localhost",
        "127.0.0.1",
    }
    assert ATHENA_FHIR_EXTRA_SANDBOX_HOSTS == frozenset({ATHENA_PREVIEW_HOST})
    with pytest.raises(PermissionError, match="fhir_base_url_not_sandbox"):
        FhirR4ReadClient(ATHENA_FHIR_R4_BASE_URL)
    assert "Appointment" in READABLE_RESOURCES
    assert "Appointment" not in ATHENA_FHIR_RESOURCES
    assert FORBIDDEN_FHIR_RESOURCES == frozenset({"Appointment"})
    assert "system/Appointment.read" not in ATHENA_FHIR_SYSTEM_READ_SCOPES
    assert len(ATHENA_FHIR_SYSTEM_READ_SCOPES) == 12


def test_both_flags_required_for_athena_fhir_available():
    only_ehr = Settings().model_copy(update={
        "workspace_ehr_read_enabled": True,
        "workspace_athena_fhir_sandbox_enabled": False,
    })
    only_athena = Settings().model_copy(update={
        "workspace_ehr_read_enabled": False,
        "workspace_athena_fhir_sandbox_enabled": True,
    })
    assert only_ehr.workspace_athena_fhir_sandbox_available is False
    assert only_athena.workspace_athena_fhir_sandbox_available is False


@pytest.mark.parametrize("action", ["fhir_patients", "fhir_medications"])
def test_plugin_allows_athena_fhir_commands_and_refuses_appointment(action):
    from cosmas_os.plugins import athena as plugin

    body = {
        "action": action,
        "provider": "athena",
        "protocol": "fhir",
        "connection_id": "33333333-3333-4333-8333-333333333333",
        "binding_sha256": "ab" * 32,
        "workspace_id": "66666666-6666-4666-8666-666666666666",
        "idempotency_key": "athena-fhir-1",
    }
    if action == "fhir_medications":
        body.update(
            observation_id="44444444-4444-4444-8444-444444444444",
            observation_sha256="cd" * 32,
            item_handle="55555555-5555-4555-8555-555555555555",
            item_sha256="ef" * 32,
        )
    assert plugin.command_allowed(body) is True
    assert plugin.command_allowed({**body, "provider": "tebra"}) is False
    assert plugin.command_allowed({"action": "status", "provider": "athena", "protocol": "fhir"}) is True
    assert "fhir_appointment" in plugin.EHR_CAPABILITY.unsupported_actions
    assert "patients" in plugin.EHR_CAPABILITY.readable_resources
    names = {row["name"] for row in plugin.tool_definitions()}
    assert "athena_read_authorized_patients" in names
    assert "athena_read_fhir_medications" in names
