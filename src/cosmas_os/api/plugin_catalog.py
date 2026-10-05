"""Pinned first-party capabilities described with MCP Tool vocabulary.

Discovery is data, not authorization. Existing HTTP handlers remain the only
execution path; this module neither installs plugins nor implements MCP transport.
"""
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from cosmas_os.api.capture_schemas import (
    CaptureAdmissionRequest,
    EncounterPrepRequest,
    ExistingCaptureRequest,
    ScribeSourcePacketRequest,
)
from cosmas_os.api.research_schemas import Save, Search
from cosmas_os.api.scheduling_schemas import (
    AppointmentPrepare,
    CurrentAppointmentRequest,
    WorkspaceAvailabilityRequest,
)
from cosmas_os.api.team_schemas import ConversationRequest
from cosmas_os.api.vendor_work_schemas import VendorProposal

META = "ai.cosmas/operation"
CONTRACT = "cosmas.plugins.v1"


@dataclass(frozen=True)
class Operation:
    id: str
    plugin: str
    title: str
    description: str
    path: str
    header: str | None
    request: dict[str, Any]
    permission: tuple[str, ...]
    health_check: str
    completion: str
    recovery: str
    tests: tuple[str, ...]
    read_only: bool = False
    public_read: bool = False
    deadline_seconds: int = 30
    method: str = "POST"
    extra_headers: tuple[tuple[str, str], ...] = ()
    path_arguments: tuple[tuple[str, dict[str, Any]], ...] = ()
    query_arguments: tuple[tuple[str, dict[str, Any]], ...] = ()
    agent_callable: bool = False


def command(action: str) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {"action": {"type": "string", "const": action}},
            "required": ["action"]}


def delivery_schema(action: str) -> dict[str, Any]:
    schema = VendorProposal.model_json_schema()
    schema["properties"]["action"] = {"type": "string", "const": action}
    schema["properties"]["share_to_practice"] = {"type": "boolean", "const": False}
    required, optional = {
        "spruce_secure_message": ({"correspondence", "message"}, {"uploaded_media_operation_id"}),
        "srfax_fax": ({"correspondence", "document"}, set()),
        "documo_fax": ({"correspondence", "document"}, set()),
        "efax_fax": ({"correspondence", "document"}, set()),
    }[action]
    schema["required"].extend(sorted(required))
    for field in {"correspondence", "document", "message", "uploaded_media_operation_id"} - required - optional:
        del schema["properties"][field]
    # Closed commands allow omitted optional fields, never explicit nulls.
    for value in schema["properties"].values():
        if "anyOf" in value:
            variants = [item for item in value.pop("anyOf") if item.get("type") != "null"]
            value.update(variants[0] if len(variants) == 1 else {"anyOf": variants})
            value.pop("default", None)
    schema["dependentRequired"] = {
        "supersedes_operation_id": ["acknowledge_prior_uncertainty"],
        "acknowledge_prior_uncertainty": ["supersedes_operation_id"],
    }
    schema["not"] = {"required": ["supersedes_operation_id", "revises"]}
    # Canonical IDs, valid dates, text and current authority remain handler checks.
    return schema


def prep_brief_schema() -> dict[str, Any]:
    """Select the prepared-brief branch, never the route's default source view."""
    schema = EncounterPrepRequest.model_json_schema()
    schema["properties"]["view"] = {"type": "string", "const": "brief"}
    bot = schema["properties"]["bot"]
    bot.update(next(value for value in bot.pop("anyOf") if value.get("type") != "null"))
    bot.pop("default", None)
    schema["required"] = ["idempotency_key", "bot", "view"]
    return schema


def appointment_proposal_schema() -> dict[str, Any]:
    """A selected slot and explicit private sharing; no cancel/approve/execute."""
    schema = AppointmentPrepare.model_json_schema()
    schema["properties"]["action"] = {"type": "string", "enum": ["book", "reschedule"]}
    schema["properties"]["slot"] = next(value for value in schema["properties"]["slot"]["anyOf"] if value.get("type") != "null")
    schema["properties"]["share"] = {"type": "boolean", "const": True}
    schema["required"] = ["bot", "action", "slot", "share", "idempotency_key"]
    return schema


def definitions() -> tuple[Operation, ...]:
    operations = []
    for provider in ("google", "microsoft"):
        for action, name, label, scope in (
            ("mail", "mail_headers", "email headers",
             "https://www.googleapis.com/auth/gmail.metadata" if provider == "google" else "Mail.Read"),
            ("calendar", "calendar_summaries", "calendar summaries",
             "https://www.googleapis.com/auth/calendar.events.readonly" if provider == "google" else "Calendars.Read"),
        ):
            operations.append(Operation(
                id=f"{provider}.{name}", plugin=provider,
                title=f"Read {provider.title()} {label}",
                description=(f"Read up to {10 if provider == 'google' else 25} email headers, without bodies or attachments."
                             if action == "mail" else "Read calendar summaries for the next seven days."),
                path=f"/connections/{provider}/session",
                header=f"X-Cosmas-{provider.title()}-Connection", request=command(action),
                permission=("authenticated account owner", "explicit bounded read", scope),
                health_check="status checks account access; only this successful operation verifies its capability",
                completion="validated bounded response, including a confirmed empty result",
                recovery="cancel or perform a new explicit read; never infer success from sign-in",
                tests=("tests/unit/test_personal_connection_failure.py",
                       "tests/integration/test_virtual_clinic_lab.py"),
                read_only=True, public_read=True, deadline_seconds=45,
            ))
    operations.extend((
        Operation(
            id="scheduling.read_availability", plugin="scheduling", title="Check appointment availability",
            description="Read currently authorized slots and their Google calendar coverage receipt. A slot is time-sensitive and is not reserved or booked.",
            path="/workspaces/{workspace_id}/scheduling/availability", header=None,
            request=WorkspaceAvailabilityRequest.model_json_schema(),
            permission=("current authenticated encounter owner and reviewed Scheduling identity",
                        "enabled bot with calendar_availability skill and current team revision",
                        "exact current scheduling account and practitioner/resource grant"),
            health_check="only a fresh authorized availability receipt establishes observed slots; sign-in is insufficient",
            completion="slots, checked_at and valid_until; empty, expired and unavailable remain distinct",
            recovery="deliberately read availability again after expiry; never treat an old slot as reserved",
            tests=("tests/integration/test_workspace_scheduling.py",), read_only=True, deadline_seconds=120,
        ),
        Operation(
            id="scheduling.read_current", plugin="scheduling", title="Read the encounter's current appointment",
            description="Read the currently mapped appointment before preparing a change. The appointment and calendar synchronization are separate outcomes.",
            path="/workspaces/{workspace_id}/appointments/current", header=None,
            request=CurrentAppointmentRequest.model_json_schema(),
            permission=("current authenticated encounter owner and reviewed Scheduling identity",
                        "current bot skill/resource grants and exact patient/encounter correspondence"),
            health_check="inspect the returned appointment and correspondence; configuration is not a current appointment",
            completion="current exact appointment observation only; missing or unknown is not cancelled",
            recovery="repeat the authorized read; do not create an appointment to recover missing read evidence",
            tests=("tests/integration/test_workspace_appointments.py",), read_only=True, deadline_seconds=120,
        ),
        Operation(
            id="scheduling.prepare_appointment", plugin="scheduling", title="Prepare an appointment for review",
            description="Save an exact selected appointment proposal in the existing work queue. Human approval and execution remain separate; preparation does not reserve a slot.",
            path="/workspaces/{workspace_id}/appointments", header=None,
            request=appointment_proposal_schema(),
            permission=("current authenticated encounter owner and reviewed Scheduling identity",
                        "current bot skill/resource grants and exact patient/encounter correspondence",
                        "explicit selected slot and private proposal sharing; availability is rechecked",
                        "human approval required before execution"),
            health_check="inspect current availability, exact proposal revision and outcome independently",
            completion="saved private proposal and exact revision/hash only; pending approval is not booking",
            recovery="retain the original request and idempotency key; read its saved proposal before considering another intent",
            tests=("tests/integration/test_workspace_appointments.py", "tests/integration/test_appointment_work.py"),
            deadline_seconds=120,
        ),
        Operation(
            id="scheduling.inspect_proposal", plugin="scheduling", title="Check saved appointment work",
            description="Read a saved proposal and its retained execution observations. Booking and Google calendar synchronization must be assessed separately.",
            path="/workspaces/{workspace_id}/appointments/{ticket_id}", header=None,
            request={"type": "object", "properties": {}, "additionalProperties": False},
            permission=("current authenticated encounter owner and mapped external identity",
                        "exact encounter and saved ticket; no new approval or execution authority"),
            health_check="read retained state; pending, unknown, failed and completed remain distinct",
            completion="saved proposal/operation state and exact evidence; a read is not new submission",
            recovery="repeat the saved-ticket read after a lost response; never resubmit to recover a receipt",
            tests=("tests/integration/test_appointment_work.py", "tests/integration/test_appointment_execution.py"),
            read_only=True, deadline_seconds=120, method="GET",
        ),
        Operation(
            id="workspace.review", plugin="workspace", title="Review saved encounter work with a bot",
            description="Ask an enabled bot to review its permitted saved sources. Chief can report saved work status "
                        "without external connectors when the model is disabled. Each bot keeps its own existing skills; "
                        "model answers and private handoffs depend on its current settings.",
            path="/workspaces/{workspace_id}/conversation", header="X-Cosmas-Model-Contract",
            request=ConversationRequest.model_json_schema(),
            permission=("authenticated encounter owner", "enabled bot address and current team revision",
                        "current bot source settings and existing skills; no new grants",
                        "selected private analysis requires its existing consent and source permissions"),
            health_check="workspace availability does not establish bot, model or connector readiness; inspect the exact outcome",
            completion="saved conversation entry and request hash; running, unknown and failed are not saved answers; "
                       "a draft or work-status reply is not approval, delivery or completion of that work",
            recovery="/workspaces/{workspace_id}/conversation/resolve with the exact original request and model contract; "
                     "observe the retained outcome before considering another request",
            tests=("tests/integration/test_chief_operations.py", "tests/integration/test_model_work_admission.py"),
            deadline_seconds=120,
        ),
        Operation(
            id="scribe.prepare_recording", plugin="scribe", title="Prepare a visit recording",
            description="Prepare the consent-bound Scribe session. This does not start the microphone.",
            path="/workspaces/{workspace_id}/capture/admission", header=None,
            request=CaptureAdmissionRequest.model_json_schema(),
            permission=("encounter access", "provider recording consent", "current Scribe connection"),
            health_check="configured connection is not recording evidence; read the exact admission receipt",
            completion="prepared session and consent receipt for this encounter",
            recovery="retain idempotency key; check the existing session before another admission",
            tests=("tests/unit/test_core_capture_contract.py",
                   "tests/integration/test_scribe_source_bridge.py"), deadline_seconds=120,
        ),
        Operation(
            id="scribe.read_existing", plugin="scribe", title="Read the encounter's existing Scribe recording",
            description="Read the encounter-bound transcript review and exact source selection when available. "
                        "This does not admit a new recording, start a microphone or share the transcript with the team.",
            path="/workspaces/{workspace_id}/capture/existing", header=None,
            request=ExistingCaptureRequest.model_json_schema(),
            permission=("authenticated encounter owner", "current connected Core account and canonical encounter",
                        "receiver-verified original session and consent"),
            health_check="connection configuration is not an available transcript; inspect the returned status and review",
            completion="current encounter review and exact selection when available; missing or pending review remains explicit",
            recovery="repeat the same existing-recording read with its retained idempotency key; never create a recording to recover a read",
            tests=("tests/unit/test_core_scribe_bridge.py", "tests/integration/test_scribe_source_bridge.py"),
            read_only=True, deadline_seconds=120,
        ),
        Operation(
            id="scribe.share_transcript", plugin="scribe", title="Share a reviewed Scribe transcript with the encounter team",
            description="After the human reviews and explicitly chooses to share the exact transcript selection, save "
                        "that source snapshot to this encounter. A shared source is not a generated draft or clinical sign-off.",
            path="/workspaces/{workspace_id}/capture/source-packets", header=None,
            request=ScribeSourcePacketRequest.model_json_schema(),
            permission=("authenticated encounter owner", "explicit human transcript review and team-sharing confirmation",
                        "exact source selection and current encounter revision", "current receiver-verified session and consent for a new save"),
            health_check="verify the saved source entry IDs and revisions; a configured connection does not establish sharing",
            completion="persisted transcript source entries bound to the selected snapshot hash; no clinical note or external delivery",
            recovery="repeat this exact request and idempotency key; the handler returns the committed save before another source read; "
                     "a changed selection or revision requires a new review",
            tests=("tests/integration/test_scribe_source_bridge.py", "tests/integration/test_documentation_capability.py"),
            deadline_seconds=120,
        ),
        Operation(
            id="visit_prep.read_brief", plugin="visit_prep", title="Read the prepared visit brief",
            description="Read the current prepared brief, its source evidence and freshness for an authorized preparation bot. "
                        "Pending, refreshing, partial and unavailable results remain visible; this does not record a visit or generate a chat answer.",
            path="/workspaces/{workspace_id}/capture/prep", header=None, request=prep_brief_schema(),
            permission=("authenticated encounter owner", "enabled bot with encounter_prep skill and evidence access",
                        "current team revision and exact core_preparation resource grant", "current connected Core account and canonical encounter"),
            health_check="both capture and Session Prep must be configured; only a ready receipt establishes an available brief",
            completion="current prepared-brief receipt with state, freshness, completeness and source provenance; "
                       "the service action receipt does not mean the clinician reviewed the brief",
            recovery="retain the idempotency key for the same read; a deliberate refresh uses a new key; "
                     "do not present pending or refreshing as ready",
            tests=("tests/integration/test_session_prep.py", "tests/unit/test_core_session_prep_flow.py"),
            deadline_seconds=120,
        ),
        Operation(
            id="research.search", plugin="research", title="Look up reviewed public sources",
            description="Send only the reviewed general query to selected public sources and retain provenance.",
            path="/workspaces/{workspace_id}/research/search", header="X-Cosmas-Research-Contract",
            request=Search.model_json_schema(),
            permission=("encounter access", "active Research bot", "explicit public query review"),
            health_check="source configuration is not query success; inspect per-source completion",
            completion="bounded source records with retrieval times, citations and content hashes",
            recovery="/workspaces/{workspace_id}/research/resolve; exact retained key, no redispatch",
            tests=("tests/unit/test_research.py", "tests/unit/test_research_transport.py"),
            public_read=True,
        ),
        Operation(
            id="research.save_excerpts", plugin="research", title="Save selected evidence",
            description="Save the selected source hashes to the current encounter for review.",
            path="/workspaces/{workspace_id}/research/{run_id}/save",
            header="X-Cosmas-Research-Contract", request=Save.model_json_schema(),
            permission=("encounter access", "explicit source selection", "current encounter revision"),
            health_check="verify the exact save receipt and entry revision",
            completion="saved entry id, revision and request hash",
            recovery="/workspaces/{workspace_id}/research/{run_id}/save/resolve; no second save",
            tests=("tests/unit/test_research.py",),
        ),
    ))
    for provider, action in (("spruce", "spruce_secure_message"),
                             ("srfax", "srfax_fax"), ("documo", "documo_fax"), ("efax", "efax_fax")):
        operations.append(Operation(
            id=f"{provider}.prepare_delivery", plugin=provider,
            title=f"Prepare {'a secure message' if provider == 'spruce' else 'a fax'} with "
                  f"{ {'srfax': 'SRFax', 'efax': 'eFax Corporate'}.get(provider, provider.title())}",
            description="Create a private reviewed-source proposal. Human approval and publication are separate.",
            path="/workspaces/{workspace_id}/vendor-work", header="X-Cosmas-Vendor-Contract",
            request=delivery_schema(action),
            permission=("encounter access", "current connection and recipient revisions",
                        "reviewed source", "human F-8 approval required before sending"),
            health_check="inspect connection, exact operation and delivery observations separately",
            completion="proposal receipt only; submitted, accepted, delivered and failed stay distinct",
            recovery="/workspaces/{workspace_id}/vendor-work/resolve; retain uncertain sends without resending",
            tests=("tests/integration/test_lab_inbound.py",
                   "tests/integration/test_virtual_clinic_lab.py"),
        ))
    from cosmas_os.api import (
        plugin_account_operations,
        plugin_journey_operations,
        plugin_managed_operations,
    )

    for module in (plugin_account_operations, plugin_journey_operations, plugin_managed_operations):
        operations.extend(module.definitions())
    return tuple(operations)


def find_operation(operation_id: str) -> Operation:
    # Static allowlist. No URL, module, package name or user manifest is executed.
    for operation in definitions():
        if operation.id == operation_id:
            return operation
    raise ValueError("unknown first-party operation")


def tool(operation: Operation, configured: bool) -> dict[str, Any]:
    body = deepcopy(operation.request)
    definitions_ = body.pop("$defs", {})
    arguments = {"request": body} if operation.method == "POST" or not operation.agent_callable else {}
    overrides = dict(operation.path_arguments)
    for name in re.findall(r"\{([a-z_]+)\}", operation.path):
        arguments[name] = deepcopy(overrides.get(name, {"type": "string", "format": "uuid"}))
    arguments.update(deepcopy(dict(operation.query_arguments)))
    input_schema: dict[str, Any] = {
        "type": "object", "additionalProperties": False,
        "properties": arguments, "required": list(arguments),
    }
    if definitions_:
        input_schema["$defs"] = definitions_
    return {
        "name": operation.id.replace(".", "_"), "title": operation.title,
        "description": operation.description, "inputSchema": input_schema,
        "annotations": {
            "readOnlyHint": operation.read_only, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": operation.public_read,
        },
        "_meta": {META: {
            "id": operation.id, "plugin": operation.plugin,
            "implementation": "first_party_http", "feature_enabled": configured,
            "account_status": "not_checked", "operation_health": "not_checked",
            "http": {"method": operation.method, "path": operation.path,
                     "contract_header": operation.header, "contract_version": "1" if operation.header else None,
                     "body_argument": "request" if operation.method == "POST" else None,
                     "authentication": "current_clerk_jwt",
                     "required_headers": {"Content-Type": "application/json",
                                          "X-Cosmas-Workspace-Protocol": "1",
                                          "X-Cosmas-Draft-Recovery": "2", **dict(operation.extra_headers)},
                     "query_arguments": list(dict(operation.query_arguments))},
            "validation": "Existing handlers also enforce current identity, grants, revisions and semantic field validation.",
            "permissions": list(operation.permission), "health_check": operation.health_check,
            "completion_evidence": operation.completion, "recovery": operation.recovery,
            "deadline_seconds": operation.deadline_seconds, "test_files": list(operation.tests),
            "external_send": False,
            "agent_callable": operation.agent_callable,
        }},
    }


def plugin_catalog(settings, runtime, *, managed=None, portal=None) -> dict[str, Any]:
    from cosmas_os.api import (
        plugin_account_operations,
        plugin_journey_operations,
        plugin_managed_operations,
    )

    account_ids = {operation.id for operation in plugin_account_operations.definitions()}
    journey_ids = {operation.id for operation in plugin_journey_operations.definitions()}
    managed_ids = {operation.id for operation in plugin_managed_operations.definitions()}

    def available(operation):
        if operation.id in account_ids:
            return plugin_account_operations.configured(operation, settings, runtime)
        if operation.id in journey_ids:
            return plugin_journey_operations.configured(operation.id, settings, runtime)
        if operation.id in managed_ids:
            return plugin_managed_operations.configured(operation, settings, runtime, managed=managed, portal=portal)
        return enabled.get(operation.plugin, False) and (bool(getattr(settings, "workspace_appointments_enabled", False))
            if operation.id.startswith("scheduling.") and operation.id != "scheduling.read_availability" else True)
    enabled = {
        "workspace": bool(getattr(settings, "workspace_available", False)),
        "google": bool(getattr(settings, "workspace_google_connection_enabled", False)
                       and getattr(runtime, "google_connection", None) is not None),
        "microsoft": bool(getattr(settings, "workspace_microsoft_connection_enabled", False)
                          and getattr(runtime, "microsoft_connection", None) is not None),
        "scribe": bool(getattr(settings, "workspace_capture_available", False)),
        "visit_prep": bool(getattr(settings, "workspace_capture_available", False)
                           and getattr(settings, "workspace_prep_enabled", False)
                           and getattr(settings, "workspace_session_prep_available", False)),
        "research": bool(getattr(settings, "workspace_research_available", False)),
        "scheduling": bool(getattr(settings, "workspace_scheduling_available", False)),
    }
    for vendor in ("spruce", "srfax", "documo", "efax"):
        enabled[vendor] = bool(getattr(settings, "vendor_work_enabled", False))
    return {
        "tools": [tool(operation, available(operation))
                  for operation in definitions()],
        "_meta": {
            "ai.cosmas/contract": CONTRACT, "ai.cosmas/schema": "MCP Tool 2025-11-25",
            "ai.cosmas/transport": "existing_authenticated_http",
            "ai.cosmas/discovery_only": True,
            "ai.cosmas/inbound": {
                "production": "Google selected-message and calendar reads; Microsoft bounded summaries; SRFax/Documo fax reads; Spruce fax metadata; separately approved eFax reads. Configuration is not account acceptance.",
                "virtual_scenarios": [
                    "inbound.google", "inbound.microsoft", "inbound.documo", "inbound.srfax",
                    "inbound.duplicate_out_of_order", "inbound.attachment_integrity",
                    "inbound.wrong_encounter", "inbound.lost_import_reply",
                    "inbound.lost_handoff_reply", "inbound.foreign_assignment",
                    "inbound.spruce_source_review",
                ],
            },
        },
    }
