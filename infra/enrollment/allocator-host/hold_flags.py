#!/usr/bin/env python3
"""Validate the private allocator activation hold-flag receipt.

Operators record which prerequisites are reviewed. This helper never enables the
worker, never opens credential files, and refuses any receipt that claims the
worker is running, hosting is enabled, a second Box (P2) is authorized, Stripe
live mode is on, or production registration is qualified. Local preparation can
stay dark until a separate founder-authorized apply.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

CONTRACT = "cosmabot.private-worker-hold-flags.v1"

# Prerequisites may become true after review; activation stays false until apply.
REVIEW_FLAGS = (
    "foundation_coordinates_reviewed",
    "managed_identity_attached",
    "private_network_path_qualified",
    "digest_pinned_images_reviewed",
    "cloudflare_token_file_present",
    "beta_tester_staging_pass",
)

# These must remain false for this held production-hosting path.
ACTIVATION_HOLDS = (
    "hosting_configuration_enabled",
    "worker_started",
    "p2_extra_box_authorized",
    "stripe_live_mode",
    "production_registration_qualified",
)

REQUIRED_KEYS = frozenset(
    {"contract_version", "environment", "practice_uuid_limit", *REVIEW_FLAGS, *ACTIVATION_HOLDS}
)


def _regular_file(path: Path) -> Path:
    if not path.is_absolute() or path.resolve() != path or not path.is_file() or path.is_symlink():
        raise ValueError("regular absolute hold-flags receipt required")
    return path


def validate_hold_flags(value: dict) -> dict:
    """Return a normalized receipt; raise ValueError when activation holds are broken."""
    if not isinstance(value, dict) or set(value) != REQUIRED_KEYS:
        raise ValueError("exact private-worker hold-flags contract required")
    if value["contract_version"] != CONTRACT:
        raise ValueError("exact private-worker hold-flags contract required")
    if value["environment"] not in {"staging", "production"}:
        raise ValueError("hold flags require staging or production environment")
    if value["practice_uuid_limit"] != 1:
        raise ValueError("F1+P1 path admits exactly one practice UUID; P2 stays held")
    for name in (*REVIEW_FLAGS, *ACTIVATION_HOLDS):
        if type(value[name]) is not bool:
            raise ValueError(f"hold flag {name} must be an explicit boolean")
    for name in ACTIVATION_HOLDS:
        if value[name] is not False:
            raise ValueError(f"activation hold {name} must remain false until separate founder authorization")
    return {
        "contract_version": CONTRACT,
        "environment": value["environment"],
        "practice_uuid_limit": 1,
        "review_flags": {name: value[name] for name in REVIEW_FLAGS},
        "activation_holds": {name: False for name in ACTIVATION_HOLDS},
        "worker_enable_command_emitted": False,
        "azure_apply_performed": False,
        "allocation_qualified": False,
    }


def load_hold_flags(path: Path) -> dict:
    raw = json.loads(_regular_file(path).read_text())
    return validate_hold_flags(raw)


def default_held_receipt(*, environment: str = "production") -> dict:
    """Invented dark receipt used by local tests; never claims readiness."""
    if environment not in {"staging", "production"}:
        raise ValueError("hold flags require staging or production environment")
    return {
        "contract_version": CONTRACT,
        "environment": environment,
        "practice_uuid_limit": 1,
        **{name: False for name in REVIEW_FLAGS},
        **{name: False for name in ACTIVATION_HOLDS},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-flags", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(load_hold_flags(arguments.hold_flags), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
