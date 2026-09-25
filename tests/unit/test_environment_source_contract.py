"""Keep prepared workspace inputs and the selected deployment source compatible."""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENVIRONMENT = ROOT / "infra/beta/environment"


def _literal_fields(path: Path, names: set[str]) -> dict:
    values = {}
    for node in ast.parse(path.read_text()).body:
        targets = (
            node.targets if isinstance(node, ast.Assign)
            else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        for target in targets:
            if isinstance(target, ast.Name) and target.id in names:
                assert target.id not in values, f"Duplicate metadata in {path}"
                values[target.id] = ast.literal_eval(node.value)
    assert set(values) == names, f"Missing literal metadata in {path}"
    return values


def test_selected_schema_matches_runtime_and_complete_migration_graph():
    selected = json.loads((ENVIRONMENT / "release-schema.json").read_text())
    assert set(selected) == {"version", "schema_revision"}
    assert type(selected["version"]) is int and selected["version"] == 1
    expected = selected["schema_revision"]
    assert _literal_fields(ROOT / "src/cosmas_os/runtime_schema.py", {
        "EXPECTED_SCHEMA_REVISION",
    }) == {"EXPECTED_SCHEMA_REVISION": expected}

    graph = {}
    for path in sorted((ROOT / "migrations/versions").glob("*.py")):
        if path.name == "__init__.py":
            continue
        metadata = _literal_fields(path, {"revision", "down_revision", "depends_on"})
        revision = metadata["revision"]
        assert isinstance(revision, str) and revision not in graph
        assert metadata["depends_on"] is None
        parents = metadata["down_revision"]
        parents = [] if parents is None else [parents] if isinstance(parents, str) else parents
        assert isinstance(parents, (list, tuple))
        assert all(isinstance(parent, str) for parent in parents)
        assert len(set(parents)) == len(parents)
        graph[revision] = parents
    referenced = {parent for parents in graph.values() for parent in parents}
    assert referenced <= graph.keys()
    assert graph.keys() - referenced == {expected}
    visited, active = set(), set()

    def visit(revision):
        assert revision not in active, "Migration cycle"
        if revision in visited:
            return
        active.add(revision)
        for parent in graph[revision]:
            visit(parent)
        active.remove(revision)
        visited.add(revision)

    visit(expected)
    assert visited == graph.keys(), "Disconnected migration history"


def test_prepared_startup_inputs_are_accepted_by_workspace_module(tmp_path, monkeypatch):
    tofu = shutil.which("tofu")
    if tofu is None:
        pytest.skip("OpenTofu is required for the local builtin-only contract check")
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "environment_startup_contract", ROOT / "scripts/prepare-operational-startup.py",
    )
    assert spec is not None and spec.loader is not None
    startup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(startup)
    identity = {
        "frontendOrigin": "https://identity.example.invalid",
        "apiOrigin": "https://api.example.invalid",
    }
    bindings = json.loads((ROOT / "docs/operational-service-bindings.example.json").read_text())
    prepared = startup.compile_inputs(identity, bindings)["os.services.tfvars.json"]
    declared = set(re.findall(
        r'variable\s+"([^"]+)"',
        "\n".join(path.read_text() for path in ENVIRONMENT.glob("*.tf")),
    ))
    assert prepared.keys() <= declared

    consumer = tmp_path / "consumer"
    (consumer / "tests").mkdir(parents=True)
    shutil.copyfile(ENVIRONMENT / "modules/workspace-runtime/main.tf", consumer / "main.tf")
    vault = "https://invented-beta.vault.azure.net/"
    inputs = {
        "hosted_enabled": prepared["workspace_hosted_enabled"],
        "features": prepared["workspace_features"],
        "public_configuration": prepared["workspace_public_configuration"],
        "secret_references": prepared["workspace_secret_references"],
        "api_origin": identity["apiOrigin"],
        "web_origin": bindings["web_origin"],
        "key_vault_uri": vault,
        "core_identity_client_id": prepared["workspace_expected_runtime_client_id"],
    }
    expected_public = {
        **{name: str(value).lower() for name, value in inputs["features"].items()},
        **inputs["public_configuration"],
        "SCHEDULING_GOOGLE_CALLBACK_URI": identity["apiOrigin"] + "/connections/scheduling/google/callback",
        "SCHEDULING_LOGIN_RETURN_ORIGIN": bindings["web_origin"],
        "CORE_CAPTURE_MANAGED_IDENTITY_CLIENT_ID": inputs["core_identity_client_id"],
    }
    variables = "\n".join(f"    {name} = {json.dumps(value)}" for name, value in inputs.items())
    expected_json = json.dumps(json.dumps(expected_public, sort_keys=True))
    (consumer / "tests/prepared.tftest.hcl").write_text(
        'run "current_prepared_inputs" {\n  command = plan\n  variables {\n'
        + variables + '\n  }\n  assert {\n'
        + f"    condition = jsonencode(output.public_env) == jsonencode(jsondecode({expected_json}))\n"
        + '    error_message = "Prepared feature and public settings must reach the runtime unchanged."\n'
        + '  }\n  assert {\n'
        + f"    condition = length(output.secret_definitions) == {len(inputs['secret_references'])} && "
        + "alltrue([for name, reference in var.secret_references : "
        + 'output.secret_definitions[output.secret_env[name]] == "${var.key_vault_uri}secrets/${reference.secret_name}/${reference.version}"])\n'
        + '    error_message = "Every prepared secret must retain its exact dedicated-vault version."\n'
        + '  }\n}\n'
    )
    mirror = tmp_path / "empty-provider-mirror"
    mirror.mkdir()
    cli_config = tmp_path / "tofurc"
    cli_config.write_text(
        'disable_checkpoint = true\nprovider_installation {\n  filesystem_mirror {\n'
        + f"    path = {json.dumps(str(mirror))}\n  }}\n}}\n"
    )
    environment = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "TF_CLI_CONFIG_FILE": str(cli_config),
        "TF_DATA_DIR": str(tmp_path / "tofu-data"),
        "TF_IN_AUTOMATION": "1",
        "CHECKPOINT_DISABLE": "1",
    }
    for arguments in (
        ["init", "-backend=false", "-input=false", "-no-color"],
        ["test", "-no-color"],
    ):
        result = subprocess.run(
            [tofu, *arguments], cwd=consumer, env=environment, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60, check=False,
        )
        assert result.returncode == 0, result.stdout
