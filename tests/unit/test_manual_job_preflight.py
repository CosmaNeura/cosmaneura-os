from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "infra/beta/protected-runner-command.sh"
SCOPE = (
    "/subscriptions/00000000-0000-4000-8000-000000000001"
    "/resourceGroups/rg-cosmas-os-beta-test01/providers/Microsoft.App/jobs"
)
NAMES = {
    "database_preparation": "caj-dbprep-cosmas-beta-test01",
    "runtime_acceptance": "caj-runtime-accept-test01",
}


def url(resource: str) -> str:
    return f"https://management.azure.com{resource}?api-version=2023-11-02-preview"


def scenario(enabled: tuple[str, ...] = tuple(NAMES)) -> tuple[dict, dict]:
    outputs = {}
    replies = {url(SCOPE): {"value": []}}
    for prefix, name in NAMES.items():
        outputs[f"{prefix}_job_enabled"] = {"value": prefix in enabled}
        if prefix not in enabled:
            # Terraform omits null outputs for jobs not created at this stage.
            continue
        resource_id = f"{SCOPE}/{name}"
        outputs[f"{prefix}_job_name"] = {"value": name}
        outputs[f"{prefix}_job_resource_id"] = {"value": resource_id}
        replies[url(SCOPE)]["value"].append({
            "id": resource_id, "name": name,
            "properties": {"configuration": {"triggerType": "Manual"}},
        })
        replies[url(f"{resource_id}/executions")] = {"value": [{
            "id": f"{resource_id}/executions/previous-001", "name": "previous-001",
            "properties": {"status": "Succeeded"},
        }]}
    return outputs, replies


def run_guard(tmp_path: Path, outputs: dict, replies: dict, *, failed_url: str = ""):
    source = RUNNER.read_text()
    start = source.index("verify_manual_jobs_idle() {\n")
    helper = source[start:source.index("\n}\n", start) + 3]
    (tmp_path / "outputs.json").write_text(json.dumps(outputs))
    (tmp_path / "replies.json").write_text(json.dumps(replies))
    mock = tmp_path / "mock_azure.py"
    mock.write_text('''import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(args) + "\\n")
assert args[:3] == ["rest", "--method", "get"], "only read-only Azure requests are allowed"
assert args[3] == "--url" and args[5:] == ["--only-show-errors", "--output", "json"]
address = args[4]
if address == os.environ["FAILED_URL"]:
    raise SystemExit(3)
with open(os.environ["REPLIES"], encoding="utf-8") as handle:
    replies = json.load(handle)
assert address in replies, "request left the exact invented job boundary"
print(json.dumps(replies[address]))
''')
    shell = '''set -euo pipefail
umask 077
die() { printf '%s\\n' "$*" >&2; exit 1; }
az() { "$TEST_PYTHON" "$MOCK_AZURE" "$@"; }
jq() { "$TEST_JQ" "$@"; }
''' + helper + '''
verify_manual_jobs_idle "$OUTPUTS" "$PREFLIGHT_DIR"
printf 'allowed\\n' > "$NEXT_STEP"
'''
    env = {
        "PATH": os.defpath, "TEST_PYTHON": sys.executable,
        "TEST_JQ": shutil.which("jq") or "/usr/bin/jq", "MOCK_AZURE": str(mock),
        "CALLS": str(tmp_path / "calls.jsonl"), "REPLIES": str(tmp_path / "replies.json"),
        "OUTPUTS": str(tmp_path / "outputs.json"), "PREFLIGHT_DIR": str(tmp_path / "preflight"),
        "NEXT_STEP": str(tmp_path / "next-step"), "FAILED_URL": failed_url,
        "GUARD_SUBSCRIPTION_ID": "00000000-0000-4000-8000-000000000001",
        "GUARD_WORKLOAD_RESOURCE_GROUP": "rg-cosmas-os-beta-test01", "GUARD_BETA_ID": "test01",
    }
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", shell], env=env,
        capture_output=True, text=True, timeout=10, check=False,
    )
    calls = [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert all(call[:3] == ["rest", "--method", "get"] for call in calls)
    assert (tmp_path / "next-step").exists() == (result.returncode == 0)
    return result, calls


@pytest.mark.parametrize("status", ["Succeeded", "Failed", "Stopped"])
def test_only_terminal_executions_allow_the_next_operation(tmp_path: Path, status: str) -> None:
    outputs, replies = scenario()
    for address, reply in replies.items():
        if "/executions?" in address:
            reply["value"][0]["properties"]["status"] = status
    result, calls = run_guard(tmp_path, outputs, replies)
    assert result.returncode == 0, result.stderr
    assert len(calls) == 3


@pytest.mark.parametrize("enabled", [(), ("database_preparation",), ("runtime_acceptance",)])
def test_absence_requires_disabled_stage_output_and_complete_live_inventory(
    tmp_path: Path, enabled: tuple[str, ...],
) -> None:
    result, calls = run_guard(tmp_path, *scenario(enabled))
    assert result.returncode == 0, result.stderr
    assert len(calls) == 1 + len(enabled)


@pytest.mark.parametrize("status", [
    "Running", "Processing", "Starting", "Waiting", "Queued", "Pending", "Degraded", "Unknown", None,
])
def test_orphaned_queued_or_unknown_execution_blocks_retry_without_cancellation(
    tmp_path: Path, status: str | None,
) -> None:
    outputs, replies = scenario()
    execution_url = url(f"{SCOPE}/{NAMES['runtime_acceptance']}/executions")
    replies[execution_url]["value"][0]["properties"]["status"] = status
    result, calls = run_guard(tmp_path, outputs, replies)
    assert result.returncode != 0
    assert len(calls) == 3


@pytest.mark.parametrize("fault", [
    "missing_enabled", "null_enabled", "string_enabled", "wrong_name", "wrong_id",
    "disabled_but_present", "enabled_but_absent", "unexpected_job", "duplicate_job", "scheduled_job",
])
def test_stage_and_exact_live_job_cross_fields_must_agree(tmp_path: Path, fault: str) -> None:
    outputs, replies = scenario()
    jobs = replies[url(SCOPE)]["value"]
    if fault == "missing_enabled":
        del outputs["database_preparation_job_enabled"]
    elif fault == "null_enabled":
        outputs["database_preparation_job_enabled"]["value"] = None
    elif fault == "string_enabled":
        outputs["database_preparation_job_enabled"]["value"] = "false"
    elif fault == "wrong_name":
        outputs["database_preparation_job_name"]["value"] = "different-job"
    elif fault == "wrong_id":
        outputs["database_preparation_job_resource_id"]["value"] = f"{SCOPE}/different-job"
    elif fault == "disabled_but_present":
        outputs["database_preparation_job_enabled"]["value"] = False
        del outputs["database_preparation_job_name"]
        del outputs["database_preparation_job_resource_id"]
    elif fault == "enabled_but_absent":
        jobs.pop(0)
    elif fault == "unexpected_job":
        jobs.append({"id": f"{SCOPE}/unreviewed-job", "name": "unreviewed-job"})
    elif fault == "duplicate_job":
        jobs.append(copy.deepcopy(jobs[0]))
    else:
        jobs[0]["properties"]["configuration"]["triggerType"] = "Schedule"
    result, _ = run_guard(tmp_path, outputs, replies)
    assert result.returncode != 0


@pytest.mark.parametrize("collection", ["jobs", "executions"])
@pytest.mark.parametrize("fault", ["missing_value", "null_value", "next_page", "failed_read"])
def test_ambiguous_or_incomplete_reads_never_prove_idle(
    tmp_path: Path, collection: str, fault: str,
) -> None:
    outputs, replies = scenario()
    address = url(SCOPE if collection == "jobs" else f"{SCOPE}/{NAMES['database_preparation']}/executions")
    if fault == "missing_value":
        replies[address] = {}
    elif fault == "null_value":
        replies[address] = {"value": None}
    elif fault == "next_page":
        replies[address]["nextLink"] = "https://pagination.example.invalid/more"
    result, _ = run_guard(tmp_path, outputs, replies, failed_url=address if fault == "failed_read" else "")
    assert result.returncode != 0


@pytest.mark.parametrize("fault", ["foreign_job", "mismatched_name", "duplicate", "missing_status"])
def test_execution_identity_and_terminal_proof_are_required(tmp_path: Path, fault: str) -> None:
    outputs, replies = scenario()
    executions = replies[url(f"{SCOPE}/{NAMES['database_preparation']}/executions")]["value"]
    if fault == "foreign_job":
        executions[0]["id"] = f"{SCOPE}/unrelated-job/executions/previous-001"
    elif fault == "mismatched_name":
        executions[0]["name"] = "another-execution"
    elif fault == "duplicate":
        executions.append(copy.deepcopy(executions[0]))
    else:
        del executions[0]["properties"]["status"]
    result, _ = run_guard(tmp_path, outputs, replies)
    assert result.returncode != 0


def test_manual_start_and_workload_apply_call_sites_keep_the_preflight_inside_the_lock() -> None:
    source = RUNNER.read_text()
    lock = source.index('flock -n 9 || die')
    for phase in ("database-prepare", "runtime-acceptance"):
        start = source.index(f"  {phase})\n")
        mutation = source.index('    az rest --method post --url "https://management.azure.com${job_id}/start?', start)
        guard = source.rindex('    verify_manual_jobs_idle "$probe_outputs"', start, mutation)
        assert lock < start < guard < mutation
    apply = source.index("  apply)\n")
    guard = source.index('      verify_manual_jobs_idle "$probe_outputs"', apply)
    mutation = source.index('bash "$repository_root/infra/beta/apply-environment-plan.sh"', apply)
    assert lock < apply < guard < mutation
    assert '.prior_state == {lineage: $state[0].lineage, serial: $state[0].serial, sha256: $hash}' in source[apply:guard]
