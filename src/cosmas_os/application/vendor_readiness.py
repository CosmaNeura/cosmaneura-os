"""Account-only fax setup counts; never reads recipients or contacts a service."""

from dataclasses import dataclass

from sqlalchemy import select

from cosmas_os.api import vendor_setup_schemas as schema
from cosmas_os.api.vendor_work_schemas import bounded, public_digest
from cosmas_os.application import vendor_settings as setup
from cosmas_os.application.workspace import WorkspaceError
from cosmas_os.vendor_setup_models import VendorSetup

PROVIDERS = ("spruce", "srfax", "documo", "efax")


@dataclass(frozen=True)
class FaxReadinessConfiguration:
    work_enabled: bool = False
    delivery_enabled: bool = False
    credential_access_configured: bool = False
    document_storage_configured: bool = False

    def __post_init__(self):
        if any(type(value) is not bool for value in vars(self).values()):
            raise ValueError("Explicit fax configuration flags required")


def readiness(s, box, actor, installed=setup.EMPTY_CATALOG, *,
              policy=setup.DEFAULT_POLICY, configuration=FaxReadinessConfiguration()):
    setup.owner(s, box, actor)
    counts = {vendor: {
        "id": vendor, "installed_accounts": 0, "active_accounts": 0,
        "review_required_accounts": 0, "unavailable_accounts": 0,
        "prepare_enabled_accounts": 0,
    } for vendor in PROVIDERS}
    for item in installed.installations.values():
        selection = item.selection
        if ((str(selection.box_id), str(selection.owner_id)) == (box, actor)
                and selection.vendor + "_fax" in item.capabilities):
            counts[selection.vendor]["installed_accounts"] += 1
    # Do not use the settings catalog: it also retrieves patient destinations.
    rows = list(s.scalars(select(VendorSetup).where(
        VendorSetup.box_id == box, VendorSetup.owner_id == actor,
        VendorSetup.kind == "account",
    ).order_by(VendorSetup.id).limit(51)))
    if len(rows) > 50:
        setup.error("vendor_setup_limit")
    for row in rows:
        h, revision = setup.current(s, row)
        review = schema.AccountReview.model_validate(revision.review).public()
        if public_digest("cosmas-vendor-setup-review.v1", review) != revision.review_sha256:
            setup.error("vendor_setup_integrity", 503)
        vendor = review["installed"]["vendor"]
        if vendor + "_fax" not in review["installed"]["capabilities"]:
            continue
        count = counts[vendor]
        view = setup.summary(s, row, h, revision, installed, policy)
        if view["usable_locally"]:
            try:
                # Reuse the same installation, current-binding and permission checks
                # as account setup. This performs only local account reads.
                setup.account_current(s, box, actor, schema.Binding(
                    setup_id=row.id, expected_version=h.version,
                    revision_id=revision.id, review_sha256=revision.review_sha256,
                ), installed)
            except WorkspaceError:
                count["unavailable_accounts"] += 1
                continue
            count["active_accounts"] += 1
            permissions = review["permissions"]
            if permissions["prepare_and_submit"] and vendor + "_fax" in permissions["actions"]:
                count["prepare_enabled_accounts"] += 1
        elif h.state == "pending_review" and view["availability"] == "available":
            count["review_required_accounts"] += 1
        else:
            count["unavailable_accounts"] += 1
    setup.fence(s)
    return bounded({
        "contract_version": 1, "scope": setup.scope(box, actor), "enabled": policy.enabled,
        **vars(configuration), "providers": list(counts.values()),
    }, 4096)
