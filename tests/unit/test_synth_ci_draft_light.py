"""Fail-closed draft-light synth-ci contract (workflow YAML only).

Locks light-mode skip, fail-closed gate, and required check names.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github/workflows/synth-ci.yml"

# Pinned from main's .github/workflows/synth-ci.yml (required status checks).
# Do not read git refs or the network; CI checkouts may lack origin/main.
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

# Pinned job keys + display names from main that produce the required checks.
MAIN_NAMED_JOBS = {
    "python-quality": "python-lint-type",
    "python-tests": "python-tests-migrate (${{ matrix.suite }})",
    "web": "web-test-build",
    "container-image": "release-image-manifest",
    "beta-infra-static": "beta-infra-static",
    "synth-gate": "synth-ci-gate",
}

MAIN_PYTHON_TEST_SUITES = [
    "backend-1",
    "backend-2",
    "backend-3",
    "backend-4",
    "signed-ui-1",
    "signed-ui-2",
    "signed-ui-3",
]

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
    assert python_tests["name"] == MAIN_NAMED_JOBS["python-tests"]
    assert python_tests["strategy"]["matrix"]["suite"] == MAIN_PYTHON_TEST_SUITES

    for job_key, expected_name in MAIN_NAMED_JOBS.items():
        assert job_key in jobs
        assert jobs[job_key]["name"] == expected_name

    gate = jobs["synth-gate"]
    assert "ci-mode" in gate["needs"]
    assert "python-tests" in gate["needs"]
    gate_script = gate["steps"][0]["run"]
    # Fail closed: only exact success passes; skipped/cancelled/failure all fail.
    assert "if result != \"success\":" in gate_script
    assert "result == \"skipped\"" not in gate_script
    assert "result in (" not in gate_script
    assert "light draft run is red by design" in gate_script
    assert "ci:full" in gate_script

    required = set(REQUIRED_CHECK_NAMES)
    current_names = _check_names(data)
    pinned_from_jobs = {
        MAIN_NAMED_JOBS["python-quality"],
        MAIN_NAMED_JOBS["web"],
        MAIN_NAMED_JOBS["container-image"],
        MAIN_NAMED_JOBS["beta-infra-static"],
        MAIN_NAMED_JOBS["synth-gate"],
        *(
            MAIN_NAMED_JOBS["python-tests"].replace("${{ matrix.suite }}", suite)
            for suite in MAIN_PYTHON_TEST_SUITES
        ),
    }
    assert pinned_from_jobs == required
    assert required <= current_names
    assert len(REQUIRED_CHECK_NAMES) == 12
    assert len(required) == 12
