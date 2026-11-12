"""Read one explicit public identity file; no environment or service access."""
import json
import subprocess
from pathlib import Path


def data_mode(identity, requested: str | None = None):
    """Preserve legacy defaults; an authenticated identity does not grant PHI use."""
    selected = requested if requested is not None else "authorized_beta" if identity is not None else "synthetic"
    if not isinstance(selected, str) or selected not in {"synthetic", "authorized_beta"} or (selected == "authorized_beta" and identity is None):
        raise ValueError("Select synthetic or authorized_beta with the matching native identity profile.")
    if identity is not None and identity["identity"]["profile"] == "operational-staging-v1" and selected != "synthetic":
        raise ValueError("The staging identity requires explicit synthetic data mode.")
    return selected


def load(path: Path | None, client: str, api_origin: str | None = None,
         installation_profile: str | None = None):
    if path is None:
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8192:
        raise ValueError("Use one bounded public native identity JSON file.")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate native identity fields are not permitted.")
            result[key] = value
        return result

    value = json.loads(path.read_text(), object_pairs_hook=unique)
    return validate(value, client, api_origin, installation_profile)


def validate(value, client: str, api_origin: str | None = None,
             installation_profile: str | None = None):
    """Load via loadOperationalNativeIdentity so omitted installation_profile
    refuses operational-production-v1 (JS requireProductionInstallationProfile)."""
    origin = value.get("apiOrigin") if api_origin is None and isinstance(value, dict) else api_origin
    root = Path(__file__).resolve().parents[1]
    # argv[5] is JSON-encoded installation_profile (null when omitted).
    result = subprocess.run([
        "node", "--input-type=module", "-e",
        "const m=await import(process.argv[1]);"
        "const profile=JSON.parse(process.argv[5]);"
        "const v=m.loadOperationalNativeIdentity(JSON.parse(process.argv[2]),process.argv[3],process.argv[4],profile);"
        "process.stdout.write(JSON.stringify({identity:v,auth:m.operationalNativeAuthSettings(v),bundle:m.operationalNativeBundle(v.client)}));",
        (root / "clients/desktop/native-identity-config.mjs").as_uri(),
        json.dumps(value), client, origin or "", json.dumps(installation_profile),
    ], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("Native identity must match the client, exact API and selected Clerk identity profile.")
    return json.loads(result.stdout)
