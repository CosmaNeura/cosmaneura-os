"""Explicit single-scope staging entrypoint; no default app or HTTP selector."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from pydantic import SecretStr

from .config import EnrollmentSettings
from .private_clock_lab import binding_value, unique_json
from .private_clock_runner import CONTRACT, create_explicit_app, require

BINDINGS_ENV = "ENROLLMENT_PRIVATE_CLOCK_BINDINGS"
JOURNAL_ENV = "ENROLLMENT_PRIVATE_CLOCK_JOURNAL_URL"
INTENT = "SERVE_STAGING_STRIPE_CLOCK"


def create_environment_app(*, slot: str, binding_sha256: str,
                           environment: Mapping[str, str]) -> FastAPI:
    """Use an operator-selected immutable scope and the deployed secret refs.

    Every enrollment field must be explicitly supplied. The ordinary API's
    environment/default factory is never called, and the binding selects no
    customer from a request. Only the selected journal credential is required.
    """
    require(slot in ("a", "b") and re.fullmatch(r"[0-9a-f]{64}", binding_sha256) is not None)
    fields = EnrollmentSettings.model_fields
    expected = {"ENROLLMENT_" + name.upper() for name in fields} | {BINDINGS_ENV, JOURNAL_ENV}
    require({name for name in environment if name.startswith("ENROLLMENT_")} == expected)
    values = {}
    for name, field in fields.items():
        raw = environment["ENROLLMENT_" + name.upper()]
        require(isinstance(raw, str) and len(raw.encode()) <= 8192)
        if isinstance(field.default, bool):
            require(raw in ("true", "false"))
            values[name] = raw == "true"
        elif isinstance(field.default, list):
            values[name] = unique_json(raw.encode())
        else:
            values[name] = raw
    settings = EnrollmentSettings.model_validate(values, strict=True)
    require(settings.data_mode == "synthetic" and not settings.stripe_live_mode
            and not settings.production_qualified)
    raw_bindings = environment[BINDINGS_ENV]
    require(isinstance(raw_bindings, str) and 1 <= len(raw_bindings.encode()) <= 25_000)
    packed = unique_json(raw_bindings.encode())
    require(isinstance(packed, dict) and set(packed) == {"contract_version", "synthetic_only", "bindings"}
            and packed["contract_version"] == "enrollment-private-clock-setup.v1"
            and packed["synthetic_only"] is True and isinstance(packed["bindings"], dict)
            and set(packed["bindings"]) == {"a", "b"})
    bindings = {key: binding_value(value) for key, value in packed["bindings"].items()}
    require(all(len({getattr(binding, name) for binding in bindings.values()}) == 2
                for name in ("practice_id", "box_id", "organization_id", "customer_id", "clock_id")))
    binding = bindings[slot]
    require(binding.sha256 == binding_sha256)
    binding.check_settings(settings)
    journal_url = environment[JOURNAL_ENV]
    require(isinstance(journal_url, str) and 1 <= len(journal_url.encode()) <= 8192)
    explicit = {name: (getattr(settings, name).get_secret_value()
                       if isinstance(getattr(settings, name), SecretStr) else getattr(settings, name))
                for name in fields}
    configuration = {"contract_version": CONTRACT, "synthetic_only": True,
                     "binding_sha256": binding_sha256, "journal_role": "clock_journal_" + slot,
                     "enrollment": explicit}
    # Container Apps injects selected versioned secrets as environment values.
    # Adapt them to the existing strict file factory, then remove the private
    # files before serving. The frozen binding/model and scoped engines remain.
    with TemporaryDirectory(prefix="cosmabot-staging-clock-") as directory:
        root = Path(directory).resolve()
        paths = {"configuration_path": root / "configuration.json", "binding_path": root / "binding.json",
                 "journal_url_path": root / "journal.url"}
        for path, raw in ((paths["configuration_path"], json.dumps(configuration)),
                          (paths["binding_path"], json.dumps(binding.model_dump())),
                          (paths["journal_url_path"], journal_url)):
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w") as output:
                output.write(raw)
        return create_explicit_app(**paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", choices=("a", "b"), required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--intent", choices=(INTENT,), required=True)
    args = parser.parse_args()
    try:
        app = create_environment_app(slot=args.slot, binding_sha256=args.binding_sha256,
                                     environment=os.environ)
        import uvicorn

        uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False, log_level="warning")
        return 0
    except Exception:
        print(json.dumps({"error": "staging_clock_composition_unavailable"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
