#!/usr/bin/env bash
# shellcheck disable=SC2034 # This sourced library intentionally publishes GUARD_* result globals.

# Shared fail-closed checks for the human-run D3 Terraform wrappers. This file
# defines functions only; callers retain `set -euo pipefail` and their traps.

guard_die() {
  printf 'D3 deployment guard refused: %s\n' "$1" >&2
  exit 1
}

guard_lower() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

guard_absolute_path() {
  local path="$1"
  local directory
  local basename_value

  directory="$(dirname -- "$path")"
  basename_value="$(basename -- "$path")"
  [[ -d "$directory" ]] || guard_die "parent directory does not exist: $directory"
  printf '%s/%s\n' "$(cd -- "$directory" && pwd -P)" "$basename_value"
}

guard_outside_repository() {
  local path="$1"
  local repository_root="$2"
  local label="$3"

  case "$path" in
    "$repository_root"|"$repository_root"/*)
      guard_die "$label must be outside the repository"
      ;;
  esac
}

guard_private_directory() {
  local path="$1"
  local label="$2"
  local mode

  [[ -d "$path" && ! -L "$path" ]] || guard_die "$label must be an existing non-symlink directory"
  mode="$(stat -f '%Lp' "$path" 2>/dev/null || stat -c '%a' "$path" 2>/dev/null)"
  mode="${mode: -3}"
  (( (8#$mode & 077) == 0 )) || guard_die "$label must not be accessible by group/other (use mode 0700)"
}

guard_private_file() {
  local path="$1"
  local label="$2"
  local mode

  [[ -f "$path" && ! -L "$path" ]] || guard_die "$label must be an existing non-symlink regular file"
  mode="$(stat -f '%Lp' "$path" 2>/dev/null || stat -c '%a' "$path" 2>/dev/null)"
  mode="${mode: -3}"
  (( (8#$mode & 077) == 0 )) || guard_die "$label must not be readable, writable, or executable by group/other (use mode 0600)"
}

guard_new_private_path() {
  local path="$1"
  local label="$2"

  [[ ! -e "$path" && ! -L "$path" ]] || guard_die "$label already exists"
  guard_private_directory "$(dirname -- "$path")" "parent directory for $label"
}

guard_validate_alert_owner_confirmation() {
  local confirmation_file="$1"
  local send_evidence_file="$2"

  guard_private_file "$confirmation_file" "alert owner confirmation"
  guard_private_file "$send_evidence_file" "alert send evidence"
  (( $(wc -c <"$confirmation_file") <= 4096 )) || guard_die "alert owner confirmation exceeds 4 KiB"
  jq -e --slurpfile send "$send_evidence_file" '
    type == "object" and
    (keys | sort) == (["challenge", "confirmed_at", "confirmation_reference", "owner_assertion", "schema_version", "send_evidence_sha256"] | sort) and
    .schema_version == 1 and
    .owner_assertion == "I CONFIRM RECEIPT OF THE D3 ALERT TEST" and
    (.challenge | strings | test("^[0-9a-f]{64}$")) and
    (.send_evidence_sha256 | strings | test("^[0-9a-f]{64}$")) and
    (.confirmed_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
    (.confirmation_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
    (.confirmation_reference | contains("@") | not) and
    .challenge == $send[0].confirmation_challenge and
    .send_evidence_sha256 == $send[0].evidence_payload_sha256
  ' "$confirmation_file" >/dev/null || guard_die "alert confirmation must bind the exact unpredictable challenge and send evidence"
}

guard_validate_pitr_revision_set() {
  local revisions_file="$1"
  local expected_revision="$2"
  local expected_image="$3"
  local expected_state="$4"
  local workload_kind="$5"

  [[ -f "$revisions_file" && ! -L "$revisions_file" ]] || guard_die "PITR $workload_kind revision snapshot is unavailable"
  [[ "$expected_revision" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$ ]] || guard_die "PITR expected $workload_kind revision is invalid"
  [[ "$expected_image" =~ @sha256:[0-9a-f]{64}$ ]] || guard_die "PITR expected $workload_kind image is not digest-pinned"
  [[ "$expected_state" == "running" || "$expected_state" == "frozen" ]] || guard_die "PITR expected revision state is invalid"
  [[ "$workload_kind" == "api" || "$workload_kind" == "worker" ]] || guard_die "PITR workload kind is invalid"
  jq -e --arg revision "$expected_revision" --arg image "$expected_image" --arg state "$expected_state" --arg kind "$workload_kind" '
    (.value | type == "array") and
    ([.value[] | select(.name == $revision and .properties.template.containers[0].image == $image)] | length) == 1 and
    if $state == "frozen" then
      ([.value[] | select(.properties.active == true)] | length) == 0 and
      ([.value[] | (.properties.replicas // 0)] | add // 0) == 0
    else
      ([.value[] | select(.properties.active == true)] | length) == 1 and
      ([.value[] | select(.name == $revision and .properties.active == true and
        (if $kind == "worker" then (.properties.replicas // 0) == 1 else (.properties.replicas // 0) >= 1 end))] | length) == 1
    end
  ' "$revisions_file" >/dev/null || guard_die "PITR $workload_kind revision set is not in the exact $expected_state state"
}

guard_find_terraform() {
  local runner_manifest="/var/lib/cosmas-deploy-runner/toolchain.json"
  local expected_hash
  local expected_version
  local actual_version

  if [[ -f "$runner_manifest" ]]; then
    [[ "$(id -u)" == "0" ]] || guard_die "protected-runner deployment wrappers must execute as root through Azure Run Command"
    guard_private_file "$runner_manifest" "protected-runner toolchain manifest"
    [[ "$(stat -c '%u' "$runner_manifest" 2>/dev/null)" == "0" ]] || guard_die "protected-runner toolchain manifest is not root-owned"
    [[ -x /usr/local/bin/tofu && ! -L /usr/local/bin/tofu ]] || guard_die "checksum-pinned protected-runner OpenTofu binary is missing"
    expected_hash="$(jq -er '.tofu_binary_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$runner_manifest")" || guard_die "protected-runner toolchain manifest has no valid OpenTofu binary hash"
    expected_version="$(jq -er '.tofu | strings | select(test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))' "$runner_manifest")" || guard_die "protected-runner toolchain manifest has no valid OpenTofu version"
    [[ "$(guard_sha256 /usr/local/bin/tofu)" == "$expected_hash" ]] || guard_die "protected-runner OpenTofu binary hash differs from the pinned toolchain manifest"
    actual_version="$(/usr/local/bin/tofu version -json | jq -er '.terraform_version')" || guard_die "cannot read protected-runner OpenTofu version"
    [[ "$actual_version" == "$expected_version" ]] || guard_die "protected-runner OpenTofu version differs from the pinned toolchain manifest"
    GUARD_TERRAFORM_BIN="/usr/local/bin/tofu"
  elif [[ -n "${COSMAS_TERRAFORM_BIN:-}" ]]; then
    [[ "$COSMAS_TERRAFORM_BIN" == /* && -x "$COSMAS_TERRAFORM_BIN" ]] || guard_die "COSMAS_TERRAFORM_BIN must identify an absolute executable"
    GUARD_TERRAFORM_BIN="$COSMAS_TERRAFORM_BIN"
  elif command -v tofu >/dev/null 2>&1; then
    GUARD_TERRAFORM_BIN="$(command -v tofu)"
  elif command -v terraform >/dev/null 2>&1; then
    GUARD_TERRAFORM_BIN="$(command -v terraform)"
  else
    guard_die "terraform or tofu is required"
  fi
}

guard_reject_terraform_overrides() {
  local module_dir="$1"
  local repository_root="${2:-}"
  local variable_name
  local implicit_file
  local config_file
  local relative_file

  while IFS='=' read -r variable_name _; do
    case "$variable_name" in
      TF_WORKSPACE|TF_CLI_ARGS|TF_CLI_ARGS_*|TF_VAR_*|TF_CLI_CONFIG_FILE|TF_LOG|TF_LOG_*|TF_REATTACH_PROVIDERS|TF_PLUGIN_CACHE_DIR|TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE)
        guard_die "environment override $variable_name is forbidden for guarded deployment"
        ;;
    esac
  done < <(env)

  for implicit_file in \
    "$module_dir/terraform.tfvars" \
    "$module_dir/terraform.tfvars.json" \
    "$module_dir"/*.auto.tfvars \
    "$module_dir"/*.auto.tfvars.json; do
    if [[ -e "$implicit_file" || -L "$implicit_file" ]]; then
      guard_die "implicit Terraform variable file is forbidden: $implicit_file"
    fi
  done

  if [[ -n "${HOME:-}" ]]; then
    for config_file in "$HOME/.terraformrc" "$HOME/.tofurc" "$HOME/.terraform.d/credentials.tfrc.json" "$HOME/.tofu.d/credentials.tfrc.json"; do
      [[ ! -e "$config_file" && ! -L "$config_file" ]] || guard_die "default Terraform/OpenTofu CLI configuration is forbidden during guarded deployment: $config_file"
    done
  fi

  while IFS= read -r config_file; do
    case "$(basename -- "$config_file")" in
      override.tf|override.tf.json|*_override.tf|*_override.tf.json)
        guard_die "Terraform override files are forbidden during guarded deployment: $config_file"
        ;;
    esac
    if [[ -n "$repository_root" ]]; then
      relative_file="${config_file#"$repository_root"/}"
      git -C "$repository_root" ls-files --error-unmatch -- "$relative_file" >/dev/null 2>&1 || guard_die "Terraform configuration is not committed in the reviewed source: $config_file"
    fi
  done < <(find "$module_dir" -path '*/.terraform' -prune -o \( -type f -o -type l \) \( -name '*.tf' -o -name '*.tf.json' \) -print)
}

guard_sha256() {
  local hash
  if command -v sha256sum >/dev/null 2>&1; then
    hash="$(sha256sum "$1")"
  elif command -v shasum >/dev/null 2>&1; then
    hash="$(shasum -a 256 "$1")"
  else
    guard_die "sha256sum or shasum is required"
  fi
  printf '%s\n' "${hash%% *}"
}

guard_sha256_stream() {
  local hash
  if command -v sha256sum >/dev/null 2>&1; then
    hash="$(sha256sum)"
  elif command -v shasum >/dev/null 2>&1; then
    hash="$(shasum -a 256)"
  else
    guard_die "sha256sum or shasum is required"
  fi
  printf '%s\n' "${hash%% *}"
}

guard_materialize_committed_file() {
  local repository_root="$1"
  local source_sha="$2"
  local repository_path="$3"
  local destination="$4"
  local expected_origin="$5"
  local actual_origin
  local status

  command -v git >/dev/null 2>&1 || guard_die "git is required to materialize committed deployment code"
  [[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || guard_die "deployment source SHA must be a full lowercase commit"
  actual_origin="$(git -C "$repository_root" remote get-url origin 2>/dev/null)" || guard_die "deployment repository has no origin"
  [[ "$actual_origin" == "$expected_origin" ]] || guard_die "deployment repository origin is not the exact reviewed upstream"
  [[ "$(git -C "$repository_root" rev-parse --verify HEAD 2>/dev/null)" == "$source_sha" ]] || guard_die "local HEAD does not match the approved deployment source SHA"
  status="$(git -C "$repository_root" status --porcelain=v1 --untracked-files=all)"
  [[ -z "$status" ]] || guard_die "deployment controller requires a completely clean checkout including untracked files"
  guard_new_private_path "$destination" "materialized deployment command"
  git -C "$repository_root" show "$source_sha:$repository_path" >"$destination" || {
    rm -f -- "$destination"
    guard_die "approved commit does not contain the protected runner command"
  }
  chmod 600 "$destination"
}

guard_source_metadata() {
  local repository_root="$1"
  local module_dir="${2:-$repository_root/infra/beta/environment}"
  local lock_file="$module_dir/.terraform.lock.hcl"
  local status

  command -v git >/dev/null 2>&1 || guard_die "git is required to bind a plan to reviewed source"
  guard_reject_terraform_overrides "$module_dir" "$repository_root"
  [[ -f "$lock_file" ]] || guard_die "provider lock file is missing for guarded module $module_dir"
  GUARD_SOURCE_SHA="$(git -C "$repository_root" rev-parse --verify HEAD 2>/dev/null)" || guard_die "repository HEAD cannot be resolved"
  [[ "$GUARD_SOURCE_SHA" =~ ^[0-9a-f]{40}$ ]] || guard_die "repository HEAD is not a full Git SHA"
  status="$(git -C "$repository_root" status --short --untracked-files=normal)"
  [[ -z "$status" ]] || guard_die "deployment plans require a clean, committed source checkout"
  GUARD_PROVIDER_LOCK_SHA256="$(guard_sha256 "$lock_file")"
  GUARD_TERRAFORM_VERSION="$("$GUARD_TERRAFORM_BIN" version -json | jq -er '.terraform_version')" || guard_die "cannot read Terraform/OpenTofu version"
}

guard_read_bootstrap_output() {
  jq -er --arg key "$1" '.[$key].value | strings | select(length > 0)' "$GUARD_BOOTSTRAP_OUTPUTS"
}

guard_load_bootstrap_outputs() {
  GUARD_BOOTSTRAP_OUTPUTS="$1"
  GUARD_SUBSCRIPTION_ID="$(guard_read_bootstrap_output subscription_id)"
  GUARD_TENANT_ID="$(guard_read_bootstrap_output tenant_id)"
  GUARD_STATE_RESOURCE_GROUP="$(guard_read_bootstrap_output backend_resource_group_name)"
  GUARD_STATE_STORAGE_ACCOUNT="$(guard_read_bootstrap_output backend_storage_account_name)"
  GUARD_STATE_CONTAINER="$(guard_read_bootstrap_output backend_container_name)"
  GUARD_STATE_KEY="$(guard_read_bootstrap_output backend_key)"
  GUARD_WORKLOAD_RESOURCE_GROUP="$(guard_read_bootstrap_output workload_resource_group_name)"
  GUARD_DEPLOY_CLIENT_ID="$(guard_read_bootstrap_output deploy_identity_client_id)"
  GUARD_DEPLOY_PRINCIPAL_ID="$(guard_read_bootstrap_output deploy_identity_principal_id)"
  GUARD_DEPLOYMENT_MODE="$(guard_read_bootstrap_output deployment_mode)"
  GUARD_DATA_CLASSIFICATION="$(guard_read_bootstrap_output data_classification)"
  GUARD_BOX_ID="$(guard_read_bootstrap_output box_id)"
  GUARD_STATE_VNET_ID="$(guard_read_bootstrap_output state_vnet_id)"
  GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID="$(guard_read_bootstrap_output state_blob_private_dns_zone_id)"
  GUARD_STATE_BLOB_PRIVATE_ENDPOINT_ID="$(guard_read_bootstrap_output state_blob_private_endpoint_id)"
  GUARD_STATE_PRIVATE_ENDPOINT_SUBNET_ID="$(guard_read_bootstrap_output state_private_endpoint_subnet_id)"
  GUARD_RUNNER_VM_NAME="$(guard_read_bootstrap_output runner_vm_name)"
  GUARD_RUNNER_IMAGE_VERSION="$(guard_read_bootstrap_output runner_image_version)"
  GUARD_RUNNER_VM_SIZE="$(guard_read_bootstrap_output runner_vm_size)"
  GUARD_RUNNER_SUBNET_ID="$(guard_read_bootstrap_output runner_subnet_id)"
  GUARD_RUNNER_NSG_ID="$(guard_read_bootstrap_output runner_network_security_group_id)"
  GUARD_RUNNER_NAT_GATEWAY_ID="$(guard_read_bootstrap_output runner_nat_gateway_id)"
  GUARD_RUNNER_EGRESS_PUBLIC_IP_ID="$(guard_read_bootstrap_output runner_egress_public_ip_id)"

  local uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
  local box_uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$'
  [[ "$GUARD_SUBSCRIPTION_ID" =~ $uuid_pattern ]] || guard_die "bootstrap subscription_id is not a UUID"
  [[ "$GUARD_TENANT_ID" =~ $uuid_pattern ]] || guard_die "bootstrap tenant_id is not a UUID"
  [[ "$GUARD_DEPLOY_CLIENT_ID" =~ $uuid_pattern ]] || guard_die "bootstrap deploy identity client ID is not a UUID"
  [[ "$GUARD_DEPLOY_PRINCIPAL_ID" =~ $uuid_pattern ]] || guard_die "bootstrap deploy identity principal ID is not a UUID"
  [[ "$GUARD_BOX_ID" =~ $box_uuid_pattern ]] || guard_die "bootstrap box_id is not an explicit RFC 4122 UUID"
  [[ "$GUARD_STATE_KEY" =~ ^early-adopter-beta/([a-z0-9][a-z0-9-]{1,8}[a-z0-9])/terraform\.tfstate$ ]] || guard_die "bootstrap backend key is outside the D3 beta prefix"
  GUARD_BETA_ID="${BASH_REMATCH[1]}"
  [[ "$GUARD_BETA_ID" != *--* ]] || guard_die "bootstrap beta_id contains consecutive hyphens"
  [[ "$GUARD_STATE_RESOURCE_GROUP" == "rg-cosmas-os-beta-state-$GUARD_BETA_ID" ]] || guard_die "backend resource group does not match the bootstrap beta_id"
  [[ "$GUARD_WORKLOAD_RESOURCE_GROUP" == "rg-cosmas-os-beta-$GUARD_BETA_ID" ]] || guard_die "workload resource group does not match the bootstrap beta_id"
  [[ "$GUARD_STATE_STORAGE_ACCOUNT" =~ ^[a-z0-9]{3,24}$ ]] || guard_die "backend storage account name is invalid"
  [[ "$GUARD_STATE_CONTAINER" == "tfstate" ]] || guard_die "backend container is not the dedicated tfstate container"
  [[ "$GUARD_DEPLOYMENT_MODE" == "synthetic_lab" || "$GUARD_DEPLOYMENT_MODE" == "authorized_beta" ]] || guard_die "bootstrap deployment_mode is invalid"
  local expected_classification="synthetic-only"
  if [[ "$GUARD_DEPLOYMENT_MODE" == "authorized_beta" ]]; then
    expected_classification="phi-authorized"
  fi
  [[ "$GUARD_DATA_CLASSIFICATION" == "$expected_classification" ]] || guard_die "bootstrap deployment mode and data classification do not match"
  GUARD_DEPLOY_IDENTITY_NAME="id-cosmas-os-beta-deploy-$GUARD_BETA_ID"
  [[ "$(guard_lower "$GUARD_STATE_VNET_ID")" == "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Network/virtualNetworks/vnet-cosmas-os-beta-state-$GUARD_BETA_ID")" ]] || guard_die "bootstrap state VNet ID is outside the D3 beta boundary"
  [[ "$(guard_lower "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID")" == "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Network/privateDnsZones/privatelink.blob.core.windows.net")" ]] || guard_die "bootstrap state Blob private DNS zone ID is outside the D3 beta boundary"
  [[ "$(guard_lower "$GUARD_STATE_BLOB_PRIVATE_ENDPOINT_ID")" == "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Network/privateEndpoints/pe-state-blob-$GUARD_BETA_ID")" ]] || guard_die "bootstrap state Blob private endpoint ID is outside the D3 beta boundary"
  [[ "$(guard_lower "$GUARD_STATE_PRIVATE_ENDPOINT_SUBNET_ID")" == "$(guard_lower "$GUARD_STATE_VNET_ID/subnets/snet-private-endpoints")" ]] || guard_die "bootstrap state private-endpoint subnet ID is outside the D3 beta boundary"
  [[ "$GUARD_RUNNER_VM_NAME" == "vm-cosmas-os-beta-runner-$GUARD_BETA_ID" ]] || guard_die "bootstrap runner VM name is outside the D3 beta boundary"
  [[ "$GUARD_RUNNER_IMAGE_VERSION" =~ ^[0-9]{2}\.[0-9]{2}\.[0-9]{8,}$ ]] || guard_die "bootstrap runner image version is not immutable and exact"
  [[ "$GUARD_RUNNER_VM_SIZE" == "Standard_B2s" ]] || guard_die "bootstrap runner VM size is not the reviewed Standard_B2s"
  [[ "$(guard_lower "$GUARD_RUNNER_SUBNET_ID")" == "$(guard_lower "$GUARD_STATE_VNET_ID/subnets/snet-deploy-runner")" ]] || guard_die "bootstrap runner subnet ID is outside the D3 beta boundary"
  [[ "$(guard_lower "$GUARD_RUNNER_NSG_ID")" == "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Network/networkSecurityGroups/nsg-cosmas-os-beta-runner-$GUARD_BETA_ID")" ]] || guard_die "bootstrap runner NSG ID is outside the D3 beta boundary"
  [[ "$(guard_lower "$GUARD_RUNNER_NAT_GATEWAY_ID")" == "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Network/natGateways/nat-cosmas-os-beta-runner-$GUARD_BETA_ID")" ]] || guard_die "bootstrap runner NAT gateway ID is outside the D3 beta boundary"
  [[ "$(guard_lower "$GUARD_RUNNER_EGRESS_PUBLIC_IP_ID")" == "$(guard_lower "/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Network/publicIPAddresses/pip-cosmas-os-beta-runner-egress-$GUARD_BETA_ID")" ]] || guard_die "bootstrap runner egress public IP ID is outside the D3 beta boundary"
}

guard_verify_resource_group() {
  local resource_group="$1"
  local group_json
  local expected_id

  group_json="$(az group show \
    --subscription "$GUARD_SUBSCRIPTION_ID" \
    --name "$resource_group" \
    --only-show-errors \
    --output json)" || guard_die "cannot read required resource group $resource_group"
  expected_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$resource_group"
  jq -e \
    --arg expected_id "$(guard_lower "$expected_id")" \
    --arg mode "$GUARD_DEPLOYMENT_MODE" \
    --arg classification "$GUARD_DATA_CLASSIFICATION" \
    --arg box "$GUARD_BOX_ID" '
      (.id | ascii_downcase) == $expected_id and
      .tags.track == "B" and
      .tags.product == "cosmas-os" and
      .tags.env == "early_adopter_beta" and
      .tags.deployment_mode == $mode and
      .tags.data_classification == $classification and
      .tags.box_scope == "dedicated" and
      .tags.box_id == $box and
      .tags.managed == "terraform"
    ' <<<"$group_json" >/dev/null || guard_die "resource group $resource_group is outside the exact D3 mode/Box boundary"
}

guard_verify_azure_context_and_boundary() {
  local account_json
  local identity_json
  local active_subscription_id
  local active_tenant_id
  local active_principal_type
  local access_token
  local token_payload
  local expected_identity_id

  account_json="$(az account show --only-show-errors --output json)" || guard_die "Azure account context is unavailable"
  active_subscription_id="$(jq -er '.id' <<<"$account_json")"
  active_tenant_id="$(jq -er '.tenantId' <<<"$account_json")"
  active_principal_type="$(jq -er '.user.type' <<<"$account_json")"
  [[ "$(guard_lower "$active_subscription_id")" == "$(guard_lower "$GUARD_SUBSCRIPTION_ID")" ]] || guard_die "active Azure subscription does not match bootstrap output"
  [[ "$(guard_lower "$active_tenant_id")" == "$(guard_lower "$GUARD_TENANT_ID")" ]] || guard_die "active Azure tenant does not match bootstrap output"
  [[ "$active_principal_type" == "servicePrincipal" ]] || guard_die "active Azure identity is not the dedicated deploy service principal"
  access_token="$(az account get-access-token --resource-type arm --query accessToken --output tsv --only-show-errors)" || guard_die "cannot obtain an ARM token for the active Azure identity"
  token_payload="$(jq -Rer 'split(".")[1] | gsub("-"; "+") | gsub("_"; "/") | @base64d | fromjson' <<<"$access_token")" || guard_die "active Azure ARM token is not a verifiable JWT"
  jq -e \
    --arg client_id "$(guard_lower "$GUARD_DEPLOY_CLIENT_ID")" \
    --arg principal_id "$(guard_lower "$GUARD_DEPLOY_PRINCIPAL_ID")" '
      ((.appid // .azp // "") | ascii_downcase) == $client_id and
      ((.oid // "") | ascii_downcase) == $principal_id
    ' <<<"$token_payload" >/dev/null || guard_die "active Azure ARM token is not issued to the exact dedicated D3 deploy identity"

  guard_verify_resource_group "$GUARD_STATE_RESOURCE_GROUP"
  guard_verify_resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP"

  identity_json="$(az identity show \
    --subscription "$GUARD_SUBSCRIPTION_ID" \
    --resource-group "$GUARD_STATE_RESOURCE_GROUP" \
    --name "$GUARD_DEPLOY_IDENTITY_NAME" \
    --only-show-errors \
    --output json)" || guard_die "cannot read the dedicated D3 deploy identity"
  expected_identity_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$GUARD_DEPLOY_IDENTITY_NAME"
  jq -e \
    --arg expected_id "$(guard_lower "$expected_identity_id")" \
    --arg client_id "$(guard_lower "$GUARD_DEPLOY_CLIENT_ID")" \
    --arg principal_id "$(guard_lower "$GUARD_DEPLOY_PRINCIPAL_ID")" '
      (.id | ascii_downcase) == $expected_id and
      (.clientId | ascii_downcase) == $client_id and
      (.principalId | ascii_downcase) == $principal_id
    ' <<<"$identity_json" >/dev/null || guard_die "the dedicated D3 deploy identity does not match bootstrap output"
}

guard_state_exists() {
  local result
  result="$(az storage blob exists \
    --auth-mode login \
    --account-name "$GUARD_STATE_STORAGE_ACCOUNT" \
    --container-name "$GUARD_STATE_CONTAINER" \
    --name "$GUARD_STATE_KEY" \
    --query exists \
    --output tsv \
    --only-show-errors)" || guard_die "remote-state existence check failed; verify private DNS, routing, and Blob data-plane access"
  [[ "$result" == "true" ]]
}

guard_validate_zero_length_unlocked_state_stub() {
  local blob_json_file="$1"

  jq -e '
    (.properties.contentLength | numbers) == 0 and
    ((.metadata // {}) | length) == 0 and
    ((.properties.lease.status // "") | ascii_downcase) == "unlocked" and
    ((.properties.lease.state // "") | ascii_downcase) == "available" and
    (.properties.etag | strings | length > 0)
  ' "$blob_json_file" >/dev/null || guard_die "remote state exists and is not an exact unlocked zero-byte planning stub"
  GUARD_STATE_STUB_ETAG="$(jq -er '.properties.etag' "$blob_json_file")"
}

guard_validate_first_state_history_file() {
  local history_file="$1"

  jq -e --arg key "$GUARD_STATE_KEY" '
    type == "array" and
    ([.[] | select(.name == $key)] | all(
      (.properties.contentLength | numbers) == 0 and
      ((.metadata // {}) | length) == 0
    ))
  ' "$history_file" >/dev/null || guard_die "remote state key has a non-empty or metadata-bearing current/deleted/versioned history and cannot be treated as new"
}

guard_verify_first_state_history() {
  local history_file

  history_file="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-state-history.XXXXXX")"
  if ! az storage blob list \
    --auth-mode login \
    --account-name "$GUARD_STATE_STORAGE_ACCOUNT" \
    --container-name "$GUARD_STATE_CONTAINER" \
    --prefix "$GUARD_STATE_KEY" \
    --include d m s v \
    --num-results '*' \
    --only-show-errors \
    --output json >"$history_file"; then
    rm -f -- "$history_file"
    guard_die "cannot enumerate current and historical versions of the first-state key"
  fi
  chmod 600 "$history_file"
  guard_validate_first_state_history_file "$history_file"
  rm -f -- "$history_file"
}

guard_remove_zero_length_unlocked_state_stub() {
  local blob_json
  local blob_json_file
  local etag

  blob_json="$(az storage blob show \
    --auth-mode login \
    --account-name "$GUARD_STATE_STORAGE_ACCOUNT" \
    --container-name "$GUARD_STATE_CONTAINER" \
    --name "$GUARD_STATE_KEY" \
    --only-show-errors \
    --output json)" || guard_die "cannot inspect the initial remote-state blob"
  blob_json_file="$(mktemp "${TMPDIR:-/tmp}/cosmas-d3-state-stub.XXXXXX")"
  printf '%s' "$blob_json" >"$blob_json_file"
  chmod 600 "$blob_json_file"
  guard_validate_zero_length_unlocked_state_stub "$blob_json_file"
  etag="$GUARD_STATE_STUB_ETAG"
  rm -f -- "$blob_json_file"
  az storage blob delete \
    --auth-mode login \
    --account-name "$GUARD_STATE_STORAGE_ACCOUNT" \
    --container-name "$GUARD_STATE_CONTAINER" \
    --name "$GUARD_STATE_KEY" \
    --if-match "$etag" \
    --only-show-errors \
    --output none || guard_die "zero-byte planning stub changed before guarded deletion"
  if guard_state_exists; then
    guard_die "zero-byte planning stub still exists after guarded deletion"
  fi
  return 0
}

guard_backend_init() {
  "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" init \
    -input=false \
    -lockfile=readonly \
    -reconfigure \
    -backend-config="resource_group_name=$GUARD_STATE_RESOURCE_GROUP" \
    -backend-config="storage_account_name=$GUARD_STATE_STORAGE_ACCOUNT" \
    -backend-config="container_name=$GUARD_STATE_CONTAINER" \
    -backend-config="key=$GUARD_STATE_KEY" \
    -backend-config="subscription_id=$GUARD_SUBSCRIPTION_ID" \
    -backend-config="tenant_id=$GUARD_TENANT_ID" \
    -backend-config="use_azuread_auth=true"
  [[ "$("$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" workspace show)" == "default" ]] || guard_die "guarded environment deployments require the default workspace"
}

guard_pull_state() {
  local destination="$1"
  "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" state pull >"$destination" || guard_die "cannot pull the exact D3 remote state"
  chmod 600 "$destination"
}

guard_validate_environment_state() {
  local state_file="$1"
  local validation_mode="${2:-complete}"
  local azure_id
  local lowered_id
  local subscription_prefix
  local resource_group

  if [[ "$validation_mode" == "partial_foundation" ]]; then
    jq -e \
      --arg box "$GUARD_BOX_ID" \
      --arg mode "$GUARD_DEPLOYMENT_MODE" \
      --arg classification "$GUARD_DATA_CLASSIFICATION" \
      --arg resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP" \
      --arg state_vnet_id "$GUARD_STATE_VNET_ID" \
      --arg state_blob_private_dns_zone_id "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" '
        (.lineage | strings | test("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")) and
        (.serial | numbers | floor == . and . >= 0) and
        ((.resources // []) | length > 0) and
        ((.outputs // {}) as $outputs |
          ((($outputs | has("box_id")) | not) or $outputs.box_id.value == $box) and
          ((($outputs | has("environment")) | not) or $outputs.environment.value == "early_adopter_beta") and
          ((($outputs | has("deployment_mode")) | not) or $outputs.deployment_mode.value == $mode) and
          ((($outputs | has("data_classification")) | not) or $outputs.data_classification.value == $classification) and
          ((($outputs | has("resource_group_name")) | not) or $outputs.resource_group_name.value == $resource_group) and
          ((($outputs | has("state_vnet_id")) | not) or $outputs.state_vnet_id.value == $state_vnet_id) and
          ((($outputs | has("state_blob_private_dns_zone_id")) | not) or $outputs.state_blob_private_dns_zone_id.value == $state_blob_private_dns_zone_id))
      ' "$state_file" >/dev/null || guard_die "partial remote state metadata or a present boundary output differs from the exact D3 foundation"
  else
    [[ "$validation_mode" == "complete" ]] || guard_die "unknown remote-state validation mode"
    jq -e \
      --arg box "$GUARD_BOX_ID" \
      --arg mode "$GUARD_DEPLOYMENT_MODE" \
      --arg classification "$GUARD_DATA_CLASSIFICATION" \
      --arg resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP" \
      --arg state_vnet_id "$GUARD_STATE_VNET_ID" \
      --arg state_blob_private_dns_zone_id "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" '
      (.lineage | strings | test("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")) and
      (.serial | numbers | floor == . and . >= 0) and
      .outputs.box_id.value == $box and
      .outputs.environment.value == "early_adopter_beta" and
      .outputs.deployment_mode.value == $mode and
      .outputs.data_classification.value == $classification and
      .outputs.resource_group_name.value == $resource_group and
      .outputs.state_vnet_id.value == $state_vnet_id and
      .outputs.state_blob_private_dns_zone_id.value == $state_blob_private_dns_zone_id
      ' "$state_file" >/dev/null || guard_die "remote state metadata/outputs do not match the exact D3 mode/Box boundary"
  fi

  subscription_prefix="/subscriptions/$(guard_lower "$GUARD_SUBSCRIPTION_ID")"
  while IFS= read -r azure_id; do
    lowered_id="$(guard_lower "$azure_id")"
    [[ "$lowered_id" == "$subscription_prefix"/* ]] || guard_die "remote state contains an Azure ID from another subscription"
    if [[ "$lowered_id" =~ /resourcegroups/([^/]+) ]]; then
      resource_group="${BASH_REMATCH[1]}"
      [[ "$resource_group" == "$(guard_lower "$GUARD_STATE_RESOURCE_GROUP")" || "$resource_group" == "$(guard_lower "$GUARD_WORKLOAD_RESOURCE_GROUP")" ]] || guard_die "remote state contains an Azure ID outside the dedicated D3 resource groups"
    fi
  done < <(jq -r '.. | strings | select(test("^/subscriptions/"; "i"))' "$state_file")

  GUARD_STATE_LINEAGE="$(jq -er '.lineage' "$state_file")"
  GUARD_STATE_SERIAL="$(jq -er '.serial' "$state_file")"
  GUARD_STATE_SHA256="$(guard_sha256 "$state_file")"
}

guard_validate_empty_environment_state() {
  local state_file="$1"

  jq -e '
    (.lineage | strings | test("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")) and
    (.serial | numbers | floor == . and . >= 0) and
    ((.resources // []) | length == 0) and
    ((.outputs // {}) | length == 0)
  ' "$state_file" >/dev/null || guard_die "initial remote state is not an empty Terraform state"

  GUARD_STATE_LINEAGE="$(jq -er '.lineage' "$state_file")"
  GUARD_STATE_SERIAL="$(jq -er '.serial' "$state_file")"
  GUARD_STATE_SHA256="$(guard_sha256 "$state_file")"
}

guard_validate_planned_boundary() {
  local plan_json="$1"

  jq -e \
    --arg box "$GUARD_BOX_ID" \
    --arg mode "$GUARD_DEPLOYMENT_MODE" \
    --arg classification "$GUARD_DATA_CLASSIFICATION" \
    --arg resource_group "$GUARD_WORKLOAD_RESOURCE_GROUP" \
    --arg state_vnet_id "$GUARD_STATE_VNET_ID" \
    --arg state_blob_private_dns_zone_id "$GUARD_STATE_BLOB_PRIVATE_DNS_ZONE_ID" '
      .planned_values.outputs.box_id.value == $box and
      .planned_values.outputs.environment.value == "early_adopter_beta" and
      .planned_values.outputs.deployment_mode.value == $mode and
      .planned_values.outputs.data_classification.value == $classification and
      .planned_values.outputs.resource_group_name.value == $resource_group and
      .planned_values.outputs.state_vnet_id.value == $state_vnet_id and
      .planned_values.outputs.state_blob_private_dns_zone_id.value == $state_blob_private_dns_zone_id
    ' "$plan_json" >/dev/null || guard_die "planned outputs do not match the exact D3 mode/Box boundary"

  # Compare placement and scale with resolved saved-plan inputs, never with
  # resource-group metadata or a live value being verified. Missing variables
  # retain the historical module defaults; explicit null/malformed values fail.
  jq -e '
    (if ((.variables // {}) | has("location")) then .variables.location.value else "centralus" end) as $location |
    (if ((.variables // {}) | has("api_max_replicas")) then .variables.api_max_replicas.value else 2 end) as $cap |
    ($location | type == "string" and test("^[a-z][a-z0-9]{2,31}$")) and
    ($cap | type == "number" and (. == 1 or . == 2)) and
    .planned_values.outputs.location.value == $location and
    .planned_values.outputs.api_max_replicas.value == $cap and
    ([.resource_changes[]? |
      select(.mode == "managed") |
      select(.type | IN(
        "azurerm_container_registry", "azurerm_storage_account", "azurerm_key_vault",
        "azurerm_postgresql_flexible_server", "azurerm_managed_redis", "azurerm_virtual_network",
        "azurerm_private_endpoint", "azurerm_user_assigned_identity",
        "azurerm_container_app_environment", "azurerm_container_app_job",
        "azurerm_log_analytics_workspace")) |
      .change.after.location == $location] | all) and
    ([.resource_changes[]? |
      select(.mode == "managed" and .type == "azurerm_container_app" and .name == "api") |
      .change.after.template[0].max_replicas == $cap] | all)
  ' "$plan_json" >/dev/null || guard_die "planned workload location or API replica cap differs from the reviewed inputs"
}

guard_validate_safe_plan_actions() {
  local plan_json="$1"
  local allow_noop="${2:-false}"

  if ! jq -e '
    [.resource_changes[]?
      | select(.mode == "managed")
      | .change.actions
      | select(
          . != ["no-op"] and
          . != ["create"] and
          . != ["update"]
        )]
    | length == 0
  ' "$plan_json" >/dev/null; then
    guard_die "plan contains delete, replacement, forget, or another unreviewed managed action"
  fi

  GUARD_CREATE_COUNT="$(jq '[.resource_changes[]? | select(.mode == "managed" and .change.actions == ["create"])] | length' "$plan_json")"
  GUARD_UPDATE_COUNT="$(jq '[.resource_changes[]? | select(.mode == "managed" and .change.actions == ["update"])] | length' "$plan_json")"
  GUARD_NOOP_COUNT="$(jq '[.resource_changes[]? | select(.mode == "managed" and .change.actions == ["no-op"])] | length' "$plan_json")"
  if [[ "$allow_noop" != "true" ]]; then
    (( GUARD_CREATE_COUNT + GUARD_UPDATE_COUNT > 0 )) || guard_die "plan contains no managed create or update to review"
  fi
}

# Emit only explicitly whitelisted, non-secret security and operability fields
# from every managed change. An unknown resource type fails closed so a newly
# introduced service cannot be approved from address/action counts alone.
guard_write_security_posture() {
  local plan_json="$1"
  local output_file="$2"

  jq '
    def projection($type; $value):
      if $value == null then null
      elif $type == "azurerm_resource_group" then
        {name: $value.name, location: $value.location, tags: $value.tags}
      elif $type == "azurerm_container_registry" then
        {name: $value.name, sku: $value.sku, admin_enabled: $value.admin_enabled,
         public_network_access_enabled: $value.public_network_access_enabled,
         network_rule_bypass_option: $value.network_rule_bypass_option,
         zone_redundancy_enabled: $value.zone_redundancy_enabled}
      elif $type == "azurerm_storage_account" then
        {name: $value.name, account_tier: $value.account_tier,
         account_replication_type: $value.account_replication_type,
         min_tls_version: $value.min_tls_version,
         public_network_access_enabled: $value.public_network_access_enabled,
         shared_access_key_enabled: $value.shared_access_key_enabled,
         default_to_oauth_authentication: $value.default_to_oauth_authentication,
         allow_nested_items_to_be_public: $value.allow_nested_items_to_be_public,
         infrastructure_encryption_enabled: $value.infrastructure_encryption_enabled,
         blob_properties: [($value.blob_properties // [])[] | {
           versioning_enabled,
           delete_retention_days: (.delete_retention_policy[0].days // null),
           container_delete_retention_days: (.container_delete_retention_policy[0].days // null)
         }]}
      elif $type == "azurerm_storage_container" then
        {name: $value.name, storage_account_id: $value.storage_account_id,
         container_access_type: $value.container_access_type}
      elif $type == "azurerm_key_vault" then
        {name: $value.name, rbac_authorization_enabled: $value.rbac_authorization_enabled,
         public_network_access_enabled: $value.public_network_access_enabled,
         purge_protection_enabled: $value.purge_protection_enabled,
         soft_delete_retention_days: $value.soft_delete_retention_days,
         enabled_for_deployment: $value.enabled_for_deployment,
         enabled_for_disk_encryption: $value.enabled_for_disk_encryption,
         enabled_for_template_deployment: $value.enabled_for_template_deployment,
         network_acls: [($value.network_acls // [])[] | {bypass, default_action}]}
      elif $type == "azurerm_key_vault_secret" then
        {name: $value.name, key_vault_id: $value.key_vault_id}
      elif $type == "azurerm_postgresql_flexible_server" then
        {name: $value.name, version: $value.version, sku_name: $value.sku_name,
         storage_mb: $value.storage_mb, delegated_subnet_id: $value.delegated_subnet_id,
         private_dns_zone_id: $value.private_dns_zone_id,
         public_network_access_enabled: $value.public_network_access_enabled,
         backup_retention_days: $value.backup_retention_days,
         geo_redundant_backup_enabled: $value.geo_redundant_backup_enabled,
         authentication: [($value.authentication // [])[] | {
           password_auth_enabled, active_directory_auth_enabled
         }]}
      elif $type == "azurerm_postgresql_flexible_server_database" then
        {name: $value.name, server_id: $value.server_id,
         charset: $value.charset, collation: $value.collation}
      elif $type == "azurerm_managed_redis" then
        {name: $value.name, sku_name: $value.sku_name,
         high_availability_enabled: $value.high_availability_enabled,
         public_network_access: $value.public_network_access,
         default_database: [($value.default_database // [])[] | {
           access_keys_authentication_enabled, client_protocol,
           clustering_policy, eviction_policy,
           persistence_append_only_file_backup_frequency
         }]}
      elif $type == "azurerm_virtual_network" then
        {name: $value.name, address_space: ($value.address_space // [] | sort)}
      elif $type == "azurerm_subnet" then
        {name: $value.name, address_prefixes: ($value.address_prefixes // [] | sort),
         default_outbound_access_enabled: $value.default_outbound_access_enabled,
         private_endpoint_network_policies: $value.private_endpoint_network_policies,
         service_endpoints: ($value.service_endpoints // [] | sort),
         delegation_services: [($value.delegation // [])[]?.service_delegation[]?.name] | sort}
      elif $type == "azurerm_network_security_group" then
        {name: $value.name,
         security_rule: [($value.security_rule // [])[] | {
           name, priority, direction, access, protocol,
           source_port_range, source_port_ranges,
           destination_port_range, destination_port_ranges,
           source_address_prefix, source_address_prefixes,
           destination_address_prefix, destination_address_prefixes
         }] | sort_by(.priority, .name)}
      elif $type == "azurerm_virtual_network_peering" then
        {name: $value.name, virtual_network_name: $value.virtual_network_name,
         remote_virtual_network_id: $value.remote_virtual_network_id,
         allow_virtual_network_access: $value.allow_virtual_network_access,
         allow_forwarded_traffic: $value.allow_forwarded_traffic,
         allow_gateway_transit: $value.allow_gateway_transit,
         use_remote_gateways: $value.use_remote_gateways}
      elif $type == "azurerm_private_dns_zone" then
        {name: $value.name, resource_group_name: $value.resource_group_name}
      elif $type == "azurerm_private_dns_zone_virtual_network_link" then
        {name: $value.name, private_dns_zone_name: $value.private_dns_zone_name,
         virtual_network_id: $value.virtual_network_id,
         registration_enabled: $value.registration_enabled}
      elif $type == "azurerm_private_endpoint" then
        {name: $value.name, subnet_id: $value.subnet_id,
         private_service_connection: [($value.private_service_connection // [])[] | {
           private_connection_resource_id, subresource_names,
           is_manual_connection
         }],
         private_dns_zone_ids: [($value.private_dns_zone_group // [])[]?.private_dns_zone_ids[]?] | sort}
      elif $type == "azurerm_role_assignment" then
        {scope: $value.scope, role_definition_name: $value.role_definition_name,
         skip_service_principal_aad_check: $value.skip_service_principal_aad_check}
      elif $type == "azurerm_user_assigned_identity" then
        {name: $value.name, resource_group_name: $value.resource_group_name}
      elif $type == "azurerm_container_app_environment" then
        {name: $value.name, infrastructure_subnet_id: $value.infrastructure_subnet_id,
         internal_load_balancer_enabled: $value.internal_load_balancer_enabled,
         log_analytics_workspace_id: $value.log_analytics_workspace_id}
      elif $type == "azurerm_container_app" then
        {name: $value.name, revision_mode: $value.revision_mode,
         identity: [($value.identity // [])[] | {type, identity_ids: (.identity_ids // [] | sort)}],
         registry: [($value.registry // [])[] | {server, identity}] | sort_by(.server),
         ingress: [($value.ingress // [])[] | {
           external_enabled, allow_insecure_connections, target_port, transport,
           traffic_weight: [(.traffic_weight // [])[] | {latest_revision, percentage}]
         }],
         template: [($value.template // [])[] | {
           min_replicas, max_replicas,
           containers: [(.container // [])[] | {
             name, image, cpu, memory, command, args,
             reviewed_environment: [(.env // [])[] |
               select(.name == "COSMAS_ENV" or .name == "DATA_MODE" or
                      .name == "AUTH_MODE" or .name == "SYNTH_SEED" or
                      .name == "BLOB_BACKEND" or .name == "SYNC_WORKER") |
               {name, value}] | sort_by(.name),
             startup_probe: (.startup_probe // []),
             readiness_probe: (.readiness_probe // []),
             liveness_probe: (.liveness_probe // [])
           }] | sort_by(.name)
         }]}
      elif $type == "azurerm_container_app_custom_domain" then
        {name: $value.name,
         container_app_id: $value.container_app_id,
         certificate_binding_type: $value.certificate_binding_type,
         container_app_environment_certificate_id: $value.container_app_environment_certificate_id}
      elif $type == "azurerm_container_app_job" then
        {name: $value.name, replica_timeout_in_seconds: $value.replica_timeout_in_seconds,
         replica_retry_limit: $value.replica_retry_limit,
         identity: [($value.identity // [])[] | {type, identity_ids: (.identity_ids // [] | sort)}],
         registry: [($value.registry // [])[] | {server, identity}] | sort_by(.server),
         secret_bindings: [($value.secret // [])[] | {
           name, identity, key_vault_secret_id,
           uses_inline_value: ((.value // null) != null)
         }] | sort_by(.name),
         manual_trigger_config: [($value.manual_trigger_config // [])[] | {parallelism, replica_completion_count}],
         template: [($value.template // [])[] | {
           containers: [(.container // [])[] | {
             name, image, cpu, memory, command, args,
             reviewed_environment: [(.env // [])[] |
               if (.name == "COSMAS_ENV" or .name == "DATA_MODE" or
                   .name == "AUTH_MODE" or .name == "SYNTH_SEED" or
                   .name == "BLOB_BACKEND" or .name == "SYNC_WORKER") then
                 {name, value, secret_name}
               else
                 {name, uses_secret: ((.secret_name // null) != null)}
               end] | sort_by(.name)
           }] | sort_by(.name)
         }]}
      elif $type == "azurerm_log_analytics_workspace" then
        {name: $value.name, sku: $value.sku, retention_in_days: $value.retention_in_days,
         daily_quota_gb: $value.daily_quota_gb}
      elif $type == "azurerm_monitor_action_group" then
        {name: $value.name, short_name: $value.short_name, enabled: $value.enabled,
         email_receiver: [($value.email_receiver // [])[] | {name, use_common_alert_schema}],
         email_receiver_count: (($value.email_receiver // []) | length)}
      elif $type == "azurerm_monitor_metric_alert" then
        {name: $value.name, scopes: ($value.scopes // [] | sort), enabled: $value.enabled,
         auto_mitigate: $value.auto_mitigate, frequency: $value.frequency,
         window_size: $value.window_size, severity: $value.severity,
         criteria: [($value.criteria // [])[] | {
           metric_namespace, metric_name, aggregation, operator, threshold,
           skip_metric_validation,
           dimensions: [(.dimension // [])[] | {name, operator, values: (.values // [] | sort)}]
         }], action_group_ids: [($value.action // [])[]?.action_group_id] | sort}
      elif $type == "azurerm_consumption_budget_subscription" then
        {name: $value.name, subscription_id: $value.subscription_id,
         amount: $value.amount, time_grain: $value.time_grain,
         time_period: [($value.time_period // [])[] | {start_date, end_date}],
         filter: [($value.filter // [])[] | {
           dimension: [(.dimension // [])[] | {name, operator, values: (.values // [] | sort)}]
         }],
         notification: [($value.notification // [])[] | {
           enabled, operator, threshold, threshold_type,
           contact_email_count: ((.contact_emails // []) | length),
           contact_group_count: ((.contact_groups // []) | length),
           contact_role_count: ((.contact_roles // []) | length)
         }] | sort_by(.threshold_type, .threshold)}
      elif $type == "azurerm_linux_virtual_machine" then
        {name: $value.name, size: $value.size, admin_username: $value.admin_username,
         disable_password_authentication: $value.disable_password_authentication,
         secure_boot_enabled: $value.secure_boot_enabled,
         vtpm_enabled: $value.vtpm_enabled,
         encryption_at_host_enabled: $value.encryption_at_host_enabled,
         network_interface_ids: ($value.network_interface_ids // [] | sort),
         identity: [($value.identity // [])[] | {type, identity_ids: (.identity_ids // [] | sort)}],
         source_image_reference: [($value.source_image_reference // [])[] | {publisher, offer, sku, version}],
         os_disk: [($value.os_disk // [])[] | {caching, storage_account_type, disk_size_gb}]}
      elif $type == "azurerm_network_interface" then
        {name: $value.name, enable_accelerated_networking: $value.enable_accelerated_networking,
         ip_forwarding_enabled: $value.ip_forwarding_enabled,
         ip_configuration: [($value.ip_configuration // [])[] | {
           name, subnet_id, private_ip_address_allocation,
           private_ip_address_version, public_ip_address_id
         }]}
      elif $type == "azurerm_public_ip" then
        {name: $value.name, sku: $value.sku, allocation_method: $value.allocation_method,
         ip_version: $value.ip_version, zones: ($value.zones // [] | sort)}
      elif $type == "azurerm_nat_gateway" then
        {name: $value.name, sku_name: $value.sku_name,
         idle_timeout_in_minutes: $value.idle_timeout_in_minutes,
         zones: ($value.zones // [] | sort)}
      elif $type == "azurerm_subnet_network_security_group_association" then
        {subnet_id: $value.subnet_id, network_security_group_id: $value.network_security_group_id}
      elif $type == "azurerm_subnet_nat_gateway_association" then
        {subnet_id: $value.subnet_id, nat_gateway_id: $value.nat_gateway_id}
      elif $type == "azurerm_nat_gateway_public_ip_association" then
        {nat_gateway_id: $value.nat_gateway_id, public_ip_address_id: $value.public_ip_address_id}
      elif $type == "random_string" then
        {length: $value.length, upper: $value.upper, lower: $value.lower,
         numeric: $value.numeric, special: $value.special}
      elif $type == "random_id" then
        {byte_length: $value.byte_length, keepers: $value.keepers}
      elif $type == "terraform_data" then
        {guard_resource: true}
      else
        error("managed resource type lacks a non-secret review projection: " + $type)
      end;

    [.resource_changes[]?
      | select(.mode == "managed")
      | {address, type, actions: .change.actions,
         before: projection(.type; .change.before),
         after: projection(.type; .change.after)}]
    | sort_by(.address)
  ' "$plan_json" >"$output_file" || guard_die "cannot generate strict non-secret security-posture review"
  chmod 600 "$output_file"
}

# Keep the human-reviewable, non-secret output summary identical across first,
# subsequent, reconciliation, and apply-time saved-plan verification. Sensitive
# custom-domain verification material is deliberately not projected.
guard_write_critical_planned_values() {
  local plan_json="$1"
  local output_file="$2"

  jq '{
    environment: .planned_values.outputs.environment.value,
    location: .planned_values.outputs.location.value,
    api_max_replicas: .planned_values.outputs.api_max_replicas.value,
    box_id: .planned_values.outputs.box_id.value,
    deployment_mode: .planned_values.outputs.deployment_mode.value,
    data_classification: .planned_values.outputs.data_classification.value,
    registry_network_posture: .planned_values.outputs.registry_network_posture.value,
    workloads_enabled: .planned_values.outputs.workloads_enabled.value,
    database_preparation_job_enabled: .planned_values.outputs.database_preparation_job_enabled.value,
    runtime_acceptance_job_enabled: .planned_values.outputs.runtime_acceptance_job_enabled.value,
    image_reference: (.planned_values.outputs.image_reference.value // null),
    web_image_reference: (.planned_values.outputs.web_image_reference.value // null),
    api_origin: (.planned_values.outputs.api_origin.value // null),
    web_origin: (.planned_values.outputs.web_origin.value // null),
    web_default_fqdn: (.planned_values.outputs.web_default_fqdn.value // null),
    web_custom_domain: (.planned_values.outputs.web_custom_domain.value // null),
    web_custom_domain_binding_enabled: .planned_values.outputs.web_custom_domain_binding_enabled.value,
    acr_login_server: (.planned_values.outputs.acr_login_server.value // null)
  }' "$plan_json" >"$output_file" || guard_die "cannot generate strict non-secret critical planned-value review"
  chmod 600 "$output_file"
}

guard_operation_returns_hashed_evidence() {
  local operation="$1"
  local artifact_kind="${2:-}"

  case "$operation" in
    probe-network|build-push|database-prepare|runtime-acceptance|domain-verification|alert-delivery|pitr-*|release-rollback|release-forward|inspect-stage|stage-generation|offboarding-acceptance|bootstrap-identity)
      return 0
      ;;
    retrieve)
      case "$artifact_kind" in
        network|build|database|runtime|domain|alert|pitr|recovery|offboarding|identity)
          return 0
          ;;
      esac
      ;;
  esac
  return 1
}

guard_validate_sanitized_evidence_hash() {
  local artifact_file="$1"
  local expected_hash
  local actual_hash

  expected_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$artifact_file")" || return 1
  actual_hash="$(jq -cS 'del(.evidence_payload_sha256)' "$artifact_file" | guard_sha256_stream)" || return 1
  [[ "$actual_hash" == "$expected_hash" ]] || return 1
  GUARD_EVIDENCE_PAYLOAD_SHA256="$expected_hash"
}

# Evidence emitted directly by a Python primitive uses Python's canonical JSON
# bytes without jq's trailing line feed. Keep this separate from the established
# shell-generated evidence contract above so the two conventions cannot be
# accepted interchangeably by accident.
guard_validate_python_sanitized_evidence_hash() {
  local artifact_file="$1"
  local expected_hash
  local actual_hash

  expected_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$artifact_file")" || return 1
  actual_hash="$(jq -cSj 'del(.evidence_payload_sha256)' "$artifact_file" | guard_sha256_stream)" || return 1
  [[ "$actual_hash" == "$expected_hash" ]] || return 1
  GUARD_EVIDENCE_PAYLOAD_SHA256="$expected_hash"
}

guard_validate_network_public_configuration() {
  local artifact_file="$1"
  local expected_source_sha="$2"
  local expected_release_id="$3"
  local expected_beta_id="$4"

  [[ "$expected_source_sha" =~ ^[0-9a-f]{40}$ ]] || guard_die "network evidence source SHA is invalid"
  [[ "$expected_release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || guard_die "network evidence release ID is invalid"
  [[ "$expected_beta_id" =~ ^[a-z0-9][a-z0-9-]{1,8}[a-z0-9]$ && "$expected_beta_id" != *--* ]] || guard_die "network evidence beta ID is invalid"

  jq -e \
    --arg source_sha "$expected_source_sha" \
    --arg release_id "$expected_release_id" \
    --arg beta_id "$expected_beta_id" '
      . as $artifact |
      .schema_version == 1 and
      .evidence_type == "protected-runner-live-network" and
      .source_sha == $source_sha and
      .release_id == $release_id and
      (.public_configuration | type == "object") and
      (.public_configuration | keys | sort) == ([
        "acr_login_server", "api_origin", "web_custom_domain",
        "web_custom_domain_binding_enabled", "web_default_fqdn", "web_origin"
      ] | sort) and
      (.public_configuration.api_origin | strings |
        startswith("https://ca-api-cosmas-beta-" + $beta_id + ".") and
        endswith(".azurecontainerapps.io") and
        test("^https://[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
      ) and
      (.public_configuration.web_default_fqdn | strings |
        startswith("ca-web-cosmas-beta-" + $beta_id + ".") and
        endswith(".azurecontainerapps.io") and
        test("^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
      ) and
      ((.public_configuration.api_origin |
        ltrimstr("https://ca-api-cosmas-beta-" + $beta_id + ".")) ==
       (.public_configuration.web_default_fqdn |
        ltrimstr("ca-web-cosmas-beta-" + $beta_id + "."))) and
      (.public_configuration.web_origin | strings |
        test("^https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")
      ) and
      (.public_configuration.web_custom_domain_binding_enabled | type == "boolean") and
      (if .public_configuration.web_custom_domain == null then
         .public_configuration.web_origin == ("https://" + .public_configuration.web_default_fqdn) and
         .public_configuration.web_custom_domain_binding_enabled == false
       else
         (.public_configuration.web_custom_domain | strings |
           test("^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")
         ) and
         .public_configuration.web_origin == ("https://" + .public_configuration.web_custom_domain)
       end) and
      (.public_configuration.acr_login_server | strings |
        test("^[a-z0-9]{5,50}\\.azurecr\\.io$")
      ) and
      ([.endpoints[]? | select(
        .kind == "acr" and
        .hostname == $artifact.public_configuration.acr_login_server and
        .port == 443
      )] | length) == 1
    ' "$artifact_file" >/dev/null || guard_die "network evidence public configuration is absent, malformed, or not bound to the requested source/release"
}

guard_validate_domain_verification_artifact() {
  local artifact_file="$1"
  local expected_source_sha="$2"
  local expected_release_id="$3"
  local expected_hash
  local actual_hash

  expected_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$artifact_file")" || guard_die "domain-verification evidence hash is invalid"
  actual_hash="$(jq -cS 'del(.evidence_payload_sha256)' "$artifact_file" | guard_sha256_stream)"
  [[ "$actual_hash" == "$expected_hash" ]] || guard_die "domain-verification evidence was modified"
  jq -e \
    --arg source_sha "$expected_source_sha" \
    --arg release_id "$expected_release_id" '
      type == "object" and
      (keys | sort) == ([
        "asuid_txt_record", "cname_record", "completed_at", "evidence_payload_sha256",
        "evidence_type", "public_dns_material_only", "release_id", "schema_version",
        "secrets_returned", "selected_hostname", "source_sha", "state"
      ] | sort) and
      .schema_version == 1 and .evidence_type == "protected-runner-domain-verification" and
      .source_sha == $source_sha and .release_id == $release_id and
      (.completed_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
      (.selected_hostname | strings | test("^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")) and
      (.selected_hostname != "app.cosmaneura.com" and
       .selected_hostname != "staging-app.cosmaneura.com" and
       .selected_hostname != "chat.cosmaneura.com" and
       .selected_hostname != "staging-chat.cosmaneura.com") and
      (.state | keys | sort) == (["lineage", "serial", "sha256"] | sort) and
      (.state.lineage | strings | test("^[0-9a-fA-F-]{36}$")) and
      (.state.serial | numbers | floor == . and . >= 0) and
      (.state.sha256 | strings | test("^[0-9a-f]{64}$")) and
      (.cname_record | keys | sort) == (["name", "target", "type"] | sort) and
      .cname_record.type == "CNAME" and .cname_record.name == .selected_hostname and
      (.cname_record.target | strings | test("^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")) and
      .cname_record.target != .selected_hostname and
      (.asuid_txt_record | keys | sort) == (["name", "type", "value"] | sort) and
      .asuid_txt_record.type == "TXT" and .asuid_txt_record.name == ("asuid." + .selected_hostname) and
      (.asuid_txt_record.value | strings | test("^[A-Za-z0-9._~=-]{8,512}$")) and
      .public_dns_material_only == true and .secrets_returned == false
    ' "$artifact_file" >/dev/null || guard_die "domain-verification evidence has an invalid or over-broad shape"
}

guard_lock_and_verify_acr_immutable_tag() {
  local registry_name="$1"
  local repository_name="$2"
  local immutable_tag="$3"
  local expected_digest="$4"
  local immutable_tag_json
  local immutable_digest_json

  [[ "$registry_name" =~ ^[a-z0-9]{5,50}$ ]] || guard_die "ACR name is invalid for immutable-tag locking"
  [[ "$repository_name" =~ ^[a-z0-9][a-z0-9._/-]{0,127}$ ]] || guard_die "ACR repository is invalid for immutable-tag locking"
  [[ "$immutable_tag" =~ ^git-[0-9a-f]{40}$ ]] || guard_die "ACR immutable source tag is invalid"
  [[ "$expected_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || guard_die "ACR expected digest is invalid"

  immutable_tag_json="$(az acr repository show \
    --name "$registry_name" \
    --image "$repository_name:$immutable_tag" \
    --only-show-errors \
    --output json)" || guard_die "cannot inspect the immutable ACR source tag"
  jq -e --arg digest "$expected_digest" '
    .digest == $digest and
    .changeableAttributes.readEnabled == true and
    .changeableAttributes.listEnabled == true and
    (.changeableAttributes.writeEnabled | type) == "boolean" and
    (.changeableAttributes.deleteEnabled | type) == "boolean"
  ' <<<"$immutable_tag_json" >/dev/null || guard_die "immutable ACR source tag metadata or digest is invalid"

  immutable_digest_json="$(az acr repository show \
    --name "$registry_name" \
    --image "$repository_name@$expected_digest" \
    --only-show-errors \
    --output json)" || guard_die "cannot inspect the immutable ACR manifest digest"
  jq -e --arg digest "$expected_digest" '
    .digest == $digest and
    .changeableAttributes.readEnabled == true and
    .changeableAttributes.listEnabled == true and
    (.changeableAttributes.writeEnabled | type) == "boolean" and
    (.changeableAttributes.deleteEnabled | type) == "boolean"
  ' <<<"$immutable_digest_json" >/dev/null || guard_die "immutable ACR manifest metadata or digest is invalid"

  if ! jq -e '.changeableAttributes.writeEnabled == false and .changeableAttributes.deleteEnabled == false' <<<"$immutable_digest_json" >/dev/null; then
    # This is the bounded recovery path for an interruption after a direct
    # source-tag push but before the lock. The caller has already pulled the
    # exact digest, checked its immutable provenance labels, and scanned it.
    az acr repository update \
      --name "$registry_name" \
      --image "$repository_name@$expected_digest" \
      --write-enabled false \
      --delete-enabled false \
      --only-show-errors \
      --output none || guard_die "cannot lock the exact immutable ACR manifest digest with the deploy identity"
  fi

  if ! jq -e '.changeableAttributes.writeEnabled == false and .changeableAttributes.deleteEnabled == false' <<<"$immutable_tag_json" >/dev/null; then
    az acr repository update \
      --name "$registry_name" \
      --image "$repository_name:$immutable_tag" \
      --write-enabled false \
      --delete-enabled false \
      --only-show-errors \
      --output none || guard_die "cannot lock the exact immutable ACR source tag with the deploy identity"
  fi

  immutable_digest_json="$(az acr repository show \
    --name "$registry_name" \
    --image "$repository_name@$expected_digest" \
    --only-show-errors \
    --output json)" || guard_die "cannot read back the locked immutable ACR manifest digest"
  immutable_tag_json="$(az acr repository show \
    --name "$registry_name" \
    --image "$repository_name:$immutable_tag" \
    --only-show-errors \
    --output json)" || guard_die "cannot read back the locked immutable ACR source tag"
  jq -e --arg digest "$expected_digest" '
    .digest == $digest and
    .changeableAttributes.readEnabled == true and
    .changeableAttributes.listEnabled == true and
    .changeableAttributes.writeEnabled == false and
    .changeableAttributes.deleteEnabled == false
  ' <<<"$immutable_tag_json" >/dev/null || guard_die "immutable ACR source tag is not digest-bound and locked"
  jq -e --arg digest "$expected_digest" '
    .digest == $digest and
    .changeableAttributes.readEnabled == true and
    .changeableAttributes.listEnabled == true and
    .changeableAttributes.writeEnabled == false and
    .changeableAttributes.deleteEnabled == false
  ' <<<"$immutable_digest_json" >/dev/null || guard_die "immutable ACR manifest digest is not write/delete locked"
}
