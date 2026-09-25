"""Managed C1 selection checks, without credential resolution or provider I/O."""

from sqlalchemy import select

from cosmas_os.application import vendor_settings as setup
from cosmas_os.application import vendor_work as work
from cosmas_os.ports.vendor_connectors import ConnectionSelection
from cosmas_os.vendor_models import VendorConnectionVersion
from cosmas_os.vendor_setup_models import VendorSetup, VendorSetupRevision


def managed(s, connection_id):
    return s.scalar(
        select(VendorSetupRevision).where(
            VendorSetupRevision.kind == "account",
            VendorSetupRevision.connection_version_id == str(connection_id),
        )
    )


def require(s, w, connection_id, catalog, *, mutating=True):
    revision = managed(s, connection_id)
    if revision is None:
        return False  # Explicit pre-existing local C1 installation, not managed setup.
    if type(catalog) is not setup.Catalog:
        work.error("vendor_selection_changed")
    try:
        # C1 owns the human/workspace serialization. A read must not upgrade its
        # shared owner lock, which would deadlock concurrent availability reads.
        setup.owner(s, w.box_id, w.owner_id)
        if (revision.box_id, revision.owner_id) != (w.box_id, w.owner_id):
            work.error("vendor_selection_changed")
        row = s.get(VendorSetup, revision.setup_id)
        if row is None or (row.box_id, row.owner_id) != (w.box_id, w.owner_id):
            work.error("vendor_selection_changed")
        head, current = setup.current(s, row)
        if head.state != "active" or current.id != revision.id:
            work.error("vendor_selection_changed")
        installed = catalog.require(
            w.box_id, w.owner_id, revision.installation_id, revision.installation_sha256
        )
        native = s.get(VendorConnectionVersion, str(connection_id))
        expected = ConnectionSelection.model_validate(
            {**installed.selection.model_dump(mode="python"), "connection_id": str(connection_id)}
        )
        if (
            native is None
            or not native.is_current
            or native.revoked_at
            or not (native.write_enabled if mutating else native.read_enabled)
            or ConnectionSelection.model_validate(native.private_selection) != expected
            or native.private_sha256 != expected.commitment()
            or native.routing != dict(installed.routing)
        ):
            work.error("vendor_selection_changed")
    except (setup.ws.WorkspaceError, ValueError):
        work.error("vendor_selection_changed")
    return True


def runtime_matches(s, connection_id, runtime):
    # Exact classes only. A subclass cannot replace an authority check at this seam.
    from cosmas_os.application.vendor_execution import VendorExecution
    from cosmas_os.application.vendor_settings_execution import VendorSettingsExecution

    expected = VendorSettingsExecution if managed(s, connection_id) else VendorExecution
    return type(runtime) is expected
