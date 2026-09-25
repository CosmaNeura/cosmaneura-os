from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "infra/beta/validate_release_schema.py"
SPEC = importlib.util.spec_from_file_location("cosmas_release_schema_validator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
schema = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(schema)
SELECTED = "head_123"
DATABASE_FLAGS = (
    "schema_at_expected_head", "runtime_role_non_admin", "runtime_ddl_denied",
    "audit_update_denied", "audit_delete_denied",
)
RUNTIME_FLAGS = (
    "sync_worker_disabled", "user_assigned_managed_identity", "blob_write_read_sha_match",
    "blob_current_representation_absent_after_delete", "blob_version_representations_absent_after_delete",
    "blob_snapshot_representations_absent_after_delete", "blob_deleted_representations_absent_after_delete",
    "blob_recoverable_absence_verified", "redis_round_trip", "redis_cleanup_confirmed",
    "database_schema_at_expected_head", "database_insert_read_rolled_back",
)


def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    for relative in ("infra/beta/environment", "src/cosmas_os", "migrations/versions"):
        (root / relative).mkdir(parents=True)
    (root / "infra/beta/environment/release-schema.json").write_text(
        json.dumps({"version": 1, "schema_revision": SELECTED}))
    (root / "src/cosmas_os/runtime_schema.py").write_text(f'EXPECTED_SCHEMA_REVISION = "{SELECTED}"\n')
    (root / "migrations/versions/base.py").write_text(
        'revision = "base_000"\ndown_revision = None\ndepends_on = None\n')
    (root / "migrations/versions/head.py").write_text(
        f'revision = "{SELECTED}"\ndown_revision = "base_000"\ndepends_on = None\n')
    return root


def test_actual_checkout_agrees_with_selected_release() -> None:
    contract = json.loads((REPO / "infra/beta/environment/release-schema.json").read_text())
    assert schema.validate_release_schema(REPO) == contract["schema_revision"]


def test_literal_validation_never_executes_source(tmp_path: Path) -> None:
    root = source_tree(tmp_path)
    marker = tmp_path / "must-not-exist"
    for relative in ("src/cosmas_os/runtime_schema.py", "migrations/versions/head.py"):
        path = root / relative
        path.write_text(path.read_text() + f"__import__('pathlib').Path({str(marker)!r}).write_text('executed')\n")
    assert schema.validate_release_schema(root) == SELECTED
    assert not marker.exists()


@pytest.mark.parametrize("raw", [
    '{"version": 1, "schema_revision": "base_000"}',
    '{"version": true, "schema_revision": "head_123"}',
    '{"version": 1, "schema_revision": "head_123", "extra": false}',
    '{"version": 1, "schema_revision": "head_123", "schema_revision": "head_123"}',
    '{"version": 1}', "[]", "{", " " * 4097,
])
def test_stale_or_ambiguous_release_metadata_is_rejected(tmp_path: Path, raw: str) -> None:
    root = source_tree(tmp_path)
    (root / "infra/beta/environment/release-schema.json").write_text(raw)
    with pytest.raises(schema.ReleaseSchemaError):
        schema.validate_release_schema(root)


@pytest.mark.parametrize("declaration", [
    'EXPECTED_SCHEMA_REVISION = "base_000"',
    'EXPECTED_SCHEMA_REVISION = str("head_123")',
    'EXPECTED_SCHEMA_REVISION = "head_123"\nEXPECTED_SCHEMA_REVISION = "head_123"',
    'EXPECTED_SCHEMA_REVISION = "head_123"\nif True:\n    EXPECTED_SCHEMA_REVISION = "base_000"',
    'EXPECTED_SCHEMA_REVISION: str',
])
def test_runtime_metadata_must_be_one_matching_literal(tmp_path: Path, declaration: str) -> None:
    root = source_tree(tmp_path)
    (root / "src/cosmas_os/runtime_schema.py").write_text(declaration + "\n")
    with pytest.raises(schema.ReleaseSchemaError):
        schema.validate_release_schema(root)


@pytest.mark.parametrize("code", [
    'def upgrade():\n    revision = "local"\n    down_revision = None\n    depends_on = None',
    'async def upgrade():\n    revision = "local"',
    'class Helper:\n    revision = "local"\n    def method(self):\n        revision = "method-local"',
    'def upgrade():\n    revision = "local"\n    def helper():\n        nonlocal revision\n        revision = "enclosing-local"',
    'def upgrade():\n    global revision\n    def helper():\n        revision = "local"\n    return revision',
    'class Helper:\n    global revision\n    def method(self):\n        revision = "method-local"',
    'helper = lambda revision: revision\nother = lambda: (revision := "local")',
    'items = [revision for revision in ()]',
    'items = {revision for revision in ()}',
    'items = {revision: revision for revision in ()}',
    'def upgrade():\n    import json as revision\n    class depends_on:\n        pass',
])
def test_migration_local_bindings_do_not_reassign_module_metadata(tmp_path: Path, code: str) -> None:
    root = source_tree(tmp_path)
    path = root / "migrations/versions/head.py"
    path.write_text(path.read_text() + code + "\n")
    assert schema.validate_release_schema(root) == SELECTED


@pytest.mark.parametrize("code", [
    'if True:\n    revision = "replacement"',
    'def upgrade():\n    global revision\n    revision = "replacement"',
    'class Helper:\n    global revision\n    revision = "replacement"',
    'def upgrade():\n    def helper():\n        global revision\n        revision = "replacement"',
    'def revision():\n    pass',
    'import json as revision',
    'del revision',
    'def upgrade():\n    global revision\n    del revision',
    'items = [(revision := item) for item in ()]',
    'items = {(revision := item) for item in ()}',
    'items = {item: (revision := item) for item in ()}',
    'def upgrade():\n    global revision\n    return [(revision := item) for item in ()]',
    'def upgrade(value=(revision := "replacement")):\n    pass',
])
def test_migration_module_and_global_rebindings_are_rejected(tmp_path: Path, code: str) -> None:
    root = source_tree(tmp_path)
    path = root / "migrations/versions/head.py"
    path.write_text(path.read_text() + code + "\n")
    with pytest.raises(schema.ReleaseSchemaError, match="ambiguous"):
        schema.validate_release_schema(root)


@pytest.mark.parametrize("global_write", [False, True])
def test_runtime_metadata_binding_respects_function_scope(tmp_path: Path, global_write: bool) -> None:
    root = source_tree(tmp_path)
    path = root / "src/cosmas_os/runtime_schema.py"
    declaration = "    global EXPECTED_SCHEMA_REVISION\n" if global_write else ""
    path.write_text(path.read_text() + "def helper():\n" + declaration
                    + '    EXPECTED_SCHEMA_REVISION = "unrelated-local-value"\n')
    if global_write:
        with pytest.raises(schema.ReleaseSchemaError, match="ambiguous"):
            schema.validate_release_schema(root)
    else:
        assert schema.validate_release_schema(root) == SELECTED


@pytest.mark.parametrize("fault", ["missing_parent", "duplicate", "depends_on", "second_head", "cycle"])
def test_incomplete_or_ambiguous_migration_graph_is_rejected(tmp_path: Path, fault: str) -> None:
    root = source_tree(tmp_path)
    migrations = root / "migrations/versions"
    if fault == "missing_parent":
        (migrations / "base.py").unlink()
    elif fault == "duplicate":
        (migrations / "duplicate.py").write_bytes((migrations / "head.py").read_bytes())
    elif fault == "depends_on":
        head = migrations / "head.py"
        head.write_text(head.read_text().replace("depends_on = None", 'depends_on = "base_000"'))
    elif fault == "second_head":
        (migrations / "other.py").write_text('revision = "other_123"\ndown_revision = "base_000"\ndepends_on = None\n')
    else:
        for revision, parent in (("cycle_a", "cycle_b"), ("cycle_b", "cycle_a")):
            (migrations / f"{revision}.py").write_text(
                f'revision = "{revision}"\ndown_revision = "{parent}"\ndepends_on = None\n')
    with pytest.raises(schema.ReleaseSchemaError):
        schema.validate_release_schema(root)


def test_source_links_and_oversize_files_are_rejected(tmp_path: Path) -> None:
    root = source_tree(tmp_path)
    runtime = root / "src/cosmas_os/runtime_schema.py"
    saved = tmp_path / "saved-runtime.py"
    runtime.rename(saved)
    runtime.symlink_to(saved)
    with pytest.raises(schema.ReleaseSchemaError, match="symlinks"):
        schema.validate_release_schema(root)
    runtime.unlink()
    runtime.write_text(" " * (schema.MAX_SOURCE_BYTES + 1))
    with pytest.raises(schema.ReleaseSchemaError, match="size limit"):
        schema.validate_release_schema(root)
    runtime.write_bytes(saved.read_bytes())
    directory = root / "migrations/versions"
    moved = tmp_path / "saved-migrations"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    with pytest.raises(schema.ReleaseSchemaError, match="symlinks"):
        schema.validate_release_schema(root)


def proof(operation: str) -> dict:
    if operation == "database":
        return {"contract": "cosmas-os-d3-database-preparation-v1", "status": "ready",
                "schema_revision": SELECTED, **dict.fromkeys(DATABASE_FLAGS, True)}
    return {"contract": "cosmas-os-d3-runtime-acceptance-v2", "status": "ready",
            "environment": "early_adopter_beta", "data_mode": "synthetic", "blob_backend": "azure",
            "database_schema_revision": SELECTED, **dict.fromkeys(RUNTIME_FLAGS, True)}


def hashed(value: dict) -> dict:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return value | {"evidence_sha256": hashlib.sha256(payload).hexdigest()}


def shell_environment(tmp_path: Path) -> dict[str, str]:
    jq = shutil.which("jq")
    assert jq is not None, "jq is required for extracted protected evidence tests"
    return {"PATH": os.defpath, "TEST_JQ": jq, "TEST_PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1", "operation_temp_dir": str(tmp_path),
            "expected_schema_revision": SELECTED, "acceptance_phase": "runtime"}


SHELL_TOOLS = '''set -euo pipefail
die() { printf '%s\\n' "$*" >&2; exit 1; }
jq() { "$TEST_JQ" "$@"; }
sha256sum() { "$TEST_PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())'; }
'''


def run_gate(tmp_path: Path, operation: str, value: dict) -> subprocess.CompletedProcess:
    source = (REPO / "infra/beta/protected-runner-command.sh").read_text()
    marker = ('    jq -e --arg schema_revision "$expected_schema_revision"' if operation == "database"
              else '    jq -e --arg phase "$acceptance_phase" --arg schema_revision "$expected_schema_revision"')
    start = source.index(marker)
    error = ("database-preparation evidence self-hash is invalid" if operation == "database"
             else "runtime-acceptance evidence self-hash is invalid")
    end = source.index("\n", source.index(error, start))
    (tmp_path / "job-evidence.json").write_text(json.dumps(value))
    return subprocess.run([shutil.which("bash") or "/bin/bash", "-c", SHELL_TOOLS + source[start:end]],
                          env=shell_environment(tmp_path), capture_output=True, text=True, timeout=15)


@pytest.mark.parametrize("operation", ["database", "runtime"])
def test_extracted_evidence_gate_accepts_selected_schema(tmp_path: Path, operation: str) -> None:
    result = run_gate(tmp_path, operation, hashed(proof(operation)))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("revision", ["0002_external_identities", "f72b834c1e90", None])
@pytest.mark.parametrize("operation", ["database", "runtime"])
def test_extracted_evidence_gate_rejects_stale_or_missing_schema(
    tmp_path: Path, operation: str, revision: str | None,
) -> None:
    value = proof(operation)
    key = "schema_revision" if operation == "database" else "database_schema_revision"
    if revision is None:
        value.pop(key)
    else:
        value[key] = revision
    assert run_gate(tmp_path, operation, hashed(value)).returncode != 0


@pytest.mark.parametrize("missing", [False, True])
@pytest.mark.parametrize("operation,field", [("database", field) for field in DATABASE_FLAGS]
                         + [("runtime", field) for field in RUNTIME_FLAGS])
def test_extracted_gate_preserves_every_denial_and_runtime_probe(
    tmp_path: Path, operation: str, field: str, missing: bool,
) -> None:
    value = proof(operation)
    if missing:
        value.pop(field)
    else:
        value[field] = False
    assert run_gate(tmp_path, operation, hashed(value)).returncode != 0


@pytest.mark.parametrize("operation", ["database", "runtime"])
def test_extracted_gate_still_checks_evidence_self_hash(tmp_path: Path, operation: str) -> None:
    value = hashed(proof(operation)) | {"evidence_sha256": "0" * 64}
    result = run_gate(tmp_path, operation, value)
    assert result.returncode != 0 and "self-hash is invalid" in result.stderr


def test_extracted_attestation_preserves_all_release_and_target_bindings(tmp_path: Path) -> None:
    source = (REPO / "infra/beta/protected-runner-command.sh").read_text()
    marker = source.index('    probe_payload="$(mktemp /run/cosmas-database-attestation.')
    start = source.index('    jq -cS -n', marker)
    end = source.index("\n", source.index("' >\"$probe_payload\"", start))
    output = tmp_path / "attestation.json"
    bindings = {"source_sha": "a" * 40, "release_id": "invented-release", "GUARD_BOX_ID": "invented-box",
                "expected_api_digest": "sha256:" + "b" * 64, "database_evidence_hash": "c" * 64,
                "execution_id": "/invented/job/executions/one", "database_server_id": "/invented/server",
                "GUARD_STATE_LINEAGE": "invented-lineage", "GUARD_STATE_SERIAL": "7",
                "GUARD_STATE_SHA256": "d" * 64, "probe_payload": str(output)}
    script = SHELL_TOOLS + "date() { printf '2026-09-25T00:00:00Z\\n'; }\n" + source[start:end]
    result = subprocess.run([shutil.which("bash") or "/bin/bash", "-c", script],
                            env=shell_environment(tmp_path) | bindings, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text()) == {
        "schema_version": 1, "evidence_type": "protected-runner-database-preparation",
        "completed_at": "2026-09-25T00:00:00Z", "source_sha": bindings["source_sha"],
        "release_id": bindings["release_id"],
        "state": {"lineage": bindings["GUARD_STATE_LINEAGE"], "serial": 7,
                  "sha256": bindings["GUARD_STATE_SHA256"]},
        "database_preparation_attestation": {
            "image_digest": "b" * 64, "schema_revision": SELECTED,
            "evidence_sha256": bindings["database_evidence_hash"], "execution_id": bindings["execution_id"],
            "box_id": bindings["GUARD_BOX_ID"], "database_server_id": bindings["database_server_id"],
        },
    }
