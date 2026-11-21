"""Copy-to-EHR profiles. Dict lookup only; never registered in VendorRegistry."""

from __future__ import annotations

from typing import get_args

from cosmas_os.application.ehr_export.types import EhrExportProfile, EhrExportProfileId
from cosmas_os.plugins.ehr.manifest import VendorId

PROFILES: dict[EhrExportProfileId, EhrExportProfile] = {
    "generic": EhrExportProfile(
        id="generic",
        display_name="Generic",
    ),
    "atlas_md": EhrExportProfile(
        id="atlas_md",
        display_name="Atlas.md",
    ),
}


def get_profile(profile_id: EhrExportProfileId | str) -> EhrExportProfile:
    """Return the copy profile for ``profile_id`` or raise ``KeyError``."""
    try:
        return PROFILES[profile_id]  # type: ignore[index]
    except KeyError as exc:
        raise KeyError("unknown_ehr_export_profile") from exc


def copy_profile_for_vendor(vendor_id: VendorId | str | None) -> EhrExportProfile:
    """Map a vendor id to its copy profile; fall back to ``generic``.

    Track D uses this when a visit needs the copy strip after a failed send.
    """
    if vendor_id is not None and vendor_id in PROFILES:
        return PROFILES[vendor_id]  # type: ignore[index]
    return PROFILES["generic"]


def known_vendor_profile_ids() -> frozenset[str]:
    """Non-generic export profile ids (must be members of ``VendorId``)."""
    return frozenset(profile_id for profile_id in PROFILES if profile_id != "generic")


def manifest_vendor_ids() -> frozenset[str]:
    """Public accessor over ``VendorId`` literals from the EHR manifest."""
    return frozenset(get_args(VendorId))
