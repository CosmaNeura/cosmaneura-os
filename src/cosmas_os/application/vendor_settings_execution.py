"""Current reviewed installation fence around the existing once-ever C1 runtime."""

from sqlalchemy import select

from cosmas_os.application import vendor_settings as settings
from cosmas_os.application import workspace as ws
from cosmas_os.application.vendor_execution import VendorExecution
from cosmas_os.ports.vendor_connectors import ConnectionSelection
from cosmas_os.vendor_models import VendorConnectionVersion, VendorWorkRevision
from cosmas_os.vendor_setup_models import VendorSetupRevision


class VendorSettingsExecution(VendorExecution):
    def __init__(self, *args, installed_catalog=lambda: settings.EMPTY_CATALOG, **kwargs):
        super().__init__(*args, **kwargs)
        self.installed_catalog = installed_catalog

    def _authorize_current(self, invocation, command, approval, mutating):
        if not super()._authorize_current(invocation, command, approval, mutating):
            return False
        try:
            with self.sessions() as s:
                settings.owner(s, invocation.box_id, invocation.owner_id, writing=True)
                revision = s.scalar(
                    select(VendorSetupRevision).where(
                        VendorSetupRevision.kind == "account",
                        VendorSetupRevision.connection_version_id
                        == str(command.selection.connection_id),
                        VendorSetupRevision.box_id == invocation.box_id,
                        VendorSetupRevision.owner_id == invocation.owner_id,
                    )
                )
                if revision is None:
                    return False
                row = settings.entity(s, invocation.box_id, invocation.owner_id, revision.setup_id)
                head, current = settings.current(s, row)
                if head.state != "active" or current.id != revision.id:
                    return False
                installed = self.installed_catalog().require(
                    invocation.box_id,
                    invocation.owner_id,
                    revision.installation_id,
                    revision.installation_sha256,
                )
                expected = ConnectionSelection.model_validate(
                    {
                        **installed.selection.model_dump(mode="python"),
                        "connection_id": command.selection.connection_id,
                    }
                )
                native = s.get(VendorConnectionVersion, revision.connection_version_id)
                if mutating:
                    work = s.get(VendorWorkRevision, str(command.revision_id))
                    if work is None:
                        return False
                    if work.correspondence_version_id is not None:
                        mapping = s.scalar(
                            select(VendorSetupRevision).where(
                                VendorSetupRevision.kind == "recipient",
                                VendorSetupRevision.correspondence_version_id
                                == work.correspondence_version_id,
                                VendorSetupRevision.box_id == invocation.box_id,
                                VendorSetupRevision.owner_id == invocation.owner_id,
                            )
                        )
                        if mapping is None:
                            return False
                        mapping_head = settings.latest(s, mapping.setup_id)
                        if (
                            mapping_head is None
                            or mapping_head.state != "active"
                            or mapping_head.revision_id != mapping.id
                            or mapping.review["account"]["expected_version"] != head.version
                        ):
                            return False
                return bool(
                    native
                    and native.is_current
                    and not native.revoked_at
                    and command.selection == expected
                    and native.routing == dict(installed.routing)
                    and (native.write_enabled if mutating else native.read_enabled)
                )
        except (ws.WorkspaceError, ValueError):
            return False
