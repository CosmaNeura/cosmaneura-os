"""Explicit chart-free physician review; local grants do not grant Core access."""

from sqlalchemy import select

from cosmas_os.application import provider_team, team_resources
from cosmas_os.application import workspace as ws
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity
from cosmas_os.ports.bot_capabilities import ConnectorUnavailable
from cosmas_os.ports.core_visit_prep import CoreVisitPrepRead, CoreVisitPrepReceipt


def read(session, *, identity, command, tenant_ref, bearer, port, reauthenticate, budget):
    def scope():
        budget.check()
        session.expire_all()
        reauthenticate()
        ws._human(session, identity.box_id, identity.principal_id)
        local = session.scalar(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.id == identity.external_identity_id,
                ExternalIdentity.box_id == identity.box_id,
                ExternalIdentity.principal_id == identity.principal_id,
                ExternalIdentity.active.is_(True),
            )
            .with_for_update(read=True)
        )
        account = session.scalar(
            select(CoreCaptureAccount)
            .where(
                CoreCaptureAccount.external_identity_id == identity.external_identity_id,
                CoreCaptureAccount.revoked_at.is_(None),
            )
            .with_for_update(read=True)
        )
        _, member, settings = provider_team.active_bot(
            session,
            identity.box_id,
            identity.principal_id,
            command.bot.address,
            command.bot.team_revision,
        )
        if (
            local is None
            or account is None
            or account.core_tenant_ref != tenant_ref
            or settings["role"] != "visit_prep"
            or not settings["include_evidence"]
        ):
            raise ws.WorkspaceError("visit_prep_access_denied", 403)
        resource = team_resources.reference(
            identity.box_id, identity.principal_id, local.id, "core_preparation", account
        )
        team_resources.require(settings, "core_preparation", resource)
        return (
            local.id,
            local.issuer,
            local.subject,
            account.core_actor_ref,
            account.core_tenant_ref,
            account.evidence_ref,
            resource,
            member.agent_id,
        )

    before = scope()
    request = CoreVisitPrepRead(
        preparation_ref=command.preparation_ref,
        expected_actor_ref=before[3],
        expected_tenant_ref=before[4],
        connection_sha256=command.connection_sha256,
        workspace_id=command.workspace_id,
        request_nonce=command.request_nonce,
    )
    session.commit()  # Release local locks before HTTP; no clinical bytes are saved.
    try:
        receipt = port.read(request, bearer)
    except ConnectorUnavailable as error:
        raise ws.WorkspaceError(
            "visit_prep_unavailable", 403 if str(error) == "visit_prep_access_denied" else 503
        ) from None
    if scope() != before:
        raise ws.WorkspaceError("visit_prep_access_denied", 403)
    body = receipt.model_dump_json().encode("utf-8")
    receipt = CoreVisitPrepReceipt.model_validate_json(body, strict=True)
    if len(body) > 262144 or (
        receipt.preparation_ref,
        receipt.connection_sha256,
        receipt.workspace_id,
        receipt.request_nonce,
    ) != (
        request.preparation_ref,
        request.connection_sha256,
        request.workspace_id,
        request.request_nonce,
    ):
        raise ws.WorkspaceError("visit_prep_unavailable", 503)
    budget.check()
    session.commit()
    budget.check()
    return body
