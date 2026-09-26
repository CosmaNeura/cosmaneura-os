"""Missing private bytes cannot reach credentials or a portal preparer."""

import pytest
from tests.unit.test_vendor_connector_foundation import command, document, fixture, submit
from tests.unit.test_vendor_portal_contract import SyntheticInMemoryPortal, upload_command

from cosmas_os.adapters.vendor_connectors.portals import PortalBinding, PortalRegistry
from cosmas_os.ports.vendor_connectors import MediaUploadIntent, PreparedPortalRequest, VendorError


@pytest.mark.asyncio
async def test_missing_spruce_upload_bytes_fail_before_any_authority_or_credential():
    selected = command("spruce", MediaUploadIntent(document=document()))
    connector, seen = fixture(selected)
    with pytest.raises(VendorError, match="artifact_changed"):
        await submit(connector, selected, data=None)
    assert seen.calls == [] and seen.credentials == seen.authorities == 0


def test_missing_portal_bytes_fail_before_pure_preparer(monkeypatch):
    implementation = SyntheticInMemoryPortal()
    registry = PortalRegistry((PortalBinding(implementation.profile, implementation),))

    def forbidden(*args):
        raise AssertionError("No preparer may receive missing document bytes")

    monkeypatch.setattr(implementation, "prepare", forbidden)
    selected = upload_command(implementation.profile)
    with pytest.raises(VendorError, match="artifact_changed"):
        registry.prepare(selected, None)
    with pytest.raises(VendorError, match="artifact_changed"):
        PreparedPortalRequest(
            command=selected, profile_sha256=implementation.profile.commitment(), document=None
        )
    assert implementation.effects == []
