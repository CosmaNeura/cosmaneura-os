"""Validate the same public feature manifest used by Vite before native composition."""
import json
import subprocess
from pathlib import Path

NATIVE_STAGING_PROFILE = "first-owner-staging-v1"

def validate_native(web: Path, **expected: object) -> dict:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((web / "cosmas-beta-features.json").read_text())
    subprocess.run([
        "node", "--input-type=module", "-e",
        "const m=await import(process.argv[1]);m.validateNativeBetaProfile(JSON.parse(process.argv[2]),JSON.parse(process.argv[3]));",
        (root / "clients/shared/beta-feature-profile.mjs").as_uri(),
        json.dumps(manifest), json.dumps(expected),
    ], check=True, timeout=15)
    return manifest
