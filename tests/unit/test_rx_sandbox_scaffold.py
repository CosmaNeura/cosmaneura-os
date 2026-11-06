"""Track 3 prescription sandbox scaffold: fail-closed send/read gates."""

from __future__ import annotations

import pytest

from cosmas_os.adapters.rx_sandbox import RxSandboxAdapter
from cosmas_os.config import Settings
from cosmas_os.plugins.rx import (
    CapabilityManifest,
    DeclaredRxConnector,
    RxReadRefused,
    RxSendRefused,
    RxTargetRefused,
    build_default_registry,
)
from cosmas_os.plugins.rx.connector import SEND_ACTIONS
from cosmas_os.plugins.rx.refusals import (
    HOSTED_TARGET_MESSAGE,
    PRODUCTION_TARGET_MESSAGE,
    SANDBOX_FLAG_MESSAGE,
    SEND_REFUSED_MESSAGE,
)
from cosmas_os.plugins.rx.registry import DEFAULT_MANIFEST


def _manifest(**overrides) -> CapabilityManifest:
    values = dict(
        vendor_id="unspecified",
        display_name="Prescription sandbox (no vendor)",
        readable_resources=frozenset({"formulary_status", "draft_status"}),
        unsupported_actions=frozenset({"send", "prescribe", "production_target"}),
        sandbox_supported=True,
        production_supported=False,
        hosted_supported=False,
        sends_supported=False,
    )
    values.update(overrides)
    return CapabilityManifest(**values)


def test_default_registry_is_unspecified_only():
    registry = build_default_registry()
    assert registry.vendor_ids() == ("unspecified",)
    assert registry.require("unspecified").capability_manifest().vendor_id == "unspecified"
    assert DEFAULT_MANIFEST.sends_supported is False
    assert DEFAULT_MANIFEST.production_supported is False


def test_settings_flags_off_by_default():
    settings = Settings()
    assert settings.workspace_rx_sandbox_enabled is False
    assert settings.workspace_rx_sandbox_available is False


def test_live_claims_cannot_be_true_on_manifest():
    with pytest.raises(ValueError, match="live_prescribing_not_part_of_this_contract"):
        _manifest(sends_supported=True)
    with pytest.raises(ValueError, match="live_prescribing_not_part_of_this_contract"):
        _manifest(production_supported=True)
    with pytest.raises(ValueError, match="live_prescribing_not_part_of_this_contract"):
        _manifest(hosted_supported=True)


@pytest.mark.parametrize("action", sorted(SEND_ACTIONS))
def test_send_always_refused(action):
    connector = DeclaredRxConnector(_manifest())
    with pytest.raises(RxSendRefused) as raised:
        connector.assert_not_send_action(action)
    assert raised.value.code == "rx_send_refused"
    assert raised.value.message == SEND_REFUSED_MESSAGE
    adapter = RxSandboxAdapter(sandbox_enabled=True, hosted=False)
    with pytest.raises(RxSendRefused):
        adapter.send(action)


def test_flags_off_refuses_sandbox_read():
    adapter = RxSandboxAdapter(sandbox_enabled=False, hosted=False)
    with pytest.raises(RxTargetRefused) as raised:
        adapter.observe("formulary_status", target="sandbox")
    assert raised.value.code == "rx_target_refused"
    assert raised.value.message == SANDBOX_FLAG_MESSAGE


def test_hosted_refuses_even_when_sandbox_flag_on():
    adapter = RxSandboxAdapter(sandbox_enabled=True, hosted=True)
    with pytest.raises(RxTargetRefused) as raised:
        adapter.observe("formulary_status", target="sandbox")
    assert raised.value.target == "hosted"
    assert raised.value.message == HOSTED_TARGET_MESSAGE


def test_production_refused():
    adapter = RxSandboxAdapter(sandbox_enabled=True, hosted=False)
    with pytest.raises(RxTargetRefused) as raised:
        adapter.observe("formulary_status", target="production")
    assert raised.value.target == "production"
    assert raised.value.message == PRODUCTION_TARGET_MESSAGE


def test_hosted_config_rejects_rx_sandbox_flag():
    settings = Settings(
        workspace_hosted_enabled=True,
        workspace_rx_sandbox_enabled=True,
    )
    assert any(
        "WORKSPACE_RX_SANDBOX_ENABLED must remain false" in error
        for error in settings.runtime_configuration_errors()
    )


def test_synthetic_success_only_when_sandbox_flag_on():
    adapter = RxSandboxAdapter(sandbox_enabled=True, hosted=False)
    status = adapter.observe("draft_status", target="sandbox")
    assert status.synthetic is True
    assert status.vendor == "unspecified"
    assert "Invented" in status.label
    assert status.resource == "draft_status"


def test_unsupported_resource_refused_even_in_sandbox():
    connector = DeclaredRxConnector(
        _manifest(readable_resources=frozenset({"formulary_status"}))
    )
    with pytest.raises(RxReadRefused):
        connector.allow_read(
            "pharmacy_directory",
            target="sandbox",
            sandbox_enabled=True,
            hosted=False,
        )
