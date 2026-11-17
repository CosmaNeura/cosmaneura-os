"""The normal backend CI command exercises the isolated extension tests/build."""
import base64
import json
import os
import subprocess
from pathlib import Path

from cosmas_os.extension_local_profile import EXTENSION_ID, EXTENSION_ORIGIN

ROOT = Path(__file__).resolve().parents[2]


def test_extension_worker_fences_and_unconfigured_bundle():
    client = ROOT / "clients" / "extension"
    env = {name: value for name, value in os.environ.items() if not name.startswith("COSMABOT_EXTENSION_")}
    env.update(COSMABOT_EXTENSION_CLERK_PUBLISHABLE_KEY="_".join(["pk", "test",
        base64.b64encode(b"invented-extension.clerk.accounts.dev$").decode()]),
        COSMABOT_EXTENSION_CLERK_ISSUER="https://invented-extension.clerk.accounts.dev",
        COSMABOT_EXTENSION_CLERK_ORGANIZATION_ID="org_invented")
    for argv in [["node", "--test", "test/fences.test.mjs"], ["node", "build.mjs"],
                 ["node", "build.mjs", "--unconfigured"]]:
        result = subprocess.run(argv, cwd=client, env=env, capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
    profile = json.loads((client / "local-profile.json").read_text())
    assert profile["extensionId"] == EXTENSION_ID
    assert profile["extensionOrigin"] == EXTENSION_ORIGIN
    manifest = json.loads((client / "dist" / "manifest.json").read_text())
    for file in [manifest["background"]["service_worker"], "panel.js", "content.js"]:
        assert (client / "dist" / file).is_file()
    assert "https:" not in manifest["content_security_policy"]["extension_pages"]
    audit = json.loads((client / "dist" / "bundle-audit.json").read_text())
    assert audit["externalImports"] == []
    assert any("@clerk/clerk-js" in name and ".no-rhc." in name for name in audit["inputs"])
