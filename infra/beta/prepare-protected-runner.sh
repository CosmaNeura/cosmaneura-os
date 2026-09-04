#!/bin/bash -p
set +x
_cosmas_wrapper_dir="$(cd -- "$(/usr/bin/dirname -- "${BASH_SOURCE[0]}")" && /bin/pwd -P)" || exit 1
# shellcheck source=local-wrapper-env.sh
. "$_cosmas_wrapper_dir/local-wrapper-env.sh"
cosmas_isolate_local_wrapper_environment "$@"
unset -f cosmas_isolate_local_wrapper_environment
unset _cosmas_wrapper_dir
set -euo pipefail

umask 077

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd -- "$script_dir/../.." && pwd -P)"
# shellcheck source=deployment-guard-lib.sh
source "$script_dir/deployment-guard-lib.sh"

usage() {
  printf '%s\n' \
    "Usage: $0 --bootstrap-outputs PATH --source-sha SHA --tofu-version VERSION --tofu-sha256 SHA256 \\" \
    "  --azure-cli-version APT_VERSION --docker-version APT_VERSION --docker-buildx-version APT_VERSION \\" \
    "  --git-version APT_VERSION --jq-version APT_VERSION \\" \
    "  --trivy-version VERSION --trivy-sha256 SHA256" \
    "" \
    "Waits for the protected runner, verifies its no-public-IP/Trusted Launch/UAMI" \
    "configuration, then sends the non-secret pinned setup script through Azure" \
    "Run Command. Package versions must first be reviewed for Ubuntu jammy."
}

bootstrap_outputs=""
source_sha=""
tofu_version=""
tofu_sha256=""
azure_cli_version=""
docker_version=""
docker_buildx_version=""
git_version=""
jq_version=""
trivy_version=""
trivy_sha256=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap-outputs) bootstrap_outputs="${2:-}"; shift 2 ;;
    --source-sha) source_sha="${2:-}"; shift 2 ;;
    --tofu-version) tofu_version="${2:-}"; shift 2 ;;
    --tofu-sha256) tofu_sha256="${2:-}"; shift 2 ;;
    --azure-cli-version) azure_cli_version="${2:-}"; shift 2 ;;
    --docker-version) docker_version="${2:-}"; shift 2 ;;
    --docker-buildx-version) docker_buildx_version="${2:-}"; shift 2 ;;
    --git-version) git_version="${2:-}"; shift 2 ;;
    --jq-version) jq_version="${2:-}"; shift 2 ;;
    --trivy-version) trivy_version="${2:-}"; shift 2 ;;
    --trivy-sha256) trivy_sha256="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) guard_die "unknown argument: $1" ;;
  esac
done

[[ -n "$bootstrap_outputs" ]] || guard_die "--bootstrap-outputs is required"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || guard_die "--source-sha must be a full lowercase Git commit"
[[ "$tofu_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || guard_die "--tofu-version must be exact"
[[ "$tofu_sha256" =~ ^[0-9a-f]{64}$ ]] || guard_die "--tofu-sha256 must be exact lowercase hex"
[[ "$trivy_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || guard_die "--trivy-version must be exact"
[[ "$trivy_sha256" =~ ^[0-9a-f]{64}$ ]] || guard_die "--trivy-sha256 must be exact lowercase hex"
for value in "$azure_cli_version" "$docker_version" "$docker_buildx_version" "$git_version" "$jq_version"; do
  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9.+:~_-]*$ ]] || guard_die "every apt package version must be supplied exactly"
done
[[ "$tofu_version:$tofu_sha256" == "1.12.5:dade9650e6b74fc7a8b986bd8717497d32f9e09cf82e479afef4977fa3085536" ]] || guard_die "OpenTofu must match the reviewed D3 1.12.5 archive pin"
[[ "$trivy_version:$trivy_sha256" == "0.74.0:2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a" ]] || guard_die "Trivy must match the reviewed D3 0.74.0 archive pin"
[[ "$azure_cli_version" == "2.89.1-1~jammy" ]] || guard_die "Azure CLI must match the reviewed Jammy package pin"
[[ "$docker_version" == "29.1.3-0ubuntu3~22.04.2" ]] || guard_die "Docker must match the reviewed Jammy 29.1.3 package pin"
[[ "$docker_buildx_version" == "0.30.1-0ubuntu1~22.04.1" ]] || guard_die "Docker Buildx must match the reviewed Jammy package pin"
[[ "$git_version" == "1:2.34.1-1ubuntu1.17" ]] || guard_die "git must match the reviewed Jammy package pin"
[[ "$jq_version" == "1.6-2.1ubuntu3.2" ]] || guard_die "jq must match the reviewed Jammy package pin"
for command_name in az jq stat; do
  command -v "$command_name" >/dev/null 2>&1 || guard_die "$command_name is required"
done

bootstrap_outputs="$(guard_absolute_path "$bootstrap_outputs")"
guard_outside_repository "$bootstrap_outputs" "$repository_root" "bootstrap output JSON"
guard_private_file "$bootstrap_outputs" "bootstrap output JSON"
guard_load_bootstrap_outputs "$bootstrap_outputs"
prepare_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-d3-runner-prepare.XXXXXX")"
chmod 0700 "$prepare_temp_dir"
committed_bootstrap_script="$prepare_temp_dir/runner-bootstrap.sh"
cleanup() {
  rm -rf -- "$prepare_temp_dir"
}
trap cleanup EXIT
guard_materialize_local_committed_file \
  "$repository_root" \
  "$source_sha" \
  "infra/beta/runner-bootstrap.sh" \
  "$committed_bootstrap_script" \
  "git@github.com:CosmaNeura/cosmaneura-os.git"

account_json="$(az account show --only-show-errors --output json)" || guard_die "Azure account context is unavailable"
[[ "$(guard_lower "$(jq -er '.id' <<<"$account_json")")" == "$(guard_lower "$GUARD_SUBSCRIPTION_ID")" ]] || guard_die "active subscription does not match bootstrap output"
[[ "$(guard_lower "$(jq -er '.tenantId' <<<"$account_json")")" == "$(guard_lower "$GUARD_TENANT_ID")" ]] || guard_die "active tenant does not match bootstrap output"

runner_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/$GUARD_RUNNER_VM_NAME"
deploy_identity_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$GUARD_DEPLOY_IDENTITY_NAME"
az vm wait --ids "$runner_id" --created --interval 10 --timeout 900 --only-show-errors
vm_json="$(az vm show --ids "$runner_id" --only-show-errors --output json)" || guard_die "cannot read protected runner"
jq -e \
  --arg identity_id "$(guard_lower "$deploy_identity_id")" \
  --arg image_version "$GUARD_RUNNER_IMAGE_VERSION" '
    .securityProfile.securityType == "TrustedLaunch" and
    .securityProfile.uefiSettings.secureBootEnabled == true and
    .securityProfile.uefiSettings.vTpmEnabled == true and
    .hardwareProfile.vmSize == "Standard_B2s" and
    .osProfile.linuxConfiguration.disablePasswordAuthentication == true and
    .storageProfile.imageReference.publisher == "Canonical" and
    .storageProfile.imageReference.offer == "0001-com-ubuntu-server-jammy" and
    .storageProfile.imageReference.sku == "22_04-lts-gen2" and
    ((.storageProfile.imageReference.version // .storageProfile.imageReference.exactVersion) == $image_version) and
    .identity.type == "UserAssigned" and
    ((.identity.userAssignedIdentities | keys | map(ascii_downcase)) == [$identity_id]) and
    ([.networkProfile.networkInterfaces[]?.id] | length == 1)
  ' <<<"$vm_json" >/dev/null || guard_die "runner is not Trusted Launch or is not bound only to the exact deploy identity"

nic_id="$(jq -er '.networkProfile.networkInterfaces[0].id' <<<"$vm_json")"
nic_json="$(az network nic show --ids "$nic_id" --only-show-errors --output json)" || guard_die "cannot read protected runner NIC"
jq -e \
  --arg subnet_id "$(guard_lower "$GUARD_RUNNER_SUBNET_ID")" '
    (.ipConfigurations | length) == 1 and
    ([.ipConfigurations[]? | select(.publicIPAddress != null)] | length == 0) and
    (.ipConfigurations[0].subnet.id | ascii_downcase) == $subnet_id
  ' <<<"$nic_json" >/dev/null || guard_die "protected runner NIC is not private-only in the exact runner subnet"

subnet_json="$(az network vnet subnet show --ids "$GUARD_RUNNER_SUBNET_ID" --only-show-errors --output json)" || guard_die "cannot read protected runner subnet"
jq -e \
  --arg subnet_id "$(guard_lower "$GUARD_RUNNER_SUBNET_ID")" \
  --arg nsg_id "$(guard_lower "$GUARD_RUNNER_NSG_ID")" \
  --arg nat_id "$(guard_lower "$GUARD_RUNNER_NAT_GATEWAY_ID")" '
    (.id | ascii_downcase) == $subnet_id and
    .defaultOutboundAccess == false and
    (.networkSecurityGroup.id | ascii_downcase) == $nsg_id and
    (.natGateway.id | ascii_downcase) == $nat_id
  ' <<<"$subnet_json" >/dev/null || guard_die "runner subnet lost its exact NSG, NAT gateway, or explicit default-outbound denial"

nsg_json="$(az network nsg show --ids "$GUARD_RUNNER_NSG_ID" --only-show-errors --output json)" || guard_die "cannot read protected runner NSG"
jq -e '
  def rule($name): first(.securityRules[] | select(.name == $name));
  (.securityRules | length) == 8 and
  (rule("AllowPrivateDeploymentPorts") |
    .priority == 100 and .direction == "Outbound" and .access == "Allow" and
    .protocol == "Tcp" and .sourceAddressPrefix == "VirtualNetwork" and
    .destinationAddressPrefix == "VirtualNetwork" and
    .sourcePortRange == "*" and
    (.destinationPortRanges | sort) == (["10000", "443", "5432"] | sort)) and
  (rule("AllowAzureInstanceMetadata") |
    .priority == 105 and .direction == "Outbound" and .access == "Allow" and
    .protocol == "Tcp" and .sourcePortRange == "*" and .destinationPortRange == "80" and
    .sourceAddressPrefix == "*" and .destinationAddressPrefix == "169.254.169.254") and
  (rule("AllowAzureWireServer") |
    .priority == 106 and .direction == "Outbound" and .access == "Allow" and
    .protocol == "Tcp" and .sourcePortRange == "*" and
    (.destinationPortRanges | sort) == (["80", "32526"] | sort) and
    .sourceAddressPrefix == "*" and .destinationAddressPrefix == "168.63.129.16") and
  (rule("AllowAzureDnsUdp") |
    .priority == 110 and .direction == "Outbound" and .access == "Allow" and
    .protocol == "Udp" and .sourcePortRange == "*" and .destinationPortRange == "53" and
    .sourceAddressPrefix == "*" and .destinationAddressPrefix == "168.63.129.16") and
  (rule("AllowAzureDnsTcp") |
    .priority == 120 and .direction == "Outbound" and .access == "Allow" and
    .protocol == "Tcp" and .sourcePortRange == "*" and .destinationPortRange == "53" and
    .sourceAddressPrefix == "*" and .destinationAddressPrefix == "168.63.129.16") and
  (rule("AllowHttpsEgress") |
    .priority == 130 and .direction == "Outbound" and .access == "Allow" and
    .protocol == "Tcp" and .sourcePortRange == "*" and .destinationPortRange == "443" and
    .sourceAddressPrefix == "*" and .destinationAddressPrefix == "Internet") and
  (rule("DenyOtherOutbound") |
    .priority == 4095 and .direction == "Outbound" and .access == "Deny" and .protocol == "*" and
    .sourcePortRange == "*" and .destinationPortRange == "*" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "*") and
  (rule("DenyAllInbound") |
    .priority == 4096 and .direction == "Inbound" and .access == "Deny" and .protocol == "*" and
    .sourcePortRange == "*" and .destinationPortRange == "*" and .sourceAddressPrefix == "*" and .destinationAddressPrefix == "*")
' <<<"$nsg_json" >/dev/null || guard_die "runner NSG rules differ from the reviewed no-inbound/HTTPS-only boundary"

nat_json="$(az network nat gateway show --ids "$GUARD_RUNNER_NAT_GATEWAY_ID" --only-show-errors --output json)" || guard_die "cannot read protected runner NAT gateway"
jq -e \
  --arg public_ip_id "$(guard_lower "$GUARD_RUNNER_EGRESS_PUBLIC_IP_ID")" '
    .sku.name == "Standard" and
    (.publicIpAddresses | length) == 1 and
    (.publicIpAddresses[0].id | ascii_downcase) == $public_ip_id
  ' <<<"$nat_json" >/dev/null || guard_die "runner NAT gateway is not Standard with the exact dedicated egress IP"

public_ip_json="$(az network public-ip show --ids "$GUARD_RUNNER_EGRESS_PUBLIC_IP_ID" --only-show-errors --output json)" || guard_die "cannot read protected runner egress IP"
jq -e '
  .sku.name == "Standard" and
  .publicIPAllocationMethod == "Static" and
  .publicIPAddressVersion == "IPv4"
' <<<"$public_ip_json" >/dev/null || guard_die "runner egress IP is not dedicated Standard/Static IPv4"

storage_json="$(az storage account show \
  --subscription "$GUARD_SUBSCRIPTION_ID" \
  --resource-group "$GUARD_STATE_RESOURCE_GROUP" \
  --name "$GUARD_STATE_STORAGE_ACCOUNT" \
  --only-show-errors \
  --output json)" || guard_die "cannot read private state storage account"
jq -e \
  --arg storage_id "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$GUARD_STATE_STORAGE_ACCOUNT")" '
    (.id | ascii_downcase) == $storage_id and
    .publicNetworkAccess == "Disabled" and
    .allowSharedKeyAccess == false and
    .defaultToOAuthAuthentication == true and
    .minimumTlsVersion == "TLS1_2"
  ' <<<"$storage_json" >/dev/null || guard_die "state storage lost its private, Azure-AD-only, TLS 1.2 boundary"

expected_state_storage_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$GUARD_STATE_STORAGE_ACCOUNT"
expected_state_dns_id="$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID"
expected_workload_rg_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP"
expected_state_rg_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP"
rbac_ready=false
for _ in $(seq 1 60); do
  if role_json="$(az role assignment list \
    --assignee-object-id "$GUARD_DEPLOY_PRINCIPAL_ID" \
    --all \
    --include-inherited \
    --fill-principal-name false \
    --only-show-errors \
    --output json 2>/dev/null)" &&
    jq -e \
      --arg workload_rg "$(guard_lower "$expected_workload_rg_id")" \
      --arg state_rg "$(guard_lower "$expected_state_rg_id")" \
      --arg storage "$(guard_lower "$expected_state_storage_id")" \
      --arg state_vnet "$(guard_lower "$GUARD_STATE_VNET_ID")" \
      --arg state_dns "$(guard_lower "$expected_state_dns_id")" '
        [
          .[] |
          {scope: (.scope | ascii_downcase), role: .roleDefinitionName}
        ] as $actual |
        ($actual | all(
          (.scope == $state_rg and .role == "Reader") or
          (.scope == $workload_rg and (.role == "Contributor" or .role == "User Access Administrator")) or
          (.scope == $storage and .role == "Storage Blob Data Contributor") or
          (.scope == $state_vnet and .role == "Network Contributor") or
          (.scope == $state_dns and .role == "Private DNS Zone Contributor") or
          ((.scope | startswith($workload_rg + "/")) and
            (.role == "AcrPush" or .role == "Storage Blob Data Contributor" or .role == "Key Vault Secrets Officer"))
        )) and
        ($actual | any(.scope == $workload_rg and .role == "Contributor")) and
        ($actual | any(.scope == $workload_rg and .role == "User Access Administrator")) and
        ($actual | any(.scope == $state_rg and .role == "Reader")) and
        ($actual | any(.scope == $storage and .role == "Storage Blob Data Contributor")) and
        ($actual | any(.scope == $state_vnet and .role == "Network Contributor")) and
        ($actual | any(.scope == $state_dns and .role == "Private DNS Zone Contributor"))
      ' <<<"$role_json" >/dev/null; then
    rbac_ready=true
    break
  fi
  sleep 10
done
[[ "$rbac_ready" == "true" ]] || guard_die "deploy identity RBAC did not converge to the exact reviewed scopes within ten minutes"

federated_credentials_json="$(az identity federated-credential list \
  --identity-name "$GUARD_DEPLOY_IDENTITY_NAME" \
  --resource-group "$GUARD_STATE_RESOURCE_GROUP" \
  --only-show-errors \
  --output json)" || guard_die "cannot inspect deploy identity federated credentials"
jq -e 'length == 0' <<<"$federated_credentials_json" >/dev/null || guard_die "deploy identity has a forbidden federated credential; D3 permits VM-attached UAMI only"

agent_ready=false
for _ in $(seq 1 60); do
  if [[ "$(az vm get-instance-view --ids "$runner_id" --query "length(instanceView.vmAgent.statuses[?code=='ProvisioningState/succeeded'])" --output tsv --only-show-errors)" == "1" ]]; then
    agent_ready=true
    break
  fi
  sleep 10
done
[[ "$agent_ready" == "true" ]] || guard_die "Azure VM Agent did not become ready within ten minutes"

# Azure CLI splits every Run Command parameter at its first equals sign. Name
# every value explicitly so Base64 padding remains data and the positional
# order consumed by runner-bootstrap.sh stays deterministic.
result_json="$(az vm run-command invoke \
  --ids "$runner_id" \
  --command-id RunShellScript \
  --scripts @"$committed_bootstrap_script" \
  --parameters \
    "subscription_id=$GUARD_SUBSCRIPTION_ID" \
    "deploy_client_id=$GUARD_DEPLOY_CLIENT_ID" \
    "state_storage_account=$GUARD_STATE_STORAGE_ACCOUNT" \
    "tofu_version=$tofu_version" \
    "tofu_sha256=$tofu_sha256" \
    "azure_cli_version=$azure_cli_version" \
    "docker_version=$docker_version" \
    "docker_buildx_version=$docker_buildx_version" \
    "git_version=$git_version" \
    "jq_version=$jq_version" \
    "trivy_version=$trivy_version" \
    "trivy_sha256=$trivy_sha256" \
    "bootstrap_outputs_base64=$(base64 <"$bootstrap_outputs" | tr -d '\n')" \
  --only-show-errors \
  --output json)" || guard_die "Azure Run Command failed while preparing the protected runner"
runner_ready_marker="D3 protected runner is ready; private state DNS and managed-identity access passed"
jq -e --arg marker "$runner_ready_marker" '
  (.value? // null) as $values |
  ($values | type == "array" and length > 0) and
  all($values[]?; (.code | type == "string" and endswith("/succeeded"))) and
  any($values[]?; .code == "ProvisioningState/succeeded") and
  ([$values[]?.message? | strings | split("\n")[]] | any(. == $marker))
' <<<"$result_json" >/dev/null || guard_die "protected runner setup did not emit the exact readiness marker"

printf '%s\n' "D3 protected runner preparation passed without a VM public IP or persistent CI/repository credential"
