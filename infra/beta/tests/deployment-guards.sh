#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
beta_dir="$(cd -- "$script_dir/.." && pwd -P)"
# shellcheck source=../deployment-guard-lib.sh
source "$beta_dir/deployment-guard-lib.sh"

test_dir="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-d3-guard-test.XXXXXX")"
chmod 700 "$test_dir"
cleanup() {
  rm -rf -- "$test_dir"
}
trap cleanup EXIT

subscription_id="00000000-0000-4000-8000-000000000001"
tenant_id="00000000-0000-4000-8000-000000000002"
deploy_client_id="00000000-0000-4000-8000-000000000005"
box_id="00000000-0000-4000-8000-000000000004"
lineage="00000000-0000-4000-8000-000000000009"
state_rg="rg-cosmas-os-beta-state-lab01"
workload_rg="rg-cosmas-os-beta-lab01"

bootstrap_outputs="$test_dir/bootstrap.json"
jq -n \
  --arg subscription_id "$subscription_id" \
  --arg tenant_id "$tenant_id" \
  --arg deploy_client_id "$deploy_client_id" \
  --arg box_id "$box_id" \
  --arg state_rg "$state_rg" \
  --arg workload_rg "$workload_rg" '
    {
      subscription_id: {value: $subscription_id},
      tenant_id: {value: $tenant_id},
      backend_resource_group_name: {value: $state_rg},
      backend_storage_account_name: {value: "cmbetatflab01abc123"},
      backend_container_name: {value: "tfstate"},
      backend_key: {value: "early-adopter-beta/lab01/terraform.tfstate"},
      workload_resource_group_name: {value: $workload_rg},
      deploy_identity_client_id: {value: $deploy_client_id},
      deploy_identity_principal_id: {value: "00000000-0000-4000-8000-000000000006"},
      deployment_mode: {value: "synthetic_lab"},
      data_classification: {value: "synthetic-only"},
      box_id: {value: $box_id},
      state_vnet_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01")},
      state_blob_private_dns_zone_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net")},
      state_blob_private_endpoint_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/privateEndpoints/pe-state-blob-lab01")},
      state_private_endpoint_subnet_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01/subnets/snet-private-endpoints")},
      runner_vm_name: {value: "vm-cosmas-os-beta-runner-lab01"},
      runner_image_version: {value: "22.04.202608200"},
      runner_vm_size: {value: "Standard_B2s"},
      runner_subnet_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01/subnets/snet-deploy-runner")},
      runner_network_security_group_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/networkSecurityGroups/nsg-cosmas-os-beta-runner-lab01")},
      runner_nat_gateway_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/natGateways/nat-cosmas-os-beta-runner-lab01")},
      runner_egress_public_ip_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $state_rg + "/providers/Microsoft.Network/publicIPAddresses/pip-cosmas-os-beta-runner-egress-lab01")}
    }
  ' >"$bootstrap_outputs"
chmod 600 "$bootstrap_outputs"
guard_load_bootstrap_outputs "$bootstrap_outputs"
[[ "$GUARD_BOX_ID" == "$box_id" && "$GUARD_BETA_ID" == "lab01" ]]

state_file="$test_dir/state.json"
jq -n \
  --arg lineage "$lineage" \
  --arg subscription_id "$subscription_id" \
  --arg box_id "$box_id" \
  --arg workload_rg "$workload_rg" '
    {
      lineage: $lineage,
      serial: 7,
      outputs: {
        box_id: {value: $box_id},
        environment: {value: "early_adopter_beta"},
        deployment_mode: {value: "synthetic_lab"},
        data_classification: {value: "synthetic-only"},
        resource_group_name: {value: $workload_rg},
        state_vnet_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01")},
        state_blob_private_dns_zone_id: {value: ("/subscriptions/" + $subscription_id + "/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net")}
      },
      resources: [{
        instances: [{attributes: {
          id: ("/subscriptions/" + $subscription_id + "/resourceGroups/" + $workload_rg + "/providers/Microsoft.Storage/storageAccounts/example")
        }}]
      }]
    }
  ' >"$state_file"
chmod 600 "$state_file"
guard_validate_environment_state "$state_file"
[[ "$GUARD_STATE_LINEAGE" == "$lineage" && "$GUARD_STATE_SERIAL" == "7" ]]

partial_state="$test_dir/partial-state.json"
jq 'del(.outputs.state_vnet_id)' "$state_file" >"$partial_state"
chmod 600 "$partial_state"
if (guard_validate_environment_state "$partial_state" >/dev/null 2>&1); then
  printf '%s\n' "expected complete-state validation to reject a partial foundation" >&2
  exit 1
fi
guard_validate_environment_state "$partial_state" partial_foundation
[[ "$GUARD_STATE_LINEAGE" == "$lineage" && "$GUARD_STATE_SERIAL" == "7" ]]

bad_state="$test_dir/bad-state.json"
jq '.resources[0].instances[0].attributes.id |= sub("rg-cosmas-os-beta-lab01"; "rg-track-a-production")' "$state_file" >"$bad_state"
chmod 600 "$bad_state"
if (guard_validate_environment_state "$bad_state" >/dev/null 2>&1); then
  printf '%s\n' "expected cross-resource-group state rejection" >&2
  exit 1
fi

plan_file="$test_dir/plan.json"
jq -n \
  --arg box_id "$box_id" \
  --arg workload_rg "$workload_rg" '
    {
      planned_values: {outputs: {
        box_id: {value: $box_id},
        environment: {value: "early_adopter_beta"},
        deployment_mode: {value: "synthetic_lab"},
        data_classification: {value: "synthetic-only"},
        resource_group_name: {value: $workload_rg},
        state_vnet_id: {value: ("/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-lab01")},
        state_blob_private_dns_zone_id: {value: ("/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net")}
      }},
      resource_changes: [
        {mode: "managed", address: "terraform_data.safe", change: {actions: ["update"]}},
        {mode: "managed", address: "random_string.suffix", change: {actions: ["no-op"]}}
      ]
    }
  ' >"$plan_file"
chmod 600 "$plan_file"
guard_validate_planned_boundary "$plan_file"
guard_validate_safe_plan_actions "$plan_file"
[[ "$GUARD_CREATE_COUNT" == "0" && "$GUARD_UPDATE_COUNT" == "1" && "$GUARD_NOOP_COUNT" == "1" ]]

security_plan="$test_dir/security-plan.json"
jq '.resource_changes += [
  {
    mode: "managed",
    address: "azurerm_storage_account.beta",
    type: "azurerm_storage_account",
    change: {
      actions: ["update"],
      before: {name: "cmbeta", public_network_access_enabled: true, shared_access_key_enabled: true},
      after: {
        name: "cmbeta",
        public_network_access_enabled: false,
        shared_access_key_enabled: false,
        administrator_password: "MUST-NOT-APPEAR"
      }
    }
  },
  {
    mode: "managed",
    address: "azurerm_key_vault.beta",
    type: "azurerm_key_vault",
    change: {
      actions: ["update"],
      before: {name: "kvcosmas", rbac_authorization_enabled: true, public_network_access_enabled: false, network_acls: [{bypass: "AzureServices", default_action: "Deny"}]},
      after: {
        name: "kvcosmas",
        rbac_authorization_enabled: true,
        public_network_access_enabled: false,
        network_acls: [{bypass: "None", default_action: "Deny"}],
        contact_email: "MUST-NOT-APPEAR"
      }
    }
  },
  {
    mode: "managed",
    address: "azurerm_container_app_custom_domain.web[0]",
    type: "azurerm_container_app_custom_domain",
    change: {
      actions: ["create"],
      before: null,
      after: {
        name: "beta.example.test",
        container_app_id: "/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-lab01/providers/Microsoft.App/containerApps/ca-cosmas-web",
        certificate_binding_type: "SniEnabled",
        container_app_environment_certificate_id: null,
        custom_domain_verification_id: "MUST-NOT-APPEAR"
      }
    }
  }
]' "$plan_file" >"$security_plan"
security_posture="$test_dir/security-posture.json"
guard_write_security_posture "$security_plan" "$security_posture"
jq -e '
  any(.[];
    .address == "azurerm_storage_account.beta" and
    .before.public_network_access_enabled == true and
    .after.public_network_access_enabled == false and
    .after.shared_access_key_enabled == false)
' "$security_posture" >/dev/null
jq -e '
  any(.[];
    .address == "azurerm_key_vault.beta" and
    .after.rbac_authorization_enabled == true and
    .before.network_acls == [{bypass: "AzureServices", default_action: "Deny"}] and
    .after.network_acls == [{bypass: "None", default_action: "Deny"}])
' "$security_posture" >/dev/null
jq -e '
  any(.[];
    .address == "azurerm_container_app_custom_domain.web[0]" and
    .after.name == "beta.example.test" and
    .after.certificate_binding_type == "SniEnabled" and
    .after.container_app_environment_certificate_id == null)
' "$security_posture" >/dev/null
if grep -q 'MUST-NOT-APPEAR' "$security_posture"; then
  printf '%s\n' "security-posture projection leaked an unapproved field" >&2
  exit 1
fi

critical_plan="$test_dir/critical-plan.json"
jq '.planned_values.outputs += {
  registry_network_posture: {value: "private"},
  workloads_enabled: {value: true},
  database_preparation_job_enabled: {value: true},
  runtime_acceptance_job_enabled: {value: true},
  image_reference: {value: "registry.example/cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
  web_image_reference: {value: "registry.example/cosmas-web@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
  web_origin: {value: "https://beta.example.test"},
  web_default_fqdn: {value: "ca-cosmas-web.example.azurecontainerapps.io"},
  web_custom_domain: {value: "beta.example.test"},
  web_custom_domain_binding_enabled: {value: true},
  web_custom_domain_verification_id: {value: "MUST-NOT-APPEAR", sensitive: true}
}' "$plan_file" >"$critical_plan"
critical_values="$test_dir/critical-values.json"
guard_write_critical_planned_values "$critical_plan" "$critical_values"
jq -e '
  .web_origin == "https://beta.example.test" and
  .web_default_fqdn == "ca-cosmas-web.example.azurecontainerapps.io" and
  .web_custom_domain == "beta.example.test" and
  .web_custom_domain_binding_enabled == true and
  (has("web_custom_domain_verification_id") | not)
' "$critical_values" >/dev/null
if grep -q 'MUST-NOT-APPEAR' "$critical_values"; then
  printf '%s\n' "critical planned-value projection leaked custom-domain verification material" >&2
  exit 1
fi

domain_payload="$test_dir/domain-verification-payload.json"
domain_artifact="$test_dir/domain-verification.json"
jq -cS -n \
  --arg source_sha "0000000000000000000000000000000000000000" \
  --arg release_id "release-a" \
  --arg lineage "$lineage" '
    {
      schema_version: 1,
      evidence_type: "protected-runner-domain-verification",
      completed_at: "2026-09-03T12:00:00Z",
      source_sha: $source_sha,
      release_id: $release_id,
      state: {lineage: $lineage, serial: 9, sha256: ("a" * 64)},
      selected_hostname: "beta.example.test",
      cname_record: {type: "CNAME", name: "beta.example.test", target: "ca-cosmas-web.example.azurecontainerapps.io"},
      asuid_txt_record: {type: "TXT", name: "asuid.beta.example.test", value: "0123456789abcdef0123456789abcdef"},
      public_dns_material_only: true,
      secrets_returned: false
    }
  ' >"$domain_payload"
domain_hash="$(guard_sha256 "$domain_payload")"
jq -cS --arg hash "$domain_hash" '. + {evidence_payload_sha256: $hash}' "$domain_payload" >"$domain_artifact"
guard_validate_domain_verification_artifact "$domain_artifact" "0000000000000000000000000000000000000000" "release-a"
domain_reserved="$test_dir/domain-verification-reserved.json"
jq -cS '
  .selected_hostname = "chat.cosmaneura.com" |
  .cname_record.name = "chat.cosmaneura.com" |
  .asuid_txt_record.name = "asuid.chat.cosmaneura.com" |
  del(.evidence_payload_sha256)
' "$domain_artifact" >"$domain_payload"
domain_hash="$(guard_sha256 "$domain_payload")"
jq -cS --arg hash "$domain_hash" '. + {evidence_payload_sha256: $hash}' "$domain_payload" >"$domain_reserved"
if (guard_validate_domain_verification_artifact "$domain_reserved" "0000000000000000000000000000000000000000" "release-a" >/dev/null 2>&1); then
  printf '%s\n' "expected existing custom-domain hostname to fail closed" >&2
  exit 1
fi
domain_overbroad="$test_dir/domain-verification-overbroad.json"
jq -cS '. + {unexpected_secret: "must-not-pass"} | del(.evidence_payload_sha256)' "$domain_artifact" >"$domain_payload"
domain_hash="$(guard_sha256 "$domain_payload")"
jq -cS --arg hash "$domain_hash" '. + {evidence_payload_sha256: $hash}' "$domain_payload" >"$domain_overbroad"
if (guard_validate_domain_verification_artifact "$domain_overbroad" "0000000000000000000000000000000000000000" "release-a" >/dev/null 2>&1); then
  printf '%s\n' "expected over-broad domain-verification evidence to fail closed" >&2
  exit 1
fi
unknown_plan="$test_dir/unknown-security-plan.json"
jq '.resource_changes += [{mode: "managed", address: "azurerm_new_service.unreviewed", type: "azurerm_new_service", change: {actions: ["create"], before: null, after: {enabled: true}}}]' "$plan_file" >"$unknown_plan"
if (guard_write_security_posture "$unknown_plan" "$test_dir/unknown-security-posture.json" >/dev/null 2>&1); then
  printf '%s\n' "expected an unreviewed managed resource type to fail closed" >&2
  exit 1
fi

if ! (
  source_tag_locked=false
  source_manifest_locked=false
  source_tag_update_count=0
  source_manifest_update_count=0
  expected_digest="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  az() {
    case "$*" in
      "acr repository show "*)
        if [[ "$*" == *"--image cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"* ]]; then
          lock_state="$source_manifest_locked"
        else
          [[ "$*" == *"--image cosmas-os:git-0000000000000000000000000000000000000000"* ]] || return 1
          lock_state="$source_tag_locked"
        fi
        if [[ "$lock_state" == "true" ]]; then
          printf '%s\n' '{"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","changeableAttributes":{"readEnabled":true,"listEnabled":true,"writeEnabled":false,"deleteEnabled":false}}'
        else
          printf '%s\n' '{"digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","changeableAttributes":{"readEnabled":true,"listEnabled":true,"writeEnabled":true,"deleteEnabled":true}}'
        fi
        ;;
      "acr repository update "*)
        [[ "$*" == *"--write-enabled false"* && "$*" == *"--delete-enabled false"* ]] || return 1
        if [[ "$*" == *"--image cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"* ]]; then
          source_manifest_locked=true
          ((source_manifest_update_count += 1))
        elif [[ "$*" == *"--image cosmas-os:git-0000000000000000000000000000000000000000"* ]]; then
          source_tag_locked=true
          ((source_tag_update_count += 1))
        else
          return 1
        fi
        ;;
      *) return 1 ;;
    esac
  }
  guard_lock_and_verify_acr_immutable_tag \
    cosmasbetaacr cosmas-os \
    git-0000000000000000000000000000000000000000 "$expected_digest"
  guard_lock_and_verify_acr_immutable_tag \
    cosmasbetaacr cosmas-os \
    git-0000000000000000000000000000000000000000 "$expected_digest"
  [[ "$source_tag_locked" == "true" && "$source_manifest_locked" == "true" ]]
  [[ "$source_tag_update_count" == "1" && "$source_manifest_update_count" == "1" ]]
); then
  printf '%s\n' "expected exact source tag and manifest digest to be locked and re-read without candidate-tag deletion" >&2
  exit 1
fi

noop_plan="$test_dir/noop-plan.json"
jq '.resource_changes[0].change.actions = ["no-op"]' "$plan_file" >"$noop_plan"
chmod 600 "$noop_plan"
if (guard_validate_safe_plan_actions "$noop_plan" >/dev/null 2>&1); then
  printf '%s\n' "expected default rejection of an all-no-op plan" >&2
  exit 1
fi
guard_validate_safe_plan_actions "$noop_plan" true
[[ "$GUARD_CREATE_COUNT" == "0" && "$GUARD_UPDATE_COUNT" == "0" && "$GUARD_NOOP_COUNT" == "2" ]]

replace_plan="$test_dir/replace-plan.json"
jq '.resource_changes[0].change.actions = ["delete", "create"]' "$plan_file" >"$replace_plan"
chmod 600 "$replace_plan"
if (guard_validate_safe_plan_actions "$replace_plan" >/dev/null 2>&1); then
  printf '%s\n' "expected replacement-plan rejection" >&2
  exit 1
fi

wrong_box_plan="$test_dir/wrong-box-plan.json"
jq '.planned_values.outputs.box_id.value = "10000000-0000-4000-8000-000000000004"' "$plan_file" >"$wrong_box_plan"
chmod 600 "$wrong_box_plan"
if (guard_validate_planned_boundary "$wrong_box_plan" >/dev/null 2>&1); then
  printf '%s\n' "expected wrong-Box plan rejection" >&2
  exit 1
fi

override_module="$test_dir/override-module"
mkdir -m 700 "$override_module"
if (export TF_CLI_ARGS_plan='-target=terraform_data.partial'; guard_reject_terraform_overrides "$override_module" >/dev/null 2>&1); then
  printf '%s\n' "expected TF_CLI_ARGS_plan rejection" >&2
  exit 1
fi
if (export TF_WORKSPACE='bypass'; guard_reject_terraform_overrides "$override_module" >/dev/null 2>&1); then
  printf '%s\n' "expected TF_WORKSPACE rejection" >&2
  exit 1
fi
touch "$override_module/hidden.auto.tfvars"
if (guard_reject_terraform_overrides "$override_module" >/dev/null 2>&1); then
  printf '%s\n' "expected ignored auto tfvars rejection" >&2
  exit 1
fi
rm -f -- "$override_module/hidden.auto.tfvars"
touch "$override_module/ignored_override.tf"
if (guard_reject_terraform_overrides "$override_module" >/dev/null 2>&1); then
  printf '%s\n' "expected ignored Terraform override-file rejection" >&2
  exit 1
fi
rm -f -- "$override_module/ignored_override.tf"
ln -s /dev/null "$override_module/ignored_override.tf"
if (guard_reject_terraform_overrides "$override_module" >/dev/null 2>&1); then
  printf '%s\n' "expected ignored Terraform override symlink rejection" >&2
  exit 1
fi
rm -f -- "$override_module/ignored_override.tf"
if (export TF_REATTACH_PROVIDERS='{}'; guard_reject_terraform_overrides "$override_module" >/dev/null 2>&1); then
  printf '%s\n' "expected TF_REATTACH_PROVIDERS rejection" >&2
  exit 1
fi

source_repo="$test_dir/source-repo"
mkdir -m 700 "$source_repo"
git -C "$source_repo" init --quiet
git -C "$source_repo" config user.name "D3 Guard Test"
git -C "$source_repo" config user.email "d3-guard@example.invalid"
printf '%s\n' '#!/usr/bin/env bash' >"$source_repo/runner.sh"
git -C "$source_repo" add runner.sh
git -C "$source_repo" commit --quiet -m "guard fixture"
git -C "$source_repo" remote add origin git@github.com:CosmaNeura/cosmaneura-os.git
source_sha="$(git -C "$source_repo" rev-parse HEAD)"
materialized="$test_dir/materialized-runner.sh"
guard_materialize_committed_file "$source_repo" "$source_sha" runner.sh "$materialized" git@github.com:CosmaNeura/cosmaneura-os.git
[[ "$(guard_sha256 "$materialized")" == "$(git -C "$source_repo" show "$source_sha:runner.sh" | shasum -a 256 | awk '{print $1}')" ]]
rm -f -- "$materialized"

printf '%s\n' '# dirty' >>"$source_repo/runner.sh"
if (guard_materialize_committed_file "$source_repo" "$source_sha" runner.sh "$materialized" git@github.com:CosmaNeura/cosmaneura-os.git >/dev/null 2>&1); then
  printf '%s\n' "expected dirty tracked-source rejection" >&2
  exit 1
fi
git -C "$source_repo" show "$source_sha:runner.sh" >"$source_repo/runner.sh"
touch "$source_repo/untracked.txt"
if (guard_materialize_committed_file "$source_repo" "$source_sha" runner.sh "$materialized" git@github.com:CosmaNeura/cosmaneura-os.git >/dev/null 2>&1); then
  printf '%s\n' "expected untracked-source rejection" >&2
  exit 1
fi
rm -f -- "$source_repo/untracked.txt"
if (guard_materialize_committed_file "$source_repo" 0000000000000000000000000000000000000000 runner.sh "$materialized" git@github.com:CosmaNeura/cosmaneura-os.git >/dev/null 2>&1); then
  printf '%s\n' "expected source-SHA mismatch rejection" >&2
  exit 1
fi
git -C "$source_repo" remote set-url origin git@example.invalid:attacker/repo.git
if (guard_materialize_committed_file "$source_repo" "$source_sha" runner.sh "$materialized" git@github.com:CosmaNeura/cosmaneura-os.git >/dev/null 2>&1); then
  printf '%s\n' "expected wrong-origin rejection" >&2
  exit 1
fi

empty_stub="$test_dir/empty-stub.json"
jq -n '{metadata: {}, properties: {contentLength: 0, etag: "etag-safe", lease: {status: "unlocked", state: "available"}}}' >"$empty_stub"
guard_validate_zero_length_unlocked_state_stub "$empty_stub"
[[ "$GUARD_STATE_STUB_ETAG" == "etag-safe" ]]
if ! (
  az() {
    if [[ "$*" == *"blob show"* ]]; then
      jq -c . "$empty_stub"
    fi
  }
  guard_state_exists() { return 1; }
  guard_remove_zero_length_unlocked_state_stub
); then
  printf '%s\n' "expected successful zero-byte stub removal to return success when the blob is absent" >&2
  exit 1
fi
metadata_stub="$test_dir/metadata-stub.json"
jq '.metadata = {terraformlockid: "must-not-delete"}' "$empty_stub" >"$metadata_stub"
if (guard_validate_zero_length_unlocked_state_stub "$metadata_stub" >/dev/null 2>&1); then
  printf '%s\n' "expected top-level metadata state-stub rejection" >&2
  exit 1
fi
GUARD_STATE_KEY="early-adopter-beta/lab01/terraform.tfstate"
history_file="$test_dir/state-history.json"
jq -n --arg key "$GUARD_STATE_KEY" '[{name: $key, metadata: {}, properties: {contentLength: 0}, versionId: "zero-stub"}]' >"$history_file"
guard_validate_first_state_history_file "$history_file"
jq '.[0].properties.contentLength = 4096 | .[0].deleted = true' "$history_file" >"$test_dir/deleted-real-state-history.json"
if (guard_validate_first_state_history_file "$test_dir/deleted-real-state-history.json" >/dev/null 2>&1); then
  printf '%s\n' "expected non-empty deleted state-version rejection" >&2
  exit 1
fi

alert_send="$test_dir/alert-send.json"
alert_confirmation="$test_dir/alert-confirmation.json"
jq -n '{
  schema_version: 1,
  evidence_type: "protected-runner-alert-delivery",
  alert_phase: "send",
  confirmation_challenge: ("a" * 64),
  evidence_payload_sha256: ("b" * 64)
}' >"$alert_send"
jq -n '{
  schema_version: 1,
  challenge: ("a" * 64),
  send_evidence_sha256: ("b" * 64),
  confirmed_at: "2026-09-03T16:00:00Z",
  owner_assertion: "I CONFIRM RECEIPT OF THE D3 ALERT TEST",
  confirmation_reference: "owner-ledger:alert-test-001"
}' >"$alert_confirmation"
chmod 600 "$alert_send" "$alert_confirmation"
guard_validate_alert_owner_confirmation "$alert_confirmation" "$alert_send"
jq '.challenge = ("c" * 64)' "$alert_confirmation" >"$test_dir/bad-alert-confirmation.json"
chmod 600 "$test_dir/bad-alert-confirmation.json"
if (guard_validate_alert_owner_confirmation "$test_dir/bad-alert-confirmation.json" "$alert_send" >/dev/null 2>&1); then
  printf '%s\n' "expected mismatched alert challenge rejection" >&2
  exit 1
fi
jq '.owner_assertion = "looks good"' "$alert_confirmation" >"$test_dir/weak-alert-confirmation.json"
chmod 600 "$test_dir/weak-alert-confirmation.json"
if (guard_validate_alert_owner_confirmation "$test_dir/weak-alert-confirmation.json" "$alert_send" >/dev/null 2>&1); then
  printf '%s\n' "expected weak alert owner assertion rejection" >&2
  exit 1
fi

pitr_revisions="$test_dir/pitr-revisions.json"
pitr_image="cosmasbeta.azurecr.io/cosmas-os@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
jq -n --arg image "$pitr_image" '{value: [{name: "ca-api--reviewed", properties: {active: true, replicas: 1, template: {containers: [{image: $image}]}}}]}' >"$pitr_revisions"
guard_validate_pitr_revision_set "$pitr_revisions" ca-api--reviewed "$pitr_image" running api
jq '.value[0].properties.active = false | .value[0].properties.replicas = 0' "$pitr_revisions" >"$test_dir/pitr-frozen-revisions.json"
guard_validate_pitr_revision_set "$test_dir/pitr-frozen-revisions.json" ca-api--reviewed "$pitr_image" frozen api
jq --arg image "$pitr_image" '.value += [{name: "ca-api--unexpected", properties: {active: true, replicas: 1, template: {containers: [{image: $image}]}}}]' "$pitr_revisions" >"$test_dir/pitr-unexpected-active.json"
if (guard_validate_pitr_revision_set "$test_dir/pitr-unexpected-active.json" ca-api--reviewed "$pitr_image" running api >/dev/null 2>&1); then
  printf '%s\n' "expected unexpected active PITR revision rejection" >&2
  exit 1
fi
jq '.value[0].properties.active = false | .value[0].properties.replicas = 1' "$pitr_revisions" >"$test_dir/pitr-not-frozen.json"
if (guard_validate_pitr_revision_set "$test_dir/pitr-not-frozen.json" ca-api--reviewed "$pitr_image" frozen api >/dev/null 2>&1); then
  printf '%s\n' "expected nonzero-replica PITR freeze rejection" >&2
  exit 1
fi

compressed_command_size="$(gzip -9 -c "$beta_dir/protected-runner-command.sh" | base64 | tr -d '\n' | wc -c | tr -d '[:space:]')"
[[ "$compressed_command_size" =~ ^[0-9]+$ && "$compressed_command_size" -le 65536 ]] || {
  printf '%s\n' "protected runner command no longer fits the bounded protected-parameter transport" >&2
  exit 1
}
grep -F '{name: "COSMAS_COMMAND_GZIP_BASE64", value: $protected_command}' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F '{name: "COSMAS_PROTECTED_PAYLOAD_BASE64", value: $protected_payload}' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F '.phase == "foundation_reconcile" and $stage == "foundation"' "$beta_dir/protected-runner-command.sh" >/dev/null
for guarded_operation in release-rollback release-forward offboarding-acceptance; do
  grep -F "\"$guarded_operation\"" "$beta_dir/transport-to-protected-runner.sh" >/dev/null
  grep -F "\"$guarded_operation\"" "$beta_dir/protected-runner-command.sh" >/dev/null
done
grep -F 'AUTHORIZE D3 IMMUTABLE DIGEST ROLLBACK AND FORWARD RECOVERY' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'AUTHORIZE D3 IMMUTABLE DIGEST ROLLBACK AND FORWARD RECOVERY' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'mutable_tags_used: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'terraform_no_drift: $terraform_no_drift' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'human_clerk_browser_steps_machine_verified: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'identifiers_returned: false, secrets_returned: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'artifact_file="$release_root/executions/recovery/$recovery_phase-attestation.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'artifact_file="$release_root/executions/offboarding/$offboarding_phase-attestation.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
if grep -Eq 'az acr repository delete .*\$attempt_tag' "$beta_dir/protected-runner-command.sh"; then
  printf '%s\n' "candidate cleanup must never delete an aliased ACR manifest by tag" >&2
  exit 1
fi
if grep -Eq 'candidate_|repository untag|guard_untag_acr' "$beta_dir/protected-runner-command.sh" "$beta_dir/deployment-guard-lib.sh"; then
  printf '%s\n' "protected image publication must not create or untag candidate aliases requiring AcrDelete" >&2
  exit 1
fi
grep -F 'docker push "$api_image"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'guard_lock_and_verify_acr_immutable_tag "$acr_name" "$api_repository" "$immutable_tag" "$api_digest"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'runtime-acceptance)' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'runtime-acceptance)' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'domain-verification)' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'domain-verification)' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'artifact_file="$release_root/executions/domain-verification/attestation.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'guard_validate_domain_verification_artifact "$artifact_out" "$source_sha" "$release_id"' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'alert-delivery)' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'alert-delivery)' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'pitr-freeze|pitr-manifest|pitr-start|pitr-complete|pitr-cleanup|pitr-resume)' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'pitr-freeze)' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'exact_api_revision_inactive: true' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F '/deactivate?api-version=2024-03-01' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F '/activate?api-version=2024-03-01' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'pitr_acceptance.py' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F '/createNotifications?api-version=2024-10-01-preview' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F '.properties.networkAcls.bypass == "None"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'realized runtime-acceptance execution differs from the exact reviewed image/command/args/environment override' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'recipient_address_returned: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'docker-buildx=$docker_buildx_package_version' "$beta_dir/runner-bootstrap.sh" >/dev/null
grep -F 'docker buildx build --load' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F '.docker_buildx_package_version' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'docker buildx build --load --platform linux/amd64' "$beta_dir/../../.github/workflows/synth-ci.yml" >/dev/null
grep -F 'corepack enable' "$beta_dir/../../.github/workflows/synth-ci.yml" >/dev/null
if grep -F 'corepack prepare pnpm@' "$beta_dir/../../.github/workflows/synth-ci.yml" >/dev/null; then
  printf '%s\n' "CI must use the hash-bound packageManager declaration instead of mutable Corepack prepare" >&2
  exit 1
fi

printf '%s\n' "D3 deployment guard shell tests passed"
