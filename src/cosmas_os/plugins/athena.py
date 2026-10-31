"""Read-only athenaOne tools over CosmaBot's existing signed routes.

Medications and allergies call ``POST /connections/ehr/reads``. Appointments
and visit-link status call ``POST /connections/cosmaneura/read``. Neither path
takes a token, and neither one prescribes, signs, books, or edits the chart.
A result is one page or one saved link status. Not connected and unsupported
stay separate from a successful read, a wrong practice, and a discarded stale
result.

PR #237 adds Elation tools on the same EHR route. ``ehr_route_allowed`` keeps
that allowlist when ``cosmas_os.plugins.elation`` is present, so either merge
order can load both modules.
"""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from cosmas_os.adapters.athena_medication_read import (
    AthenaMedicationError,
    RecordedNumber,
    clinical_loads,
)
from cosmas_os.api.ehr_read_schemas import AthenaAllergies, AthenaMedications, Status
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.plugins.runtime import PluginError
from cosmas_os.ports.athena_allergy_ehr import AthenaAllergiesObservation
from cosmas_os.ports.athena_medication_ehr import AthenaMedicationsObservation
from cosmas_os.ports.athena_schedule import AthenaCommand, AthenaScheduleResponse
from cosmas_os.ports.athena_visit_links import AthenaVisitLinkCommand, AthenaVisitLinkResponse

EHR_PATH = "/connections/ehr/reads"
SCHEDULE_PATH = "/connections/cosmaneura/read"
EHR_HEADER = "X-Cosmas-Ehr-Read"
SCHEDULE_HEADER = "X-Cosmas-Connection-Contract"
EHR_DEADLINE = 45
SCHEDULE_DEADLINE = 30
RECOVERY = (
    "Repeat this same read to recover an uncertain result. "
    "This tool does not prescribe, sign, book, or change Athena."
)

NOT_CONNECTED = (
    "Athena is not connected. Connect Athena for this practice in CosmaBot, then try this read again."
)
UNSUPPORTED = "This Athena read is not supported."
WRONG_PRACTICE = (
    "That request is for a different practice than the Athena account connected to this sign-in."
)
EXPIRED = "Athena access expired or was revoked. Reconnect Athena in CosmaBot before reading again."
MALFORMED = "Athena returned a response CosmaBot could not read. No chart data is shown."
TIMEOUT = (
    "The Athena read timed out before a result was confirmed. "
    "Repeat this same request to recover it. A different request is not sent automatically."
)
UNCONFIRMED = (
    "The Athena read did not finish and the result was not confirmed. "
    "Repeat this same request to recover it. A different request is not sent automatically."
)
STALE = (
    "The Athena account changed while this was being read. The result was discarded. "
    "Check the connected practice and read again."
)
SIGN_IN = "Sign in to CosmaBot again before reading Athena."
UNAVAILABLE = "That Athena record is not available for this read. No chart data is shown."
REJECTED = "Athena could not complete this read. No chart data is shown."
EMPTY_PAGE = "No rows were returned on this page. That does not mean the chart is empty."
SECTION = (
    "Showing this returned section. This is not a complete chart, "
    "and this read does not ask for another page."
)
APPOINTMENT_STATUS = {
    "f": "Booked",
    "2": "Checked in",
    "3": "Checked out",
    "4": "Charge entered",
    "x": "Cancelled",
}
CONNECTION_STATUS = {"connected", "review_required", "ready_to_connect"}

DIGEST = re.compile(r"^[0-9a-f]{64}$")
EHR_COMMANDS = {
    "status": Status,
    "core_allergies": AthenaAllergies,
    "core_medications": AthenaMedications,
}
UNSUPPORTED_DETAILS = {"ehr_read_unavailable"}
EXPIRED_DETAILS = {
    "ehr_read_binding_changed",
    "ehr_read_binding_unavailable",
    "workspace_access_denied",
    "ehr_read_source_unavailable",
    "ehr_read_core_grant_unavailable",
    "ehr_read_core_medication_grant_unavailable",
    "core_connection_access_denied",
}
MALFORMED_DETAILS = {
    "ehr_read_response_invalid",
    "ehr_read_response_too_large",
    "ehr_read_source_invalid",
}
TIMEOUT_DETAILS = {"ehr_read_timeout", "ehr_read_unconfirmed"}
STALE_DETAILS = {
    "ehr_read_superseded",
    "ehr_read_core_grant_changed",
    "ehr_read_core_medication_grant_changed",
    "core_connection_changed",
}
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
    "invalid_core_connection_request",
    "core_connection_unavailable",
}
UUID_FIELDS = {
    "connection_id", "observation_id", "item_handle", "workspace_id", "command_key",
}
DIGEST_FIELDS = {
    "binding_sha256", "observation_sha256", "item_sha256", "connection_sha256",
    "account_sha256", "command_sha256",
}
DATE_FIELDS = {"start_date", "end_date"}
LINK_REF = re.compile(r"^athena_visit_link_[0-7][0-9a-hjkmnp-tv-z]{25}$")


@dataclass(frozen=True)
class Spec:
    name: str
    operation_id: str
    title: str
    description: str
    route: str
    action: str
    kind: str
    clinical_scope: str | None
    arguments: tuple[str, ...]
    workspace: bool = False


def _schema(arguments: tuple[str, ...]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name in arguments:
        if name in UUID_FIELDS:
            properties[name] = {"type": "string", "format": "uuid"}
        elif name in DIGEST_FIELDS:
            properties[name] = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
        elif name in DATE_FIELDS:
            properties[name] = {"type": "string", "format": "date"}
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
    "connection_id", "binding_sha256", "workspace_id", "observation_id", "observation_sha256",
    "item_handle", "item_sha256", "idempotency_key",
)
SPECS = (
    Spec(
        name="athena_read_appointments", operation_id="athena.read_appointments",
        title="Read Athena appointments",
        description=(
            "Read one page of athenaOne appointments for the practice connected to this sign-in. "
            "The schedule does not include patient names. This does not book or change a visit. "
            "If Athena is not connected, or this read is not supported, the result says so in plain language."
        ),
        route="schedule", action="athena_appointments", kind="appointments", clinical_scope=None,
        arguments=("connection_sha256", "account_sha256", "start_date", "end_date"),
    ),
    Spec(
        name="athena_read_medications", operation_id="athena.read_medications",
        title="Read Athena medications",
        description=(
            "Read the returned Athena medication section for one authorized patient. "
            "This does not prescribe, sign, or change the chart. "
            "Not connected and not supported are separate from a returned section."
        ),
        route="ehr", action="core_medications", kind="medications", clinical_scope="medications",
        arguments=VISIT, workspace=True,
    ),
    Spec(
        name="athena_read_allergies", operation_id="athena.read_allergies",
        title="Read Athena allergies",
        description=(
            "Read the returned Athena allergy section for one authorized patient. "
            "This does not change the chart. "
            "Not connected and not supported are separate from a returned section."
        ),
        route="ehr", action="core_allergies", kind="allergies", clinical_scope=None,
        arguments=VISIT, workspace=True,
    ),
    Spec(
        name="athena_read_visit_link_status", operation_id="athena.read_visit_link_status",
        title="Read Athena visit-link status",
        description=(
            "Read the status of one saved Athena visit link. "
            "This does not link, unlink, or open a visit. "
            "If Athena is not connected, or visit links are not supported, the result says so in plain language."
        ),
        route="schedule", action="athena_visit_status", kind="visit_status", clinical_scope=None,
        arguments=("connection_sha256", "account_sha256", "command_key", "command_sha256"),
    ),
)
BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = tuple(spec.name for spec in SPECS)


def optional_elation() -> Any | None:
    """Elation tools from PR #237, when that module is on the tree."""
    try:
        return importlib.import_module("cosmas_os.plugins.elation")
    except ImportError:
        return None


def tool_definitions() -> list[dict[str, Any]]:
    rows = []
    for spec in SPECS:
        path = EHR_PATH if spec.route == "ehr" else SCHEDULE_PATH
        header = EHR_HEADER if spec.route == "ehr" else SCHEDULE_HEADER
        rows.append({
            "name": spec.name, "title": spec.title, "description": spec.description,
            "inputSchema": _schema(spec.arguments),
            "annotations": {
                "readOnlyHint": True, "destructiveHint": False,
                "idempotentHint": True, "openWorldHint": True,
            },
            "_meta": {"ai.cosmas/operation": {
                "id": spec.operation_id, "plugin": "athena",
                "implementation": "first_party_http", "account_status": "not_checked",
                "read_only": True, "external_send": False,
                "http": {"method": "POST", "path": path, "contract_header": header},
            }},
        })
    return rows


def command_allowed(body: object) -> bool:
    """True only for the closed Athena chart reads these tools send."""
    if not isinstance(body, dict) or body.get("provider") != "athena" or body.get("protocol") != "core":
        return False
    action = body.get("action")
    model = EHR_COMMANDS.get(action) if isinstance(action, str) else None
    if model is None:
        return False
    try:
        parsed = model.model_validate(body)
    except ValidationError:
        return False
    if parsed.action != action or parsed.provider != "athena" or parsed.protocol != "core":
        return False
    if action == "core_allergies":
        return parsed.clinical_scope is None
    if action == "core_medications":
        return parsed.clinical_scope == "medications"
    return action == "status" and parsed.clinical_scope in (None, "medications")


def ehr_route_allowed(body: object) -> bool:
    """Athena chart reads, plus Elation reads when PR #237 is checked out."""
    if command_allowed(body):
        return True
    module = optional_elation()
    if module is None:
        return False
    return bool(module.command_allowed(body))


def schedule_command_allowed(body: object) -> bool:
    """True only for one connection check, the first appointment page, or one link status."""
    if not isinstance(body, dict):
        return False
    action = body.get("action")
    if action in {"athena_connection", "athena_appointments"}:
        model = AthenaCommand
    elif action == "athena_visit_status":
        model = AthenaVisitLinkCommand
    else:
        return False
    try:
        parsed = model.model_validate(body)
    except ValidationError:
        return False
    if parsed.action != action:
        return False
    if action == "athena_appointments":
        return isinstance(parsed, AthenaCommand) and parsed.offset == 0
    return True


def _state(state: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"state": state, "message": message, "read_only": True, "confirmed": state == "ready", **extra}


def _done(spec: Spec, result: dict[str, Any]) -> dict[str, Any]:
    return {"operation": spec.operation_id, "result": result, "recovery": RECOVERY}


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
        nonce = str(uuid4())
        if spec.kind == "appointments":
            AthenaCommand.model_validate({
                "action": "athena_appointments", "request_nonce": nonce,
                "connection_sha256": arguments["connection_sha256"],
                "account_sha256": arguments["account_sha256"],
                "start_date": arguments["start_date"], "end_date": arguments["end_date"], "offset": 0,
            })
        elif spec.kind == "visit_status":
            AthenaVisitLinkCommand.model_validate({
                "action": "athena_visit_status", "request_nonce": nonce,
                "connection_sha256": arguments["connection_sha256"],
                "account_sha256": arguments["account_sha256"],
                "command_key": arguments["command_key"], "command_sha256": arguments["command_sha256"],
            })
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise PluginError("invalid_tool_arguments") from None
    return arguments


def _ehr_status_body(spec: Spec) -> dict[str, Any]:
    body: dict[str, Any] = {"action": "status", "provider": "athena", "protocol": "core"}
    if spec.clinical_scope:
        body["clinical_scope"] = spec.clinical_scope
    return body


def _ehr_read_body(spec: Spec, arguments: dict[str, Any]) -> dict[str, Any]:
    body = {name: arguments[name] for name in spec.arguments}
    body["action"] = spec.action
    body["provider"] = "athena"
    body["protocol"] = "core"
    if spec.clinical_scope:
        body["clinical_scope"] = spec.clinical_scope
    return body


def _connection_body(connection_sha256: str) -> dict[str, Any]:
    return {
        "action": "athena_connection", "request_nonce": str(uuid4()),
        "connection_sha256": connection_sha256,
    }


def _schedule_read_body(spec: Spec, arguments: dict[str, Any]) -> dict[str, Any]:
    nonce = str(uuid4())
    if spec.kind == "appointments":
        return {
            "action": "athena_appointments", "request_nonce": nonce,
            "connection_sha256": arguments["connection_sha256"],
            "account_sha256": arguments["account_sha256"],
            "start_date": arguments["start_date"], "end_date": arguments["end_date"], "offset": 0,
        }
    return {
        "action": "athena_visit_status", "request_nonce": nonce,
        "connection_sha256": arguments["connection_sha256"],
        "account_sha256": arguments["account_sha256"],
        "command_key": arguments["command_key"], "command_sha256": arguments["command_sha256"],
    }


def _wire(payload: object) -> tuple[dict[str, Any], str | None]:
    if not isinstance(payload, dict):
        raise ValueError
    body = dict(payload)
    nonce = body.pop("_nonce", None)
    if nonce is not None and (not isinstance(nonce, str) or UUID(nonce).version != 4):
        raise ValueError
    return body, nonce


def _parse_ehr_status(body: dict[str, Any], spec: Spec) -> dict[str, Any]:
    allowed = {
        "contract_version", "provider", "protocol", "mode", "status", "connection_id",
        "binding_sha256", "practice_label", "transport", "clinical_scope",
    }
    required = allowed if spec.clinical_scope else allowed - {"clinical_scope"}
    if set(body) - allowed or not required <= set(body):
        raise ValueError
    if spec.clinical_scope is None and "clinical_scope" in body:
        raise ValueError
    practice = body["practice_label"]
    connection = body["connection_id"]
    binding = body["binding_sha256"]
    if (type(body["contract_version"]) is not int or body["contract_version"] != 1
            or body["provider"] != "athena" or body["protocol"] != "core" or body["mode"] != "synthetic"
            or body["status"] not in {"not_enabled", "not_configured", "setup_required", "ready"}
            or body["transport"] != "mock"):
        raise ValueError
    if spec.clinical_scope and body.get("clinical_scope") != "medications":
        raise ValueError
    if connection is not None and (not isinstance(connection, str) or str(UUID(connection)) != connection):
        raise ValueError
    if binding is not None and (not isinstance(binding, str) or DIGEST.fullmatch(binding) is None):
        raise ValueError
    if practice is not None and (not isinstance(practice, str) or not 1 <= len(practice) <= 200):
        raise ValueError
    if body["status"] == "ready" and (connection is None or binding is None or practice is None):
        raise ValueError
    return {
        "status": body["status"], "connection_id": connection, "binding_sha256": binding,
        "practice_label": practice, "clinical_scope": body.get("clinical_scope"),
    }


def _account_view(discovery: AthenaScheduleResponse) -> dict[str, Any]:
    account = discovery.account
    return {
        "connection_sha256": discovery.connection.connection_sha256,
        "account_sha256": None if account is None else account.account_sha256,
        "practice_label": discovery.connection.practice_label,
        "department_label": None if account is None else account.department_label,
        "timezone": None if account is None else account.department_timezone,
        "environment": None if account is None else account.environment,
    }


def _parse_connection(body: dict[str, Any], nonce: str | None) -> dict[str, Any]:
    allowed = {"contract_version", "action", "connection_status", "athena_discovery"}
    if set(body) != allowed or nonce is None:
        raise ValueError
    status = body["connection_status"]
    if (type(body["contract_version"]) is not int or body["contract_version"] != 1
            or body["action"] != "athena_connection" or status not in CONNECTION_STATUS):
        raise ValueError
    discovery = AthenaScheduleResponse.model_validate(body["athena_discovery"])
    if (discovery.action != "connection" or str(discovery.request_nonce) != nonce
            or discovery.appointments or discovery.total_count is not None
            or discovery.next_offset is not None or discovery.complete or discovery.truncated):
        raise ValueError
    return {"connection_status": status, **_account_view(discovery)}


def _parse_status(spec: Spec, payload: object, _arguments: dict[str, Any]) -> dict[str, Any]:
    body, nonce = _wire(payload)
    if spec.route == "ehr":
        return _parse_ehr_status(body, spec)
    return _parse_connection(body, nonce)


def _gate(spec: Spec, status: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any] | None:
    if spec.route == "ehr":
        if status["status"] == "not_enabled":
            return _state("unsupported", UNSUPPORTED)
        if status["status"] in {"not_configured", "setup_required"}:
            return _state("not_connected", NOT_CONNECTED)
        if (arguments["connection_id"] != status["connection_id"]
                or arguments["binding_sha256"] != status["binding_sha256"]):
            return _state("wrong_practice", WRONG_PRACTICE)
        return None
    if status["connection_status"] != "connected" or status["account_sha256"] is None:
        return _state("not_connected", NOT_CONNECTED)
    if (arguments["connection_sha256"] != status["connection_sha256"]
            or arguments["account_sha256"] != status["account_sha256"]):
        return _state("wrong_practice", WRONG_PRACTICE)
    return None


def _failure(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or "error" not in payload:
        return None
    status = payload.get("http_status")
    detail = payload.get("detail")
    if payload.get("error") == "timeout" or status == 504:
        return _state("timeout", TIMEOUT, automatic_retry=False)
    if payload.get("error") == "response_unconfirmed":
        return _state("timeout", UNCONFIRMED, automatic_retry=False)
    if payload.get("error") == "sign_in_required" or status == 401:
        return _state("sign_in", SIGN_IN)
    if detail in UNSUPPORTED_DETAILS or (detail == "core_connection_unavailable" and status == 404):
        return _state("unsupported", UNSUPPORTED)
    if detail == "core_connection_required":
        return _state("not_connected", NOT_CONNECTED)
    if detail in EXPIRED_DETAILS or status == 403:
        return _state("expired", EXPIRED)
    if detail == "ehr_read_provider_mismatch":
        return _state("wrong_practice", WRONG_PRACTICE)
    if detail in MALFORMED_DETAILS:
        return _state("malformed", MALFORMED)
    if detail in TIMEOUT_DETAILS:
        return _state("timeout", TIMEOUT, automatic_retry=False)
    if detail in STALE_DETAILS:
        return _state("stale", STALE)
    if detail in UNAVAILABLE_DETAILS and not (detail == "core_connection_unavailable" and status == 404):
        return _state("unavailable", UNAVAILABLE)
    return _state("unavailable", REJECTED)


def _patient(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError
    patient: dict[str, Any] = {
        "first_name": parsed["firstname"], "last_name": parsed["lastname"],
        "birth_date": parsed.get("dob"),
    }
    if "middlename" in parsed:
        patient["middle_name"] = parsed["middlename"]
    if "status" in parsed:
        patient["recorded_status"] = parsed["status"]
    if "deceaseddate" in parsed:
        patient["recorded_death_date"] = parsed["deceaseddate"]
    return patient


def _practice(status: dict[str, Any], department: str | None = None) -> dict[str, Any]:
    practice: dict[str, Any] = {"label": status["practice_label"]}
    if department is not None:
        practice["department"] = department
    if status.get("timezone"):
        practice["timezone"] = status["timezone"]
    return practice


def _allergy_rows(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for record in section["allergies"]:
        if "reactions" not in record:
            reactions = None
        else:
            reactions = [{"name": item.get("reactionname"), "severity": item.get("severity")}
                         for item in record["reactions"]]
        rows.append({
            "allergen_name": record.get("allergenname"),
            "criticality": record.get("criticality"),
            "onset_date": record.get("onsetdate"),
            "deactivation_date": record.get("deactivatedate"),
            "note": record.get("note"),
            "reactions": reactions,
        })
    return rows


def _allergy_message(section: dict[str, Any], rows: list[Any]) -> str:
    if "nkda" not in section:
        statement = "Athena did not provide a no-known-drug-allergies statement."
    elif section["nkda"] is True:
        statement = "Athena recorded no known drug allergies as true."
    else:
        statement = "Athena recorded no known drug allergies as false."
    message = f"{SECTION} {statement}"
    if section.get("nkda") is True and rows:
        message += " Athena also returned allergy records. Both are shown; this read does not reconcile them."
    if not rows:
        message = f"{message} {EMPTY_PAGE}"
    return message


def _medication_rows(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for group in section["medications"]:
        for record in group:
            quantity = record.get("quantity")
            rows.append({
                "medication_name": record.get("medication"),
                "status": record.get("status"),
                "route": record.get("route"),
                "directions": record.get("unstructuredsig"),
                "quantity": quantity.token if isinstance(quantity, RecordedNumber) else None,
                "discontinued": record.get("isdiscontinued"),
            })
    return rows


def _medication_message(section: dict[str, Any], rows: list[Any]) -> str:
    reported = section.get("nomedicationsreported")
    if reported is True:
        statement = "Athena recorded that no medications were reported."
    elif reported is False:
        statement = "Athena recorded that no-medications-reported is false."
    else:
        statement = "Athena did not provide a no-medications-reported statement."
    message = f"{SECTION} {statement}"
    if reported is True and rows:
        message += " Athena also returned medication records. Both are shown; this read does not reconcile them."
    if not rows:
        message = f"{message} {EMPTY_PAGE}"
    return message


def _matches_parent(public: dict[str, Any], arguments: dict[str, Any]) -> bool:
    parent = public["parent"]
    item = public["item"]
    return (parent["observation_id"] == arguments["observation_id"]
            and parent["source_sha256"] == arguments["observation_sha256"]
            and parent["item_sha256"] == arguments["item_sha256"]
            and item["handle"] == arguments["item_handle"]
            and item["sha256"] == arguments["item_sha256"]
            and public["workspace_id"] == arguments["workspace_id"])


def _project_chart(spec: Spec, body: dict[str, Any], arguments: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "provider", "protocol", "clinical_scope", "contract_version", "observation_id", "observation_key",
        "transport", "connection_id", "binding_sha256", "source_sha256", "payload_sha256", "observation",
    }
    required = allowed if spec.clinical_scope else allowed - {"clinical_scope"}
    observation = body.get("observation")
    if (set(body) - allowed or not required <= set(body) or type(body["contract_version"]) is not int
            or body["contract_version"] != 1 or body["provider"] != "athena" or body["protocol"] != "core"
            or body["transport"] != "mock" or body["observation_key"] != arguments["idempotency_key"]
            or body["connection_id"] != arguments["connection_id"]
            or body["binding_sha256"] != arguments["binding_sha256"]
            or not isinstance(body["observation_id"], str)
            or str(UUID(body["observation_id"])) != body["observation_id"]
            or not isinstance(body["source_sha256"], str) or DIGEST.fullmatch(body["source_sha256"]) is None
            or not isinstance(body["payload_sha256"], str) or DIGEST.fullmatch(body["payload_sha256"]) is None
            or not isinstance(observation, dict) or payload_hash(observation) != body["payload_sha256"]):
        raise ValueError
    if spec.clinical_scope and body.get("clinical_scope") != "medications":
        raise ValueError
    if spec.clinical_scope is None and "clinical_scope" in body:
        raise ValueError
    if (body["connection_id"] != status["connection_id"] or body["binding_sha256"] != status["binding_sha256"]):
        return _state("wrong_practice", WRONG_PRACTICE)
    model = AthenaMedicationsObservation if spec.kind == "medications" else AthenaAllergiesObservation
    public = model.model_validate(observation).model_dump(mode="json")
    if public["practice_label"] != status["practice_label"] or not _matches_parent(public, arguments):
        return _state("wrong_practice", WRONG_PRACTICE) if public["practice_label"] != status["practice_label"] else _state("malformed", MALFORMED)
    if spec.kind == "allergies":
        section = json.loads(public["item"]["section_json"])
        rows = _allergy_rows(section)
        message = _allergy_message(section, rows)
    else:
        section = clinical_loads(public["item"]["section_json"])
        rows = _medication_rows(section)
        message = _medication_message(section, rows)
    return _state(
        "ready", message, more_available=False,
        practice=_practice(status, public["item"]["department_label"]),
        patient=_patient(public["item"]["patient_identity_json"]),
        observation_id=body["observation_id"], source_sha256=body["source_sha256"], rows=rows,
    )


def _page_consistent(discovery: AthenaScheduleResponse) -> bool:
    total = discovery.total_count
    count = len(discovery.appointments)
    if total is None or count > total or (count == 0 and total > 0):
        return False
    more = count < total
    expected_next = count if more and count <= 10_000 else None
    return (discovery.next_offset == expected_next and discovery.complete is (not more)
            and discovery.truncated is (more and expected_next is None))


def _project_appointments(body: dict[str, Any], arguments: dict[str, Any], status: dict[str, Any], nonce: str | None) -> dict[str, Any]:
    allowed = {"contract_version", "action", "connection_status", "athena_discovery"}
    if (set(body) != allowed or nonce is None or type(body["contract_version"]) is not int
            or body["contract_version"] != 1 or body["action"] != "athena_appointments"
            or body["connection_status"] != "connected"):
        raise ValueError
    discovery = AthenaScheduleResponse.model_validate(body["athena_discovery"])
    account = discovery.account
    if (discovery.action != "appointments" or str(discovery.request_nonce) != nonce or account is None
            or not _page_consistent(discovery)):
        raise ValueError
    viewed = _account_view(discovery)
    if any(viewed[key] != status[key] for key in viewed):
        return _state("wrong_practice", WRONG_PRACTICE)
    start, end = arguments["start_date"], arguments["end_date"]
    rows = []
    for row in discovery.appointments:
        local = row.source_local_start.date().isoformat()
        if not start <= local <= end or row.department_timezone != account.department_timezone:
            raise ValueError
        rows.append({
            "local_start": row.source_local_start.isoformat(),
            "timezone": row.department_timezone,
            "duration_minutes": row.duration_minutes,
            "status": APPOINTMENT_STATUS[row.source_status],
        })
    more = discovery.next_offset is not None or discovery.truncated
    message = ("Showing this page; more appointments may be available. This read does not ask for the next page."
               if more else "Showing the returned page.")
    if not rows:
        message = f"{message} {EMPTY_PAGE}"
    return _state("ready", message, more_available=more, practice=_practice(status, account.department_label), rows=rows)


def _project_visit(body: dict[str, Any], arguments: dict[str, Any], status: dict[str, Any], nonce: str | None) -> dict[str, Any]:
    allowed = {"contract_version", "action", "connection_status", "athena_visit_link"}
    if (set(body) != allowed or nonce is None or type(body["contract_version"]) is not int
            or body["contract_version"] != 1 or body["action"] != "athena_visit_status"
            or body["connection_status"] != "connected"):
        raise ValueError
    link = AthenaVisitLinkResponse.model_validate(body["athena_visit_link"])
    viewed = _account_view(AthenaScheduleResponse.model_validate({
        "action": "connection", "request_nonce": str(link.request_nonce), "checked_at": link.checked_at,
        "connection": link.connection, "account": link.account,
    }))
    if link.action != "status" or str(link.request_nonce) != nonce:
        raise ValueError
    if str(link.command_key) != arguments["command_key"] or link.command_sha256 != arguments["command_sha256"]:
        raise ValueError
    if any(viewed[key] != status[key] for key in viewed):
        return _state("wrong_practice", WRONG_PRACTICE)
    if link.state == "not_found":
        if link.applied or link.operation is not None or link.link_ref is not None:
            raise ValueError
        message = "No Athena visit link was found for that saved request."
    elif link.state == "linked" and link.applied and link.operation == "link":
        message = "This Athena visit is linked. This read does not change the link."
    elif link.state == "removed" and link.applied and link.operation == "unlink":
        message = "This Athena visit link was removed. This read does not change the link."
    elif link.state == "review_required" and link.applied and link.operation in {"link", "unlink"}:
        message = (
            "This Athena visit link still needs a person to review it in CosmaBot. "
            "This read does not link or remove it."
        )
    else:
        raise ValueError
    if link.link_ref is not None and LINK_REF.fullmatch(link.link_ref) is None:
        raise ValueError
    return _state(
        "ready", message, more_available=False, link_state=link.state,
        practice=_practice(status, link.account.department_label),
    )


def _project(spec: Spec, payload: object, arguments: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    try:
        body, nonce = _wire(payload)
        if spec.route == "ehr":
            return _project_chart(spec, body, arguments, status)
        if spec.kind == "appointments":
            return _project_appointments(body, arguments, status, nonce)
        return _project_visit(body, arguments, status, nonce)
    except (AthenaMedicationError, ValueError, TypeError, ValidationError, RecursionError, KeyError):
        return _state("malformed", MALFORMED)


def _exchange(runtime, method_path: tuple[str, str], header: tuple[str, str], body: dict[str, Any], timeout: int) -> dict[str, Any]:
    path, kind = method_path
    allowed = command_allowed(body) if kind == "ehr" else schedule_command_allowed(body)
    if not allowed:
        raise PluginError("invalid_tool_arguments")
    return runtime.request("POST", path, headers={header[0]: header[1]}, body=body, timeout=timeout, closed_detail=True)


def _tagged(payload: object, nonce: str | None) -> object:
    if isinstance(payload, dict) and nonce is not None:
        return {**payload, "_nonce": nonce}
    return payload


def _exchange_status(runtime, spec: Spec, arguments: dict[str, Any]) -> object:
    if spec.route == "ehr":
        return _exchange(runtime, (EHR_PATH, "ehr"), (EHR_HEADER, "1"), _ehr_status_body(spec), EHR_DEADLINE)
    body = _connection_body(arguments["connection_sha256"])
    payload = _exchange(runtime, (SCHEDULE_PATH, "schedule"), (SCHEDULE_HEADER, "1"), body, SCHEDULE_DEADLINE)
    return _tagged(payload, body["request_nonce"])


def _exchange_read(runtime, spec: Spec, arguments: dict[str, Any]) -> object:
    if spec.route == "ehr":
        return _exchange(runtime, (EHR_PATH, "ehr"), (EHR_HEADER, "1"), _ehr_read_body(spec, arguments), EHR_DEADLINE)
    body = _schedule_read_body(spec, arguments)
    payload = _exchange(runtime, (SCHEDULE_PATH, "schedule"), (SCHEDULE_HEADER, "1"), body, SCHEDULE_DEADLINE)
    return _tagged(payload, body["request_nonce"])


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


def _same(spec: Spec, before: dict[str, Any], after: dict[str, Any]) -> bool:
    if spec.route == "ehr":
        return (before["status"] == after["status"] == "ready"
                and before["connection_id"] == after["connection_id"]
                and before["binding_sha256"] == after["binding_sha256"]
                and before["practice_label"] == after["practice_label"]
                and before["clinical_scope"] == after["clinical_scope"])
    keys = ("connection_sha256", "account_sha256", "practice_label", "department_label", "timezone", "environment")
    return (before["connection_status"] == after["connection_status"] == "connected"
            and all(before[key] == after[key] for key in keys))


def call(runtime, name: str, arguments: object) -> dict[str, Any]:
    spec = BY_NAME.get(name)
    if spec is None:
        raise PluginError("unknown_tool")
    checked = _validate(spec, arguments)
    if (runtime.workspace_id is not None and spec.workspace
            and checked["workspace_id"] != runtime.workspace_id):
        raise PluginError("workspace_outside_session")
    try:
        status_payload = _exchange_status(runtime, spec, checked)
    except PluginError as error:
        return _done(spec, _stopped(error))
    failed = _failure(status_payload)
    if failed is not None:
        return _done(spec, failed)
    try:
        status = _parse_status(spec, status_payload, checked)
    except (ValidationError, ValueError, TypeError):
        return _done(spec, _state("malformed", MALFORMED))
    gated = _gate(spec, status, checked)
    if gated is not None:
        return _done(spec, gated)
    try:
        payload = _exchange_read(runtime, spec, checked)
    except PluginError as error:
        return _done(spec, _stopped(error))
    failed = _failure(payload)
    if failed is not None:
        return _done(spec, failed)
    projected = _project(spec, payload, checked, status)
    if projected["state"] != "ready":
        return _done(spec, projected)
    try:
        after_payload = _exchange_status(runtime, spec, checked)
    except PluginError as error:
        return _done(spec, _stopped(error))
    if _failure(after_payload) is not None:
        return _done(spec, _state("stale", STALE))
    try:
        after = _parse_status(spec, after_payload, checked)
    except (ValidationError, ValueError, TypeError):
        return _done(spec, _state("stale", STALE))
    if not _same(spec, status, after):
        return _done(spec, _state("stale", STALE))
    return _done(spec, projected)
