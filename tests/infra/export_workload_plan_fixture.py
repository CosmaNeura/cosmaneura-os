#!/usr/bin/env python3
"""Export one actual, fully mocked operational workspace plan without Azure access."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def fixture_source(source: str) -> str:
    prefix = source[:source.index('\nrun "')]
    prefix = prefix.replace("synthetic.centralus.azurecontainerapps.io", "synthetic.eastus2.azurecontainerapps.io")
    prefix = prefix.replace("abc123.centralus.redis.azure.net", "abc123.eastus2.redis.azure.net")
    start = source.index('run "eastus2_workloads_preserve_centralus_bootstrap_boundary"')
    variables_start = source.index("  variables {\n", start)
    variables_end = source.index("\n  }\n", variables_start)
    variables = source[variables_start:variables_end].replace("app.beta.cosmaneura.com", "workspace.example.invalid")
    key = "pk_live_" + base64.b64encode(b"clerk.example.invalid$").decode()
    extra = {
        "workspace_hosted_enabled": True,
        "workspace_apple_enabled": True,
        "workspace_desktop_enabled": True,
        "workspace_features": {
            "WORKSPACE_AI_ACTIVITY_ENABLED": True,
            "WORKSPACE_TEAM_SETUP_ENABLED": True,
            "WORKSPACE_ROUTINES_ENABLED": True,
        },
        "workspace_public_configuration": {"WORKSPACE_LLM_BACKEND": "disabled"},
        "workspace_secret_references": {
            "WORKSPACE_LLM_API_KEY": {"secret_name": "fixture-model-key", "version": "1" * 32},
            "RESEARCH_OPENFDA_API_KEY": {"secret_name": "fixture-research-key", "version": "2" * 32},
        },
        "workspace_operational_identity": {
            "version": 1, "profile": "operational-beta-v1", "client": "desktop",
            "apiOrigin": "https://ca-api-cosmas-beta-lab01.synthetic.eastus2.azurecontainerapps.io",
            "publishableKey": key, "frontendOrigin": "https://clerk.example.invalid",
            "organizationId": "org_beta_lab_test", "audience": "cosmas-beta-lab",
        },
    }
    for name, value in extra.items():
        variables += f"\n    {name} = {json.dumps(value)}"
    resource_prefix = (
        "/subscriptions/00000000-0000-4000-8000-000000000001"
        "/resourceGroups/rg-cosmas-os-beta-lab01/providers"
    )
    overrides = {
        "azurerm_user_assigned_identity.web": {
            "id": f"{resource_prefix}/Microsoft.ManagedIdentity/userAssignedIdentities/id-cosmas-beta-web-lab01",
            "client_id": "00000000-0000-4000-8000-000000000009",
            "principal_id": "00000000-0000-4000-8000-000000000010",
        },
        "azurerm_log_analytics_workspace.beta": {
            "id": f"{resource_prefix}/Microsoft.OperationalInsights/workspaces/law-cosmas-beta-lab01",
            "workspace_id": "00000000-0000-4000-8000-000000000015",
        },
        "azurerm_subnet.container_apps": {
            "id": f"{resource_prefix}/Microsoft.Network/virtualNetworks/vnet-cosmas-beta-lab01/subnets/snet-container-apps",
        },
    }
    for role in ("api", "worker", "web"):
        overrides[f"azurerm_container_app.{role}"] = {
            "id": f"{resource_prefix}/Microsoft.App/containerApps/ca-{role}-cosmas-beta-lab01",
        }
    for role, name in (("database_preparation", "caj-dbprep-cosmas-beta-lab01"),
                       ("runtime_acceptance", "caj-runtime-accept-lab01")):
        overrides[f"azurerm_container_app_job.{role}"] = {"id": f"{resource_prefix}/Microsoft.App/jobs/{name}"}
    for role, name in (("database_url", "database-url"), ("redis_url", "redis-url"),
                       ("human_deploy_evidence_reference", "human-deploy-evidence-reference")):
        reference = f"https://kvcosmaslab01abc123.vault.azure.net/secrets/{name}"
        overrides[f"azurerm_key_vault_secret.{role}"] = {"id": reference + "/" + "3" * 32,
                                                            "versionless_id": reference}
    rendered = prefix + '\nrun "operational_workspace_plan_export" {\n  command = plan\n' + variables + "\n  }\n"
    for target, values in overrides.items():
        rendered += f"\n  override_resource {{\n    target = {target}\n    values = {json.dumps(values)}\n  }}\n"
    rendered += '''
  assert {
    condition = (
      output.location == "eastus2" && output.api_max_replicas == 1 &&
      azurerm_container_app.api[0].max_inactive_revisions == 3 &&
      azurerm_container_app.worker[0].max_inactive_revisions == 3 &&
      azurerm_container_app.web[0].max_inactive_revisions == 3 &&
      length(module.workspace_runtime.secret_definitions) == 2 &&
      local.workspace_client_origins == ["https://workspace.example.invalid", "capacitor://localhost", "app://cosmas"]
    )
    error_message = "The exported fixture must use the current explicit EastUS2/native/secret/retention contract."
  }
}
'''
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-mirror", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--sandbox-profile", type=Path, required=True)
    parser.add_argument("--tofu", type=Path, default=Path("/opt/homebrew/bin/tofu"))
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    destination = args.output_directory.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    root = destination / "environment"
    home = destination / "home"
    # Provider RPC uses Unix sockets, whose paths must stay short on macOS.
    scratch = Path(tempfile.mkdtemp(prefix="cosmas-plan-", dir="/private/tmp"))
    home.mkdir()
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z", "infra/beta/environment"], cwd=repo,
    ).decode().split("\0")
    source_hashes = {}
    for relative in filter(None, tracked):
        original = repo / relative
        if original.suffix not in {".tf", ".hcl", ".json"}:
            continue
        if original.is_symlink():
            raise ValueError("environment source must be regular files")
        target = root / original.relative_to(repo / "infra/beta/environment")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        source_hashes[relative] = hashlib.sha256(original.read_bytes()).hexdigest()
    test_name = "tests/operational_workspace_plan.tftest.hcl"
    (root / test_name).write_text(fixture_source((root / "tests/deployment_modes.tftest.hcl").read_text()))
    mirror = args.provider_mirror.resolve(strict=True)
    config = destination / "tofurc"
    config.write_text('disable_checkpoint = true\nprovider_installation {\n filesystem_mirror {\n'
                      f'  path = {json.dumps(str(mirror))}\n'
                      '  include = ["registry.opentofu.org/hashicorp/azurerm", "registry.opentofu.org/hashicorp/random"]\n'
                      ' }\n}\n')
    environment = {
        "PATH": os.defpath, "HOME": str(home), "TMPDIR": str(scratch),
        "TF_CLI_CONFIG_FILE": str(config), "TF_DATA_DIR": str(destination / "terraform-data"),
        "TF_IN_AUTOMATION": "1", "CHECKPOINT_DISABLE": "1",
    }
    commands = []
    try:
        for name, options in (
            ("init", ["init", "-backend=false", "-input=false", "-lockfile=readonly", "-no-color"]),
            ("plan", ["test", "-json", "-verbose", "-no-color", f"-filter={test_name}"]),
        ):
            command = ["/usr/bin/sandbox-exec", "-f", str(args.sandbox_profile.resolve(strict=True)),
                       str(args.tofu.resolve(strict=True)), *options]
            log = destination / f"{name}.log"
            with log.open("w") as handle:
                result = subprocess.run(command, cwd=root, env=environment, stdout=handle,
                                        stderr=subprocess.STDOUT, timeout=120, check=False)
            commands.append({"argv": command, "exit_code": result.returncode, "log": str(log)})
            if result.returncode:
                raise RuntimeError(f"mocked export {name} failed; inspect {log}")
        events = [json.loads(line) for line in (destination / "plan.log").read_text().splitlines()]
        plans = [event for event in events if event.get("type") == "test_plan"]
        if len(plans) != 1:
            raise ValueError("expected exactly one verbose mocked-plan event")
        (destination / "test-plan-event.json").write_text(json.dumps(plans[0], indent=2) + "\n")
        (destination / "plan.json").write_text(json.dumps(plans[0]["test_plan"], indent=2) + "\n")
        print(json.dumps({"plan_event_keys": list(plans[0]), "output": str(destination)}))
    finally:
        shutil.rmtree(scratch)
        (destination / "EXPORT.json").write_text(json.dumps({
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "source_sha256": source_hashes, "commands": commands,
            "test_source_sha256": hashlib.sha256((root / test_name).read_bytes()).hexdigest(),
            "network_boundary": "loopback-only sandbox; filesystem-only provider mirror; all providers mocked",
            "data": "invented public identity and versioned secret references only; no services activated",
            "scratch_removed": not scratch.exists(),
        }, indent=2) + "\n")


if __name__ == "__main__":
    main()
