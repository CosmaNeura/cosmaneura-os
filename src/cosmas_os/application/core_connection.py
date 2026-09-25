"""Provider-confirmed reuse of Core's reviewed account correspondence."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter
from sqlalchemy import select

from cosmas_os.application import workspace as ws
from cosmas_os.models import AuditEvent, CoreCaptureAccount, ExternalIdentity
from cosmas_os.ports.athena_visit_links import AthenaVisitLinkCommand
from cosmas_os.ports.athena_schedule import AthenaCommand, AthenaScheduleRequest
from cosmas_os.ports.core_appointment_setup import AppointmentSetupCommand, AppointmentSetupRequest
from cosmas_os.ports.core_encounters import (
    AppointmentRef,
    Closed,
    ConnectionRequest,
    Digest,
    EncounterCursor,
    EncounterRequest,
    EncountersRequest,
    EncounterWindow,
)


class ConnectionCommand(Closed):
    action: Literal["connection", "connect", "encounters", "encounter", "open"]
    request_nonce: UUID
    connection_sha256: Digest | None = None
    window: EncounterWindow | None = None
    cursor: EncounterCursor | None = None
    appointment_ref: AppointmentRef | None = None
    source_sha256: Digest | None = None

    def validate_selection(self):
        present = {name for name in ("connection_sha256", "window", "cursor", "appointment_ref", "source_sha256")
                   if getattr(self, name) is not None}
        expected = {"connection":set(), "connect":{"connection_sha256"},
            "encounters":{"connection_sha256", "window"},
            "encounter":{"connection_sha256", "appointment_ref", "source_sha256"},
            "open":{"connection_sha256", "appointment_ref", "source_sha256"}}[self.action]
        if present - ({"cursor"} if self.action == "encounters" else set()) != expected:
            raise ws.WorkspaceError("invalid_core_connection_request", 422)


COMMAND_ADAPTER = TypeAdapter(Annotated[ConnectionCommand | AthenaCommand | AppointmentSetupCommand | AthenaVisitLinkCommand, Field(discriminator="action")])


def execute(session, *, identity, command, tenant_ref, bearer, port, reauthenticate, budget):
    if isinstance(command, ConnectionCommand):
        command.validate_selection()
    athena_link = isinstance(command, AthenaVisitLinkCommand)
    athena = isinstance(command, AthenaCommand)
    setup = isinstance(command, AppointmentSetupCommand)

    def current():
        budget.check()
        session.expire_all()
        reauthenticate()
        ws._human(session, identity.box_id, identity.principal_id, creating=command.action in {"connect", "open", "athena_visit_link", "athena_visit_unlink"})
        local = session.scalar(select(ExternalIdentity).where(
            ExternalIdentity.id == identity.external_identity_id,
            ExternalIdentity.box_id == identity.box_id,
            ExternalIdentity.principal_id == identity.principal_id,
            ExternalIdentity.active.is_(True),
        ).with_for_update())
        if local is None:
            raise ws.WorkspaceError("core_connection_access_denied", 403)
        active = session.scalar(select(CoreCaptureAccount).where(
            CoreCaptureAccount.external_identity_id == local.id,
            CoreCaptureAccount.revoked_at.is_(None),
        ).with_for_update())
        retired = session.scalar(select(CoreCaptureAccount.id).where(
            CoreCaptureAccount.external_identity_id == local.id,
            CoreCaptureAccount.revoked_at.is_not(None),
        ).limit(1))
        state = (local.id, local.issuer, local.subject,
            None if active is None else (active.id, active.core_actor_ref, active.core_tenant_ref),
            retired is not None)
        return state, active

    before, account = current()
    if athena_link or athena or setup or command.action in {"encounters", "encounter", "open"}:
        if account is None or account.core_tenant_ref != tenant_ref:
            raise ws.WorkspaceError("core_connection_required", 409)
        args = dict(expected_tenant_ref=tenant_ref, expected_actor_ref=account.core_actor_ref,
                    connection_sha256=command.connection_sha256, request_nonce=command.request_nonce)
        if athena_link:
            request = command.as_core(tenant_ref, account.core_actor_ref)
        elif setup:
            request = AppointmentSetupRequest.model_validate({**args,
                "action":"preview" if command.action == "appointment_setup_preview" else "connect",
                "window":command.window, "cursor":command.cursor, "plan_sha256":command.plan_sha256})
        elif athena:
            request = AthenaScheduleRequest.model_validate({**args,
                "action":"connection" if command.action == "athena_connection" else "appointments",
                "account_sha256":command.account_sha256, "start_date":command.start_date,
                "end_date":command.end_date, "offset":command.offset or 0})
        elif command.action == "encounters":
            request = EncountersRequest.model_validate({**args, "window":command.window, "cursor":command.cursor})
        else:
            request = EncounterRequest.model_validate({**args, "appointment_ref":command.appointment_ref,
                                       "source_sha256":command.source_sha256})
    else:
        request = ConnectionRequest(expected_tenant_ref=tenant_ref, request_nonce=command.request_nonce)
    # No local identity/account locks are held across the remote Core operation.
    session.commit()
    if athena_link:
        result = port.athena_visit_link(request, bearer)
    elif setup:
        result = port.setup_appointments(request, bearer)
    else:
        result = port.read_athena(request, bearer) if athena else port.read(request, bearer)
    after, account = current()
    if after != before:
        raise ws.WorkspaceError("core_connection_changed", 409)
    matches = account is not None and (
        account.core_actor_ref, account.core_tenant_ref
    ) == (result.connection.actor_ref, result.connection.tenant_ref)
    status = "connected" if matches else "review_required" if account is not None or before[4] else "ready_to_connect"
    if command.action == "connect":
        if command.connection_sha256 != result.connection.connection_sha256:
            raise ws.WorkspaceError("core_connection_changed", 409)
        if status == "review_required":
            # A user confirmation cannot reverse an administrative revocation or
            # remap a prior reviewed correspondence to another actor/practice.
            raise ws.WorkspaceError("core_connection_review_required", 409)
        if account is None:
            account = CoreCaptureAccount(external_identity_id=identity.external_identity_id,
                core_actor_ref=result.connection.actor_ref, core_tenant_ref=result.connection.tenant_ref,
                reviewed_by="Core reviewed correspondence; confirmed by provider",
                evidence_ref="core-connection:v1:"+result.connection.connection_sha256,
                reviewed_at=result.checked_at)
            session.add(account)
            session.flush()
            session.add(AuditEvent(box_id=identity.box_id, aggregate_type="core_capture_account",
                aggregate_id=account.id, event_type="workspace.core_account_connected",
                actor_principal_id=identity.principal_id, outcome="connected",
                detail={"connection_sha256":result.connection.connection_sha256}))
            budget.check()
            session.commit()
        status = "connected"
    if (athena_link or athena or setup or command.action in {"encounters", "encounter", "open"}) and not matches:
        raise ws.WorkspaceError("core_connection_changed", 409)
    budget.check()
    if athena_link:
        return {"contract_version":1,"action":command.action,"connection_status":status,"athena_visit_link":result.model_dump(mode="json")}
    if setup:
        return {"contract_version":1, "action":command.action,
                "connection_status":status, "appointment_setup":result.model_dump(mode="json")}
    if athena:
        return {"contract_version":1, "action":command.action,
                "connection_status":status, "athena_discovery":result.model_dump(mode="json")}
    response = {"contract_version":1, "action":command.action,
            "connection_status":status, "discovery":result.model_dump(mode="json")}
    if command.action == "open":
        from cosmas_os.application.core_workspace import open_selected
        response["workspace"] = open_selected(session, identity=identity, account=account,
                                              discovery=result, budget=budget)
    return response
