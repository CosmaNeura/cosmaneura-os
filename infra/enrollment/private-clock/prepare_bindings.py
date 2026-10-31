"""Pack two previously qualified protected manifests; no vendor/cloud calls."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from database import input_bindings, unique_json
from prepare import private_read, private_write
from scope import coordinates


def pack(coordinates_file: Path, a: Path, b: Path, output: Path) -> dict:
    c = coordinates(private_read(coordinates_file))
    value = {"contract_version": "enrollment-private-clock-setup.v1", "synthetic_only": True,
             "bindings": {"a": unique_json(private_read(a)), "b": unique_json(private_read(b))}}
    raw = json.dumps(value, sort_keys=True)
    input_bindings(raw, c["postgres_fqdn"], c["binding_sha256"])
    private_write(output, raw.encode())
    return {"packed": True, "bindings": 2, "cloud_calls": False, "hosted_qualified": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coordinates", type=Path, required=True)
    parser.add_argument("--binding-a", type=Path, required=True)
    parser.add_argument("--binding-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(pack(args.coordinates, args.binding_a, args.binding_b, args.output)))
        return 0
    except Exception as error:
        print(json.dumps({"error": "private_clock_bindings_failed", "class": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
