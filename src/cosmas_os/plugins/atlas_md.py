"""Atlas.md reads for the CosmaBot connectors plugin.

This repository has no Atlas.md read API. Each tool answers that in plain
language and does not call a network endpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from cosmas_os.plugins.runtime import PluginError

UNSUPPORTED = "This Atlas.md read is not supported yet."
RECOVERY = "There is no Atlas.md read to repeat. This tool does not call Atlas.md."
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "required": [],
}


@dataclass(frozen=True)
class Spec:
    name: str
    operation_id: str
    title: str
    description: str


SPECS = (
    Spec(
        name="atlas_md_read_appointments",
        operation_id="atlas_md.read_appointments",
        title="Read Atlas.md appointments",
        description=(
            "Ask whether CosmaBot can read Atlas.md appointments. "
            "This read is not supported yet. The tool takes no arguments and does not contact Atlas.md."
        ),
    ),
    Spec(
        name="atlas_md_read_patients",
        operation_id="atlas_md.read_patients",
        title="Read Atlas.md patients",
        description=(
            "Ask whether CosmaBot can read Atlas.md patients. "
            "This read is not supported yet. The tool takes no arguments and does not contact Atlas.md."
        ),
    ),
)
BY_NAME = {spec.name: spec for spec in SPECS}
NAMES = tuple(spec.name for spec in SPECS)


def tool_definitions() -> list[dict[str, Any]]:
    rows = []
    for spec in SPECS:
        rows.append({
            "name": spec.name,
            "title": spec.title,
            "description": spec.description,
            "inputSchema": {
                "type": "object", "additionalProperties": False, "properties": {}, "required": [],
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "_meta": {"ai.cosmas/operation": {
                "id": spec.operation_id,
                "plugin": "atlas_md",
                "implementation": "unsupported",
                "account_status": "not_checked",
                "read_only": True,
                "external_send": False,
            }},
        })
    return rows


def _state() -> dict[str, Any]:
    return {"state": "unsupported", "message": UNSUPPORTED, "read_only": True, "confirmed": False}


def _validate(arguments: object) -> None:
    try:
        if (not isinstance(arguments, dict)
                or len(json.dumps(arguments, allow_nan=False).encode()) > 65536
                or list(Draft202012Validator(SCHEMA).iter_errors(arguments))):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise PluginError("invalid_tool_arguments") from None


def call(_runtime, name: str, arguments: object) -> dict[str, Any]:
    """Return the unsupported state. ``_runtime`` is unused so no request is sent."""
    spec = BY_NAME.get(name)
    if spec is None:
        raise PluginError("unknown_tool")
    _validate(arguments)
    return {"operation": spec.operation_id, "result": _state(), "recovery": RECOVERY}
