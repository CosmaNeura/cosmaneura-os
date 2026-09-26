"""Owner restrictions on two existing read purposes, never resource grants."""

from datetime import date, datetime

from sqlalchemy import select

from cosmas_os.application import provider_team as team
from cosmas_os.application import workspace as ws
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import CoreCaptureAccount, ExternalIdentity, SchedulingAccount

PURPOSES = ("core_preparation", "scheduling_context")
LABELS = {
    "core_preparation": "Current reviewed preparation account",
    "scheduling_context": "Current reviewed scheduling account",
}


def policy_present(configuration):
    return bool(
        configuration
        and (
            "model_work" in configuration
            or any("resources" in bot for bot in configuration["bots"])
        )
    )


def scope_hash(account):
    def scalar(value):
        return value.isoformat() if isinstance(value, (date, datetime)) else value

    # Every immutable correspondence/review field enters the private commitment.
    return payload_hash(
        {column.name: scalar(getattr(account, column.name)) for column in account.__table__.columns}
    )


def reference(box, owner, external_identity_id, purpose, account):
    if (
        purpose not in PURPOSES
        or account.external_identity_id != external_identity_id
        or account.revoked_at is not None
    ):
        raise ws.WorkspaceError("bot_resource_restricted")
    return payload_hash(
        {
            "domain": "team-resource.v1",
            "box": box,
            "owner": owner,
            "external_identity_id": external_identity_id,
            "purpose": purpose,
            "local_account_id": account.id,
            "scope_sha256": scope_hash(account),
        }
    )


def inventory(s, box, owner, external_identity_id):
    ws._human(s, box, owner)
    identity = (
        s.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.id == external_identity_id,
                ExternalIdentity.box_id == box,
                ExternalIdentity.principal_id == owner,
                ExternalIdentity.active.is_(True),
            )
        )
        if external_identity_id is not None
        else None
    )
    if external_identity_id is not None and identity is None:
        raise ws.WorkspaceError("workspace_access_denied", 403)
    resources = []
    if identity:
        for purpose, model in (
            ("core_preparation", CoreCaptureAccount),
            ("scheduling_context", SchedulingAccount),
        ):
            account = s.scalar(
                select(model).where(
                    model.external_identity_id == external_identity_id, model.revoked_at.is_(None)
                )
            )
            if account:
                resources.append(
                    {
                        "purpose": purpose,
                        "resource_ref": reference(
                            box, owner, external_identity_id, purpose, account
                        ),
                        "label": LABELS[purpose],
                    }
                )
    return {
        "contract_version": 1,
        "resources": resources,
        "inventory_sha256": payload_hash(resources),
    }


def require(settings, purpose, current_ref):
    resources = settings.get("resources")
    if resources is not None and not any(
        value["purpose"] == purpose and value["resource_ref"] == current_ref
        for value in resources["allowed"]
    ):
        raise ws.WorkspaceError("bot_resource_restricted")


def source(settings, purpose, current_inventory):
    resource = settings.get("resources")
    current = {value["purpose"]: value["resource_ref"] for value in current_inventory["resources"]}
    selected = (
        next(
            (value["resource_ref"] for value in resource["allowed"] if value["purpose"] == purpose),
            None,
        )
        if resource
        else None
    )
    return {
        "kind": "resource",
        "purpose": purpose,
        "mode": "inherit" if resource is None else "allow_list",
        "selection": "inherited"
        if resource is None
        else "denied"
        if selected is None
        else "current"
        if current.get(purpose) == selected
        else "unavailable",
        "inventory_sha256": current_inventory["inventory_sha256"],
    }


def validate_transition(previous, configuration, current_inventory):
    old = {team.bot_address(bot): bot for bot in previous["bots"]} if previous else {}
    current = {
        (value["purpose"], value["resource_ref"]) for value in current_inventory["resources"]
    }
    for bot in configuration["bots"]:
        existing = old.get(team.bot_address(bot), {}).get("resources", {}).get("allowed", [])
        retained = {(value["purpose"], value["resource_ref"]) for value in existing}
        for value in bot.get("resources", {}).get("allowed", []):
            binding = (value["purpose"], value["resource_ref"])
            if binding not in current and binding not in retained:
                raise ws.WorkspaceError("team_resource_changed")
