"""Private, versioned Provider Team templates using existing agent principals."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from cosmas_os.api.team_schemas import TeamConfiguration
from cosmas_os.application.workspace import WorkspaceError, _human
from cosmas_os.config import settings as runtime_settings
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.models import AuditEvent, Principal, ProviderBot, ProviderTeamRevision
from cosmas_os.ports.bot_capabilities import (
    BASELINE_ROLES,
    CUSTOM_BOT,
    CUSTOM_SKILLS,
    ROLE_TEMPLATES,
    TEMPLATE_VERSION,
)

BOT_DEFINITIONS = {**ROLE_TEMPLATES, "custom": CUSTOM_BOT}


def bot_address(settings):
    return settings.get("instance_id") or settings["role"]


def configuration_value(configuration):
    result = TeamConfiguration.model_validate(configuration).model_dump(mode="json")
    if result.get("practice_profile") and not any(value for key, value in result["practice_profile"].items() if key != "version"):
        result.pop("practice_profile")
    # Preserve the exact v1 representation/digest for old requests and retries.
    for bot in result["bots"]:
        for field in ("instance_id", "job_focus", "working_preferences", "retired", "skills", "blocked_capabilities", "resources"):
            if not bot.get(field):
                bot.pop(field, None)
        if bot.get("blocked_capabilities"):
            order = ("model_answer", "private_draft_handoff", "practice_work_brief")
            bot["blocked_capabilities"].sort(key=order.index)
        if "resources" in bot:
            bot["resources"]["allowed"].sort(key=lambda item: item["purpose"])
    if not result["presets"]:
        del result["presets"]
    else:
        order = ("provider", "front_desk", "practice_manager")
        result["presets"].sort(key=lambda item: order.index(item["preset_id"]))
    return result


def blocked(settings, capability):
    return capability in settings.get("blocked_capabilities", ())


def default_configuration():
    return configuration_value(
        {
            "practice_context": "Direct Primary Care",
            "bots": [
                {"role": role, "name": template["name"], "enabled": True}
                for role, template in ROLE_TEMPLATES.items() if role in BASELINE_ROLES
            ],
        }
    )


def starter_configuration(box: str, owner: str):
    """Offer a stable private Research identity without installing any agents."""
    configuration = default_configuration()
    # This deterministic UUID-shaped address is not a credential or an access
    # grant. Its separate domain and owner scope keep repeated unsaved reads
    # stable while the ordinary explicit save creates the actual principals.
    instance_id = str(UUID(hex=payload_hash({
        "contract": "provider-team-starter-research.v1", "box": box, "owner": owner,
    })[:32], version=4))
    configuration["bots"].append({
        "role": "research", "name": ROLE_TEMPLATES["research"]["name"],
        "instance_id": instance_id, "enabled": True,
    })
    return configuration_value(configuration)


def current(s: Session, box: str, owner: str):
    return s.scalar(
        select(ProviderTeamRevision)
        .where(
            ProviderTeamRevision.box_id == box,
            ProviderTeamRevision.owner_id == owner,
        )
        .order_by(ProviderTeamRevision.revision.desc())
        .limit(1)
    )


def read(s: Session, box: str, owner: str, *, version: ProviderTeamRevision | None = None):
    _human(s, box, owner)
    version = version or current(s, box, owner)
    config = version.configuration if version else starter_configuration(box, owner)
    members = {
        bot.instance_id or bot.role: bot.agent_id
        for bot in s.scalars(
            select(ProviderBot).where(
                ProviderBot.box_id == box,
                ProviderBot.owner_id == owner,
            )
        )
    }
    llm_enabled = runtime_settings.workspace_llm_available
    capture_enabled = runtime_settings.workspace_capture_available
    notes_enabled = capture_enabled and runtime_settings.workspace_capture_notes_enabled
    corrections_enabled = notes_enabled and runtime_settings.workspace_capture_corrections_enabled
    templates = {}
    for role, template in BOT_DEFINITIONS.items():
        capabilities = [dict(c) for c in template["capabilities"] if c["key"] != "assistant.answer"]
        if role == "research":
            for capability in capabilities:
                if capability["key"] == "research.public.read":
                    capability["state"] = "enabled" if (runtime_settings.workspace_research_available
                        and runtime_settings.workspace_research_io_enabled) else "awaiting_connection"
        if role == "scribe":
            for capability in capabilities:
                if capability["key"] in {"scribe.capture", "scribe.transcript.read"}:
                    capability["state"] = "enabled" if capture_enabled else "awaiting_connection"
                elif capability["key"] == "core.note.draft":
                    capability["state"] = "enabled" if notes_enabled else "awaiting_connection"
                if capability["key"] == "scribe.transcript.read" and not corrections_enabled:
                    capability["label"] = "Visit transcript"
        if role == "visit_prep":
            for capability in capabilities:
                if capability["key"] == "core.session_prep.read":
                    capability["label"] = "Saved intake and prior visit drafts"
                    capability["state"] = "enabled" if capture_enabled and runtime_settings.workspace_prep_enabled else "awaiting_connection"
                    capability["contract"] = "core.encounter-context.v1"
                    if runtime_settings.workspace_session_prep_available:
                        capability.update(label="Session Prep brief", state="enabled",
                                          contract="core.session-prep.brief.v1")
        capabilities.append(
            {
                "key": "assistant.answer",
                "label": "GPT-4.1 conversation",
                "state": "enabled" if llm_enabled else "awaiting_connection",
                "connector": "CosmasCode · GPT-4.1",
                "contract": "openai.chat.completions.v1",
            }
        )
        if role == "chief":
            capabilities.append({"key": "workspace.draft.handoff", "label": "Private bot draft handoffs",
                "state": "enabled" if llm_enabled else "awaiting_connection",
                "connector": "Provider Team", "contract": "workspace.draft.handoff.v1"})
            capabilities.append({"key": "workspace.clinical.drafts", "label": "Saved-note drafts with provider directions",
                "state": "enabled" if llm_enabled else "awaiting_connection",
                "connector": "Provider Team", "contract": "clinical-team-drafts.request.v2"})
        templates[role] = {"role": role, "agent_id": None, **template, "capabilities": capabilities}
    skills = [{"key": key, **value} for key, value in CUSTOM_SKILLS.items()]
    for skill in skills:
        if skill["key"] == "inbox_review":
            skill["state"] = "enabled" if (runtime_settings.inbox_work_enabled and runtime_settings.workspace_llm_available) else "awaiting_connection"
        elif skill["key"] == "membership_review":
            skill["state"] = "enabled" if ((runtime_settings.membership_work_enabled or runtime_settings.finance_work_enabled) and runtime_settings.workspace_llm_available) else "awaiting_connection"
        elif skill["key"] == "encounter_prep":
            skill["state"] = "enabled" if capture_enabled and runtime_settings.workspace_prep_enabled else "awaiting_connection"
        elif skill["key"] == "calendar_availability":
            skill["state"] = "enabled" if runtime_settings.workspace_scheduling_available else "awaiting_connection"

    def member(bot):
        descriptor = {**templates[bot["role"]], "agent_id": members.get(bot_address(bot)),
                      **({"instance_id": bot["instance_id"]} if bot.get("instance_id") else {})}
        if bot["role"] == "chief":
            descriptor["capabilities"] = [dict(capability) for capability in descriptor["capabilities"]]
            for capability in descriptor["capabilities"]:
                if capability["key"] == "workspace.clinical.drafts":
                    capability["state"] = "enabled" if (llm_enabled and bot["enabled"] and not bot.get("retired")
                        and bot.get("include_evidence", True) and not blocked(bot, "model_answer")
                        and not blocked(bot, "private_draft_handoff")) else "awaiting_connection"
        if bot["role"] == "custom":
            descriptor.update(name=bot["name"], description=bot["job_focus"],
                capabilities=[skill for skill in skills if skill["key"] in bot.get("skills", ())]
                             + templates["custom"]["capabilities"])
        return descriptor

    return {
        "revision": version.revision if version else 0,
        "template_version": version.template_version if version else TEMPLATE_VERSION,
        "configuration": config,
        "members": [member(bot) for bot in config["bots"]],
        "templates": [template for role, template in templates.items() if role not in {"chief", "custom"}],
        "custom_skills": skills,
        "llm": {"enabled": llm_enabled, "model": "gpt-4.1"},
        "scheduling": {"enabled": runtime_settings.workspace_scheduling_available},
        "capture": {"enabled": capture_enabled,
                    "prep_enabled": capture_enabled and runtime_settings.workspace_prep_enabled,
                    "prep_work_enabled": capture_enabled and runtime_settings.workspace_prep_enabled and runtime_settings.workspace_prep_work_enabled,
                    "notes_enabled": notes_enabled,
                    "corrections_enabled": corrections_enabled},
    }


def save(s: Session, box: str, owner: str, *, expected: int, key: str, configuration: dict,
         setup_review=None, external_identity_id=None, team_contract: int = 0):
    from cosmas_os.application import team_setup
    # Serialize creation/configuration and hold the same owner lock read by chat.
    _human(s, box, owner, creating=True)
    configuration = configuration_value(configuration)
    previous = current(s, box, owner)
    team_setup.require_compatible(team_contract, previous.configuration if previous else None, configuration)
    command = {"expected": expected, "configuration": configuration}
    if setup_review is not None:
        command["setup_review"] = setup_review
    digest = payload_hash(command)
    replay = s.scalar(
        select(ProviderTeamRevision).where(
            ProviderTeamRevision.box_id == box,
            ProviderTeamRevision.owner_id == owner,
            ProviderTeamRevision.idempotency_key == key,
        )
    )
    if replay:
        if replay.request_hash != digest:
            raise WorkspaceError("idempotency_conflict")
        return read(s, box, owner, version=replay)
    revision = previous.revision if previous else 0
    if revision != expected:
        raise WorkspaceError("team_revision_conflict")
    if revision >= 100:
        raise WorkspaceError("team_history_limit")
    team_setup.validate_transition(previous.configuration if previous else None, configuration)
    if setup_review is not None or team_setup.review_required(previous.configuration if previous else None, configuration):
        team_setup.available()
        if setup_review is None:
            raise WorkspaceError("team_setup_review_required")
        team_setup.verify_review(s, box, owner, external_identity_id, previous, configuration, setup_review)
    if previous and not {bot_address(bot) for bot in previous.configuration["bots"]} <= {
        bot_address(bot) for bot in configuration["bots"]
    }:
        raise WorkspaceError("team_member_missing", 409)
    members = {
        bot.instance_id or bot.role: bot
        for bot in s.scalars(
            select(ProviderBot).where(
                ProviderBot.box_id == box,
                ProviderBot.owner_id == owner,
            )
        )
    }
    prior_settings = {bot_address(bot): bot for bot in previous.configuration["bots"]} if previous else {}
    # Validate retirement transitions before touching any principal. A saved
    # retirement is permanent; old client payloads cannot silently resurrect it.
    for settings in configuration["bots"]:
        address = bot_address(settings)
        prior = prior_settings.get(address)
        if prior and prior.get("retired") and settings != prior:
            raise WorkspaceError("team_member_retired", 409)
        if settings.get("retired") and address not in members:
            raise WorkspaceError("team_member_unavailable", 409)
    for settings in configuration["bots"]:
        role = settings["role"]
        address = bot_address(settings)
        if address not in members:
            principal = Principal(
                box_id=box,
                principal_type="agent",
                display_name=BOT_DEFINITIONS[role]["name"],
                agent_key="provider_" + role,
                is_owner=False,
            )
            s.add(principal)
            s.flush()
            s.add(ProviderBot(agent_id=principal.id, box_id=box, owner_id=owner, role=role,
                              instance_id=settings.get("instance_id")))
        else:
            if members[address].role != role:
                raise WorkspaceError("team_template_immutable", 409)
            principal = s.get(Principal, members[address].agent_id)
            if (
                principal is None
                or principal.principal_type != "agent"
            ):
                raise WorkspaceError("team_member_unavailable")
            if prior_settings.get(address, {}).get("retired"):
                if principal.tombstoned_at is None or principal.state != "disabled":
                    raise WorkspaceError("team_member_unavailable")
                continue
            if principal.tombstoned_at is not None:
                raise WorkspaceError("team_member_unavailable")
        if settings.get("retired"):
            principal.tombstoned_at = datetime.now(UTC)
            s.add(AuditEvent(box_id=box, aggregate_type="provider_team", aggregate_id=principal.id,
                event_type="provider_team.bot_retired", actor_principal_id=owner, outcome="retired",
                detail={"revision": revision + 1}))
        # Organization principal listings must not expose private custom names.
        principal.display_name = BOT_DEFINITIONS[role]["name"]
        principal.state = "active" if settings["enabled"] else "disabled"
        principal.config_version = f"provider-team-{revision + 1}"
    version = ProviderTeamRevision(
        box_id=box,
        owner_id=owner,
        revision=revision + 1,
        template_version=TEMPLATE_VERSION,
        configuration=configuration,
        idempotency_key=key,
        request_hash=digest,
    )
    s.add(version)
    s.flush()
    s.add(
        AuditEvent(
            box_id=box,
            aggregate_type="provider_team",
            aggregate_id=version.id,
            event_type="provider_team.configured",
            actor_principal_id=owner,
            outcome="saved",
            detail={"revision": version.revision},
        )
    )
    s.commit()
    return read(s, box, owner, version=version)


def active_bot(s: Session, box: str, owner: str, role: str, expected: int):
    version = current(s, box, owner)
    if not version or version.revision != expected:
        raise WorkspaceError("team_revision_conflict")
    settings = next((b for b in version.configuration["bots"] if bot_address(b) == role), None)
    if settings is None:
        raise WorkspaceError("bot_paused", 409)
    if role not in ROLE_TEMPLATES:
        try:
            if str(UUID(role)) != role:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise WorkspaceError("bot_paused", 409) from None
    bot = s.scalar(
        select(ProviderBot).where(
            ProviderBot.box_id == box,
            ProviderBot.owner_id == owner,
            ProviderBot.role == settings["role"],
            ProviderBot.instance_id == settings.get("instance_id"),
        )
    )
    principal = (
        s.scalar(
            select(Principal)
            .where(
                Principal.id == bot.agent_id,
                Principal.box_id == box,
                Principal.principal_type == "agent",
                Principal.state == "active",
                Principal.tombstoned_at.is_(None),
            )
            .with_for_update(read=True)
        )
        if bot
        else None
    )
    if bot is None or settings.get("retired") or not settings["enabled"] or principal is None:
        raise WorkspaceError("bot_paused", 409)
    return version, bot, settings


def address_for_agent(s: Session, box: str, owner: str, agent_id: str):
    bot = s.scalar(select(ProviderBot).where(ProviderBot.agent_id == agent_id,
        ProviderBot.box_id == box, ProviderBot.owner_id == owner))
    if bot is None:
        raise WorkspaceError("team_member_unavailable")
    return bot.instance_id or bot.role
