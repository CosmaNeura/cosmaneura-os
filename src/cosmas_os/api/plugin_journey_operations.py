"""Callable first-party journey operations backed by existing authenticated routes.

Only private draft work and reads belong here. Human review, source-sharing
consent, grants, clinical writes and outbound execution remain outside agent
tools. A descriptor does not bypass the handler's current owner/bot authority.
"""

from copy import deepcopy
from typing import TYPE_CHECKING, Any

from cosmas_os.api.capture_schemas import CaptureOperationRequest
from cosmas_os.api.handoff_review_schemas import HandoffRevision
from cosmas_os.api.research_schemas import Resolve
from cosmas_os.api.scheduling_patient_schemas import Inspect, Status
from cosmas_os.api.scheduling_patient_schemas import Resolve as PatientResolve
from cosmas_os.api.team_schemas import ConversationRequest, HandoffRetry
from cosmas_os.application.core_connection import ConnectionCommand

if TYPE_CHECKING:
    from cosmas_os.api.plugin_catalog import Operation


def empty_request() -> dict[str, Any]:
    return {"type": "object", "properties": {}, "additionalProperties": False}


def saved_source_draft_schema() -> dict[str, Any]:
    """Chief uses already shared sources; a tool cannot manufacture consent."""
    schema = ConversationRequest.model_json_schema()
    allowed = {"expected_revision", "team_revision", "idempotency_key", "role", "content"}
    schema["properties"] = {name: value for name, value in schema["properties"].items() if name in allowed}
    schema["properties"]["role"] = {"type": "string", "const": "chief"}
    schema.pop("$defs", None)
    return schema


def core_read_schema(action: str) -> dict[str, Any]:
    """Select a read branch; never accept connect, open or mapping changes."""
    fields = {
        "connection": {"request_nonce"},
        "encounters": {"request_nonce", "connection_sha256", "window", "cursor"},
        "encounter": {"request_nonce", "connection_sha256", "appointment_ref", "source_sha256"},
    }[action]
    schema = ConnectionCommand.model_json_schema()
    schema["properties"] = {name: value for name, value in schema["properties"].items()
                            if name in fields or name == "action"}
    schema["properties"]["action"] = {"type": "string", "const": action}
    schema["required"] = sorted((fields - {"cursor"}) | {"action"})
    for value in schema["properties"].values():
        if "anyOf" in value:
            variants = [item for item in value.pop("anyOf") if item.get("type") != "null"]
            value.update(variants[0] if len(variants) == 1 else {"anyOf": variants})
            value.pop("default", None)
    return schema


def scribe_read_schema(kind: str) -> dict[str, Any]:
    """Read one receiver-verified session observation, without capture controls."""
    if kind not in {"transcription_status", "capture_source"}:
        raise ValueError("unsupported Scribe journey read")
    schema = CaptureOperationRequest.model_json_schema()
    schema.pop("$defs", None)
    schema["properties"]["operation"] = {
        "type": "object", "additionalProperties": False,
        "properties": {"kind": {"type": "string", "const": kind}}, "required": ["kind"],
    }
    return schema


def definitions() -> tuple["Operation", ...]:
    # Lazy import keeps the central catalog free to compose this module.
    from cosmas_os.api.plugin_catalog import Operation

    operations = [
        Operation(
            id="workspace.read", plugin="workspace", title="Reopen saved encounter work",
            description="Read the current encounter, saved sources, private drafts and exact handoff/review states. Reopening never creates a new draft or accepts a result.",
            path="/workspaces/{workspace_id}", header="X-Cosmas-Model-Contract", request=empty_request(),
            permission=("current authenticated encounter owner", "current permitted source projections and team authority"),
            health_check="inspect saved revisions and withheld-source states; a read is not a fresh model run",
            completion="current workspace revision and retained handoff result/review evidence, with running and unknown states preserved",
            recovery="repeat this read after remount or lost responses; never retry a model request solely to recover display state",
            tests=("tests/integration/test_handoff_review.py", "tests/integration/test_handoff_full_source.py"),
            method="GET", read_only=True, agent_callable=True,
        ),
        Operation(
            id="workspace.list", plugin="workspace", title="Read accessible encounters",
            description="List only encounters available to the current authenticated owner. Encounter selection does not create an account mapping or grant.",
            path="/workspaces", header=None, request=empty_request(),
            permission=("current authenticated owner", "existing encounter access"),
            health_check="returned encounters are access observations; missing access remains explicit",
            completion="bounded owner encounter catalog only",
            recovery="repeat the catalog read; do not infer authority from an old selection",
            tests=("tests/integration/test_workspace_auth.py",),
            method="GET", read_only=True, agent_callable=True,
        ),
        Operation(
            id="workspace.draft_from_saved_sources", plugin="workspace", title="Ask Chief to prepare private team drafts",
            description="Ask Chief to use already shared, currently permitted encounter sources. Chief may reserve private specialist handoffs under current settings. This operation cannot assert new source-sharing or analysis consent.",
            path="/workspaces/{workspace_id}/conversation", header="X-Cosmas-Model-Contract", request=saved_source_draft_schema(),
            permission=("current authenticated encounter owner", "enabled Chief and exact current team/workspace revisions",
                        "existing source grants and private_draft_handoff capability; no new consent or grants"),
            health_check="inspect exact saved/reserved/running/unknown/failed outcome and each specialist handoff separately",
            completion="retained request hash and saved draft entry or admitted work; human acceptance is a separate UI action",
            recovery="workspace.resolve_saved_source_draft with the unchanged original command and key; resolve before any deliberate new request",
            tests=("tests/integration/test_model_work_admission.py", "tests/integration/test_handoff_full_source.py"),
            deadline_seconds=120, agent_callable=True,
        ),
        Operation(
            id="workspace.resolve_saved_source_draft", plugin="workspace", title="Resolve a pending Chief draft request",
            description="Observe the original saved-source Chief request without redispatching. Retain the exact original request even when its result is uncertain.",
            path="/workspaces/{workspace_id}/conversation/resolve", header="X-Cosmas-Model-Contract", request=saved_source_draft_schema(),
            permission=("current authenticated encounter owner", "exact original request and idempotency key; current identity rechecked"),
            health_check="not_found, reserved, running, saved, unknown and failed are distinct retained outcomes",
            completion="original admission and saved-entry observation only; no fresh model call",
            recovery="repeat this observation until an exact outcome is known; never change the original command to recover it",
            tests=("tests/integration/test_model_work_api.py",),
            read_only=True, deadline_seconds=120, agent_callable=True,
        ),
    ]
    for identity, suffix, readonly in (("workspace.retry_handoff", "retry", False),
                                      ("workspace.resolve_handoff_retry", "retry/resolve", True)):
        operations.append(Operation(
            id=identity, plugin="workspace", title="Observe a handoff retry" if readonly else "Retry a failed private handoff",
            description=("Resolve the exact original retry request without another dispatch." if readonly else
                         "Request a deliberate retry only for the exact prior failed private handoff attempt. Current source, team, identity and work limits are rechecked."),
            path=f"/workspaces/{{workspace_id}}/handoffs/{{handoff_id}}/{suffix}",
            header="X-Cosmas-Model-Contract", request=HandoffRetry.model_json_schema(),
            permission=("current authenticated encounter owner", "exact previous attempt and current source/team authority",
                        "retry is not result acceptance or permission to repeat unknown work"),
            health_check="inspect original retry admission and exact attempt state",
            completion="retained retry outcome and result-entry anchor only; running or unknown is not completed",
            recovery="resolve_handoff_retry with exact original body/key; reopen workspace to read saved output before another intent",
            tests=("tests/integration/test_model_work_api.py", "tests/integration/test_workspace_handoffs.py"),
            read_only=readonly, deadline_seconds=120, agent_callable=True,
        ))
    operations.append(Operation(
        id="workspace.revise_after_human_feedback", plugin="workspace", title="Prepare a revision after saved human feedback",
        description="Consume an existing exact human changes-requested review receipt to reserve a private revision. The bot cannot write the feedback review or accept its own draft.",
        path="/workspaces/{workspace_id}/handoffs/{handoff_id}/revision", header="X-Cosmas-Handoff-Review",
        extra_headers=(("X-Cosmas-Model-Contract", "1"),), request=HandoffRevision.model_json_schema(),
        permission=("current authenticated encounter owner", "existing current human review_id with changes_requested",
                    "exact parent result/source/team binding and current workspace revision"),
        health_check="verify returned revision handoff and retained human review linkage; stale review/source fails closed",
        completion="new private revision handoff bound to the saved human feedback, never human acceptance",
        recovery="repeat exact body/key to recover saved reservation; workspace.read observes revision/result; changed feedback requires a new human review",
        tests=("tests/integration/test_handoff_review.py",), deadline_seconds=120, agent_callable=True,
    ))
    for action, title in (("connection", "Check the current Core account correspondence"),
                          ("encounters", "Read Core encounter choices"),
                          ("encounter", "Read an exact Core encounter")):
        operations.append(Operation(
            id=f"core.read_{action}", plugin="core", title=title,
            description="Read the current Core correspondence or selected encounter evidence. The account must already be connected for encounter reads; this cannot connect, remap or open an encounter.",
            path="/connections/cosmaneura/read", header="X-Cosmas-Connection-Contract", request=core_read_schema(action),
            permission=("current authenticated account owner", "existing reviewed Core account correspondence for encounter reads",
                        "exact connection/source hash and bounded encounter window where selected"),
            health_check="ready_to_connect or review_required is not connected; only exact current correspondence verifies a read",
            completion="bounded current connection/encounter observation with source digest; no mapping or clinical mutation",
            recovery="perform an explicit read again after stale hashes; do not manufacture a connect confirmation",
            tests=("tests/unit/test_core_connection_transport.py", "tests/integration/test_core_record_location.py"),
            read_only=True, agent_callable=True,
        ))
    operations.append(Operation(
        id="core.read_record_location", plugin="core", title="Read the encounter's current record location",
        description="Read the receiver-verified Core record location for this exact encounter. A returned link is navigation evidence; it does not sign, edit or submit a clinical record.",
        path="/workspaces/{workspace_id}/cosmaneura-record/location", header="X-Cosmas-Record-Contract", request=empty_request(),
        permission=("current authenticated encounter owner", "current reviewed Core actor/tenant and canonical patient/encounter correspondence"),
        health_check="only current validated location evidence establishes the record link",
        completion="current exact encounter record-location receipt only",
        recovery="repeat current location read; revoked or changed correspondence remains unavailable",
        tests=("tests/integration/test_core_record_location.py",), method="GET", read_only=True, agent_callable=True,
    ))
    for kind, name in (("transcription_status", "read_transcription_status"), ("capture_source", "read_source_review")):
        operations.append(Operation(
            id=f"scribe.{name}", plugin="scribe", title="Read Scribe transcription status" if kind == "transcription_status" else "Read Scribe's current source review",
            description="Read only this exact receiver-verified session observation. No microphone, recording control, transcript correction, translation decision or source-sharing confirmation is accepted.",
            path="/workspaces/{workspace_id}/capture/operations", header=None, request=scribe_read_schema(kind),
            permission=("current authenticated encounter owner", "existing receiver-verified session, consent and current Core correspondence"),
            health_check="session creation is not transcription completion; exact status/review receipt is required",
            completion="current exact session observation; human review and sharing remain separate",
            recovery="repeat this read with the retained key; never create another session to recover a receipt",
            tests=("tests/unit/test_core_capture_operations.py", "tests/integration/test_scribe_source_bridge.py"),
            read_only=True, deadline_seconds=120, agent_callable=True,
        ))
    for name, path in (("list_prepared_work", "/workspaces/{workspace_id}/prep-work"),
                       ("read_prepared_work", "/workspaces/{workspace_id}/prep-work/{ticket_id}")):
        operations.append(Operation(
            id=f"visit_prep.{name}", plugin="visit_prep", title="Read saved preparation work",
            description="Inspect existing preparation proposal, publication and review evidence. This read never publishes private context, approves or verifies completion for a human.",
            path=path, header=None, request=empty_request(),
            permission=("current authenticated encounter owner", "existing preparation work access"),
            health_check="pending approval, internally published and ready for review remain distinct",
            completion="saved exact ticket/revision/source-snapshot evidence only",
            recovery="repeat saved work read after a lost response; do not repropose work to recover its status",
            tests=("tests/integration/test_preparation_work.py",), method="GET", read_only=True, agent_callable=True,
        ))
    operations.append(Operation(
        id="scheduling.list_saved_proposals", plugin="scheduling", title="Read saved appointment proposals",
        description="Inspect the encounter's existing appointment work without approving, submitting, cancelling or changing it. Calendar synchronization and booking remain separate observations.",
        path="/workspaces/{workspace_id}/appointments", header=None, request=empty_request(),
        permission=("current authenticated encounter owner", "existing Scheduling identity and encounter access"),
        health_check="retained pending, unknown and completed work must be read separately from connector status",
        completion="bounded existing appointment work catalog only",
        recovery="repeat saved work read; never submit an appointment to recover an uncertain receipt",
        tests=("tests/integration/test_workspace_appointments.py",), method="GET", read_only=True, deadline_seconds=120, agent_callable=True,
    ))
    for name, schema in (("read_patient_binding", Status.model_json_schema()),
                         ("inspect_patient_binding_request", Inspect.model_json_schema()),
                         ("resolve_patient_binding_request", PatientResolve.model_json_schema())):
        operations.append(Operation(
            id=f"scheduling.{name}", plugin="scheduling", title="Read the encounter's Scheduling patient binding",
            description="Observe only existing patient correspondence or its retained request receipt. No lookup preview, human identity confirmation or grant can be issued by this operation.",
            path="/workspaces/{workspace_id}/scheduling-patient/setup", header="X-Cosmas-Scheduling-Patient", request=schema,
            permission=("current authenticated encounter owner", "existing reviewed Scheduling identity and exact request where selected"),
            health_check="missing or revoked correspondence is unavailable; an old request receipt is not a current grant",
            completion="current binding state or retained exact request resolution, without provider lookup or mapping mutation",
            recovery="inspect/resolve the original request before proposing any separate human-reviewed correspondence change",
            tests=("tests/integration/test_scheduling_patient_restore.py",), read_only=True, deadline_seconds=40, agent_callable=True,
        ))
    uuid4 = {"type": "string", "pattern": r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}
    for name, path, query in (("read_catalog", "/research/catalog", ()),
                              ("read_history", "/workspaces/{workspace_id}/research", (("bot", deepcopy(uuid4)),)),
                              ("read_saved_evidence", "/workspaces/{workspace_id}/research/saved", (("bot", deepcopy(uuid4)),))):
        operations.append(Operation(
            id=f"research.{name}", plugin="research", title="Read Research evidence and availability",
            description="Read the source catalog or the selected bot's retained lookup/saved-evidence history. This performs no new public query, evidence save or analysis-consent confirmation.",
            path=path, header="X-Cosmas-Research-Contract", request=empty_request(), query_arguments=query,
            permission=("current authenticated encounter owner for histories", "exact selected Research bot UUID and existing evidence access"),
            health_check="configured source catalog is not a completed lookup; per-source errors and partial results remain visible",
            completion="retained provenance, result state and source hashes; no fresh external request",
            recovery="read existing saved evidence/history to recover display state; do not redispatch a query",
            tests=("tests/unit/test_research.py", "tests/integration/test_research_runtime_privileges.py"),
            method="GET", read_only=True, agent_callable=True,
        ))
    for name, path in (("resolve_lookup", "/workspaces/{workspace_id}/research/resolve"),
                       ("resolve_evidence_save", "/workspaces/{workspace_id}/research/{run_id}/save/resolve")):
        operations.append(Operation(
            id=f"research.{name}", plugin="research", title="Resolve retained Research work",
            description="Resolve an original lookup or selected-evidence save by its exact retained key. This cannot start a public query or save evidence again.",
            path=path, header="X-Cosmas-Research-Contract", request=Resolve.model_json_schema(),
            permission=("current authenticated encounter owner", "exact original key and run where selected"),
            health_check="read the original result state and per-source evidence; incomplete is not successful",
            completion="retained original lookup/save receipt only",
            recovery="repeat this read-only resolution; a new lookup needs separate reviewed human public-query authority",
            tests=("tests/unit/test_research.py", "tests/integration/test_research_runtime_privileges.py"),
            read_only=True, agent_callable=True,
        ))
    return tuple(operations)


def configured(operation_id: str, settings: Any, runtime: Any = None) -> bool:
    """Mirror feature gates only; account, grant and operation health stay unchecked."""
    if operation_id not in {operation.id for operation in definitions()}:
        return False

    def enabled(*names):
        return all(bool(getattr(settings, name, False)) for name in names)

    if operation_id.startswith("workspace."):
        return enabled("workspace_available")
    if operation_id == "core.read_record_location":
        return enabled("workspace_core_record_available")
    if operation_id.startswith("core."):
        return enabled("workspace_core_connection_available")
    if operation_id.startswith("scribe."):
        return enabled("workspace_capture_available") and (operation_id != "scribe.read_source_review" or
            enabled("workspace_capture_source_enabled", "workspace_capture_notes_enabled", "workspace_capture_corrections_enabled"))
    if operation_id.startswith("visit_prep."):
        return enabled("workspace_available", "workspace_prep_work_enabled")
    if operation_id.startswith("scheduling."):
        return enabled("workspace_scheduling_available", "workspace_appointments_enabled") if operation_id == "scheduling.list_saved_proposals" else enabled("workspace_scheduling_patient_setup_available")
    if operation_id.startswith("research."):
        return enabled("workspace_research_available")
    return False
