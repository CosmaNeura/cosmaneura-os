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


def load(path: Path | None, client: str, api_origin: str | None = None):
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
    return validate(value, client, api_origin)


def validate(value, client: str, api_origin: str | None = None):
    origin = value.get("apiOrigin") if api_origin is None and isinstance(value, dict) else api_origin
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([
        "node", "--input-type=module", "-e",
        "const m=await import(process.argv[1]);const v=m.validateOperationalNativeIdentity(JSON.parse(process.argv[2]),process.argv[3],process.argv[4]);"
        "process.stdout.write(JSON.stringify({identity:v,auth:m.operationalNativeAuthSettings(v),bundle:m.operationalNativeBundle(v.client)}));",
        (root / "clients/desktop/native-identity-config.mjs").as_uri(), json.dumps(value), client, origin or "",
    ], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("Native identity must match the client, exact API and selected Clerk identity profile.")
    return json.loads(result.stdout)
