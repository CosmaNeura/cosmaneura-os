"""Private local prerequisite projection and invented rehearsal; no effect ports."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

from sqlalchemy import select

from cosmas_os.application import provider_team as team
from cosmas_os.application import team_resources
from cosmas_os.application import workspace as ws
from cosmas_os.models import (
    CoreCaptureAccount,
    ExternalIdentity,
    Principal,
    ProviderBot,
    SchedulingAccount,
)
from cosmas_os.ports.bot_capabilities import BASELINE_ROLES, ROLE_TEMPLATES, supports_skill

CONTRACT = "private-team-presets.v1"
CATALOG_VERSION = 1
MAX_REQUEST_BYTES = 4_194_304
MAX_RESPONSE_BYTES = 8_388_608
CAPABILITIES = (
    "saved_notebook",
    "saved_evidence",
    "work_status",
    "model_answer",
    "private_draft_handoff",
    "practice_work_brief",
    "encounter_prep",
    "consented_capture",
    "clinical_note",
    "transcript_correction",
    "calendar_availability",
    "staff_handoff",
    "inbox_operations",
    "membership_billing",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def available():
    if (
        not team.runtime_settings.workspace_available
        or not team.runtime_settings.workspace_team_setup_enabled
    ):
        raise ws.WorkspaceError("team_setup_unavailable", 404)


def enhanced(configuration):
    return bool(
        configuration
        and (
            team_resources.policy_present(configuration)
            or configuration.get("presets")
            or any(bot.get("blocked_capabilities") for bot in configuration["bots"])
        )
    )


def inbox_configuration(configuration):
    return bool(configuration and (
        any("inbox_review" in bot.get("skills", ()) for bot in configuration["bots"])
        or any(preset["preset_id"] == "front_desk" and preset["version"] == 2 for preset in configuration.get("presets", ()))
    ))


def membership_configuration(configuration):
    return bool(configuration and (
        any("membership_review" in bot.get("skills", ()) for bot in configuration["bots"])
        or any(p["preset_id"] == "practice_manager" and p["version"] == 2 for p in configuration.get("presets", ()))
    ))


def require_compatible(compatible, *configurations):
    if compatible < 4 and any(membership_configuration(value) for value in configurations):
        raise ws.WorkspaceError("team_contract_required", 426)
    if compatible < 3 and any(inbox_configuration(value) for value in configurations):
        raise ws.WorkspaceError("team_contract_required", 426)
    if compatible < 2 and any(
        team_resources.policy_present(configuration) for configuration in configurations
    ):
        raise ws.WorkspaceError("team_contract_required", 426)
    if not compatible and any(enhanced(configuration) for configuration in configurations):
        raise ws.WorkspaceError("team_contract_required", 426)


def validate_transition(previous, configuration):
    if not previous:
        return
    old_bots = {team.bot_address(bot): bot for bot in previous["bots"]}
    new_bots = {team.bot_address(bot): bot for bot in configuration["bots"]}
    bindings = {preset["preset_id"]: preset for preset in configuration.get("presets", ())}
    previous_ids = {preset["preset_id"] for preset in previous.get("presets", ())}
    for preset in configuration.get("presets", ()):
        if preset["preset_id"] not in previous_ids and preset["preset_id"] != "provider":
            if any(
                address in old_bots for slot, address in preset["slots"].items() if slot != "chief"
            ):
                raise ws.WorkspaceError("team_preset_binding_immutable")
    for prior in previous.get("presets", ()):
        current = bindings.get(prior["preset_id"])
        if current is None:
            raise ws.WorkspaceError("team_preset_missing")
        if current["version"] != prior["version"] and not (
            prior["preset_id"] in {"front_desk", "practice_manager"} and prior["version"] == 1 and current["version"] == 2
        ):
            raise ws.WorkspaceError("team_catalog_changed")
        for slot, address in prior["slots"].items():
            target = current["slots"][slot]
            if target == address:
                continue
            if (
                address not in old_bots
                or not old_bots[address].get("retired")
                or target in old_bots
                or target not in new_bots
                or new_bots[target]["role"] != "custom"
                or new_bots[target].get("retired")
            ):
                raise ws.WorkspaceError("team_preset_binding_immutable")


def review_required(previous, configuration):
    previous = previous or {"bots": []}
    for skill in ("membership_review",):
        if {team.bot_address(b) for b in previous["bots"] if skill in b.get("skills", ())} != {team.bot_address(b) for b in configuration["bots"] if skill in b.get("skills", ())}:
            return True
    old_inbox = {team.bot_address(bot) for bot in previous["bots"] if "inbox_review" in bot.get("skills", ())}
    new_inbox = {team.bot_address(bot) for bot in configuration["bots"] if "inbox_review" in bot.get("skills", ())}
    if old_inbox != new_inbox:
        return True
    if previous.get("model_work") != configuration.get("model_work"):
        return True
    old_resources = {team.bot_address(bot): bot.get("resources") for bot in previous["bots"]}
    if any(
        old_resources.get(team.bot_address(bot)) != bot.get("resources")
        for bot in configuration["bots"]
    ):
        return True
    if previous.get("presets", []) != configuration.get("presets", []):
        return True
    old = {team.bot_address(bot): bot.get("blocked_capabilities", []) for bot in previous["bots"]}
    new = {
        team.bot_address(bot): bot.get("blocked_capabilities", []) for bot in configuration["bots"]
    }
    return any(old.get(address, []) != new.get(address, []) for address in old.keys() | new.keys())


def _slot(
    slot,
    *,
    role="custom",
    address=None,
    name,
    job_focus="",
    skills=(),
    enabled=True,
    notebook=False,
    evidence=False,
):
    return {
        "slot": slot,
        "role": role,
        "address": address,
        "name": name,
        "job_focus": job_focus,
        "working_preferences": "",
        "enabled": enabled,
        "response_style": "brief",
        "include_notebook": notebook,
        "include_evidence": evidence,
        "skills": list(skills),
        "blocked_capabilities": [],
    }


def catalog(version=1):
    provider = [
        _slot(role, role=role, address=role, name=value["name"], notebook=True, evidence=True)
        for role, value in ROLE_TEMPLATES.items() if role in BASELINE_ROLES
    ]
    return {
        "contract": CONTRACT,
        "version": version,
        "presets": [
            {
                "preset_id": "provider",
                "version": 1,
                "label": "Provider",
                "purpose": "Keep the existing private clinical and work coworkers together.",
                "slots": provider,
                "unavailable_capabilities": [],
            },
            {
                "preset_id": "front_desk",
                "version": 2 if version >= 3 else 1,
                "label": "Front Desk",
                "purpose": "Draft reviewed administrative Inbox replies and review scheduling and preparation." if version >= 3 else "Review scheduling and saved preparation; keep unconnected inbox work visible.",
                "slots": [
                    _slot(
                        "inbox",
                        name="Inbox",
                        enabled=version >= 3,
                        skills=("inbox_review",) if version >= 3 else (),
                        job_focus="Draft administrative replies from a selected reviewed message and human triage for human review." if version >= 3 else "Keep unconnected inbox work visible for human review.",
                    ),
                    _slot(
                        "scheduling",
                        name="Scheduling",
                        skills=("work_status", "calendar_availability"),
                        evidence=True,
                        job_focus="Review scheduling availability and accountable work.",
                    ),
                    _slot(
                        "intake",
                        name="Intake",
                        skills=("work_status", "encounter_prep"),
                        evidence=True,
                        job_focus="Prepare current saved intake information for provider review.",
                    ),
                ],
                "unavailable_capabilities": [] if version >= 3 else ["inbox_operations"],
            },
            {
                "preset_id": "practice_manager",
                "version": 2 if version >= 4 else 1,
                "label": "Practice Manager",
                "purpose": "Review membership and payment evidence and coordinate accountable practice work." if version >= 4 else "Review accountable work; keep unconnected membership and billing work visible.",
                "slots": [
                    _slot(
                        "operations",
                        name="Operations",
                        skills=("work_status",),
                        job_focus="Review accountable practice work and private work briefs.",
                    ),
                    _slot(
                        "membership_billing",
                        name="Membership / Billing",
                        enabled=version >= 4,
                        skills=("membership_review",) if version >= 4 else (),
                        job_focus="Review selected membership or payment evidence and prepare human next steps." if version >= 4 else "Keep unconnected membership and billing work visible for human review.",
                    ),
                    _slot(
                        "chief",
                        role="chief",
                        address="chief",
                        name=ROLE_TEMPLATES["chief"]["name"],
                        notebook=True,
                        evidence=True,
                    ),
                ],
                "unavailable_capabilities": [] if version >= 4 else ["membership_billing"],
            },
        ],
    }


def context(s, box, owner, external_identity_id, previous, configuration, *, contract=1):
    """Read only caller-owned local facts; private correspondence enters a hash only."""
    ws._human(s, box, owner)
    settings = team.runtime_settings
    identity = None
    if external_identity_id is not None:
        identity = s.scalar(
            select(ExternalIdentity)
            .where(
                ExternalIdentity.id == external_identity_id,
                ExternalIdentity.box_id == box,
                ExternalIdentity.principal_id == owner,
                ExternalIdentity.active.is_(True),
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if identity is None:
            raise ws.WorkspaceError("workspace_access_denied", 403)
    accounts, private_accounts = {}, {}
    for key, model in (("core", CoreCaptureAccount), ("scheduling", SchedulingAccount)):
        rows = (
            list(
                s.scalars(
                    select(model)
                    .where(model.external_identity_id == identity.id)
                    .order_by(model.reviewed_at.desc(), model.id)
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
            )
            if identity
            else []
        )
        active = next((row for row in rows if row.revoked_at is None), None)
        accounts[key] = (
            "unverified"
            if identity is None
            else "reviewed"
            if active
            else "revoked"
            if rows
            else "missing"
        )
        private_accounts[key] = [
            {
                "id": row.id,
                "reviewed_at": row.reviewed_at.isoformat(),
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            }
            for row in rows
        ]
    runtime = {
        "model": settings.workspace_llm_available,
        "capture": settings.workspace_capture_available,
        "prep": settings.workspace_capture_available and settings.workspace_prep_enabled,
        "notes": settings.workspace_capture_available and settings.workspace_capture_notes_enabled,
        "corrections": settings.workspace_capture_available
        and settings.workspace_capture_notes_enabled
        and settings.workspace_capture_corrections_enabled,
        "scheduling": settings.workspace_scheduling_available,
        "routines": settings.workspace_available and settings.workspace_routines_enabled,
    }
    if contract >= 3:
        runtime["inbox"] = settings.inbox_work_enabled and settings.workspace_llm_available
    if contract >= 4:
        runtime["membership"] = (settings.membership_work_enabled or settings.finance_work_enabled) and settings.workspace_llm_available
    from cosmas_os.application import routines

    now = routines._now(s)
    schedules, private_schedules = {}, {}
    existing_bots = list(
        s.scalars(
            select(ProviderBot).where(ProviderBot.box_id == box, ProviderBot.owner_id == owner)
        )
    )
    for bot in existing_bots:
        revision = routines._latest(s, bot)
        status = routines._eligibility(s, bot, revision, now)[0] if revision else "not_configured"
        schedules[bot.instance_id or bot.role] = {
            "kind": "routine",
            "revision": revision.revision if revision else 0,
            "status": status,
        }
        private_schedules[bot.instance_id or bot.role] = {
            "revision_id": revision.id if revision else None,
            "team_revision_id": revision.team_revision_id if revision else None,
            "status": status,
        }
    private = {
        "contract_version": 1,
        "catalog_version": 1,
        "box": box,
        "owner": owner,
        "external_identity_id": identity.id if identity else None,
        "team_revision": previous.revision if previous else 0,
        "runtime": runtime,
        "accounts": private_accounts,
        "routines": private_schedules,
    }
    extra = {}
    if contract >= 2:
        from cosmas_os.application import model_work

        inventory = team_resources.inventory(s, box, owner, external_identity_id)
        private.update(
            contract_version=contract, catalog_version=contract, inventory_sha256=inventory["inventory_sha256"]
        )
        extra = {
            "contract_version": contract,
            "resource_inventory": inventory,
            "model_usage": model_work.usage(s, box, owner, configuration=configuration),
        }
    return {
        **extra,
        "team_revision": previous.revision if previous else 0,
        "runtime": runtime,
        "accounts": accounts,
        "routines": schedules,
        "prerequisites_sha256": digest(private),
        "configuration_changed": previous is None or previous.configuration != configuration,
    }


def evaluate(configuration, facts):
    """Pure policy projection; no session, client, credential or effect port."""
    rows = []
    unavailable = {}
    for preset in configuration.get("presets", ()):
        if preset["preset_id"] == "front_desk" and preset["version"] == 1:
            unavailable[preset["slots"]["inbox"]] = "inbox_operations"
        if preset["preset_id"] == "practice_manager" and preset["version"] == 1:
            unavailable[preset["slots"]["membership_billing"]] = "membership_billing"
    for bot in configuration["bots"]:
        address = team.bot_address(bot)

        def add(
            capability,
            *,
            selected=True,
            restricted=False,
            runtime=None,
            account=None,
            scope=None,
            local=True,
            routine=False,
            missing=False,
            bot=bot,
            address=address,
        ):
            sources = []
            if runtime:
                sources.append(
                    {"kind": "runtime", "key": runtime, "enabled": facts["runtime"][runtime]}
                )
            if account:
                sources.append(
                    {"kind": "account", "key": account, "state": facts["accounts"][account]}
                )
            if scope:
                sources.append({"kind": "scope", "key": scope, "required": True})
            if routine:
                schedule = deepcopy(
                    facts["routines"].get(
                        address, {"kind": "routine", "revision": 0, "status": "not_configured"}
                    )
                )
                if restricted:
                    schedule["status"] = "restricted"
                elif (
                    facts["configuration_changed"]
                    and schedule["revision"]
                    and schedule["status"] != "paused"
                ):
                    schedule["status"] = "team_changed"
                sources.append(schedule)
            if missing:
                state, explanation = (
                    "unavailable_in_beta",
                    "This operational lane has no qualified beta connection or execution capability.",
                )
            elif bot.get("retired"):
                state, explanation = (
                    "retired",
                    "This retired coworker retains history and cannot take new work.",
                )
            elif not bot["enabled"]:
                state, explanation = "paused", "This coworker is paused."
            elif not selected or restricted:
                state, explanation = (
                    "disabled_by_owner",
                    "This skill or source is not selected, or an owner restriction excludes it.",
                )
            elif (
                runtime
                and not facts["runtime"][runtime]
                or account
                and facts["accounts"][account] != "reviewed"
            ):
                state, explanation = (
                    "connection_required",
                    "The configured runtime or this signed account’s reviewed connection is unavailable.",
                )
            elif scope in {"encounter", "recording_consent", "provider_review"}:
                state, explanation = (
                    "requires_encounter",
                    "Select an encounter; current patient, consent and receiver checks still apply.",
                )
            elif not local or scope:
                state, explanation = (
                    "available_for_scoped_request",
                    "Local prerequisites permit a scoped request. Service and device acceptance are not established.",
                )
            else:
                state, explanation = (
                    "ready_local",
                    "This local capability is available within its existing human and work scope.",
                )
            if facts.get("contract_version", 1) >= 2:
                immutable_denial = state in {
                    "paused",
                    "retired",
                    "disabled_by_owner",
                    "unavailable_in_beta",
                }
                if capability in {"encounter_prep", "calendar_availability"}:
                    purpose = (
                        "core_preparation"
                        if capability == "encounter_prep"
                        else "scheduling_context"
                    )
                    resource = team_resources.source(bot, purpose, facts["resource_inventory"])
                    sources.append(resource)
                    if not immutable_denial and resource["selection"] in {"denied", "unavailable"}:
                        state = (
                            "resource_restricted"
                            if resource["selection"] == "denied"
                            else "resource_unavailable"
                        )
                        explanation = (
                            "The owner excludes this source purpose."
                            if state == "resource_restricted"
                            else "The selected reviewed source is no longer current; the restriction is retained."
                        )
                if capability in {"model_answer", "private_draft_handoff"} or capability in {"inbox_operations", "membership_billing"} and not missing:
                    usage = facts["model_usage"]
                    limit = configuration.get("model_work", {}).get("max_attempts_per_24h")
                    work_state = (
                        "unlimited"
                        if limit is None
                        else "paused"
                        if limit == 0
                        else "exhausted"
                        if usage["occupied_units"] >= limit
                        else "available"
                    )
                    sources.append(
                        {
                            "kind": "model_work",
                            "limit": limit,
                            "occupied_units": usage["occupied_units"],
                            "state": work_state,
                            "as_of": usage["as_of"],
                        }
                    )
                    if not immutable_denial and work_state in {"paused", "exhausted"}:
                        state, explanation = (
                            "work_limit_reached",
                            "The owner’s model attempt allowance does not admit another call. Existing results remain readable.",
                        )
            rows.append(
                {
                    "bot": address,
                    "capability": capability,
                    "selected": bool(selected),
                    "restricted": bool(restricted),
                    "state": state,
                    "explanation": explanation,
                    "sources": sources,
                }
            )

        saved, work = supports_skill(bot, "saved_context"), supports_skill(bot, "work_status")
        add("saved_notebook", selected=saved, restricted=not bot["include_notebook"])
        add("saved_evidence", selected=saved, restricted=not bot["include_evidence"])
        add("work_status", selected=work)
        add(
            "model_answer",
            restricted=team.blocked(bot, "model_answer"),
            runtime="model",
            local=False,
        )
        add(
            "private_draft_handoff",
            selected=work,
            restricted=team.blocked(bot, "private_draft_handoff")
            or team.blocked(bot, "model_answer"),
            runtime="model",
            local=False,
        )
        add(
            "practice_work_brief",
            selected=work,
            restricted=team.blocked(bot, "practice_work_brief"),
            runtime="routines",
            routine=True,
        )
        if bot["role"] in {"scribe", "visit_prep", "custom"}:
            add(
                "encounter_prep",
                selected=supports_skill(bot, "encounter_prep"),
                restricted=not bot["include_evidence"],
                runtime="prep",
                account="core",
                scope="encounter",
            )
        if bot["role"] == "scribe":
            add("consented_capture", runtime="capture", account="core", scope="recording_consent")
            add("clinical_note", runtime="notes", account="core", scope="provider_review")
            add("transcript_correction", runtime="corrections", account="core", scope="encounter")
        if bot["role"] in {"follow_up", "custom"}:
            add(
                "calendar_availability",
                selected=supports_skill(bot, "calendar_availability"),
                restricted=not bot["include_evidence"],
                runtime="scheduling",
                account="scheduling",
                scope="encounter",
            )
        add("staff_handoff", selected=work, scope="work_item")
        if facts.get("contract_version", 1) >= 3 and supports_skill(bot, "inbox_review"):
            add("inbox_operations", selected=True, restricted=team.blocked(bot, "model_answer"),
                runtime="inbox", scope="reviewed_inbox", local=False)
        elif address in unavailable and unavailable[address] == "inbox_operations":
            add(unavailable[address], selected=False, missing=True)
        if facts.get("contract_version", 1) >= 4 and supports_skill(bot, "membership_review"):
            add("membership_billing", selected=True, restricted=team.blocked(bot, "model_answer"),
                runtime="membership", scope="reviewed_membership", local=False)
        elif address in unavailable and unavailable[address] == "membership_billing":
            add(unavailable[address], selected=False, missing=True)
    contract = facts.get("contract_version", 1)
    return {
        "contract_version": contract,
        "catalog_version": contract,
        "team_revision": facts["team_revision"],
        "configuration_sha256": digest(configuration),
        "prerequisites_sha256": facts["prerequisites_sha256"],
        "capabilities": rows,
    }


def setup(s, box, owner, external_identity_id, *, contract=1):
    available()
    ws._human(s, box, owner)
    previous = team.current(s, box, owner)
    value = team.read(s, box, owner, version=previous)
    configuration = value["configuration"]
    require_compatible(contract, configuration)
    facts = context(s, box, owner, external_identity_id, previous, configuration, contract=contract)
    return {"team": value, "catalog": catalog(contract), "setup": evaluate(configuration, facts)}


def rehearsal(s, box, owner, external_identity_id, *, expected, configuration, contract=1):
    available()
    ws._human(s, box, owner)
    previous = team.current(s, box, owner)
    if expected != (previous.revision if previous else 0):
        raise ws.WorkspaceError("team_revision_conflict")
    if expected >= 100:
        raise ws.WorkspaceError("team_history_limit")
    configuration = team.configuration_value(configuration)
    require_compatible(contract, previous.configuration if previous else None, configuration)
    validate_transition(previous.configuration if previous else None, configuration)
    prior_bots = previous.configuration["bots"] if previous else []
    old = {team.bot_address(bot): bot for bot in prior_bots}
    new = {team.bot_address(bot): bot for bot in configuration["bots"]}
    if not old.keys() <= new.keys():
        raise ws.WorkspaceError("team_member_missing")
    if any(bot.get("retired") and new[address] != bot for address, bot in old.items()):
        raise ws.WorkspaceError("team_member_retired")
    if any(new[address]["role"] != bot["role"] for address, bot in old.items()):
        raise ws.WorkspaceError("team_template_immutable")
    if any(bot.get("retired") and address not in old for address, bot in new.items()):
        raise ws.WorkspaceError("team_member_unavailable")
    members = {
        bot.instance_id or bot.role: bot
        for bot in s.scalars(
            select(ProviderBot).where(ProviderBot.box_id == box, ProviderBot.owner_id == owner)
        )
    }
    for address, bot in old.items():
        member = members.get(address)
        principal = s.get(Principal, member.agent_id) if member else None
        if (
            principal is None
            or principal.principal_type != "agent"
            or bot.get("retired")
            and (principal.tombstoned_at is None or principal.state != "disabled")
            or not bot.get("retired")
            and principal.tombstoned_at is not None
        ):
            raise ws.WorkspaceError("team_member_unavailable")
    facts = context(s, box, owner, external_identity_id, previous, configuration, contract=contract)
    if contract >= 2:
        team_resources.validate_transition(
            previous.configuration if previous else None, configuration, facts["resource_inventory"]
        )
    projection = evaluate(configuration, facts)
    cases = []
    for name, capability in [
        ("private_sources", "saved_notebook"),
        ("work_brief", "practice_work_brief"),
        ("scheduling", "calendar_availability"),
        ("preparation", "encounter_prep"),
        ("inbox", "inbox_operations"),
        ("membership_billing", "membership_billing"),
        ("human_control", "staff_handoff"),
    ]:
        options = [row for row in projection["capabilities"] if row["capability"] == capability]
        selected = next(
            (
                row
                for row in options
                if row["state"]
                in {"ready_local", "available_for_scoped_request", "requires_encounter"}
            ),
            options[0] if options else None,
        )
        if name in {"membership_billing", "inbox"} and (contract < (4 if name == "membership_billing" else 3) or selected is None or selected["state"] == "unavailable_in_beta"):
            result, explanation = (
                "unavailable",
                "The invented example leaves this unconnected operational work with a human.",
            )
        elif selected is None or selected["state"] in {
            "paused",
            "retired",
            "disabled_by_owner",
            "resource_restricted",
            "resource_unavailable",
            "work_limit_reached",
        }:
            result, explanation = (
                "withheld",
                "The invented example withholds work and private sources excluded by these settings.",
            )
        elif name == "membership_billing":
            result, explanation = (
                "prerequisite_required",
                "Select one current membership or payment record and review its evidence. Explicit consent requests a private reconciliation review within the model attempt allowance. Human ledger claims remain distinct from processor observations; changes, reminders and money movement require separate human review.",
            )
        elif name == "inbox":
            result, explanation = (
                "prerequisite_required",
                "Select a current reviewed message, administrative human triage and encounter. Explicit consent admits a private draft within the model attempt allowance; a human reviews and sends it separately. Clinical and urgent work stays with a human.",
            )
        elif name in {"scheduling", "preparation"} or selected["state"] == "connection_required":
            result, explanation = (
                "prerequisite_required",
                "The invented example requires current encounter information and a scoped receiver check; missing saved information stays missing.",
            )
        elif name == "human_control":
            result, explanation = (
                "demonstrated",
                "The invented work proposal waits for exact human approval, staff acceptance and evidenced human review. No work record is created.",
            )
        else:
            result, explanation = (
                "demonstrated",
                "The invented local example can show selected saved context or accountable work status. No real source was read and no result was saved.",
            )
        cases.append(
            {
                "case_id": name,
                "bot": selected["bot"] if selected else None,
                "result": result,
                "explanation": explanation,
            }
        )
    review = {
        key: projection[key]
        for key in ("catalog_version", "configuration_sha256", "prerequisites_sha256")
    }
    if contract >= 2:
        limit = configuration.get("model_work", {}).get("max_attempts_per_24h")
        blocked = limit is not None and facts["model_usage"]["occupied_units"] >= limit
        cases.append(
            {
                "case_id": "model_work_policy",
                "bot": None,
                "result": "withheld" if blocked else "demonstrated",
                "explanation": "The invented check evaluates the owner’s attempt allowance without reserving or calling a model. Attempt limits are not currency budgets.",
            }
        )
        for bot in configuration["bots"]:
            denied = any(
                team_resources.source(bot, purpose, facts["resource_inventory"])["selection"]
                in {"denied", "unavailable"}
                for purpose in team_resources.PURPOSES
            )
            cases.append(
                {
                    "case_id": "resource_policy",
                    "bot": team.bot_address(bot),
                    "result": "withheld" if denied else "demonstrated",
                    "explanation": "The invented check retains source restrictions; current identity, encounter and receiver authority are still required. No source is retrieved.",
                }
            )
    return {
        "scenario_id": "team_policy_setup.v1" if contract >= 2 else "preset_setup.v1",
        "expected_revision": expected,
        "configuration": configuration,
        "setup": projection,
        "setup_review": review,
        "configuration_checks": "passed",
        "cases": cases,
    }


def verify_review(s, box, owner, external_identity_id, previous, configuration, review):
    contract = review["catalog_version"]
    if (
        contract not in {1, 2, 3, 4}
        or contract == 1
        and any(
            team_resources.policy_present(value)
            for value in (previous.configuration if previous else None, configuration)
        )
    ):
        raise ws.WorkspaceError("team_catalog_changed")
    require_compatible(contract, previous.configuration if previous else None, configuration)
    if review["configuration_sha256"] != digest(configuration):
        raise ws.WorkspaceError("team_setup_configuration_changed")
    facts = context(s, box, owner, external_identity_id, previous, configuration, contract=contract)
    if contract >= 2:
        team_resources.validate_transition(
            previous.configuration if previous else None, configuration, facts["resource_inventory"]
        )
    if review["prerequisites_sha256"] != facts["prerequisites_sha256"]:
        raise ws.WorkspaceError("team_setup_prerequisites_changed")
