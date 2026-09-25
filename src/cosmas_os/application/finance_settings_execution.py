"""Installed-account fence layered on the qualified financial execution primitive."""

from sqlalchemy import select

from cosmas_os.application import finance_settings as settings
from cosmas_os.application import workspace as ws
from cosmas_os.application.finance_execution import FinanceExecution
from cosmas_os.finance_models import FinanceConnectionVersion, FinanceWorkRevision
from cosmas_os.finance_setup_models import FinanceSetupRevision
from cosmas_os.ports.vendor_connectors import ConnectionSelection


class FinanceSettingsExecution(FinanceExecution):
    def __init__(self, *args, installed_catalog=lambda: settings.EMPTY_CATALOG, **kwargs):
        super().__init__(*args, **kwargs)
        self.installed_catalog = installed_catalog

    def current_authority(self, invocation, command, approval, mutating):
        if not super().current_authority(invocation, command, approval, mutating):
            return False
        try:
            with self.sessions() as s:
                settings.owner(s, invocation.box_id, invocation.owner_id, writing=True)
                r = s.scalar(
                    select(FinanceSetupRevision).where(
                        FinanceSetupRevision.kind == "account",
                        FinanceSetupRevision.connection_version_id
                        == str(command.selection.connection_id),
                        FinanceSetupRevision.box_id == invocation.box_id,
                        FinanceSetupRevision.owner_id == invocation.owner_id,
                    )
                )
                if r is None:
                    return False
                row = settings.entity(s, invocation.box_id, invocation.owner_id, r.setup_id)
                head, current = settings.current(s, row)
                if head.state != "active" or current.id != r.id:
                    return False
                installed = self.installed_catalog().require(
                    invocation.box_id,
                    invocation.owner_id,
                    r.installation_id,
                    r.installation_sha256,
                )
                expected = ConnectionSelection.model_validate(
                    {
                        **installed.selection.model_dump(mode="python"),
                        "connection_id": command.selection.connection_id,
                    }
                )
                native = s.get(FinanceConnectionVersion, r.connection_version_id)
                if mutating:
                    work = s.get(FinanceWorkRevision, str(command.revision_id))
                    mapping = (
                        s.scalar(
                            select(FinanceSetupRevision).where(
                                FinanceSetupRevision.kind == "customer",
                                FinanceSetupRevision.customer_version_id
                                == work.customer_version_id,
                                FinanceSetupRevision.box_id == invocation.box_id,
                                FinanceSetupRevision.owner_id == invocation.owner_id,
                            )
                        )
                        if work
                        else None
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
                    and (native.write_enabled if mutating else native.read_enabled)
                )
        except (ws.WorkspaceError, ValueError):
            return False
