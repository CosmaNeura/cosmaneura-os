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
        location: {value: "centralus"},
        api_max_replicas: {value: 2},
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

region_plan="$test_dir/region-plan.json"
jq '
  .variables = {location: {value: "eastus2"}, api_max_replicas: {value: 1}} |
  .planned_values.outputs.location.value = "eastus2" |
  .planned_values.outputs.api_max_replicas.value = 1 |
  .resource_changes += [
    {mode: "data", type: "azurerm_resource_group", change: {after: {location: "centralus"}}},
    {mode: "managed", type: "azurerm_container_app_environment", change: {after: {location: "eastus2"}}},
    {mode: "managed", type: "azurerm_container_app", name: "api", change: {after: {template: [{max_replicas: 1}]}}}
  ]
' "$plan_file" >"$region_plan"
guard_validate_planned_boundary "$region_plan"
for mutation in \
  '.planned_values.outputs.location.value = "centralus"' \
  '.resource_changes[3].change.after.location = "centralus"' \
  '.variables.location.value = "East US 2"' \
  '.variables.location.value = null' \
  '.planned_values.outputs.api_max_replicas.value = 2' \
  '.resource_changes[4].change.after.template[0].max_replicas = 2' \
  '.variables.api_max_replicas.value = true' \
  '.variables.api_max_replicas.value = "1"' \
  'del(.planned_values.outputs.location)' \
  'del(.planned_values.outputs.api_max_replicas)'; do
  jq "$mutation" "$region_plan" >"$test_dir/wrong-profile.json"
  if (guard_validate_planned_boundary "$test_dir/wrong-profile.json" >/dev/null 2>&1); then
    printf '%s\n' "expected exact reviewed workload profile rejection: $mutation" >&2
    exit 1
  fi
done

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
  api_origin: {value: "https://ca-api-cosmas-beta-lab01.example.azurecontainerapps.io"},
  web_origin: {value: "https://beta.example.test"},
  web_default_fqdn: {value: "ca-cosmas-web.example.azurecontainerapps.io"},
  web_custom_domain: {value: "beta.example.test"},
  web_custom_domain_binding_enabled: {value: true},
  acr_login_server: {value: "cosmasbetalab01.azurecr.io"},
  web_custom_domain_verification_id: {value: "MUST-NOT-APPEAR", sensitive: true}
}' "$plan_file" >"$critical_plan"
critical_values="$test_dir/critical-values.json"
guard_write_critical_planned_values "$critical_plan" "$critical_values"
jq -e '
  .location == "centralus" and
  .api_max_replicas == 2 and
  .api_origin == "https://ca-api-cosmas-beta-lab01.example.azurecontainerapps.io" and
  .web_origin == "https://beta.example.test" and
  .web_default_fqdn == "ca-cosmas-web.example.azurecontainerapps.io" and
  .web_custom_domain == "beta.example.test" and
  .web_custom_domain_binding_enabled == true and
  .acr_login_server == "cosmasbetalab01.azurecr.io" and
  (has("web_custom_domain_verification_id") | not)
' "$critical_values" >/dev/null
if grep -q 'MUST-NOT-APPEAR' "$critical_values"; then
  printf '%s\n' "critical planned-value projection leaked custom-domain verification material" >&2
  exit 1
fi

network_public_configuration="$test_dir/network-public-configuration.json"
jq -n '
  {
    schema_version: 1,
    evidence_type: "protected-runner-live-network",
    source_sha: ("a" * 40),
    release_id: "release-a",
    public_configuration: {
      api_origin: "https://ca-api-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io",
      web_origin: "https://ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io",
      web_default_fqdn: "ca-web-cosmas-beta-lab01.synthetic.centralus.azurecontainerapps.io",
      web_custom_domain: null,
      web_custom_domain_binding_enabled: false,
      acr_login_server: "cosmasbetalab01.azurecr.io"
    },
    endpoints: [{kind: "acr", hostname: "cosmasbetalab01.azurecr.io", port: 443}]
  }
' >"$network_public_configuration"
guard_validate_network_public_configuration "$network_public_configuration" "$(printf 'a%.0s' {1..40})" release-a lab01

guard_operation_returns_hashed_evidence probe-network ""
guard_operation_returns_hashed_evidence inspect-stage ""
guard_operation_returns_hashed_evidence stage-generation ""
guard_operation_returns_hashed_evidence retrieve network
for unhashed_operation in plan apply; do
  if guard_operation_returns_hashed_evidence "$unhashed_operation" ""; then
    printf '%s\n' "$unhashed_operation output must retain its distinct plan/result hash contract" >&2
    exit 1
  fi
done
if guard_operation_returns_hashed_evidence retrieve review; then
  printf '%s\n' "review retrieval must not be treated as a self-hashed evidence artifact" >&2
  exit 1
fi
network_public_configuration_hash="$(jq -cS '.' "$network_public_configuration" | guard_sha256_stream)"
jq -S --arg hash "$network_public_configuration_hash" '. + {evidence_payload_sha256: $hash}' \
  "$network_public_configuration" >"$test_dir/network-public-configuration-hashed.json"
guard_validate_sanitized_evidence_hash "$test_dir/network-public-configuration-hashed.json"
[[ "$GUARD_EVIDENCE_PAYLOAD_SHA256" == "$network_public_configuration_hash" ]] || {
  printf '%s\n' "network evidence hash validator did not retain the verified hash" >&2
  exit 1
}
jq '.public_configuration.web_origin = "https://tampered.example.test"' \
  "$test_dir/network-public-configuration-hashed.json" >"$test_dir/network-public-configuration-tampered.json"
if (guard_validate_sanitized_evidence_hash "$test_dir/network-public-configuration-tampered.json" >/dev/null 2>&1); then
  printf '%s\n' "expected workstation evidence validation to reject a tampered retrieved artifact" >&2
  exit 1
fi

jq '.public_configuration.api_origin += "/path"' "$network_public_configuration" >"$test_dir/network-public-configuration-path.json"
if (guard_validate_network_public_configuration "$test_dir/network-public-configuration-path.json" "$(printf 'a%.0s' {1..40})" release-a lab01 >/dev/null 2>&1); then
  printf '%s\n' "expected network public configuration to reject an API origin with a path" >&2
  exit 1
fi

jq '.public_configuration.acr_login_server = "other.azurecr.io"' "$network_public_configuration" >"$test_dir/network-public-configuration-acr-mismatch.json"
if (guard_validate_network_public_configuration "$test_dir/network-public-configuration-acr-mismatch.json" "$(printf 'a%.0s' {1..40})" release-a lab01 >/dev/null 2>&1); then
  printf '%s\n' "expected network public configuration to reject an ACR hostname mismatch" >&2
  exit 1
fi

jq '.public_configuration.unexpected_secret = "MUST-NOT-APPEAR"' "$network_public_configuration" >"$test_dir/network-public-configuration-overbroad.json"
if (guard_validate_network_public_configuration "$test_dir/network-public-configuration-overbroad.json" "$(printf 'a%.0s' {1..40})" release-a lab01 >/dev/null 2>&1); then
  printf '%s\n' "expected network public configuration to reject an over-broad payload" >&2
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

pitr_distinct_reviewer_helper="$test_dir/pitr-distinct-reviewer-helper.sh"
sed -n '/^pitr_reviewer_references_are_distinct() {$/,/^}$/p' "$beta_dir/protected-runner-command.sh" >"$pitr_distinct_reviewer_helper"
chmod 0600 "$pitr_distinct_reviewer_helper"
[[ "$(grep -c '^pitr_reviewer_references_are_distinct() {$' "$pitr_distinct_reviewer_helper")" == "1" ]] || {
  printf '%s\n' "PITR distinct-reviewer helper could not be isolated for behavioral tests" >&2
  exit 1
}
# shellcheck disable=SC1090 # Extracted committed function is the test subject.
source "$pitr_distinct_reviewer_helper"
pitr_reviewer_references_are_distinct "operator-ledger:pitr-001" "owner-ledger:pitr-002"
if pitr_reviewer_references_are_distinct "owner-ledger:pitr-001" "owner-ledger:pitr-001"; then
  printf '%s\n' "PITR accepted the manifest preparer as the billable-operation reviewer" >&2
  exit 1
fi
for invalid_reference in 'owner@example.test' ' two-leading' 'ab'; do
  if pitr_reviewer_references_are_distinct "$invalid_reference" "owner-ledger:pitr-002"; then
    printf '%s\n' "PITR accepted an invalid manifest-preparer reference" >&2
    exit 1
  fi
done
unset -f pitr_reviewer_references_are_distinct

# Python primitives hash compact canonical JSON bytes without a trailing line
# feed. Shell-generated evidence retains the established jq-line convention.
# Exercise both contracts so a missing `jq -j` cannot silently strand live
# evidence at the protected-runner boundary.
python_evidence="$test_dir/python-evidence.json"
python_payload='{"contract":"python-helper","schema_version":1}'
python_payload_hash="$(printf '%s' "$python_payload" | sha256sum | awk '{print $1}')"
printf '%s\n' "$python_payload" | jq -S --arg hash "$python_payload_hash" '. + {evidence_payload_sha256: $hash}' >"$python_evidence"
guard_validate_python_sanitized_evidence_hash "$python_evidence"
[[ "$GUARD_EVIDENCE_PAYLOAD_SHA256" == "$python_payload_hash" ]]
if guard_validate_sanitized_evidence_hash "$python_evidence"; then
  printf '%s\n' "shell-newline evidence validator accepted Python canonical bytes" >&2
  exit 1
fi

shell_evidence="$test_dir/shell-evidence.json"
printf '%s\n' "$python_payload" >"$test_dir/shell-evidence-payload.json"
shell_payload_hash="$(sha256sum "$test_dir/shell-evidence-payload.json" | awk '{print $1}')"
jq -S --arg hash "$shell_payload_hash" '. + {evidence_payload_sha256: $hash}' "$test_dir/shell-evidence-payload.json" >"$shell_evidence"
guard_validate_sanitized_evidence_hash "$shell_evidence"
[[ "$GUARD_EVIDENCE_PAYLOAD_SHA256" == "$shell_payload_hash" ]]
if guard_validate_python_sanitized_evidence_hash "$shell_evidence"; then
  printf '%s\n' "Python canonical evidence validator accepted shell newline bytes" >&2
  exit 1
fi

for python_hash_binding in \
  'stage_transition_hash="$(jq -cSj' \
  'database_evidence_hash="$(jq -cSj' \
  'prior_state_hash="$(jq -cSj '\''.prior_attestation.acceptance_output' \
  'runtime_evidence_hash="$(jq -cSj' \
  '"$(jq -cSj '\''del(.manifest_sha256)' \
  'pitr_output_hash="$(jq -cSj' \
  'recovery_output_hash="$(jq -cSj' \
  'current_offboarding_output_hash="$(jq -cSj' \
  'prior_state_hash="$(jq -cSj '\''.prior_attestation.offboarding_output' \
  'offboarding_output_hash="$(jq -cSj'; do
  grep -F "$python_hash_binding" "$beta_dir/protected-runner-command.sh" >/dev/null || {
    printf '%s\n' "protected runner lost a newline-free Python evidence hash binding: $python_hash_binding" >&2
    exit 1
  }
done

compressed_command_size="$(bzip2 -9 -c "$beta_dir/protected-runner-command.sh" | base64 | tr -d '\n' | wc -c | tr -d '[:space:]')"
[[ "$compressed_command_size" =~ ^[0-9]+$ && "$compressed_command_size" -le 65536 ]] || {
  printf '%s\n' "protected runner command no longer fits the bounded protected-parameter transport" >&2
  exit 1
}
grep -F '{name: "COSMAS_COMMAND_BZIP2_BASE64", value: $protected_command}' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'decoder=bz2.BZ2Decompressor(); decoded=decoder.decompress(data,524289)' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'len(data) <= 49152 and len(decoded) <= 524288 and decoder.eof and not decoder.unused_data' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F '{name: "COSMAS_PROTECTED_PAYLOAD_BASE64", value: $protected_payload}' "$beta_dir/transport-to-protected-runner.sh" >/dev/null

managed_cleanup_helpers="$test_dir/managed-run-command-cleanup-helpers.sh"
for cleanup_function in \
  managed_run_command_inventory_is_valid \
  managed_run_command_read_inventory \
  managed_run_command_show_instance \
  managed_run_command_inventory_proves_absent \
  managed_run_command_delete_and_verify_absent \
  transport_signal_exit \
  transport_install_signal_traps \
  transport_defer_signal \
  transport_install_deferred_signal_traps \
  transport_cleanup_managed_command \
  transport_complete_managed_command_cleanup \
  transport_remove_local_protected_files \
  transport_cleanup_on_exit; do
  sed -n "/^${cleanup_function}() {$/,/^}$/p" "$beta_dir/transport-to-protected-runner.sh" >>"$managed_cleanup_helpers"
done
chmod 0600 "$managed_cleanup_helpers"
[[ "$(grep -c '^managed_run_command_delete_and_verify_absent() {$' "$managed_cleanup_helpers")" == "1" ]] || {
  printf '%s\n' "managed Run Command cleanup helper could not be isolated for behavioral tests" >&2
  exit 1
}
# shellcheck disable=SC1090 # Extracted committed functions are the test subject.
source "$managed_cleanup_helpers"

cleanup_runner_id="/subscriptions/$subscription_id/resourceGroups/$state_rg/providers/Microsoft.Compute/virtualMachines/vm-cosmas-os-beta-runner-lab01"
cleanup_command_id="$cleanup_runner_id/runCommands/cosmas-d3-20260903120000-1234"
cleanup_api_version="2024-07-01"
cleanup_scratch="$test_dir/managed-cleanup-direct"
mkdir -m 0700 "$cleanup_scratch"
cleanup_mock_state="present"
cleanup_mock_delete_behavior="remove"
cleanup_mock_inventory_mode="complete"
cleanup_mock_delete_calls=0
cleanup_mock_get_calls=0
cleanup_mock_show_calls=0
cleanup_mock_sleep_calls=0
cleanup_mock_events=""
cleanup_mock_reappear_after_sleep=0
az() {
  if [[ "${1:-}" == "vm" && "${2:-}" == "run-command" && "${3:-}" == "show" ]]; then
    shift 3
    local subscription=""
    local resource_group=""
    local vm_name=""
    local command_name=""
    local instance_view=false
    while (( $# > 0 )); do
      case "$1" in
        --subscription) subscription="${2:-}"; shift 2 ;;
        --resource-group) resource_group="${2:-}"; shift 2 ;;
        --vm-name) vm_name="${2:-}"; shift 2 ;;
        --run-command-name) command_name="${2:-}"; shift 2 ;;
        --instance-view) instance_view=true; shift ;;
        --only-show-errors) shift ;;
        --output) [[ "${2:-}" == "json" ]] || return 96; shift 2 ;;
        *) return 97 ;;
      esac
    done
    [[ "$subscription" == "$GUARD_SUBSCRIPTION_ID" ]] || return 98
    [[ "$resource_group" == "$GUARD_STATE_RESOURCE_GROUP" ]] || return 99
    [[ "$vm_name" == "$GUARD_RUNNER_VM_NAME" ]] || return 100
    [[ "$command_name" == "${cleanup_command_id##*/}" ]] || return 101
    [[ "$instance_view" == "true" ]] || return 102
    cleanup_mock_show_calls=$((cleanup_mock_show_calls + 1))
    printf '%s\n' '{"provisioningState":"Succeeded","instanceView":{"executionState":"Succeeded"}}'
    return 0
  fi
  [[ "${1:-}" == "rest" ]] || return 90
  shift
  local method=""
  local url=""
  while (( $# > 0 )); do
    case "$1" in
      --method) method="${2:-}"; shift 2 ;;
      --url) url="${2:-}"; shift 2 ;;
      --only-show-errors) shift ;;
      --output) shift 2 ;;
      *) return 91 ;;
    esac
  done
  case "$method" in
    delete)
      [[ "$url" == "https://management.azure.com${cleanup_command_id}?api-version=${cleanup_api_version}" ]] || return 92
      cleanup_mock_delete_calls=$((cleanup_mock_delete_calls + 1))
      cleanup_mock_events="${cleanup_mock_events}D"
      case "$cleanup_mock_delete_behavior" in
        remove) cleanup_mock_state="absent"; return 0 ;;
        error-absent) cleanup_mock_state="absent"; return 1 ;;
        linger) cleanup_mock_state="present"; return 0 ;;
        *) return 93 ;;
      esac
      ;;
    get)
      [[ "$url" == "https://management.azure.com${cleanup_runner_id}/runCommands?api-version=${cleanup_api_version}" ]] || return 94
      cleanup_mock_get_calls=$((cleanup_mock_get_calls + 1))
      cleanup_mock_events="${cleanup_mock_events}G"
      if [[ "$cleanup_mock_inventory_mode" == "paginated" ]]; then
        jq -n --arg next_link "https://management.azure.com/next" '{value: [], nextLink: $next_link}'
      elif [[ "$cleanup_mock_state" == "present" ]]; then
        jq -n --arg id "$cleanup_command_id" '{value: [{id: $id}]}'
      else
        printf '%s\n' '{"value":[]}'
      fi
      ;;
    *) return 95 ;;
  esac
}
sleep() {
  cleanup_mock_sleep_calls=$((cleanup_mock_sleep_calls + 1))
  cleanup_mock_events="${cleanup_mock_events}S"
  if [[ "$cleanup_mock_reappear_after_sleep" -gt 0 && "$cleanup_mock_sleep_calls" -eq "$cleanup_mock_reappear_after_sleep" ]]; then
    cleanup_mock_state="present"
  fi
}

cleanup_show_result="$test_dir/managed-run-command-show.json"
managed_run_command_show_instance "$cleanup_runner_id" "$cleanup_command_id" "$cleanup_show_result"
jq -e '.provisioningState == "Succeeded" and .instanceView.executionState == "Succeeded"' "$cleanup_show_result" >/dev/null
[[ "$cleanup_mock_show_calls" == "1" ]] || {
  printf '%s\n' "managed Run Command instance read did not use the explicit resource selectors" >&2
  exit 1
}
if managed_run_command_show_instance "$cleanup_runner_id" "$cleanup_runner_id/runCommands/not-cosmas-d3" "$cleanup_show_result"; then
  printf '%s\n' "managed Run Command instance read accepted a non-D3 command" >&2
  exit 1
fi
[[ "$cleanup_mock_show_calls" == "1" ]] || {
  printf '%s\n' "invalid managed Run Command instance read reached Azure" >&2
  exit 1
}
if managed_run_command_show_instance "$cleanup_runner_id" "$cleanup_runner_id/runCommands/parent/cosmas-d3-20260903120000-5678" "$cleanup_show_result"; then
  printf '%s\n' "managed Run Command instance read accepted a nested child resource ID" >&2
  exit 1
fi
other_runner_id="${cleanup_runner_id%/*}/another-runner"
if managed_run_command_show_instance "$other_runner_id" "$other_runner_id/runCommands/cosmas-d3-20260903120000-5678" "$cleanup_show_result"; then
  printf '%s\n' "managed Run Command instance read accepted a different runner resource ID" >&2
  exit 1
fi
[[ "$cleanup_mock_show_calls" == "1" ]] || {
  printf '%s\n' "invalid nested or mismatched managed Run Command read reached Azure" >&2
  exit 1
}

managed_run_command_delete_and_verify_absent "$cleanup_runner_id" "$cleanup_command_id" "$cleanup_api_version" "$cleanup_scratch" 3 0 false
[[ "$cleanup_mock_delete_calls" == "2" && "$cleanup_mock_get_calls" == "2" && "$cleanup_mock_events" == "DGSDG" ]] || {
  printf '%s\n' "managed Run Command cleanup did not require DELETE plus repeated absence readback" >&2
  exit 1
}

cleanup_mock_state="absent"
cleanup_mock_delete_behavior="remove"
cleanup_mock_delete_calls=0
cleanup_mock_get_calls=0
cleanup_mock_sleep_calls=0
cleanup_mock_events=""
cleanup_mock_reappear_after_sleep=2
managed_run_command_delete_and_verify_absent "$cleanup_runner_id" "$cleanup_command_id" "$cleanup_api_version" "$cleanup_scratch" 5 0 true
[[ "$cleanup_mock_delete_calls" == "5" && "$cleanup_mock_get_calls" == "5" && "$cleanup_mock_sleep_calls" == "4" && "$cleanup_mock_events" == "DGSDGSDGSDGSDG" ]] || {
  printf '%s\n' "ambiguous submission cleanup did not span the full settle window after delayed creation" >&2
  exit 1
}

cleanup_mock_state="present"
cleanup_mock_delete_behavior="error-absent"
cleanup_mock_reappear_after_sleep=0
cleanup_mock_delete_calls=0
cleanup_mock_get_calls=0
cleanup_mock_sleep_calls=0
cleanup_mock_events=""
managed_run_command_delete_and_verify_absent "$cleanup_runner_id" "$cleanup_command_id" "$cleanup_api_version" "$cleanup_scratch" 3 0 false
[[ "$cleanup_mock_delete_calls" == "2" && "$cleanup_mock_get_calls" == "2" ]] || {
  printf '%s\n' "DELETE error with independently proven absence was not handled idempotently" >&2
  exit 1
}

cleanup_mock_state="present"
cleanup_mock_delete_behavior="linger"
cleanup_mock_inventory_mode="complete"
cleanup_mock_delete_calls=0
cleanup_mock_get_calls=0
cleanup_mock_sleep_calls=0
cleanup_mock_events=""
if managed_run_command_delete_and_verify_absent "$cleanup_runner_id" "$cleanup_command_id" "$cleanup_api_version" "$cleanup_scratch" 3 0 false; then
  printf '%s\n' "managed Run Command cleanup accepted a resource that remained listed" >&2
  exit 1
fi
[[ "$cleanup_mock_delete_calls" == "3" && "$cleanup_mock_get_calls" == "3" && "$cleanup_mock_sleep_calls" == "2" ]] || {
  printf '%s\n' "managed Run Command cleanup retries were not bounded exactly" >&2
  exit 1
}

cleanup_mock_state="absent"
cleanup_mock_delete_behavior="remove"
cleanup_mock_inventory_mode="paginated"
cleanup_mock_delete_calls=0
cleanup_mock_get_calls=0
cleanup_mock_sleep_calls=0
if managed_run_command_delete_and_verify_absent "$cleanup_runner_id" "$cleanup_command_id" "$cleanup_api_version" "$cleanup_scratch" 3 0 false; then
  printf '%s\n' "managed Run Command cleanup treated a paginated inventory as complete absence proof" >&2
  exit 1
fi
[[ "$cleanup_mock_delete_calls" == "3" && "$cleanup_mock_get_calls" == "3" ]] || {
  printf '%s\n' "incomplete inventory cleanup did not exhaust its bounded verification" >&2
  exit 1
}

cleanup_mock_inventory_mode="complete"
cleanup_mock_delete_calls=0
if managed_run_command_delete_and_verify_absent "$cleanup_runner_id" "$cleanup_runner_id/runCommands/not-cosmas-d3" "$cleanup_api_version" "$cleanup_scratch" 3 0 false; then
  printf '%s\n' "managed Run Command cleanup accepted a non-D3 target" >&2
  exit 1
fi
[[ "$cleanup_mock_delete_calls" == "0" ]] || {
  printf '%s\n' "managed Run Command cleanup attempted DELETE outside its exact target prefix" >&2
  exit 1
}
unset -f az sleep

cleanup_harness="$test_dir/managed-run-command-cleanup-harness.sh"
cat >"$cleanup_harness" <<'HARNESS'
#!/usr/bin/env bash
set -euo pipefail

helpers="$1"
scenario="$2"
transport_temp_dir="$3"
audit_file="$4"
# shellcheck disable=SC1090
source "$helpers"

runner_id="/subscriptions/00000000-0000-4000-8000-000000000001/resourceGroups/rg-cosmas-os-beta-state-lab01/providers/Microsoft.Compute/virtualMachines/vm-cosmas-os-beta-runner-lab01"
run_command_id="$runner_id/runCommands/cosmas-d3-20260903120000-5678"
managed_run_command_api_version="2024-07-01"
managed_run_command_cleanup_attempts=3
managed_run_command_cleanup_retry_seconds=0
managed_run_command_cleanup_failure_status=74
command_cleanup_required=true
command_cleanup_attempted=false
command_submission_acknowledged=true
mock_state="present"
signal_raised=false
mkdir -m 0700 "$transport_temp_dir"
payload_file="$transport_temp_dir/protected-payload"
payload_b64_file="$transport_temp_dir/protected-payload-b64"
request_file="$transport_temp_dir/run-command-request.json"
view_file="$transport_temp_dir/run-command-view.json"
touch "$payload_file" "$payload_b64_file" "$request_file" "$view_file"
chmod 0600 "$payload_file" "$payload_b64_file" "$request_file" "$view_file"

az() {
  [[ "${1:-}" == "rest" ]] || return 90
  shift
  local method=""
  local url=""
  while (( $# > 0 )); do
    case "$1" in
      --method) method="${2:-}"; shift 2 ;;
      --url) url="${2:-}"; shift 2 ;;
      --only-show-errors) shift ;;
      --output) shift 2 ;;
      *) return 91 ;;
    esac
  done
  case "$method" in
    delete)
      [[ "$url" == "https://management.azure.com${run_command_id}?api-version=${managed_run_command_api_version}" ]] || return 92
      for protected_file in "$payload_file" "$payload_b64_file" "$request_file" "$view_file"; do
        [[ ! -e "$protected_file" ]] || printf '%s\n' "protected-file-present-during-delete" >>"$audit_file"
      done
      printf '%s\n' "$url" >>"$audit_file"
      if [[ "$signal_raised" == "false" ]]; then
        case "$scenario" in
          during-hup) signal_raised=true; kill -HUP "$$" ;;
          during-int) signal_raised=true; kill -INT "$$" ;;
          during-term) signal_raised=true; kill -TERM "$$" ;;
        esac
      fi
      if [[ "$scenario" != "cleanup-failure" ]]; then
        mock_state="absent"
      fi
      ;;
    get)
      [[ "$url" == "https://management.azure.com${runner_id}/runCommands?api-version=${managed_run_command_api_version}" ]] || return 93
      if [[ "$mock_state" == "present" ]]; then
        jq -n --arg id "$run_command_id" '{value: [{id: $id}]}'
      else
        printf '%s\n' '{"value":[]}'
      fi
      ;;
    *) return 94 ;;
  esac
}
sleep() { :; }

trap transport_cleanup_on_exit EXIT
transport_install_signal_traps
case "$scenario" in
  success)
    transport_remove_local_protected_files
    transport_complete_managed_command_cleanup || exit 74
    exit 0
    ;;
  runner-failure) exit 23 ;;
  put-failure) command_submission_acknowledged=false; exit 31 ;;
  hup) kill -HUP "$$" ;;
  int) kill -INT "$$" ;;
  term) kill -TERM "$$" ;;
  during-hup|during-int|during-term)
    transport_remove_local_protected_files
    transport_complete_managed_command_cleanup || exit 74
    exit 0
    ;;
  cleanup-failure) exit 0 ;;
  *) exit 99 ;;
esac
HARNESS
chmod 0700 "$cleanup_harness"

run_cleanup_harness_case() {
  local scenario="$1"
  local expected_status="$2"
  local expected_failure_message="${3:-false}"
  local scratch="$test_dir/cleanup-harness-$scenario"
  local audit="$test_dir/cleanup-harness-$scenario.audit"
  local output
  local actual_status

  : >"$audit"
  set +e
  output="$(bash "$cleanup_harness" "$managed_cleanup_helpers" "$scenario" "$scratch" "$audit" 2>&1)"
  actual_status=$?
  set -e
  [[ "$actual_status" == "$expected_status" ]] || {
    printf '%s\n' "cleanup harness $scenario returned $actual_status instead of $expected_status" >&2
    exit 1
  }
  [[ ! -e "$scratch" ]] || {
    printf '%s\n' "cleanup harness $scenario retained local protected files" >&2
    exit 1
  }
  if grep -F 'protected-file-present-during-delete' "$audit" >/dev/null; then
    printf '%s\n' "cleanup harness $scenario retained protected files during remote cleanup" >&2
    exit 1
  fi
  grep -F "https://management.azure.com/subscriptions/" "$audit" >/dev/null || {
    printf '%s\n' "cleanup harness $scenario did not attempt exact-ID deletion" >&2
    exit 1
  }
  if [[ "$expected_failure_message" == "true" ]]; then
    grep -F 'cleanup failed closed' <<<"$output" >/dev/null || {
      printf '%s\n' "cleanup harness $scenario did not report its distinct cleanup failure" >&2
      exit 1
    }
  fi
}

run_cleanup_harness_case success 0
run_cleanup_harness_case runner-failure 23
run_cleanup_harness_case put-failure 31
run_cleanup_harness_case hup 129
run_cleanup_harness_case int 130
run_cleanup_harness_case term 143
run_cleanup_harness_case during-hup 129
run_cleanup_harness_case during-int 130
run_cleanup_harness_case during-term 143
run_cleanup_harness_case cleanup-failure 74 true

grep -F 'command_cleanup_required=true' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
cleanup_required_line="$(grep -nF 'command_cleanup_required=true' "$beta_dir/transport-to-protected-runner.sh" | tail -1 | cut -d: -f1)"
submission_line="$(grep -nF -- '--method put' "$beta_dir/transport-to-protected-runner.sh" | tail -1 | cut -d: -f1)"
[[ "$cleanup_required_line" =~ ^[0-9]+$ && "$submission_line" =~ ^[0-9]+$ && "$cleanup_required_line" -lt "$submission_line" ]] || {
  printf '%s\n' "managed Run Command cleanup obligation must be armed before submission" >&2
  exit 1
}
for required_trap in \
  'trap transport_cleanup_on_exit EXIT' \
  "trap 'transport_signal_exit HUP' HUP" \
  "trap 'transport_signal_exit INT' INT" \
  "trap 'transport_signal_exit TERM' TERM" \
  "trap 'transport_defer_signal HUP' HUP" \
  "trap 'transport_defer_signal INT' INT" \
  "trap 'transport_defer_signal TERM' TERM"; do
  grep -F "$required_trap" "$beta_dir/transport-to-protected-runner.sh" >/dev/null || {
    printf '%s\n' "protected transport is missing required trap: $required_trap" >&2
    exit 1
  }
done
if grep -F 'az vm run-command delete' "$beta_dir/transport-to-protected-runner.sh" >/dev/null; then
  printf '%s\n' "managed Run Command cleanup must use the exact ARM ID and verified collection readback" >&2
  exit 1
fi
if grep -E '^[[:space:]]*az vm run-command show[[:space:]]+--ids([[:space:]]|$)' "$beta_dir/transport-to-protected-runner.sh" >/dev/null; then
  printf '%s\n' "managed Run Command polling must not use the Azure CLI-incompatible --ids selector" >&2
  exit 1
fi
previous_bootstrap_parameter_line=0
# shellcheck disable=SC2016 # These are literal source-code assertions.
for bootstrap_parameter in \
  'subscription_id=$GUARD_SUBSCRIPTION_ID' \
  'deploy_client_id=$GUARD_DEPLOY_CLIENT_ID' \
  'state_storage_account=$GUARD_STATE_STORAGE_ACCOUNT' \
  'tofu_version=$tofu_version' \
  'tofu_sha256=$tofu_sha256' \
  'azure_cli_version=$azure_cli_version' \
  'docker_version=$docker_version' \
  'docker_buildx_version=$docker_buildx_version' \
  'git_version=$git_version' \
  'jq_version=$jq_version' \
  'trivy_version=$trivy_version' \
  'trivy_sha256=$trivy_sha256' \
  'bootstrap_outputs_base64=$(base64 <"$bootstrap_outputs" | tr -d '\''\n'\'')'; do
  bootstrap_parameter_line="$(grep -nF "\"$bootstrap_parameter\"" "$beta_dir/prepare-protected-runner.sh" | cut -d: -f1)"
  [[ "$bootstrap_parameter_line" =~ ^[0-9]+$ && "$bootstrap_parameter_line" -gt "$previous_bootstrap_parameter_line" ]] || {
    printf '%s\n' "runner bootstrap parameters must remain explicitly named and ordered" >&2
    exit 1
  }
  previous_bootstrap_parameter_line="$bootstrap_parameter_line"
done
grep -F 'runner_ready_marker="D3 protected runner is ready; private state DNS and managed-identity access passed"' "$beta_dir/prepare-protected-runner.sh" >/dev/null
# shellcheck disable=SC2016 # These are literal jq source-code assertions.
grep -F '($values | type == "array" and length > 0) and' "$beta_dir/prepare-protected-runner.sh" >/dev/null
# shellcheck disable=SC2016
grep -F 'all($values[]?; (.code | type == "string" and endswith("/succeeded"))) and' "$beta_dir/prepare-protected-runner.sh" >/dev/null
# shellcheck disable=SC2016
grep -F 'any($values[]?; .code == "ProvisioningState/succeeded") and' "$beta_dir/prepare-protected-runner.sh" >/dev/null
# shellcheck disable=SC2016 # This is a literal jq source-code assertion.
grep -F '[$values[]?.message? | strings | split("\n")[]] | any(. == $marker)' "$beta_dir/prepare-protected-runner.sh" >/dev/null
if grep -F 'select(.code | endswith("/succeeded"))' "$beta_dir/prepare-protected-runner.sh" >/dev/null; then
  printf '%s\n' "runner preparation must require its exact terminal readiness marker" >&2
  exit 1
fi
runner_ready_marker="D3 protected runner is ready; private state DNS and managed-identity access passed"
# shellcheck disable=SC2016 # Exercise the same literal readiness predicate used by the controller.
runner_readiness_filter='
  (.value? // null) as $values |
  ($values | type == "array" and length > 0) and
  all($values[]?; (.code | type == "string" and endswith("/succeeded"))) and
  any($values[]?; .code == "ProvisioningState/succeeded") and
  ([$values[]?.message? | strings | split("\n")[]] | any(. == $marker))
'
valid_runner_result="$(jq -n --arg marker "$runner_ready_marker" '{value: [{code: "ProvisioningState/succeeded", message: ("Enable succeeded:\n[stdout]\n" + $marker + "\n[stderr]\n")}]}')"
jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<"$valid_runner_result" >/dev/null
wrong_code_runner_result="$(jq -n --arg marker "$runner_ready_marker" '{value: [{code: "ComponentStatus/StdOut/succeeded", message: $marker}]}')"
if jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<"$wrong_code_runner_result" >/dev/null; then
  printf '%s\n' "runner readiness must reject a non-provisioning success code" >&2
  exit 1
fi
failed_runner_result="$(jq -n --arg marker "$runner_ready_marker" '{value: [{code: "ProvisioningState/failed", message: $marker}]}')"
if jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<"$failed_runner_result" >/dev/null; then
  printf '%s\n' "runner readiness must reject a failed result even when its marker is present" >&2
  exit 1
fi
mixed_runner_result="$(jq -n --arg marker "$runner_ready_marker" '{value: [{code: "ProvisioningState/succeeded", message: $marker}, {code: "ComponentStatus/StdErr/failed", message: "bootstrap failed"}]}')"
if jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<"$mixed_runner_result" >/dev/null; then
  printf '%s\n' "runner readiness must reject mixed success and failure results" >&2
  exit 1
fi
if jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<'{"value":[]}' >/dev/null; then
  printf '%s\n' "runner readiness must reject an empty result array" >&2
  exit 1
fi
missing_marker_runner_result='{"value":[{"code":"ProvisioningState/succeeded","message":"Enable succeeded"}]}'
if jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<"$missing_marker_runner_result" >/dev/null; then
  printf '%s\n' "runner readiness must reject success without the exact terminal marker" >&2
  exit 1
fi
near_marker_runner_result="$(jq -n --arg marker "${runner_ready_marker}." '{value: [{code: "ProvisioningState/succeeded", message: $marker}]}')"
if jq -e --arg marker "$runner_ready_marker" "$runner_readiness_filter" <<<"$near_marker_runner_result" >/dev/null; then
  printf '%s\n' "runner readiness must reject a near-match terminal marker" >&2
  exit 1
fi
payload_validation_line="$(grep -nF 'base64.b64decode(sys.stdin.buffer.read(), validate=True)' "$beta_dir/runner-bootstrap.sh" | cut -d: -f1)"
apt_mutation_line="$(grep -nF "sed -i \\" "$beta_dir/runner-bootstrap.sh" | head -1 | cut -d: -f1)"
[[ "$payload_validation_line" =~ ^[0-9]+$ && "$apt_mutation_line" =~ ^[0-9]+$ && "$payload_validation_line" -lt "$apt_mutation_line" ]] || {
  printf '%s\n' "bootstrap payload must be validated before apt source mutation" >&2
  exit 1
}
bootstrap_payload_matcher="$test_dir/bootstrap-payload-matcher.sh"
sed -n '/^bootstrap_payload_matches_context() {$/,/^}$/p' "$beta_dir/runner-bootstrap.sh" >"$bootstrap_payload_matcher"
[[ "$(grep -c '^bootstrap_payload_matches_context() {$' "$bootstrap_payload_matcher")" == "1" ]] || {
  printf '%s\n' "runner bootstrap must define one executable payload/context validator" >&2
  exit 1
}
# shellcheck disable=SC1090 # The extracted committed function is the test subject.
source "$bootstrap_payload_matcher"
valid_bootstrap_payload="$({ jq '.runner_image_version.value = "22.04.202608060"' "$bootstrap_outputs" | base64 | tr -d '\n'; })"
bootstrap_payload_matches_context "$valid_bootstrap_payload" "$subscription_id" "$deploy_client_id" 'cmbetatflab01abc123'
for rejected_bootstrap_payload in '=' 'e30='; do
  if bootstrap_payload_matches_context "$rejected_bootstrap_payload" "$subscription_id" "$deploy_client_id" 'cmbetatflab01abc123'; then
    printf '%s\n' "bootstrap payload validator accepted malformed or incomplete input" >&2
    exit 1
  fi
done
if bootstrap_payload_matches_context "$valid_bootstrap_payload" '00000000-0000-4000-8000-000000000099' "$deploy_client_id" 'cmbetatflab01abc123'; then
  printf '%s\n' "bootstrap payload validator accepted the wrong subscription" >&2
  exit 1
fi
if bootstrap_payload_matches_context "$valid_bootstrap_payload" "$subscription_id" '00000000-0000-4000-8000-000000000099' 'cmbetatflab01abc123'; then
  printf '%s\n' "bootstrap payload validator accepted the wrong deploy client" >&2
  exit 1
fi
if bootstrap_payload_matches_context "$valid_bootstrap_payload" "$subscription_id" "$deploy_client_id" 'wrongstorageaccount'; then
  printf '%s\n' "bootstrap payload validator accepted the wrong state storage account" >&2
  exit 1
fi
missing_bootstrap_field_payload="$({ jq 'del(.tenant_id)' "$bootstrap_outputs" | base64 | tr -d '\n'; })"
if bootstrap_payload_matches_context "$missing_bootstrap_field_payload" "$subscription_id" "$deploy_client_id" 'cmbetatflab01abc123'; then
  printf '%s\n' "bootstrap payload validator accepted a missing required field" >&2
  exit 1
fi
unset -f bootstrap_payload_matches_context
for buildx_script in runner-bootstrap.sh protected-runner-command.sh; do
  buildx_matcher="$test_dir/${buildx_script%.sh}-buildx-matcher.sh"
  sed -n '/^docker_buildx_output_matches_pin() {$/,/^}$/p' "$beta_dir/$buildx_script" >"$buildx_matcher"
  [[ "$(grep -c '^docker_buildx_output_matches_pin() {$' "$buildx_matcher")" == "1" ]] || {
    printf '%s\n' "$buildx_script must define one executable Buildx output matcher" >&2
    exit 1
  }
  # shellcheck disable=SC1090 # The extracted committed function is the test subject.
  source "$buildx_matcher"
  docker_buildx_output_matches_pin 'github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1~22.04.1' '0.30.1-0ubuntu1~22.04.1'
  for rejected_buildx_output in \
    'github.com/docker/buildx v0.30.1 0.30.1-0ubuntu1~22.04.1' \
    'github.com/docker/buildx 0.30.10 0.30.1-0ubuntu1~22.04.1' \
    'github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1~22.04.2' \
    'github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1~22.04.1 extra'; do
    if docker_buildx_output_matches_pin "$rejected_buildx_output" '0.30.1-0ubuntu1~22.04.1'; then
      printf '%s\n' "$buildx_script accepted a non-exact Docker Buildx version output" >&2
      exit 1
    fi
  done
  unset -f docker_buildx_output_matches_pin
done

attestation_window_helper="$test_dir/attestation-window-helper.sh"
sed -n '/^attestation_generation_window_status() {$/,/^}$/p' "$beta_dir/protected-runner-command.sh" >"$attestation_window_helper"
[[ "$(grep -c '^attestation_generation_window_status() {$' "$attestation_window_helper")" == "1" ]] || {
  printf '%s\n' "protected runner must define one executable attestation generation window validator" >&2
  exit 1
}
# shellcheck disable=SC1090 # The extracted committed function is the test subject.
source "$attestation_window_helper"
alert_window_evidence="$test_dir/alert-window-evidence.json"
jq -n '{completed_at: "2030-01-01T00:00:00Z"}' >"$alert_window_evidence"
[[ "$(attestation_generation_window_status alert-send "$alert_window_evidence" '2030-01-01T04:00:00Z')" == "live" ]]
[[ "$(attestation_generation_window_status alert-send "$alert_window_evidence" '2030-01-01T04:00:01Z')" == "expired" ]]
if attestation_generation_window_status alert-send "$alert_window_evidence" '2029-12-31T23:59:59Z' >/dev/null 2>&1; then
  printf '%s\n' "alert generation validator accepted evidence issued in the future" >&2
  exit 1
fi
offboarding_window_evidence="$test_dir/offboarding-window-evidence.json"
jq -n '{offboarding_output: {issued_at: "2030-01-01T00:00:00Z", expires_at: "2030-01-01T04:00:00Z"}}' >"$offboarding_window_evidence"
[[ "$(attestation_generation_window_status offboarding-baseline "$offboarding_window_evidence" '2030-01-01T04:00:00Z')" == "live" ]]
[[ "$(attestation_generation_window_status offboarding-baseline "$offboarding_window_evidence" '2030-01-01T04:00:01Z')" == "expired" ]]
jq '.offboarding_output.expires_at = "2030-01-01T03:59:59Z"' "$offboarding_window_evidence" >"$test_dir/offboarding-invalid-window.json"
if attestation_generation_window_status offboarding-baseline "$test_dir/offboarding-invalid-window.json" '2030-01-01T04:00:01Z' >/dev/null 2>&1; then
  printf '%s\n' "offboarding generation validator accepted a non-four-hour handoff window" >&2
  exit 1
fi

generation_resolver="$test_dir/attestation-generation-resolver.sh"
sed -n '/^resolve_attestation_generation() {$/,/^}$/p' "$beta_dir/protected-runner-command.sh" >"$generation_resolver"
[[ "$(grep -c '^resolve_attestation_generation() {$' "$generation_resolver")" == "1" ]] || {
  printf '%s\n' "protected runner must define one executable attestation generation resolver" >&2
  exit 1
}
# The production helper requires Linux stat and root ownership. These focused
# tests isolate its pointer/name/hash behavior while the runner enforces root.
stat() {
  [[ "$1" == "-c" ]] || return 1
  case "$2" in
    %a)
      if [[ -d "$3" ]]; then
        printf '%s\n' "700"
      else
        printf '%s\n' "600"
      fi
      ;;
    %u) printf '%s\n' "0" ;;
    *) return 1 ;;
  esac
}
die() {
  printf '%s\n' "$1" >&2
  exit 1
}
# shellcheck disable=SC1090 # The extracted committed function is the test subject.
source "$generation_resolver"
generation_dir="$test_dir/generations"
mkdir "$generation_dir"
generation_payload="$test_dir/generation-payload.json"
jq -cS -n '{schema_version: 1, evidence_type: "test-generation"}' >"$generation_payload"
generation_hash="$(sha256sum "$generation_payload" | awk '{print $1}')"
generation_name="$generation_hash.json"
jq -S --arg hash "$generation_hash" '. + {evidence_payload_sha256: $hash}' "$generation_payload" >"$generation_dir/$generation_name"
chmod 600 "$generation_dir/$generation_name"
printf '%s\n' "$generation_name" >"$test_dir/generation.current"
chmod 600 "$test_dir/generation.current"
[[ "$(resolve_attestation_generation "$test_dir/generation.current" "$generation_dir" "test evidence")" == "$generation_dir/$generation_name" ]]
printf '%s\n' '../outside.json' >"$test_dir/generation.current"
if (resolve_attestation_generation "$test_dir/generation.current" "$generation_dir" "test evidence" >/dev/null 2>&1); then
  printf '%s\n' "attestation generation resolver accepted path traversal" >&2
  exit 1
fi
printf '%s\n' "$generation_name" >"$test_dir/generation.current"
jq '.schema_version = 2' "$generation_dir/$generation_name" >"$test_dir/tampered-generation.json"
mv "$test_dir/tampered-generation.json" "$generation_dir/$generation_name"
chmod 600 "$generation_dir/$generation_name"
if (resolve_attestation_generation "$test_dir/generation.current" "$generation_dir" "test evidence" >/dev/null 2>&1); then
  printf '%s\n' "attestation generation resolver accepted modified evidence" >&2
  exit 1
fi

alert_orphan_helper="$test_dir/alert-orphan-helper.sh"
sed -n '/^find_reconcilable_alert_send_generation() {$/,/^}$/p' "$beta_dir/protected-runner-command.sh" >"$alert_orphan_helper"
[[ "$(grep -c '^find_reconcilable_alert_send_generation() {$' "$alert_orphan_helper")" == "1" ]] || {
  printf '%s\n' "alert orphan-reconciliation helper could not be isolated for behavioral tests" >&2
  exit 1
}
# shellcheck disable=SC1090 # Extracted committed function is the test subject.
source "$alert_orphan_helper"
alert_orphan_dir="$test_dir/alert-orphans"
mkdir "$alert_orphan_dir"
alert_source_sha="$(printf 'a%.0s' {1..40})"
alert_state_sha256="$(printf 'b%.0s' {1..64})"
alert_action_group="/subscriptions/$subscription_id/resourceGroups/$workload_rg/providers/Microsoft.Insights/actionGroups/ag-cosmas-beta-lab01"
alert_api_id="/subscriptions/$subscription_id/resourceGroups/$workload_rg/providers/Microsoft.Insights/metricAlerts/ma-api"
alert_worker_id="/subscriptions/$subscription_id/resourceGroups/$workload_rg/providers/Microsoft.Insights/metricAlerts/ma-worker"
write_alert_send_generation() {
  local completed_at="$1"
  local challenge="$2"
  local payload_file="$test_dir/alert-generation-payload.json"
  local payload_hash

  jq -cS -n \
    --arg completed_at "$completed_at" --arg source_sha "$alert_source_sha" --arg release_id "candidate-one" \
    --arg lineage "$lineage" --argjson serial 7 --arg state_sha256 "$alert_state_sha256" \
    --arg action_group "$alert_action_group" --arg api_alert "$alert_api_id" --arg worker_alert "$alert_worker_id" \
    --arg challenge "$challenge" --arg operation_hash "$(printf 'd%.0s' {1..64})" \
    --arg send_intent_hash "$(printf '1%.0s' {1..64})" '
      {
        schema_version: 1, evidence_type: "protected-runner-alert-delivery", alert_phase: "send",
        completed_at: $completed_at, source_sha: $source_sha, release_id: $release_id,
        state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
        action_group: {resource_id: $action_group},
        metric_alerts: {api: {resource_id: $api_alert}, worker: {resource_id: $worker_alert}},
        notification_test: {
          alert_type: "metricstaticthreshold", azure_operation_completed: true,
          email_action_count: 1, email_action_succeeded: true,
          delivery_confirmed_by_owner: false
        },
        confirmation_challenge: $challenge, send_intent_sha256: $send_intent_hash,
        notification_operation_sha256: $operation_hash,
        recipient_address_returned: false, secrets_returned: false
      }
    ' >"$payload_file"
  payload_hash="$(sha256sum "$payload_file" | awk '{print $1}')"
  jq -S --arg hash "$payload_hash" '. + {evidence_payload_sha256: $hash}' "$payload_file" >"$alert_orphan_dir/$payload_hash.json"
  chmod 600 "$alert_orphan_dir/$payload_hash.json"
  printf '%s\n' "$alert_orphan_dir/$payload_hash.json"
}
expired_orphan="$(write_alert_send_generation '2029-12-31T20:00:00Z' "$(printf 'f%.0s' {1..64})")"
first_orphan="$(write_alert_send_generation '2030-01-01T00:00:00Z' "$(printf 'c%.0s' {1..64})")"
discovered_orphan="$(find_reconcilable_alert_send_generation \
  "$alert_orphan_dir" "$alert_source_sha" candidate-one "$lineage" 7 "$alert_state_sha256" \
  "$alert_action_group" "$alert_api_id" "$alert_worker_id" '2030-01-01T01:00:00Z')"
[[ "$discovered_orphan" == "live|$first_orphan" ]] || {
  printf '%s\n' "alert send orphan reconciliation did not recover the exact live generation" >&2
  exit 1
}
[[ -f "$expired_orphan" ]]
expired_only_dir="$test_dir/alert-expired-orphans"
mkdir "$expired_only_dir"
cp "$expired_orphan" "$expired_only_dir/${expired_orphan##*/}"
expired_reconciliation="$(find_reconcilable_alert_send_generation \
  "$expired_only_dir" "$alert_source_sha" candidate-one "$lineage" 7 "$alert_state_sha256" \
  "$alert_action_group" "$alert_api_id" "$alert_worker_id" '2030-01-01T01:00:00Z')"
[[ "$expired_reconciliation" == "expired|$expired_only_dir/${expired_orphan##*/}" ]] || {
  printf '%s\n' "alert send orphan reconciliation did not restore the latest expired successful generation" >&2
  exit 1
}
second_orphan="$(write_alert_send_generation '2030-01-01T00:01:00Z' "$(printf 'e%.0s' {1..64})")"
if (find_reconcilable_alert_send_generation \
  "$alert_orphan_dir" "$alert_source_sha" candidate-one "$lineage" 7 "$alert_state_sha256" \
  "$alert_action_group" "$alert_api_id" "$alert_worker_id" '2030-01-01T01:00:00Z' >/dev/null 2>&1); then
  printf '%s\n' "alert send orphan reconciliation accepted multiple matching live generations" >&2
  exit 1
fi
[[ -f "$second_orphan" ]]

alert_intent_helper="$test_dir/alert-intent-helper.sh"
sed -n '/^find_unresolved_alert_send_intent() {$/,/^}$/p' "$beta_dir/protected-runner-command.sh" >"$alert_intent_helper"
[[ "$(grep -c '^find_unresolved_alert_send_intent() {$' "$alert_intent_helper")" == "1" ]] || {
  printf '%s\n' "alert send-intent helper could not be isolated for behavioral tests" >&2
  exit 1
}
# shellcheck disable=SC1090 # Extracted committed function is the test subject.
source "$alert_intent_helper"
alert_request_sha256="$(printf '2%.0s' {1..64})"
write_alert_send_intent() {
  local target_dir="$1"
  local intent_key="$2"
  local supersedes="$3"
  local retry_approval="$4"
  local payload_file="$test_dir/alert-intent-payload.json"
  local payload_hash

  jq -cS -n \
    --arg intent_key "$intent_key" --arg source_sha "$alert_source_sha" --arg release_id "candidate-one" \
    --arg lineage "$lineage" --argjson serial 7 --arg state_sha256 "$alert_state_sha256" \
    --arg action_group "$alert_action_group" --arg api_alert "$alert_api_id" --arg worker_alert "$alert_worker_id" \
    --arg request_sha256 "$alert_request_sha256" --arg supersedes "$supersedes" --arg retry_approval "$retry_approval" '
      {
        schema_version: 1, evidence_type: "protected-runner-alert-send-intent",
        issued_at: "2030-01-01T00:00:00Z", intent_key_sha256: $intent_key,
        source_sha: $source_sha, release_id: $release_id,
        state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
        action_group_resource_id: $action_group,
        api_alert_resource_id: $api_alert,
        worker_alert_resource_id: $worker_alert,
        notification_request_sha256: $request_sha256,
        predecessor_send_evidence_sha256: "none",
        supersedes_intent_sha256: (if $supersedes == "" then null else $supersedes end),
        retry_approval_sha256: (if $retry_approval == "" then null else $retry_approval end),
        client_request_id: "123e4567-e89b-12d3-a456-426614174000",
        confirmation_challenge: ("3" * 64),
        post_may_have_started: true,
        recipient_address_returned: false,
        secrets_returned: false
      }
    ' >"$payload_file"
  payload_hash="$(sha256sum "$payload_file" | awk '{print $1}')"
  jq -S --arg hash "$payload_hash" '. + {evidence_payload_sha256: $hash}' "$payload_file" >"$target_dir/$intent_key.json"
  chmod 600 "$target_dir/$intent_key.json"
  printf '%s|%s\n' "$target_dir/$intent_key.json" "$payload_hash"
}

intent_dir="$test_dir/alert-intents"
intent_evidence_dir="$test_dir/alert-intent-evidence"
mkdir "$intent_dir" "$intent_evidence_dir"
intent_record="$(write_alert_send_intent "$intent_dir" "$(printf '4%.0s' {1..64})" "" "")"
intent_path="${intent_record%%|*}"
intent_hash="${intent_record##*|}"
unresolved_intent="$(find_unresolved_alert_send_intent \
  "$intent_dir" "$intent_evidence_dir" "$alert_source_sha" candidate-one \
  "$alert_action_group" "$alert_request_sha256")"
[[ "$unresolved_intent" == "$intent_path" ]] || {
  printf '%s\n' "alert send-intent helper did not return the exact unresolved intent" >&2
  exit 1
}
resolved_payload="$test_dir/resolved-alert-intent-evidence.json"
jq -cS -n --arg intent_hash "$intent_hash" '{
  schema_version: 1, evidence_type: "protected-runner-alert-delivery", alert_phase: "send",
  send_intent_sha256: $intent_hash,
  notification_test: {azure_operation_completed: true, email_action_succeeded: true}
}' >"$resolved_payload"
resolved_hash="$(sha256sum "$resolved_payload" | awk '{print $1}')"
jq -S --arg hash "$resolved_hash" '. + {evidence_payload_sha256: $hash}' "$resolved_payload" >"$intent_evidence_dir/$resolved_hash.json"
chmod 600 "$intent_evidence_dir/$resolved_hash.json"
[[ -z "$(find_unresolved_alert_send_intent \
  "$intent_dir" "$intent_evidence_dir" "$alert_source_sha" candidate-one \
  "$alert_action_group" "$alert_request_sha256")" ]] || {
  printf '%s\n' "resolved alert send intent remained blocking" >&2
  exit 1
}

supersession_dir="$test_dir/alert-intent-supersession"
empty_evidence_dir="$test_dir/alert-empty-evidence"
mkdir "$supersession_dir" "$empty_evidence_dir"
first_intent_record="$(write_alert_send_intent "$supersession_dir" "$(printf '5%.0s' {1..64})" "" "")"
first_intent_hash="${first_intent_record##*|}"
second_intent_record="$(write_alert_send_intent "$supersession_dir" "$(printf '6%.0s' {1..64})" "$first_intent_hash" "$(printf '7%.0s' {1..64})")"
second_intent_path="${second_intent_record%%|*}"
[[ "$(find_unresolved_alert_send_intent \
  "$supersession_dir" "$empty_evidence_dir" "$alert_source_sha" candidate-one \
  "$alert_action_group" "$alert_request_sha256")" == "$second_intent_path" ]] || {
  printf '%s\n' "owner-authorized alert intent supersession did not leave exactly the new attempt unresolved" >&2
  exit 1
}

multiple_dir="$test_dir/alert-intent-multiple"
mkdir "$multiple_dir"
write_alert_send_intent "$multiple_dir" "$(printf '8%.0s' {1..64})" "" "" >/dev/null
write_alert_send_intent "$multiple_dir" "$(printf '9%.0s' {1..64})" "" "" >/dev/null
if (find_unresolved_alert_send_intent \
  "$multiple_dir" "$empty_evidence_dir" "$alert_source_sha" candidate-one \
  "$alert_action_group" "$alert_request_sha256" >/dev/null 2>&1); then
  printf '%s\n' "alert send-intent helper accepted multiple unresolved attempts" >&2
  exit 1
fi
tampered_intent="$(find "$multiple_dir" -type f -name '*.json' | head -n 1)"
jq '.post_may_have_started = false' "$tampered_intent" >"$test_dir/tampered-intent.json"
mv "$test_dir/tampered-intent.json" "$tampered_intent"
chmod 600 "$tampered_intent"
if (find_unresolved_alert_send_intent \
  "$multiple_dir" "$empty_evidence_dir" "$alert_source_sha" candidate-one \
  "$alert_action_group" "$alert_request_sha256" >/dev/null 2>&1); then
  printf '%s\n' "alert send-intent helper accepted a modified intent" >&2
  exit 1
fi
unset -f write_alert_send_intent find_unresolved_alert_send_intent write_alert_send_generation find_reconcilable_alert_send_generation resolve_attestation_generation attestation_generation_window_status stat die

grep -F '.phase == "foundation_reconcile" and $stage == "foundation"' "$beta_dir/protected-runner-command.sh" >/dev/null
for guarded_operation in release-rollback release-forward inspect-stage stage-generation offboarding-acceptance; do
  grep -F "\"$guarded_operation\"" "$beta_dir/transport-to-protected-runner.sh" >/dev/null
  grep -F "\"$guarded_operation\"" "$beta_dir/protected-runner-command.sh" >/dev/null
done
for recovery_confirmation in \
  'AUTHORIZE D3 IMMUTABLE DIGEST ROLLBACK' \
  'AUTHORIZE D3 IMMUTABLE DIGEST FORWARD RESTORATION'; do
  grep -F "$recovery_confirmation" "$beta_dir/transport-to-protected-runner.sh" >/dev/null
  grep -F "$recovery_confirmation" "$beta_dir/protected-runner-command.sh" >/dev/null
done
grep -F 'rollback_state_sha256' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'rollback_state_sha256' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'AUTHORIZE D3 IMMUTABLE STAGE GENERATION TRANSITION' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'stage_generation_transition.py' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'validate_stage_tfvars_payload "$replacement_tfvars_file" "$stage"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F '"$execution_state" == "TimedOut"' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F '"$provisioning_state" == "Canceled"' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'mutable_tags_used: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'terraform_no_drift: $terraform_no_drift' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'human_clerk_browser_steps_machine_verified: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'identifiers_returned: false, secrets_returned: false' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'artifact_file="$release_root/executions/recovery/$recovery_phase-attestation.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'alert_current_pointer="$alert_root/$alert_phase.current"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'alert_delivery_name="$evidence_hash.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'stored_send_file="$alert_evidence_dir/$prior_evidence_hash.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'reconciled_alert_send="$(find_reconcilable_alert_send_generation' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'mv -f -- "$alert_delivery_pointer_tmp" "$alert_current_pointer"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'AUTHORIZE D3 ALERT RETRY AFTER AMBIGUOUS SEND' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F -- '--alert-retry-approval' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'protected-runner-alert-send-intent-inspection' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'protected-runner-alert-send-intent-inspection' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
grep -F 'fsync_path "$alert_delivery_evidence_tmp"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'fsync_path "$alert_evidence_dir"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'fsync_path "$alert_root"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'fsync_path "$release_root"' "$beta_dir/protected-runner-command.sh" >/dev/null
alert_orphan_reconcile_line="$(grep -nF 'reconciled_alert_send="$(find_reconcilable_alert_send_generation' "$beta_dir/protected-runner-command.sh" | cut -d: -f1)"
alert_intent_publish_line="$(grep -nF 'ln -- "$alert_send_intent_tmp" "$alert_send_intent_file"' "$beta_dir/protected-runner-command.sh" | cut -d: -f1)"
alert_notification_post_line="$(grep -nF 'notification_status="$(curl --config "$curl_config_file" --request POST' "$beta_dir/protected-runner-command.sh" | cut -d: -f1)"
[[ "$alert_orphan_reconcile_line" =~ ^[0-9]+$ && "$alert_notification_post_line" =~ ^[0-9]+$ && "$alert_orphan_reconcile_line" -lt "$alert_notification_post_line" ]] || {
  printf '%s\n' "alert orphan reconciliation must run before any replacement notification POST" >&2
  exit 1
}
[[ "$alert_intent_publish_line" =~ ^[0-9]+$ && "$alert_notification_post_line" =~ ^[0-9]+$ && "$alert_intent_publish_line" -lt "$alert_notification_post_line" ]] || {
  printf '%s\n' "durable alert send intent must be published before any notification POST" >&2
  exit 1
}
inspect_intent_start_line="$(grep -nF 'if [[ "$alert_phase" == "inspect-intent" ]]; then' "$beta_dir/protected-runner-command.sh" | cut -d: -f1)"
inspect_intent_discovery_line="$(awk -v start="$inspect_intent_start_line" 'NR > start && /unresolved_alert_send_intent="\$\(find_unresolved_alert_send_intent/ {print NR; exit}' "$beta_dir/protected-runner-command.sh")"
inspect_intent_pointer_line="$(awk -v start="$inspect_intent_start_line" 'NR > start && /inspected_alert_send_intent="\$\(resolve_alert_send_intent_pointer/ {print NR; exit}' "$beta_dir/protected-runner-command.sh")"
[[ "$inspect_intent_discovery_line" =~ ^[0-9]+$ && "$inspect_intent_pointer_line" =~ ^[0-9]+$ && "$inspect_intent_discovery_line" -lt "$inspect_intent_pointer_line" ]] || {
  printf '%s\n' "alert intent inspection must discover a pointerless unresolved attempt before requiring pointer metadata" >&2
  exit 1
}
grep -F 'mv -f -- "$alert_send_intent_pointer_tmp" "$alert_send_intent_pointer"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'offboarding_current_pointer="$offboarding_root/$offboarding_phase.current"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'offboarding_evidence_name="$evidence_hash.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'stored_baseline_file="$offboarding_evidence_dir/$prior_wrapper_hash.json"' "$beta_dir/protected-runner-command.sh" >/dev/null
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
grep -F 'public_configuration: {' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'guard_validate_network_public_configuration "$network_evidence_tmp" "$source_sha" "$release_id" "$GUARD_BETA_ID"' "$beta_dir/protected-runner-command.sh" >/dev/null
grep -F 'guard_validate_network_public_configuration "$artifact_out" "$source_sha" "$release_id" "$GUARD_BETA_ID"' "$beta_dir/transport-to-protected-runner.sh" >/dev/null
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
