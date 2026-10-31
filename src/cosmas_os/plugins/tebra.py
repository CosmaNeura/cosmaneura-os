"""Read-only Tebra tools over the existing signed CosmaBot EHR read route.

Practice appointments and the verified visit call ``POST /connections/ehr/reads``
with provider ``tebra``. Authorized patients and medication records call that
same route with protocol ``fhir``. These tools do not hold tokens, follow a
cursor, or send a free-form query. A result is one page or one verified visit.
Not connected and unsupported stay separate from a successful read, a wrong
practice, and a discarded stale result.

The SOAP patient search is not its own route; it runs inside the existing
visit verification, which ``tebra_read_visit`` calls. A later medication page,
and Tebra problems, allergies, labs, or a SOAP medication list, are not
routes. Those reads stay unsupported here instead of adding an API.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from cosmas_os.api.ehr_read_schemas import FhirMedications, FhirPatients, Observe, Status, Verify
from cosmas_os.domain.hashing import payload_hash
from cosmas_os.plugins.runtime import PluginError
from cosmas_os.ports.ehr_reads import TebraVerifiedObservation, TebraWindowObservation, Window
from cosmas_os.ports.tebra_fhir_ehr import FhirMedicationsObservation, FhirPatientsObservation

PATH = "/connections/ehr/reads"
HEADER = "X-Cosmas-Ehr-Read"
DEADLINE = 45
RECOVERY = (
    "Repeat this same read to recover an uncertain result. "
    "This tool does not prescribe, sign, book, or change Tebra."
)

NOT_CONNECTED = (
    "Tebra is not connected. Connect Tebra for this practice in CosmaBot, then try this read again."
)
UNSUPPORTED = "This Tebra read is not supported."
WRONG_PRACTICE = (
    "That request is for a different practice than the Tebra account connected to this sign-in."
)
EXPIRED = "Tebra access expired or was revoked. Reconnect Tebra in CosmaBot before reading again."
MALFORMED = "Tebra returned a response CosmaBot could not read. No chart data is shown."
TIMEOUT = (
    "The Tebra read timed out before a result was confirmed. "
    "Repeat this same request to recover it. A different request is not sent automatically."
)
UNCONFIRMED = (
    "The Tebra read did not finish and the result was not confirmed. "
    "Repeat this same request to recover it. A different request is not sent automatically."
)
STALE = (
    "The Tebra account changed while this was being read. The result was discarded. "
    "Check the connected practice and read again."
)
SIGN_IN = "Sign in to CosmaBot again before reading Tebra."
UNAVAILABLE = "That Tebra record is not available for this read. No chart data is shown."
REJECTED = "Tebra could not complete this read. No chart data is shown."
EMPTY_PAGE = "No rows were returned on this page. That does not mean the chart is empty."
APPOINTMENTS = "Showing returned appointments only; this is not a complete schedule."
VISIT_PAGE = (
    "Showing this verified visit. This is not a complete schedule, "
    "and this read does not ask for another page."
)
PATIENTS_PAGE = (
    "Showing authorized patients for this encounter. This is not a complete patient list, "
    "and this read does not ask for another page."
)
MEDICATIONS_MORE = "More medication records are available; only this page was read."
MEDICATIONS_PAGE = (
    "Showing this page of medication records. This is not a complete chart, "
    "and this read does not ask for another page."
)

DIGEST = re.compile(r"^[0-9a-f]{64}$")
WARNING = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
COMMANDS = {
    "status": Status,
    "observe": Observe,
    "verify": Verify,
    "fhir_patients": FhirPatients,
    "fhir_medications": FhirMedications,
}
OBSERVATIONS = {
    "window": TebraWindowObservation,
    "verified_visit": TebraVerifiedObservation,
    "fhir_patients": FhirPatientsObservation,
    "fhir_medications": FhirMedicationsObservation,
}
UNSUPPORTED_DETAILS = {"ehr_read_unavailable"}
EXPIRED_DETAILS = {
    "ehr_read_binding_changed",
    "ehr_read_binding_unavailable",
    "workspace_access_denied",
    "ehr_read_source_unavailable",
    "ehr_read_fhir_grant_unavailable",
}
MALFORMED_DETAILS = {
    "ehr_read_response_invalid",
    "ehr_read_response_too_large",
    "ehr_read_source_invalid",
}
TIMEOUT_DETAILS = {"ehr_read_timeout", "ehr_read_unconfirmed"}
STALE_DETAILS = {"ehr_read_superseded", "ehr_read_fhir_grant_changed"}
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
PRACTICE_STATUS = {
    "contract_version", "provider", "mode", "status", "connection_id", "binding_sha256",
    "practice", "installation", "transport",
}
FHIR_STATUS = {
    "contract_version", "provider", "protocol", "mode", "transport", "status",
    "connection_id", "binding_sha256", "display_label",
}
PRACTICE_RECEIPT = {
    "provider", "contract_version", "observation_id", "observation_key", "transport",
    "connection_id", "binding_sha256", "source_sha256", "payload_sha256", "observation",
}
FHIR_RECEIPT = PRACTICE_RECEIPT | {"protocol"}


@dataclass(frozen=True)
class Spec:
    name: str
    operation_id: str
    title: str
    description: str
    action: str
    kind: str
    family: str
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
        elif name == "birth_date":
            properties[name] = {"type": "string", "format": "date"}
        elif name == "idempotency_key":
            properties[name] = {
                "type": "string", "minLength": 8, "maxLength": 100, "pattern": "^[A-Za-z0-9:_-]+$",
            }
        elif name == "last_name":
            properties[name] = {"type": "string", "minLength": 1, "maxLength": 255}
        else:
            raise ValueError(name)
    return {
        "type": "object", "additionalProperties": False,
        "properties": properties, "required": list(arguments),
    }


VISIT = (
    "connection_id", "binding_sha256", "observation_id", "observation_sha256",
    "item_handle", "item_sha256", "last_name", "birth_date", "idempotency_key",
)
PATIENTS = ("connection_id", "binding_sha256", "workspace_id", "idempotency_key")
MEDICATIONS = (
    "connection_id", "binding_sha256", "workspace_id", "observation_id", "observation_sha256",
    "item_handle", "item_sha256", "idempotency_key",
)
SPECS = (
    Spec(
        name="tebra_read_appointments", operation_id="tebra.read_appointments",
        title="Read Tebra appointments",
        description=(
            "Read one page of Tebra appointments for the practice connected to this sign-in. "
            "Returned rows are not a complete schedule. This does not book or change a visit. "
            "If Tebra is not connected, or this read is not supported, the result says so in plain language."
        ),
        action="observe", kind="window", family="practice",
        arguments=("connection_id", "binding_sha256", "starts_at", "ends_at", "idempotency_key"),
    ),
    Spec(
        name="tebra_read_visit", operation_id="tebra.read_visit",
        title="Read one verified Tebra visit",
        description=(
            "Read the patient on one selected Tebra appointment. The surname and birth date are the "
            "closed fields that appointment verification already requires. This is not a chart search, "
            "and it does not book or change the visit. Not connected and not supported are separate "
            "from the returned visit."
        ),
        action="verify", kind="verified_visit", family="practice", arguments=VISIT,
    ),
    Spec(
        name="tebra_read_authorized_patients", operation_id="tebra.read_authorized_patients",
        title="Read authorized Tebra patients",
        description=(
            "Read the authorized Tebra patients already granted for this encounter. "
            "This does not search the chart and does not change a patient. "
            "Not connected and not supported are separate from the returned list."
        ),
        action="fhir_patients", kind="fhir_patients", family="fhir", arguments=PATIENTS, workspace=True,
    ),
    Spec(
        name="tebra_read_medications", operation_id="tebra.read_medications",
        title="Read Tebra medication records",
        description=(
            "Read one page of Tebra medication records for one authorized patient. "
            "This does not prescribe, sign, or change the chart, and it does not ask for the next page. "
            "Not connected and not supported are separate from a returned page."
        ),
        action="fhir_medications", kind="fhir_medications", family="fhir",
        arguments=MEDICATIONS, workspace=True,
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
                "id": spec.operation_id, "plugin": "tebra",
                "implementation": "first_party_http", "account_status": "not_checked",
                "read_only": True, "external_send": False,
                "http": {"method": "POST", "path": PATH, "contract_header": HEADER},
            }},
        })
    return rows


def command_allowed(body: object) -> bool:
    """True only for the closed Tebra read commands these tools send."""
    if not isinstance(body, dict) or body.get("provider") != "tebra":
        return False
    action = body.get("action")
    model = COMMANDS.get(action) if isinstance(action, str) else None
    if model is None:
        return False
    try:
        parsed = model.model_validate(body)
    except ValidationError:
        return False
    if parsed.action != action or parsed.provider != "tebra":
        return False
    if action in {"fhir_patients", "fhir_medications"}:
        return parsed.protocol == "fhir"
    if action == "status":
        return (parsed.protocol in {None, "fhir"} and parsed.clinical_scope is None
                and parsed.include_problems is None and parsed.include_medications is None
                and parsed.include_labs is None)
    return parsed.protocol is None and parsed.clinical_scope is None


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
            if name == "last_name" and (
                    value != value.strip() or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
                raise ValueError
            if name == "birth_date":
                born = date.fromisoformat(value)
                if len(value) != 10 or born.isoformat() != value or not date(1850, 1, 1) <= born <= date.today():
                    raise ValueError
        if spec.action == "observe":
            Window(starts_at=datetime.fromisoformat(arguments["starts_at"]),
                   ends_at=datetime.fromisoformat(arguments["ends_at"]))
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise PluginError("invalid_tool_arguments") from None
    return arguments


def _status_body(spec: Spec) -> dict[str, Any]:
    body: dict[str, Any] = {"action": "status", "provider": "tebra"}
    if spec.family == "fhir":
        body["protocol"] = "fhir"
    return body


def _read_body(spec: Spec, arguments: dict[str, Any]) -> dict[str, Any]:
    body = {name: arguments[name] for name in spec.arguments}
    body["action"] = spec.action
    body["provider"] = "tebra"
    if spec.family == "fhir":
        body["protocol"] = "fhir"
    return body


def _mode(value: object) -> None:
    if not isinstance(value, str) or not 1 <= len(value) <= 32:
        raise ValueError


def _binding(connection: object, binding: object) -> tuple[str | None, str | None]:
    checked_connection: str | None
    checked_binding: str | None
    if connection is None:
        checked_connection = None
    elif isinstance(connection, str) and str(UUID(connection)) == connection:
        checked_connection = connection
    else:
        raise ValueError
    if binding is None:
        checked_binding = None
    elif isinstance(binding, str) and DIGEST.fullmatch(binding) is not None:
        checked_binding = binding
    else:
        raise ValueError
    return checked_connection, checked_binding


def _parse_practice_status(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) != PRACTICE_STATUS:
        raise ValueError
    _mode(body["mode"])
    if (type(body["contract_version"]) is not int or body["contract_version"] != 1
            or body["provider"] != "tebra" or body["status"] not in {
                "not_enabled", "not_configured", "setup_required", "ready"}
            or body["transport"] != "mock" or body["installation"] is not None):
        raise ValueError
    connection, binding = _binding(body["connection_id"], body["binding_sha256"])
    practice = body["practice"]
    if practice is not None:
        if (not isinstance(practice, dict) or set(practice) != {"label", "timezone"}
                or not isinstance(practice["label"], str) or not 1 <= len(practice["label"]) <= 200
                or not isinstance(practice["timezone"], str)):
            raise ValueError
        try:
            ZoneInfo(practice["timezone"])
        except Exception:
            raise ValueError from None
    if body["status"] == "ready" and (connection is None or binding is None or practice is None):
        raise ValueError
    return {
        "status": body["status"], "connection_id": connection, "binding_sha256": binding,
        "practice": None if practice is None else {"label": practice["label"], "timezone": practice["timezone"]},
        "label": None,
    }


def _parse_fhir_status(body: dict[str, Any]) -> dict[str, Any]:
    if set(body) != FHIR_STATUS:
        raise ValueError
    _mode(body["mode"])
    if (type(body["contract_version"]) is not int or body["contract_version"] != 1
            or body["provider"] != "tebra" or body["protocol"] != "fhir"
            or body["status"] not in {"not_enabled", "not_configured", "ready"}
            or body["transport"] != "mock"):
        raise ValueError
    connection, binding = _binding(body["connection_id"], body["binding_sha256"])
    label = body["display_label"]
    if label is not None and (not isinstance(label, str) or not 1 <= len(label) <= 200):
        raise ValueError
    if body["status"] == "ready" and (connection is None or binding is None or label is None):
        raise ValueError
    if body["status"] != "ready" and (connection is not None or binding is not None or label is not None):
        raise ValueError
    return {
        "status": body["status"], "connection_id": connection, "binding_sha256": binding,
        "practice": None, "label": label,
    }


def _parse_status(body: object, spec: Spec) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError
    if spec.family == "fhir":
        return _parse_fhir_status(body)
    return _parse_practice_status(body)


def _gate(status: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any] | None:
    if status["status"] == "not_enabled":
        return _state("unsupported", UNSUPPORTED)
    if status["status"] in {"not_configured", "setup_required"}:
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


def _names(entry: dict[str, Any]) -> str:
    text = entry.get("text")
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for key in ("prefix", "given"):
        values = entry.get(key)
        if values is None:
            continue
        if not isinstance(values, list) or any(not isinstance(part, str) or not part.strip() for part in values):
            raise ValueError
        parts.extend(values)
    family = entry.get("family")
    if family is not None:
        if not isinstance(family, str) or not family.strip():
            raise ValueError
        parts.append(family)
    suffix = entry.get("suffix")
    if suffix is not None:
        if not isinstance(suffix, list) or any(not isinstance(part, str) or not part.strip() for part in suffix):
            raise ValueError
        parts.extend(suffix)
    if not parts:
        raise ValueError
    return " ".join(parts)


def _patient_view(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict) or parsed.get("resourceType") != "Patient":
        raise ValueError
    rows = parsed.get("name")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 20:
        raise ValueError
    names = []
    for entry in rows:
        if not isinstance(entry, dict):
            raise ValueError
        names.append(_names(entry))
    born = parsed.get("birthDate")
    if born is not None and (not isinstance(born, str) or not 4 <= len(born) <= 64):
        raise ValueError
    return {"names": names, "birth_date": born}


def _directions(raw: str | None) -> str | None:
    if raw is None:
        return None
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or len(parsed) > 20:
        raise ValueError
    texts = []
    for row in parsed:
        if not isinstance(row, dict):
            raise ValueError
        text = row.get("text")
        if text is None:
            continue
        if not isinstance(text, str) or not text.strip():
            raise ValueError
        texts.append(text)
    return "\n".join(texts) if texts else None


def _record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "medication_name": row["medication_name"],
        "status": row["status"],
        "intent": row["intent"],
        "authored_on": row["authored_on"],
        "do_not_perform": row["do_not_perform"],
        "directions": _directions(row["dosage_instructions_json"]),
    }


def _page_message(spec: Spec, public: dict[str, Any]) -> tuple[str, bool]:
    if spec.kind == "window":
        return APPOINTMENTS, False
    if spec.kind == "verified_visit":
        return VISIT_PAGE, False
    if spec.kind == "fhir_patients":
        return PATIENTS_PAGE, False
    if public["item"]["coverage"] == "more_rows_available":
        return MEDICATIONS_MORE, True
    return MEDICATIONS_PAGE, False


def _rows(spec: Spec, public: dict[str, Any]) -> list[Any]:
    if spec.kind == "window":
        return list(public["items"])
    if spec.kind == "verified_visit":
        item = public["item"]
        return [{
            "handle": item["handle"], "sha256": item["sha256"], "starts_at": item["starts_at"],
            "ends_at": item["ends_at"], "status": item["status"], "patient": item["patient"],
        }]
    if spec.kind == "fhir_patients":
        return [{"handle": item["handle"], "sha256": item["sha256"],
                 **_patient_view(item["patient_identity_json"])} for item in public["items"]]
    return [_record(row) for row in public["item"]["records"]]


def _project(spec: Spec, payload: object, arguments: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _state("malformed", MALFORMED)
    allowed = FHIR_RECEIPT if spec.family == "fhir" else PRACTICE_RECEIPT
    observation = payload.get("observation")
    try:
        if (set(payload) != allowed or type(payload["contract_version"]) is not int
                or payload["contract_version"] != 1 or payload["provider"] != "tebra"
                or payload["observation_key"] != arguments["idempotency_key"]
                or payload["connection_id"] != arguments["connection_id"]
                or payload["binding_sha256"] != arguments["binding_sha256"]
                or payload["transport"] != "mock"
                or not isinstance(payload["observation_id"], str)
                or str(UUID(payload["observation_id"])) != payload["observation_id"]
                or not isinstance(payload["source_sha256"], str) or DIGEST.fullmatch(payload["source_sha256"]) is None
                or not isinstance(payload["payload_sha256"], str) or DIGEST.fullmatch(payload["payload_sha256"]) is None
                or (spec.family == "fhir" and payload["protocol"] != "fhir")
                or not isinstance(observation, dict) or payload_hash(observation) != payload["payload_sha256"]):
            raise ValueError
        if (payload["connection_id"] != status["connection_id"]
                or payload["binding_sha256"] != status["binding_sha256"]):
            return _state("wrong_practice", WRONG_PRACTICE)
        parsed = OBSERVATIONS[spec.kind].model_validate(observation)
        public = parsed.model_dump(mode="json")
        if spec.kind == "fhir_medications":
            warnings = public["item"]["warnings"]
            if any(not isinstance(code, str) or WARNING.fullmatch(code) is None for code in warnings):
                raise ValueError
    except (ValueError, TypeError, ValidationError, RecursionError, json.JSONDecodeError):
        return _state("malformed", MALFORMED)
    if spec.family == "practice":
        practice = public["practice"]
        if practice != status["practice"]:
            return _state("wrong_practice", WRONG_PRACTICE)
    elif public["display_label"] != status["label"] or public["workspace_id"] != arguments["workspace_id"]:
        return _state("wrong_practice", WRONG_PRACTICE)
    if spec.kind == "verified_visit" and public["item"]["handle"] != arguments["item_handle"]:
        return _state("malformed", MALFORMED)
    if spec.kind == "fhir_medications":
        parent = public["parent"]
        if (parent["observation_id"] != arguments["observation_id"]
                or parent["source_sha256"] != arguments["observation_sha256"]
                or parent["item_sha256"] != arguments["item_sha256"]
                or public["item"]["handle"] != arguments["item_handle"]):
            return _state("malformed", MALFORMED)
    try:
        rows = _rows(spec, public)
        message, more = _page_message(spec, public)
        patient = _patient_view(public["item"]["patient_identity_json"]) if spec.kind == "fhir_medications" else None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return _state("malformed", MALFORMED)
    if not rows:
        message = f"{message} {EMPTY_PAGE}"
    result = _state("ready", message, more_available=more, observation_id=payload["observation_id"],
                    source_sha256=payload["source_sha256"], rows=rows)
    if spec.family == "practice":
        result["practice"] = public["practice"]
    else:
        result["practice"] = {"label": public["display_label"]}
    if spec.kind == "verified_visit":
        result["patient"] = public["item"]["patient"]
    elif spec.kind == "fhir_medications":
        result["patient"] = patient
        result["warnings"] = list(public["item"]["warnings"])
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
    return before == after and before["status"] == "ready"


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
    gated = _gate(status, checked)
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
