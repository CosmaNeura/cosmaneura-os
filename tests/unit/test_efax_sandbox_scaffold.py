"""Track 3 eFax/fax sandbox scaffold: reuse provider ids, fail-closed gates."""

from __future__ import annotations

import pytest

from cosmas_os.adapters.efax_sandbox import EFaxSandboxAdapter
from cosmas_os.config import Settings
from cosmas_os.plugins.efax import (
    CapabilityManifest,
    DeclaredEFaxConnector,
    EFaxSendRefused,
    EFaxTargetRefused,
    build_default_registry,
)
from cosmas_os.plugins.efax.connector import SEND_ACTIONS
from cosmas_os.plugins.efax.refusals import (
    HOSTED_TARGET_MESSAGE,
    PRODUCTION_TARGET_MESSAGE,
    SANDBOX_FLAG_MESSAGE,
    SEND_REFUSED_MESSAGE,
)


def test_default_registry_covers_existing_providers_only():
    registry = build_default_registry()
    assert registry.provider_ids() == ("documo", "efax", "spruce", "srfax")
    for provider_id in registry.provider_ids():
        manifest = registry.require(provider_id).capability_manifest()
        assert manifest.sends_supported is False
        assert manifest.production_supported is False
        assert manifest.hosted_supported is False


def test_settings_flags_off_by_default():
    settings = Settings()
    assert settings.workspace_efax_sandbox_enabled is False
    assert settings.workspace_efax_sandbox_available is False
    # Live inbound/outbound flags stay independent and off.
    assert settings.efax_inbound_enabled is False
    assert settings.vendor_io_enabled is False
    assert settings.vendor_work_enabled is False


def test_live_claims_cannot_be_true_on_manifest():
    with pytest.raises(ValueError, match="live_fax_not_part_of_this_scaffold"):
        CapabilityManifest(
            provider_id="efax",
            display_name="eFax",
            readable_resources=frozenset({"sandbox_receipt"}),
            unsupported_actions=frozenset({"send"}),
            sandbox_supported=True,
            sends_supported=True,
        )


@pytest.mark.parametrize("action", sorted(SEND_ACTIONS))
def test_send_always_refused(action):
    adapter = EFaxSandboxAdapter(sandbox_enabled=True, hosted=False)
    with pytest.raises(EFaxSendRefused) as raised:
        adapter.send(action)
    assert raised.value.code == "efax_send_refused"
    assert raised.value.message == SEND_REFUSED_MESSAGE


def test_flags_off_refuses_sandbox_read():
    adapter = EFaxSandboxAdapter(sandbox_enabled=False, hosted=False)
    with pytest.raises(EFaxTargetRefused) as raised:
        adapter.observe("efax", "sandbox_receipt", target="sandbox")
    assert raised.value.message == SANDBOX_FLAG_MESSAGE


def test_hosted_refuses_even_when_sandbox_flag_on():
    adapter = EFaxSandboxAdapter(sandbox_enabled=True, hosted=True)
    with pytest.raises(EFaxTargetRefused) as raised:
        adapter.observe("srfax", "delivery_status", target="sandbox")
    assert raised.value.target == "hosted"
    assert raised.value.message == HOSTED_TARGET_MESSAGE


def test_production_refused():
    adapter = EFaxSandboxAdapter(sandbox_enabled=True, hosted=False)
    with pytest.raises(EFaxTargetRefused) as raised:
        adapter.observe("documo", "inbound_metadata", target="production")
    assert raised.value.target == "production"
    assert raised.value.message == PRODUCTION_TARGET_MESSAGE


def test_hosted_config_rejects_efax_sandbox_flag():
    settings = Settings(
        workspace_hosted_enabled=True,
        workspace_efax_sandbox_enabled=True,
    )
    assert any(
        "WORKSPACE_EFAX_SANDBOX_ENABLED must remain false" in error
        for error in settings.runtime_configuration_errors()
    )


def test_synthetic_success_only_when_sandbox_flag_on():
    adapter = EFaxSandboxAdapter(sandbox_enabled=True, hosted=False)
    for provider_id in ("efax", "srfax", "documo", "spruce"):
        status = adapter.observe(provider_id, "sandbox_receipt", target="sandbox")
        assert status.synthetic is True
        assert status.provider_id == provider_id
        assert "Invented" in status.label


def test_assert_not_send_action_allows_reads():
    connector = DeclaredEFaxConnector(
        CapabilityManifest(
            provider_id="efax",
            display_name="eFax Corporate (sandbox scaffold)",
            readable_resources=frozenset({"sandbox_receipt"}),
            unsupported_actions=frozenset({"send", "production_target"}),
            sandbox_supported=True,
        )
    )
    connector.assert_not_send_action("observe")
    connector.assert_not_send_action("sandbox_receipt")
    with pytest.raises(EFaxSendRefused):
        connector.assert_not_send_action("submit")
