"""Pinned first-party capabilities described with MCP Tool vocabulary.

Discovery is data, not authorization. Existing HTTP handlers remain the only
execution path; this module neither installs plugins nor implements MCP transport.
"""
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from cosmas_os.api.capture_schemas import CaptureAdmissionRequest
from cosmas_os.api.research_schemas import Save, Search
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


def command(action: str) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "properties": {"action": {"type": "string", "const": action}},
            "required": ["action"]}


def delivery_schema(action: str) -> dict[str, Any]:
    schema = VendorProposal.model_json_schema()
    schema["properties"]["action"] = {"type": "string", "const": action}
    required, optional = {
        "spruce_secure_message": ({"correspondence", "message"}, {"uploaded_media_operation_id"}),
        "srfax_fax": ({"correspondence", "document"}, set()),
        "documo_fax": ({"correspondence", "document"}, set()),
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
                             ("srfax", "srfax_fax"), ("documo", "documo_fax")):
        operations.append(Operation(
            id=f"{provider}.prepare_delivery", plugin=provider,
            title=f"Prepare {'a secure message' if provider == 'spruce' else 'a fax'} with {provider.title()}",
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
    arguments = {"request": body}
    for name in ("workspace_id", "run_id"):
        if "{" + name + "}" in operation.path:
            arguments[name] = {"type": "string", "format": "uuid"}
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
            "http": {"method": "POST", "path": operation.path,
                     "contract_header": operation.header, "contract_version": "1" if operation.header else None,
                     "body_argument": "request", "authentication": "current_clerk_jwt",
                     "required_headers": {"Content-Type": "application/json",
                                          "X-Cosmas-Workspace-Protocol": "1",
                                          "X-Cosmas-Draft-Recovery": "2"}},
            "validation": "Existing handlers also enforce current identity, grants, revisions and semantic field validation.",
            "permissions": list(operation.permission), "health_check": operation.health_check,
            "completion_evidence": operation.completion, "recovery": operation.recovery,
            "deadline_seconds": operation.deadline_seconds, "test_files": list(operation.tests),
            "external_send": False,
        }},
    }


def plugin_catalog(settings, runtime) -> dict[str, Any]:
    enabled = {
        "google": bool(getattr(settings, "workspace_google_connection_enabled", False)
                       and getattr(runtime, "google_connection", None) is not None),
        "microsoft": bool(getattr(settings, "workspace_microsoft_connection_enabled", False)
                          and getattr(runtime, "microsoft_connection", None) is not None),
        "scribe": bool(getattr(settings, "workspace_capture_available", False)),
        "research": bool(getattr(settings, "workspace_research_available", False)),
    }
    for vendor in ("spruce", "srfax", "documo"):
        enabled[vendor] = bool(getattr(settings, "vendor_work_enabled", False))
    return {
        "tools": [tool(operation, enabled[operation.plugin]) for operation in definitions()],
        "_meta": {
            "ai.cosmas/contract": CONTRACT, "ai.cosmas/schema": "MCP Tool 2025-11-25",
            "ai.cosmas/transport": "existing_authenticated_http",
            "ai.cosmas/discovery_only": True,
            "ai.cosmas/inbound": {
                "production": "Spruce reviewed inbox only; no Google, Microsoft or fax inbox transport",
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
