"""Fail-closed draft-light synth-ci contract (workflow YAML only)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/synth-ci.yml"

REQUIRED_CHECK_NAMES = (
    "beta-infra-static",
    "python-lint-type",
    "python-tests-migrate (backend-1)",
    "python-tests-migrate (backend-2)",
    "python-tests-migrate (backend-3)",
    "python-tests-migrate (backend-4)",
    "python-tests-migrate (signed-ui-1)",
    "python-tests-migrate (signed-ui-2)",
    "python-tests-migrate (signed-ui-3)",
    "web-test-build",
    "release-image-manifest",
    "synth-ci-gate",
)

PYTHON_TESTS_IF = "needs.ci-mode.outputs.full != 'false'"
CANCEL_IN_PROGRESS = "${{ github.event_name == 'pull_request' }}"


def _load_workflow(text: str) -> dict:
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data


def _on_block(data: dict) -> dict:
    # PyYAML parses unquoted key `on:` as boolean True.
    block = data.get("on", data.get(True))
    assert isinstance(block, dict)
    return block


def _check_names(data: dict) -> set[str]:
    names: set[str] = set()
    jobs = data["jobs"]
    for job in jobs.values():
        name = job.get("name")
        if not isinstance(name, str):
            continue
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        suites = matrix.get("suite")
        if isinstance(suites, list):
            for suite in suites:
                names.add(name.replace("${{ matrix.suite }}", str(suite)))
        else:
            names.add(name)
    return names


def _main_workflow_text() -> str:
    result = subprocess.run(
        ["git", "show", "origin/main:.github/workflows/synth-ci.yml"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_synth_ci_draft_light_fail_closed_contract():
    text = WORKFLOW.read_text(encoding="utf-8")
    data = _load_workflow(text)
    on = _on_block(data)

    assert "paths" not in on
    assert "paths-ignore" not in on
    assert on["pull_request"]["types"] == [
        "opened",
        "synchronize",
        "reopened",
        "ready_for_review",
        "labeled",
    ]

    concurrency = data["concurrency"]
    assert concurrency["cancel-in-progress"] == CANCEL_IN_PROGRESS
    assert concurrency["group"] == (
        "${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}"
    )

    jobs = data["jobs"]
    assert "ci-mode" in jobs
    ci_mode = jobs["ci-mode"]
    assert ci_mode["runs-on"] == "ubuntu-latest"
    assert ci_mode["outputs"]["full"] == "${{ steps.decide.outputs.full }}"
    decide = ci_mode["steps"][0]
    assert decide["id"] == "decide"
    assert decide["env"]["LIGHT"] == (
        "${{ github.event_name == 'pull_request' && "
        "github.event.pull_request.draft == true && "
        "!contains(github.event.pull_request.labels.*.name, 'ci:full') }}"
    )
    assert 'echo "full=false"' in decide["run"]
    assert 'echo "full=true"' in decide["run"]

    python_tests = jobs["python-tests"]
    assert python_tests["needs"] == ["ci-mode"]
    assert python_tests["if"] == PYTHON_TESTS_IF
    assert python_tests["name"] == "python-tests-migrate (${{ matrix.suite }})"

    gate = jobs["synth-gate"]
    assert gate["name"] == "synth-ci-gate"
    assert "ci-mode" in gate["needs"]
    assert "python-tests" in gate["needs"]
    gate_script = gate["steps"][0]["run"]
    # Fail closed: only exact success passes; skipped/cancelled/failure all fail.
    assert "if result != \"success\":" in gate_script
    assert "result == \"skipped\"" not in gate_script
    assert "result in (" not in gate_script
    assert "light draft run is red by design" in gate_script
    assert "ci:full" in gate_script

    assert jobs["container-image"]["name"] == "release-image-manifest"

    required = set(REQUIRED_CHECK_NAMES)
    current_names = _check_names(data)
    main_names = _check_names(_load_workflow(_main_workflow_text()))
    assert required <= main_names
    assert required <= current_names
    assert required & main_names == required & current_names
