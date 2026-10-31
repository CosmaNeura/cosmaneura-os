"""Read-only Elation tools over the existing signed CosmaBot EHR read route.

These tools do not hold tokens or choose a vendor. They call
``POST /connections/ehr/reads`` through the current application session.
A result is one page. Not connected and unsupported stay separate from a
successful read, a wrong practice, and a discarded stale result.

Chart rows are returned to the signed-in tool caller. This module does not log
them. Handlers that do log go through the plugin process scrubber.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from cosmas_os.api.ehr_read_schemas import LabRead, Medications, Observe, Problems, Status
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.plugins.runtime import PluginError
from cosmas_os.ports.ehr_reads import (
    MedicationsObservation,
    ProblemsObservation,
    Window,
    WindowObservation,
)
from cosmas_os.ports.elation_lab_ehr import LabReportsObservation

PATH = "/connections/ehr/reads"
HEADER = "X-Cosmas-Ehr-Read"
DEADLINE = 45
RECOVERY = (
    "Repeat this same read to recover an uncertain result. "
    "This tool does not prescribe, sign, book, or change Elation."
)

NOT_CONNECTED = (
    "Elation is not connected. Connect Elation for this practice in CosmaBot, then try this read again."
)
UNSUPPORTED = "This Elation read is not supported."
WRONG_PRACTICE = (
    "That request is for a different practice than the Elation account connected to this sign-in."
)
EXPIRED = "Elation access expired or was revoked. Reconnect Elation in CosmaBot before reading again."
MALFORMED = "Elation returned a response CosmaBot could not read. No chart data is shown."
TIMEOUT = (
    "The Elation read timed out before a result was confirmed. "
    "Repeat this same request to recover it. A different request is not sent automatically."
)
UNCONFIRMED = (
    "The Elation read did not finish and the result was not confirmed. "
    "Repeat this same request to recover it. A different request is not sent automatically."
)
STALE = (
    "The Elation account changed while this was being read. The result was discarded. "
    "Check the connected practice and read again."
)
SIGN_IN = "Sign in to CosmaBot again before reading Elation."
UNAVAILABLE = "That Elation visit is not available for this read. No chart data is shown."
REJECTED = "Elation could not complete this read. No chart data is shown."
EMPTY_PAGE = "No rows were returned on this page. That does not mean the chart is empty."

DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMANDS = {
    "status": Status,
    "observe": Observe,
    "problems": Problems,
    "medications": Medications,
    "lab_reports": LabRead,
}
OBSERVATIONS = {
    "window": WindowObservation,
    "verified_problems": ProblemsObservation,
    "verified_medications": MedicationsObservation,
    "lab_reports": LabReportsObservation,
}
UNSUPPORTED_DETAILS = {
    "ehr_read_unavailable",
    "ehr_read_problems_unavailable",
    "ehr_read_medications_unavailable",
    "ehr_read_labs_unavailable",
}
EXPIRED_DETAILS = {
    "ehr_read_binding_changed",
    "ehr_read_binding_unavailable",
    "workspace_access_denied",
    "ehr_read_source_unavailable",
}
MALFORMED_DETAILS = {
    "ehr_read_response_invalid",
    "ehr_read_response_too_large",
    "ehr_read_source_invalid",
}
TIMEOUT_DETAILS = {"ehr_read_timeout", "ehr_read_unconfirmed"}
STALE_DETAILS = {"ehr_read_superseded"}
UNAVAILABLE_DETAILS = {
    "ehr_read_not_observed",
    "ehr_read_observation_unavailable",
    "ehr_read_appointment_changed",
    "ehr_read_patient_changed",
    "ehr_read_record_unavailable",
    "idempotency_conflict",
    "ehr_read_history_limit",
    "invalid_ehr_read_request",
    "ehr_read_rate_limited",
}
UUID_FIELDS = {"connection_id", "observation_id", "item_handle", "workspace_id"}
DIGEST_FIELDS = {"binding_sha256", "observation_sha256", "item_sha256"}


@dataclass(frozen=True)
class Spec:
    name: str
    operation_id: str
    title: str
    description: str
    action: str
    kind: str
    include: str | None
    capability: str | None
    arguments: tuple[str, ...]
    workspace: bool = False


def _schema(arguments: tuple[str, ...]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name in arguments:
        if name in UUID_FIELDS:
            properties[name] = {"type": "string", "format": "uuid"}
        elif name in DIGEST_FIELDS:
            properties[name] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        elif name in {"starts_at", "ends_at"}:
            properties[name] = {"type": "string", "format": "date-time"}
        elif name == "idempotency_key":
            properties[name] = {
                "type": "string", "minLength": 8, "maxLength": 100, "pattern": "^[A-Za-z0-9:_-]+$",
            }
        else:
            raise ValueError(name)
    return {
        "type": "object", "additionalProperties": False,
        "properties": properties, "required": list(arguments),
    }


VISIT = (
    "connection_id", "binding_sha256", "observation_id", "observation_sha256",
    "item_handle", "item_sha256", "idempotency_key",
)
SPECS = (
    Spec(
        name="elation_read_appointments", operation_id="elation.read_appointments",
        title="Read Elation appointments",
        description=(
            "Read one page of Elation appointments for the practice connected to this sign-in. "
            "This does not book or change a visit. If Elation is not connected, or this read is "
            "not supported, the result says so in plain language."
        ),
        action="observe", kind="window", include=None, capability=None,
        arguments=("connection_id", "binding_sha256", "starts_at", "ends_at", "idempotency_key"),
    ),
    Spec(
        name="elation_read_problems", operation_id="elation.read_problems",
        title="Read Elation problems",
        description=(
            "Read one page of Elation problems for a verified visit. "
            "This does not diagnose, prescribe, or change the chart. "
            "Not connected and not supported are separate from a returned page."
        ),
        action="problems", kind="verified_problems", include="include_problems", capability="problems",
        arguments=VISIT,
    ),
    Spec(
        name="elation_read_medications", operation_id="elation.read_medications",
        title="Read Elation medications",
        description=(
            "Read one page of Elation medications for a verified visit. "
            "This does not prescribe, sign, or change the chart. "
            "Not connected and not supported are separate from a returned page."
        ),
        action="medications", kind="verified_medications", include="include_medications",
        capability="medications", arguments=VISIT,
    ),
    Spec(
        name="elation_read_labs", operation_id="elation.read_labs",
        title="Read Elation labs",
        description=(
            "Read one page of Elation lab report candidates for a verified visit. "
            "This does not open attachments, sign a report, or change the chart. "
            "Not connected and not supported are separate from a returned page."
        ),
        action="lab_reports", kind="lab_reports", include="include_labs", capability="labs",
        arguments=("workspace_id",) + VISIT, workspace=True,
    ),
)
BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = tuple(spec.name for spec in SPECS)


def tool_definitions() -> list[dict[str, Any]]:
    rows = []
    for spec in SPECS:
        rows.append({
            "name": spec.name, "title": spec.title, "description": spec.description,
            "inputSchema": _schema(spec.arguments),
            "annotations": {
                "readOnlyHint": True, "destructiveHint": False,
                "idempotentHint": True, "openWorldHint": True,
            },
            "_meta": {"ai.cosmas/operation": {
                "id": spec.operation_id, "plugin": "elation",
                "implementation": "first_party_http", "account_status": "not_checked",
                "read_only": True, "external_send": False,
                "http": {"method": "POST", "path": PATH, "contract_header": HEADER},
            }},
        })
    return rows


def command_allowed(body: object) -> bool:
    """True only for the closed Elation read commands these tools send."""
    if not isinstance(body, dict) or body.get("provider") != "elation":
        return False
    action = body.get("action")
    model = COMMANDS.get(action) if isinstance(action, str) else None
    if model is None:
        return False
    try:
        parsed = model.model_validate(body)
    except ValidationError:
        return False
    return parsed.action == action and parsed.provider == "elation"


def _state(state: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "message": message, "read_only": True, "confirmed": state == "ready", **extra}


def _validate(spec: Spec, arguments: object) -> dict[str, Any]:
    schema = _schema(spec.arguments)
    try:
        if (not isinstance(arguments, dict) or len(json.dumps(arguments, allow_nan=False).encode()) > 65536
                or list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(arguments))):
            raise ValueError
        for name in spec.arguments:
            value = arguments[name]
            if name in UUID_FIELDS and (str(UUID(value)) != value or UUID(value).int == 0):
                raise ValueError
            if name in DIGEST_FIELDS and DIGEST.fullmatch(value) is None:
                raise ValueError
        if spec.action == "observe":
            Window(starts_at=datetime.fromisoformat(arguments["starts_at"]),
                   ends_at=datetime.fromisoformat(arguments["ends_at"]))
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise PluginError("invalid_tool_arguments") from None
    return arguments


def _status_body(spec: Spec) -> dict[str, Any]:
    body: dict[str, Any] = {"action": "status", "provider": "elation"}
    if spec.include:
        body[spec.include] = True
    return body


def _read_body(spec: Spec, arguments: dict[str, Any]) -> dict[str, Any]:
    body = {name: arguments[name] for name in spec.arguments}
    body["action"] = spec.action
    body["provider"] = "elation"
    return body


def _parse_status(body: object, spec: Spec) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError
    allowed = {
        "contract_version", "provider", "mode", "status", "connection_id", "binding_sha256",
        "practice", "installation", "transport", "problems", "medications", "labs",
    }
    required = allowed - {"problems", "medications", "labs"}
    if set(body) - allowed or not required <= set(body):
        raise ValueError
    if (type(body["contract_version"]) is not int or body["contract_version"] != 1
            or body["provider"] != "elation" or not isinstance(body["mode"], str)
            or not 1 <= len(body["mode"]) <= 32 or body["status"] not in {
                "not_enabled", "not_configured", "setup_required", "ready"}
            or body["transport"] not in {"mock", "vendor_sandbox"}):
        raise ValueError
    connection = body["connection_id"]
    binding = body["binding_sha256"]
    practice = body["practice"]
    if connection is not None and (not isinstance(connection, str) or str(UUID(connection)) != connection):
        raise ValueError
    if binding is not None and (not isinstance(binding, str) or DIGEST.fullmatch(binding) is None):
        raise ValueError
    if practice is not None:
        if (not isinstance(practice, dict) or set(practice) != {"label", "timezone"}
                or not isinstance(practice["label"], str) or not 1 <= len(practice["label"]) <= 200
                or not isinstance(practice["timezone"], str)):
            raise ValueError
        try:
            ZoneInfo(practice["timezone"])
        except Exception:
            raise ValueError from None
    installation = body["installation"]
    if installation is not None and (
            not isinstance(installation, dict) or set(installation) != {"id", "sha256"}
            or not isinstance(installation["id"], str) or str(UUID(installation["id"])) != installation["id"]
            or not isinstance(installation["sha256"], str) or DIGEST.fullmatch(installation["sha256"]) is None):
        raise ValueError
    capability = None
    if spec.capability:
        if spec.capability not in body:
            raise ValueError
        capability = body[spec.capability]
        if capability not in {"available", "not_enabled", "not_configured"}:
            raise ValueError
    if body["status"] == "ready" and (connection is None or binding is None or practice is None):
        raise ValueError
    return {
        "status": body["status"], "connection_id": connection, "binding_sha256": binding,
        "practice": None if practice is None else {"label": practice["label"], "timezone": practice["timezone"]},
        "capability": capability,
    }


def _gate(spec: Spec, status: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any] | None:
    if status["status"] == "not_enabled":
        return _state("unsupported", UNSUPPORTED)
    if status["status"] in {"not_configured", "setup_required"}:
        return _state("not_connected", NOT_CONNECTED)
    if spec.capability and status["capability"] == "not_enabled":
        return _state("unsupported", UNSUPPORTED)
    if spec.capability and status["capability"] == "not_configured":
        return _state("not_connected", NOT_CONNECTED)
    if (arguments["connection_id"] != status["connection_id"]
            or arguments["binding_sha256"] != status["binding_sha256"]):
        return _state("wrong_practice", WRONG_PRACTICE)
    return None


def _failure(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or "error" not in payload:
        return None
    if payload.get("error") == "timeout":
        return _state("timeout", TIMEOUT, automatic_retry=False)
    if payload.get("error") == "response_unconfirmed":
        return _state("timeout", UNCONFIRMED, automatic_retry=False)
    if payload.get("error") == "sign_in_required" or payload.get("http_status") == 401:
        return _state("sign_in", SIGN_IN)
    detail = payload.get("detail")
    if detail in UNSUPPORTED_DETAILS:
        return _state("unsupported", UNSUPPORTED)
    if detail in EXPIRED_DETAILS or payload.get("http_status") == 403:
        return _state("expired", EXPIRED)
    if detail == "ehr_read_provider_mismatch":
        return _state("wrong_practice", WRONG_PRACTICE)
    if detail in MALFORMED_DETAILS:
        return _state("malformed", MALFORMED)
    if detail in TIMEOUT_DETAILS:
        return _state("timeout", TIMEOUT, automatic_retry=False)
    if detail in STALE_DETAILS:
        return _state("stale", STALE)
    if detail in UNAVAILABLE_DETAILS:
        return _state("unavailable", UNAVAILABLE)
    return _state("unavailable", REJECTED)


def _page_message(kind: str, public: dict[str, Any]) -> tuple[str, bool]:
    if kind == "window":
        more = public["coverage"] == "more_rows_available"
        text = ("Showing this page; more appointments may be available." if more
                else "Showing the returned page.")
        return text, more
    if kind == "lab_reports":
        coverage = public["coverage"]
        more = coverage == "more_rows_available"
        text = {
            "more_rows_available": "Showing this page; more lab report candidates may be available.",
            "returned_page_only": "Showing this page of lab report candidates. This is not a complete lab history.",
            "continuation_unknown": "Showing this page. Elation did not say whether more lab report candidates exist.",
        }[coverage]
        return text, more
    list_name = "problems" if kind == "verified_problems" else "medications"
    noun = "problem rows" if list_name == "problems" else "medication records"
    coverage = public["item"][list_name]["coverage"]
    more = coverage == "more_rows_available"
    text = {
        "more_rows_available": f"More {noun} are available; only this page was read.",
        "end_of_results": "End of returned results; not a complete chart.",
        "unknown": f"Elation did not say whether more {noun} exist.",
    }[coverage]
    return text, more


def _rows(kind: str, public: dict[str, Any]) -> list[Any]:
    if kind == "verified_problems":
        return list(public["item"]["problems"]["items"])
    if kind == "verified_medications":
        return list(public["item"]["medications"]["items"])
    return list(public["items"])


def _project(spec: Spec, payload: object, arguments: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _state("malformed", MALFORMED)
    allowed = {
        "contract_version", "observation_id", "observation_key", "connection_id", "binding_sha256",
        "source_sha256", "payload_sha256", "observation", "transport",
    }
    required = allowed - {"transport"}
    observation = payload.get("observation")
    try:
        if (set(payload) - allowed or not required <= set(payload) or type(payload["contract_version"]) is not int
                or payload["contract_version"] != 1 or payload["observation_key"] != arguments["idempotency_key"]
                or payload["connection_id"] != arguments["connection_id"]
                or payload["binding_sha256"] != arguments["binding_sha256"]
                or not isinstance(payload["observation_id"], str)
                or str(UUID(payload["observation_id"])) != payload["observation_id"]
                or not isinstance(payload["source_sha256"], str) or DIGEST.fullmatch(payload["source_sha256"]) is None
                or not isinstance(payload["payload_sha256"], str) or DIGEST.fullmatch(payload["payload_sha256"]) is None
                or not isinstance(observation, dict) or payload_hash(observation) != payload["payload_sha256"]
                or "transport" in payload and payload["transport"] not in {"mock", "vendor_sandbox"}):
            raise ValueError
        if (payload["connection_id"] != status["connection_id"]
                or payload["binding_sha256"] != status["binding_sha256"]):
            return _state("wrong_practice", WRONG_PRACTICE)
        parsed = OBSERVATIONS[spec.kind].model_validate(observation)
        public = parsed.model_dump(mode="json")
    except (ValueError, TypeError, ValidationError, RecursionError):
        return _state("malformed", MALFORMED)
    practice = public["practice"]
    if (practice["label"], practice["timezone"]) != (status["practice"]["label"], status["practice"]["timezone"]):
        return _state("wrong_practice", WRONG_PRACTICE)
    if spec.kind == "lab_reports" and public["workspace_id"] != arguments["workspace_id"]:
        return _state("malformed", MALFORMED)
    if spec.kind != "window":
        parent = public["parent"]
        if (parent["observation_id"] != arguments["observation_id"]
                or parent["source_sha256"] != arguments["observation_sha256"]
                or parent["item_sha256"] != arguments["item_sha256"]):
            return _state("malformed", MALFORMED)
    if spec.kind in {"verified_problems", "verified_medications"} and (
            public["item"]["handle"] != arguments["item_handle"]
            or public["item"]["sha256"] != arguments["item_sha256"]):
        return _state("malformed", MALFORMED)
    message, more = _page_message(spec.kind, public)
    rows = _rows(spec.kind, public)
    if not rows:
        message = f"{message} {EMPTY_PAGE}"
    result = _state("ready", message, more_available=more, practice=practice,
                    observation_id=payload["observation_id"], source_sha256=payload["source_sha256"], rows=rows)
    if spec.kind in {"verified_problems", "verified_medications"}:
        result["patient"] = public["item"]["patient"]
    return result


def _exchange(runtime, body: dict[str, Any]) -> dict[str, Any]:
    if not command_allowed(body):
        raise PluginError("invalid_tool_arguments")
    return runtime.request("POST", PATH, headers={HEADER: "1"}, body=body, timeout=DEADLINE, closed_detail=True)


def _stopped(error: PluginError) -> dict[str, Any]:
    if str(error) == "session_changed":
        return _state("stale", STALE)
    if str(error) == "sign_in_required":
        return _state("sign_in", SIGN_IN)
    if str(error) in {"invalid_api_response", "unsupported_api_response", "response_limit_exceeded"}:
        return _state("malformed", MALFORMED)
    if str(error) == "invalid_tool_arguments":
        raise error
    return _state("unavailable", REJECTED)


def _same_account(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return (before["status"] == after["status"] == "ready"
            and before["connection_id"] == after["connection_id"]
            and before["binding_sha256"] == after["binding_sha256"]
            and before["practice"] == after["practice"]
            and before["capability"] == after["capability"])


def call(runtime, name: str, arguments: object) -> dict[str, Any]:
    spec = BY_NAME.get(name)
    if spec is None:
        raise PluginError("unknown_tool")
    checked = _validate(spec, arguments)
    if (runtime.workspace_id is not None and spec.workspace
            and checked["workspace_id"] != runtime.workspace_id):
        raise PluginError("workspace_outside_session")
    try:
        status_payload = _exchange(runtime, _status_body(spec))
    except PluginError as error:
        return {"operation": spec.operation_id, "result": _stopped(error), "recovery": RECOVERY}
    failed = _failure(status_payload)
    if failed is not None:
        return {"operation": spec.operation_id, "result": failed, "recovery": RECOVERY}
    try:
        status = _parse_status(status_payload, spec)
    except (ValidationError, ValueError, TypeError):
        return {"operation": spec.operation_id, "result": _state("malformed", MALFORMED), "recovery": RECOVERY}
    gated = _gate(spec, status, checked)
    if gated is not None:
        return {"operation": spec.operation_id, "result": gated, "recovery": RECOVERY}
    try:
        payload = _exchange(runtime, _read_body(spec, checked))
    except PluginError as error:
        return {"operation": spec.operation_id, "result": _stopped(error), "recovery": RECOVERY}
    failed = _failure(payload)
    if failed is not None:
        return {"operation": spec.operation_id, "result": failed, "recovery": RECOVERY}
    projected = _project(spec, payload, checked, status)
    if projected["state"] != "ready":
        return {"operation": spec.operation_id, "result": projected, "recovery": RECOVERY}
    try:
        after_payload = _exchange(runtime, _status_body(spec))
    except PluginError as error:
        return {"operation": spec.operation_id, "result": _stopped(error), "recovery": RECOVERY}
    if _failure(after_payload) is not None:
        return {"operation": spec.operation_id, "result": _state("stale", STALE), "recovery": RECOVERY}
    try:
        after = _parse_status(after_payload, spec)
    except (ValidationError, ValueError, TypeError):
        return {"operation": spec.operation_id, "result": _state("stale", STALE), "recovery": RECOVERY}
    if not _same_account(status, after):
        return {"operation": spec.operation_id, "result": _state("stale", STALE), "recovery": RECOVERY}
    return {"operation": spec.operation_id, "result": projected, "recovery": RECOVERY}
