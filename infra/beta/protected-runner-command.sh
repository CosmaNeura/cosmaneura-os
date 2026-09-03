#!/usr/bin/env bash
set -euo pipefail

# This script is sent through Azure managed Run Command. Its final positional
# argument is a protected parameter; never call it through the ordinary
# `az vm run-command invoke --parameters` path.

umask 077

die() {
  printf 'D3 protected runner command refused: %s\n' "$1" >&2
  exit 1
}

[[ "$(id -u)" == "0" ]] || die "Azure Run Command must execute as root"
[[ $# -eq 0 ]] || die "named managed Run Command parameters must not be supplied positionally"

subscription_id="${COSMAS_SUBSCRIPTION_ID:-}"
deploy_client_id="${COSMAS_DEPLOY_CLIENT_ID:-}"
operation="${COSMAS_OPERATION:-}"
stage="${COSMAS_STAGE:-}"
release_id="${COSMAS_RELEASE_ID:-}"
source_sha="${COSMAS_SOURCE_SHA:-}"

uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
[[ "$subscription_id" =~ $uuid_pattern ]] || die "subscription ID is invalid"
[[ "$deploy_client_id" =~ $uuid_pattern ]] || die "deploy identity client ID is invalid"
[[ "$operation" == "stage-source" || "$operation" == "probe-network" || "$operation" == "build-push" || "$operation" == "stage-vars" || "$operation" == "plan" || "$operation" == "apply" || "$operation" == "database-prepare" || "$operation" == "runtime-acceptance" || "$operation" == "domain-verification" || "$operation" == "alert-delivery" || "$operation" == "pitr-freeze" || "$operation" == "pitr-manifest" || "$operation" == "pitr-start" || "$operation" == "pitr-complete" || "$operation" == "pitr-cleanup" || "$operation" == "pitr-resume" || "$operation" == "release-rollback" || "$operation" == "release-forward" || "$operation" == "offboarding-acceptance" || "$operation" == "bootstrap-identity" || "$operation" == "retrieve" ]] || die "operation is invalid"
[[ "$stage" == "source" || "$stage" == "network" || "$stage" == "images" || "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" || "$stage" == "acceptance" || "$stage" == "domain" || "$stage" == "alert" || "$stage" == "pitr" || "$stage" == "recovery" || "$stage" == "offboarding" || "$stage" == "identity" ]] || die "stage is invalid"
[[ "$release_id" =~ ^[a-z0-9][a-z0-9-]{2,31}$ ]] || die "release ID must be 3-32 lowercase letters, digits, or hyphens"
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || die "source SHA must be a full lowercase Git commit"
[[ "${COSMAS_PROTECTED_PAYLOAD_BASE64:-}" =~ ^[A-Za-z0-9+/=]*$ ]] || die "protected payload is not base64"
for docker_override in DOCKER_HOST DOCKER_CONTEXT DOCKER_CONFIG DOCKER_API_VERSION BUILDKIT_HOST DOCKER_BUILDKIT DOCKER_TLS DOCKER_TLS_VERIFY DOCKER_CERT_PATH; do
  [[ ! -v "$docker_override" ]] || die "inherited Docker routing/TLS override is forbidden: $docker_override"
done

runner_root="/var/lib/cosmas-deploy-runner"
bootstrap_outputs="$runner_root/bootstrap-outputs.json"
toolchain_manifest="$runner_root/toolchain.json"
repository_root="/opt/cosmas-os/releases/$source_sha"
release_root="$runner_root/releases/$release_id"
build_root="$runner_root/builds/$source_sha"
stage_root="$release_root/stages/$stage"
payload_file="$(mktemp /run/cosmas-protected-payload.XXXXXX)"
azure_config_dir=""
deploy_key_file=""
known_hosts_file=""
source_staging=""
docker_config_dir=""
build_probe_dir=""
runtime_env_file=""
runtime_manifest_file=""
private_result_file=""
curl_config_file=""
operation_temp_dir=""
probe_state=""
probe_outputs=""
probe_payload=""
network_pointer_tmp=""
network_evidence_tmp=""
build_evidence_tmp=""
database_evidence_tmp=""
database_pointer_tmp=""
runtime_acceptance_evidence_tmp=""
runtime_acceptance_pointer_tmp=""
alert_delivery_evidence_tmp=""
alert_delivery_pointer_tmp=""
domain_verification_evidence_tmp=""
identity_evidence_tmp=""
foundation_state=""
pitr_database_url_file=""

cleanup() {
  rm -f -- "$payload_file"
  [[ -z "$deploy_key_file" ]] || rm -f -- "$deploy_key_file"
  [[ -z "$known_hosts_file" ]] || rm -f -- "$known_hosts_file"
  [[ -z "$source_staging" || ! -d "$source_staging" ]] || rm -rf -- "$source_staging"
  [[ -z "$azure_config_dir" || ! -d "$azure_config_dir" ]] || rm -rf -- "$azure_config_dir"
  [[ -z "$docker_config_dir" || ! -d "$docker_config_dir" ]] || rm -rf -- "$docker_config_dir"
  [[ -z "$build_probe_dir" || ! -d "$build_probe_dir" ]] || rm -rf -- "$build_probe_dir"
  [[ -z "$runtime_env_file" ]] || rm -f -- "$runtime_env_file"
  [[ -z "$runtime_manifest_file" ]] || rm -f -- "$runtime_manifest_file"
  [[ -z "$private_result_file" ]] || rm -f -- "$private_result_file"
  [[ -z "$curl_config_file" ]] || rm -f -- "$curl_config_file"
  [[ -z "$operation_temp_dir" || ! -d "$operation_temp_dir" ]] || rm -rf -- "$operation_temp_dir"
  [[ -z "$probe_state" ]] || rm -f -- "$probe_state"
  [[ -z "$probe_outputs" ]] || rm -f -- "$probe_outputs"
  [[ -z "$probe_payload" ]] || rm -f -- "$probe_payload"
  [[ -z "$network_pointer_tmp" ]] || rm -f -- "$network_pointer_tmp"
  [[ -z "$network_evidence_tmp" ]] || rm -f -- "$network_evidence_tmp"
  [[ -z "$build_evidence_tmp" ]] || rm -f -- "$build_evidence_tmp"
  [[ -z "$database_evidence_tmp" ]] || rm -f -- "$database_evidence_tmp"
  [[ -z "$database_pointer_tmp" ]] || rm -f -- "$database_pointer_tmp"
  [[ -z "$runtime_acceptance_evidence_tmp" ]] || rm -f -- "$runtime_acceptance_evidence_tmp"
  [[ -z "$runtime_acceptance_pointer_tmp" ]] || rm -f -- "$runtime_acceptance_pointer_tmp"
  [[ -z "$alert_delivery_evidence_tmp" ]] || rm -f -- "$alert_delivery_evidence_tmp"
  [[ -z "$alert_delivery_pointer_tmp" ]] || rm -f -- "$alert_delivery_pointer_tmp"
  [[ -z "$domain_verification_evidence_tmp" ]] || rm -f -- "$domain_verification_evidence_tmp"
  [[ -z "$identity_evidence_tmp" ]] || rm -f -- "$identity_evidence_tmp"
  [[ -z "$foundation_state" ]] || rm -f -- "$foundation_state"
  [[ -z "$pitr_database_url_file" ]] || rm -f -- "$pitr_database_url_file"
}
trap cleanup EXIT

printf '%s' "${COSMAS_PROTECTED_PAYLOAD_BASE64:-}" | base64 --decode >"$payload_file" || die "protected payload could not be decoded"
unset COSMAS_SUBSCRIPTION_ID COSMAS_DEPLOY_CLIENT_ID COSMAS_OPERATION COSMAS_STAGE COSMAS_RELEASE_ID COSMAS_SOURCE_SHA COSMAS_PROTECTED_PAYLOAD_BASE64
chmod 0600 "$payload_file"
[[ -f "$bootstrap_outputs" && ! -L "$bootstrap_outputs" ]] || die "protected bootstrap outputs are missing"
[[ "$(stat -c '%a' "$bootstrap_outputs")" == "600" && "$(stat -c '%u' "$bootstrap_outputs")" == "0" ]] || die "protected bootstrap outputs are not root-owned mode 0600"
tenant_id="$(jq -er '.tenant_id.value | strings' "$bootstrap_outputs")" || die "bootstrap tenant ID is missing"
[[ "$(jq -er '.subscription_id.value | ascii_downcase' "$bootstrap_outputs")" == "${subscription_id,,}" ]] || die "subscription differs from protected bootstrap outputs"
[[ "$(jq -er '.deploy_identity_client_id.value | ascii_downcase' "$bootstrap_outputs")" == "${deploy_client_id,,}" ]] || die "deploy identity differs from protected bootstrap outputs"
[[ "$tenant_id" =~ $uuid_pattern ]] || die "bootstrap tenant ID is invalid"
command -v flock >/dev/null 2>&1 || die "flock is required to serialize protected deployment operations"
runner_lock="/var/lock/cosmas-d3-protected-runner.lock"
[[ ! -L "$runner_lock" ]] || die "protected runner lock path must not be a symlink"
exec 9>"$runner_lock"
chmod 0600 "$runner_lock"
flock -n 9 || die "another protected deployment operation is active"

validate_source() {
  [[ -d "$repository_root/.git" && ! -L "$repository_root" ]] || die "approved source has not been staged"
  [[ "$(stat -c '%u' "$repository_root")" == "0" ]] || die "staged source is not root-owned"
  [[ "$(git -C "$repository_root" rev-parse --verify HEAD)" == "$source_sha" ]] || die "staged source does not match the approved commit"
  [[ -z "$(git -C "$repository_root" status --porcelain=v1 --untracked-files=all)" ]] || die "staged source checkout is not clean"
  [[ "$(git -C "$repository_root" remote get-url origin)" == "ssh://git@ssh.github.com:443/CosmaNeura/cosmaneura-os.git" ]] || die "staged source origin is not the fixed CosmaNeura repository over SSH port 443"
  [[ "$(git -C "$repository_root" remote get-url --push origin)" == "DISABLED" ]] || die "staged source push URL is not disabled"
}

verify_pinned_toolchain() {
  local expected_version
  local expected_hash
  [[ -f "$toolchain_manifest" && ! -L "$toolchain_manifest" ]] || die "protected toolchain manifest is missing"
  [[ "$(stat -c '%a' "$toolchain_manifest")" == "600" && "$(stat -c '%u' "$toolchain_manifest")" == "0" ]] || die "protected toolchain manifest is not root-owned mode 0600"
  [[ -x /usr/local/bin/tofu && ! -L /usr/local/bin/tofu ]] || die "pinned OpenTofu binary is missing"
  expected_version="$(jq -er '.tofu | strings' "$toolchain_manifest")" || die "toolchain OpenTofu version is missing"
  expected_hash="$(jq -er '.tofu_binary_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$toolchain_manifest")" || die "toolchain OpenTofu hash is missing"
  [[ "$(sha256sum /usr/local/bin/tofu | awk '{print $1}')" == "$expected_hash" ]] || die "OpenTofu binary differs from the setup-time checksum"
  [[ "$(/usr/local/bin/tofu version -json | jq -er '.terraform_version')" == "$expected_version" ]] || die "OpenTofu version differs from the setup-time pin"
  [[ -x /usr/local/bin/trivy && ! -L /usr/local/bin/trivy ]] || die "pinned Trivy binary is missing"
  expected_hash="$(jq -er '.trivy_binary_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$toolchain_manifest")" || die "toolchain Trivy hash is missing"
  expected_version="$(jq -er '.trivy | strings | select(test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))' "$toolchain_manifest")" || die "toolchain Trivy version is missing"
  [[ "$(sha256sum /usr/local/bin/trivy | awk '{print $1}')" == "$expected_hash" ]] || die "Trivy binary differs from the setup-time checksum"
  [[ "$(/usr/local/bin/trivy --version | awk 'NR == 1 {print $2}')" == "$expected_version" ]] || die "Trivy version differs from the setup-time pin"
  [[ ! -e /root/.terraformrc && ! -e /root/.tofurc && ! -e /root/.terraform.d/credentials.tfrc.json && ! -e /root/.tofu.d/credentials.tfrc.json ]] || die "an unreviewed default Terraform/OpenTofu CLI configuration is present"
  while IFS='|' read -r package_name manifest_version_key binary_name manifest_hash_key; do
    expected_version="$(jq -er --arg key "$manifest_version_key" '.[$key] | strings' "$toolchain_manifest")" || die "toolchain package version is missing: $package_name"
    [[ "$(dpkg-query -W -f='${Version}' "$package_name")" == "$expected_version" ]] || die "installed package version differs from the setup-time pin: $package_name"
    expected_hash="$(jq -er --arg key "$manifest_hash_key" '.[$key] | strings | select(test("^[0-9a-f]{64}$"))' "$toolchain_manifest")" || die "toolchain binary hash is missing: $binary_name"
    [[ "$(sha256sum "$(command -v "$binary_name")" | awk '{print $1}')" == "$expected_hash" ]] || die "installed binary differs from the setup-time pin: $binary_name"
  done <<'TOOLS'
azure-cli|azure_cli_package_version|az|azure_cli_binary_sha256
docker.io|docker_package_version|docker|docker_binary_sha256
git|git_package_version|git|git_binary_sha256
jq|jq_package_version|jq|jq_binary_sha256
TOOLS
  [[ "$(jq -er '.docker_server_version' "$toolchain_manifest")" == "29.1.3" ]] || die "setup-time Docker server is not the reviewed 29.1.3 release"
  expected_hash="$(jq -er '.dockerd_binary_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$toolchain_manifest")" || die "toolchain Docker daemon hash is missing"
  [[ "$(sha256sum /usr/bin/dockerd | awk '{print $1}')" == "$expected_hash" ]] || die "Docker daemon binary differs from the setup-time pin"
  export DOCKER_HOST=unix:///var/run/docker.sock
  export DOCKER_BUILDKIT=1
  [[ "$(docker version --format '{{.Server.Version}}')" == "29.1.3" ]] || die "Docker server drifted from the reviewed 29.1.3 bundled frontend"
  [[ "$(jq -er '.docker_buildx_package_version' "$toolchain_manifest")" == "0.30.1-0ubuntu1~22.04.1" ]] || die "setup-time Docker Buildx package is not the reviewed Jammy release"
  [[ -x /usr/libexec/docker/cli-plugins/docker-buildx && ! -L /usr/libexec/docker/cli-plugins/docker-buildx ]] || die "pinned Docker Buildx plugin is missing"
  expected_hash="$(jq -er '.docker_buildx_binary_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$toolchain_manifest")" || die "toolchain Docker Buildx hash is missing"
  [[ "$(sha256sum /usr/libexec/docker/cli-plugins/docker-buildx | awk '{print $1}')" == "$expected_hash" ]] || die "Docker Buildx plugin differs from the setup-time checksum"
  [[ "$(docker buildx version)" == *"v0.30.1"* ]] || die "Docker Buildx plugin drifted from the reviewed 0.30.1 release"
}

fresh_managed_identity_login() {
  local identity_ready=false
  local variable_name

  while IFS='=' read -r variable_name _; do
    case "$variable_name" in
      TF_WORKSPACE|TF_CLI_ARGS|TF_CLI_ARGS_*|TF_VAR_*|TF_CLI_CONFIG_FILE|TF_LOG|TF_LOG_*|TF_REATTACH_PROVIDERS|TF_PLUGIN_CACHE_DIR|TF_PLUGIN_CACHE_MAY_BREAK_DEPENDENCY_LOCK_FILE|ARM_*|AZURE_CLIENT_ID|AZURE_CLIENT_SECRET|AZURE_TENANT_ID|AZURE_FEDERATED_TOKEN_FILE)
        unset "$variable_name"
        ;;
    esac
  done < <(env)
  azure_config_dir="$(mktemp -d /run/cosmas-azure-session.XXXXXX)"
  chmod 0700 "$azure_config_dir"
  export AZURE_CONFIG_DIR="$azure_config_dir"
  for _ in $(seq 1 60); do
    if az login --identity --client-id "$deploy_client_id" --allow-no-subscriptions --output none >/dev/null 2>&1 &&
      az account set --subscription "$subscription_id" >/dev/null 2>&1; then
      identity_ready=true
      break
    fi
    sleep 10
  done
  [[ "$identity_ready" == "true" ]] || die "attached deploy identity did not become usable within ten minutes"
  export ARM_USE_MSI=true
  export ARM_USE_AZUREAD=true
  export ARM_CLIENT_ID="$deploy_client_id"
  export ARM_SUBSCRIPTION_ID="$subscription_id"
  export ARM_TENANT_ID="$tenant_id"
  export COSMAS_TERRAFORM_BIN=/usr/local/bin/tofu
  export TF_IN_AUTOMATION=1
}

emit_sanitized_artifact() {
  local artifact="$1"
  local encoded
  jq -e 'type == "object" and .schema_version == 1' "$artifact" >/dev/null || die "wrapper did not produce a valid sanitized artifact"
  encoded="$(gzip -9 -c "$artifact" | base64 -w 0)"
  (( ${#encoded} <= 3000 )) || die "sanitized artifact exceeds the bounded Run Command return channel"
  printf 'COSMAS_SANITIZED_ARTIFACT_B64=%s\n' "$encoded"
}

bind_release_to_source() {
  install -d -o root -g root -m 0700 "$release_root"
  if [[ -e "$release_root/source-sha" ]]; then
    [[ "$(cat "$release_root/source-sha")" == "$source_sha" ]] || die "release ID is already bound to a different source commit"
  else
    printf '%s\n' "$source_sha" >"$release_root/source-sha"
    chmod 0600 "$release_root/source-sha"
  fi
}

current_network_evidence_file() {
  local pointer="$release_root/network-evidence.current"
  local generation

  [[ -f "$pointer" && ! -L "$pointer" ]] || die "current live runner-network evidence pointer is missing"
  [[ "$(stat -c '%a' "$pointer")" == "600" && "$(stat -c '%u' "$pointer")" == "0" ]] || die "live runner-network evidence pointer is not root-owned mode 0600"
  generation="$(cat "$pointer")"
  [[ "$generation" =~ ^[0-9a-f-]{36}-[0-9]+\.json$ ]] || die "live runner-network evidence pointer is invalid"
  printf '%s\n' "$release_root/network-evidence/$generation"
}

verify_release_network_evidence() {
  local evidence
  local expected_hash
  local actual_hash
  local expected_runner_id
  local expected_runner_subnet_id
  local expected_box_id
  local expected_deployment_mode

  evidence="$(current_network_evidence_file)"
  [[ -f "$evidence" && ! -L "$evidence" ]] || die "live runner-network evidence generation is missing for this release"
  [[ "$(stat -c '%a' "$evidence")" == "600" && "$(stat -c '%u' "$evidence")" == "0" ]] || die "live runner-network evidence is not root-owned mode 0600"
  expected_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$evidence")" || die "live runner-network evidence hash is invalid"
  actual_hash="$(jq -cS 'del(.evidence_payload_sha256)' "$evidence" | sha256sum | awk '{print $1}')"
  [[ "$actual_hash" == "$expected_hash" ]] || die "live runner-network evidence was modified after probing"
  expected_runner_id="/subscriptions/$subscription_id/resourceGroups/$(jq -er '.backend_resource_group_name.value' "$bootstrap_outputs")/providers/Microsoft.Compute/virtualMachines/$(jq -er '.runner_vm_name.value' "$bootstrap_outputs")"
  expected_runner_subnet_id="$(jq -er '.runner_subnet_id.value' "$bootstrap_outputs")"
  expected_box_id="$(jq -er '.box_id.value' "$bootstrap_outputs")"
  expected_deployment_mode="$(jq -er '.deployment_mode.value' "$bootstrap_outputs")"
  jq -e \
    --arg source_sha "$source_sha" \
    --arg release_id "$release_id" \
    --arg runner_id "${expected_runner_id,,}" \
    --arg runner_subnet_id "${expected_runner_subnet_id,,}" \
    --arg box_id "$expected_box_id" \
    --arg deployment_mode "$expected_deployment_mode" '
      .schema_version == 1 and
      .evidence_type == "protected-runner-live-network" and
      .source_sha == $source_sha and .release_id == $release_id and
      (.runner.resource_id | ascii_downcase) == $runner_id and
      (.runner.subnet_id | ascii_downcase) == $runner_subnet_id and
      .boundary.box_id == $box_id and .boundary.deployment_mode == $deployment_mode and
      (.state.lineage | strings | test("^[0-9a-fA-F-]{36}$")) and
      (.state.serial | numbers | floor == . and . >= 0) and
      (.state.sha256 | strings | test("^[0-9a-f]{64}$")) and
      ([.endpoints[].kind] | sort) == (["acr", "postgres", "key_vault", "managed_redis", "workload_blob", "state_blob"] | sort) and
      ([.endpoints[] | select(.kind != "acr") | select(
        .all_addresses_private != true or .tcp_reachable != true or
        .public_network_access_disabled != true or .resolved_address_count < 1 or .exact_resource_address_match != true or
        (.kind == "key_vault" and .trusted_services_bypass_disabled != true) or
        ((.kind == "postgres" and .port != 5432) or
         (.kind == "managed_redis" and .port != 10000) or
         ((.kind != "postgres" and .kind != "managed_redis") and .port != 443))
      )] | length) == 0 and
      ((.registry.posture == "private" and .registry.public_exception_reference_sha256 == null and
        ([.endpoints[] | select(.kind == "acr" and .port == 443 and .resolved_address_count >= 1 and .all_addresses_private == true and .tcp_reachable == true and .public_network_access_disabled == true and .exact_resource_address_match == true)] | length) == 1) or
       (.registry.posture == "synthetic_public_exception" and $deployment_mode == "synthetic_lab" and
        (.registry.public_exception_reference_sha256 | strings | test("^[0-9a-f]{64}$")) and
        ([.endpoints[] | select(.kind == "acr" and .port == 443 and .resolved_address_count >= 1 and .all_addresses_private == false and .tcp_reachable == true and .public_network_access_disabled == false and .exact_resource_address_match == true)] | length) == 1))
    ' "$evidence" >/dev/null || die "live runner-network evidence is not bound to this runner, Box, source, release, and private endpoint set"
  VERIFIED_NETWORK_EVIDENCE="$evidence"
}

verify_release_build_evidence() {
  local evidence="$build_root/build-evidence.json"
  local expected_hash
  local actual_hash
  local expected_box_id

  [[ -f "$evidence" && ! -L "$evidence" ]] || die "accepted image build evidence is missing for this immutable release"
  [[ "$(stat -c '%a' "$evidence")" == "600" && "$(stat -c '%u' "$evidence")" == "0" ]] || die "image build evidence is not root-owned mode 0600"
  expected_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$evidence")" || die "image build evidence hash is invalid"
  actual_hash="$(jq -cS 'del(.evidence_payload_sha256)' "$evidence" | sha256sum | awk '{print $1}')"
  [[ "$actual_hash" == "$expected_hash" ]] || die "image build evidence was modified after acceptance"
  expected_box_id="$(jq -er '.box_id.value' "$bootstrap_outputs")"
  jq -e \
    --arg source_sha "$source_sha" \
    --arg release_id "$release_id" \
    --arg box_id "$expected_box_id" '
      .schema_version == 1 and .evidence_type == "protected-runner-build-push" and
      .source_sha == $source_sha and .build_release_id == $release_id and .box_id == $box_id and
      (.registry.resource_id | strings | startswith("/subscriptions/")) and
      .registry.admin_user_enabled == false and
      .build_isolation.platform == "linux/amd64" and .build_isolation.network == "bridge" and
      .build_isolation.host_network_forbidden == true and
      .build_isolation.container_to_azure_platform_endpoints_blocked_and_probed == true and
      (.images.api.digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.images.web.digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      .images.api.tag_write_delete_locked == true and
      .images.api.manifest_write_delete_locked == true and
      .images.web.tag_write_delete_locked == true and
      .images.web.manifest_write_delete_locked == true and
      .images.api.high_critical_vulnerabilities == 0 and
      .images.web.high_critical_vulnerabilities == 0 and
      (.images.api.trivy_report_sha256 | strings | test("^[0-9a-f]{64}$")) and
      (.images.web.trivy_report_sha256 | strings | test("^[0-9a-f]{64}$"))
    ' "$evidence" >/dev/null || die "image build evidence is not bound to this source/release/Box with clean Trivy results"
}

probe_exact_private_endpoint() {
  local hostname="$1"
  local port="$2"
  local private_endpoint_id="$3"
  local service_resource_id="$4"
  local expected_subnet_id="$5"
  local addresses
  local endpoint_json
  local expected_addresses
  local nic_id
  local nic_json

  [[ "$hostname" =~ ^[A-Za-z0-9.-]+$ ]] || die "private endpoint hostname is invalid"
  endpoint_json="$(az network private-endpoint show --ids "$private_endpoint_id" --only-show-errors --output json)" || die "cannot read exact private endpoint: $private_endpoint_id"
  jq -e \
    --arg endpoint_id "${private_endpoint_id,,}" \
    --arg service_id "${service_resource_id,,}" \
    --arg subnet_id "${expected_subnet_id,,}" '
      (.id | ascii_downcase) == $endpoint_id and
      (.subnet.id | ascii_downcase) == $subnet_id and
      (.privateLinkServiceConnections | length) == 1 and
      (.privateLinkServiceConnections[0].privateLinkServiceId | ascii_downcase) == $service_id and
      .privateLinkServiceConnections[0].privateLinkServiceConnectionState.status == "Approved" and
      ([.networkInterfaces[]?.id] | length) >= 1
    ' <<<"$endpoint_json" >/dev/null || die "private endpoint does not target the exact resource/subnet with an approved connection"

  expected_addresses='[]'
  while IFS= read -r nic_id; do
    nic_json="$(az network nic show --ids "$nic_id" --only-show-errors --output json)" || die "cannot read a private-endpoint NIC"
    expected_addresses="$(jq -cn --argjson existing "$expected_addresses" --argjson nic "$nic_json" '$existing + [$nic.ipConfigurations[]?.privateIPAddress] | map(select(type == "string")) | unique')"
  done < <(jq -er '.networkInterfaces[].id' <<<"$endpoint_json")
  [[ "$(jq 'length' <<<"$expected_addresses")" -ge 1 ]] || die "private endpoint exposes no exact NIC private address"

  addresses="$(getent ahostsv4 "$hostname" 2>/dev/null | awk '{print $1}' | sort -u)"
  [[ -n "$addresses" ]] || die "private endpoint DNS did not resolve: $hostname"
  python3 - "$expected_addresses" $addresses <<'PY' || die "private DNS answers do not match the exact private-endpoint NIC: $hostname"
import ipaddress
import json
import sys

expected = set(json.loads(sys.argv[1]))
actual = set(sys.argv[2:])
for value in actual:
    address = ipaddress.ip_address(value)
    if (
        address.version != 4
        or not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or value not in expected
    ):
        raise SystemExit(1)
if not actual:
    raise SystemExit(1)
PY
  timeout 10 bash -c 'exec 3<>"/dev/tcp/$1/$2"' _ "$hostname" "$port" >/dev/null 2>&1 || die "private TCP probe failed: $hostname:$port"
  wc -w <<<"$addresses" | tr -d '[:space:]'
}

probe_exact_delegated_subnet() {
  local hostname="$1"
  local port="$2"
  local subnet_id="$3"
  local addresses
  local subnet_json
  local prefixes

  [[ "$hostname" =~ ^[A-Za-z0-9.-]+$ ]] || die "delegated-service hostname is invalid"
  subnet_json="$(az network vnet subnet show --ids "$subnet_id" --only-show-errors --output json)" || die "cannot read exact delegated subnet"
  jq -e --arg subnet_id "${subnet_id,,}" '
    (.id | ascii_downcase) == $subnet_id and
    ([.delegations[]?.serviceName] | index("Microsoft.DBforPostgreSQL/flexibleServers")) != null and
    ((.addressPrefixes // [ .addressPrefix ]) | map(select(type == "string")) | length) >= 1
  ' <<<"$subnet_json" >/dev/null || die "PostgreSQL subnet is not the exact reviewed delegated subnet"
  prefixes="$(jq -c '(.addressPrefixes // [ .addressPrefix ]) | map(select(type == "string"))' <<<"$subnet_json")"
  addresses="$(getent ahostsv4 "$hostname" 2>/dev/null | awk '{print $1}' | sort -u)"
  [[ -n "$addresses" ]] || die "delegated-service DNS did not resolve: $hostname"
  python3 - "$prefixes" $addresses <<'PY' || die "PostgreSQL DNS answers are outside the exact delegated subnet: $hostname"
import ipaddress
import json
import sys

networks = [ipaddress.ip_network(value) for value in json.loads(sys.argv[1])]
actual = [ipaddress.ip_address(value) for value in sys.argv[2:]]
if not actual:
    raise SystemExit(1)
for address in actual:
    if (
        address.version != 4
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not any(address in network for network in networks)
    ):
        raise SystemExit(1)
PY
  timeout 10 bash -c 'exec 3<>"/dev/tcp/$1/$2"' _ "$hostname" "$port" >/dev/null 2>&1 || die "delegated-service TCP probe failed: $hostname:$port"
  wc -w <<<"$addresses" | tr -d '[:space:]'
}

probe_public_endpoint() {
  local hostname="$1"
  local port="$2"
  local addresses

  [[ "$hostname" =~ ^[A-Za-z0-9.-]+$ ]] || die "public-exception endpoint hostname is invalid"
  addresses="$(getent ahostsv4 "$hostname" 2>/dev/null | awk '{print $1}' | sort -u)"
  [[ -n "$addresses" ]] || die "public-exception endpoint DNS did not resolve: $hostname"
  python3 - $addresses <<'PY' || die "public-exception endpoint unexpectedly resolved only to private addresses: $hostname"
import ipaddress
import sys

addresses = sys.argv[1:]
if not addresses or all(ipaddress.ip_address(value).is_private for value in addresses):
    raise SystemExit(1)
for value in addresses:
    address = ipaddress.ip_address(value)
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
        raise SystemExit(1)
PY
  timeout 10 bash -c 'exec 3<>"/dev/tcp/$1/$2"' _ "$hostname" "$port" >/dev/null 2>&1 || die "public-exception TCP probe failed: $hostname:$port"
  wc -w <<<"$addresses" | tr -d '[:space:]'
}

acr_tag_digest_or_absent() {
  local registry_name="$1"
  local repository="$2"
  local tag="$3"
  local repositories_json
  local tags_json
  local digest

  repositories_json="$(az acr repository list --name "$registry_name" --only-show-errors --output json)" || die "cannot enumerate ACR repositories before immutable-tag publication"
  if ! jq -e --arg repository "$repository" 'index($repository) != null' <<<"$repositories_json" >/dev/null; then
    printf '\n'
    return 0
  fi
  tags_json="$(az acr repository show-tags --name "$registry_name" --repository "$repository" --detail --only-show-errors --output json)" || die "cannot enumerate ACR tags before immutable-tag publication"
  [[ "$(jq --arg tag "$tag" '[.[] | select(.name == $tag)] | length' <<<"$tags_json")" -le 1 ]] || die "ACR returned duplicate immutable-tag metadata"
  digest="$(jq -r --arg tag "$tag" '[.[] | select(.name == $tag)][0].digest // ""' <<<"$tags_json")"
  [[ -z "$digest" || "$digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die "ACR returned an invalid digest for an immutable tag"
  printf '%s\n' "$digest"
}

ensure_docker_platform_isolation() {
  local isolation_log="$1"
  local blocked_platform_ip
  local platform_endpoint

  command -v iptables >/dev/null 2>&1 || die "iptables is required to isolate containers from Azure IMDS"
  for blocked_platform_ip in 169.254.169.254/32 168.63.129.16/32; do
    if ! iptables -C DOCKER-USER -d "$blocked_platform_ip" -j REJECT >/dev/null 2>&1; then
      iptables -I DOCKER-USER 1 -d "$blocked_platform_ip" -j REJECT || die "cannot install the container-to-Azure-platform deny rule"
    fi
    iptables -C DOCKER-USER -d "$blocked_platform_ip" -j REJECT >/dev/null 2>&1 || die "container-to-Azure-platform deny rule is not active"
  done
  docker pull python:3.13-slim@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00 >>"$isolation_log" 2>&1 || die "cannot pull the digest-pinned IMDS probe/base image"
  if docker run --rm --network bridge \
    python:3.13-slim@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00 \
    python -c 'import socket; socket.create_connection(("169.254.169.254", 80), 3)' >/dev/null 2>&1; then
    die "a container can reach Azure IMDS; refusing to expose the deploy UAMI"
  fi
  for platform_endpoint in 168.63.129.16:80 168.63.129.16:32526; do
    if docker run --rm --network bridge \
      python:3.13-slim@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00 \
      python -c 'import socket,sys; host,port=sys.argv[1].split(":"); socket.create_connection((host, int(port)), 3)' "$platform_endpoint" >/dev/null 2>&1; then
      die "a container can reach the Azure wire server; refusing to expose the deploy UAMI"
    fi
  done
  build_probe_dir="$(mktemp -d /run/cosmas-build-network-probe.XXXXXX)"
  chmod 0700 "$build_probe_dir"
  cat >"$build_probe_dir/Dockerfile" <<'PROBE'
FROM python:3.13-slim@sha256:cc9dffa47c8294ba9bb795a8dfaeb7b76f2b30acade2c52a461a2999d127eb00
RUN python -c 'import socket; endpoints=(("169.254.169.254",80),("168.63.129.16",80),("168.63.129.16",32526)); failures=[]; exec("for pair in endpoints:\n try:\n  connection=socket.create_connection(pair,3); connection.close(); failures.append(pair)\n except OSError:\n  pass"); raise SystemExit(1 if failures else 0)'
PROBE
  if ! docker buildx build --load --platform linux/amd64 --network bridge --no-cache --file "$build_probe_dir/Dockerfile" "$build_probe_dir" >>"$isolation_log" 2>&1; then
    die "the exact docker-build sandbox can reach Azure IMDS/WireServer, or the isolation probe failed"
  fi
  rm -rf -- "$build_probe_dir"
  build_probe_dir=""
}

prepare_pitr_context() {
  validate_source
  verify_pinned_toolchain
  bind_release_to_source
  verify_release_network_evidence
  PITR_NETWORK_EVIDENCE="$VERIFIED_NETWORK_EVIDENCE"
  verify_release_build_evidence
  fresh_managed_identity_login
  # shellcheck source=deployment-guard-lib.sh
  source "$repository_root/infra/beta/deployment-guard-lib.sh"
  GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
  guard_find_terraform
  guard_source_metadata "$repository_root"
  guard_load_bootstrap_outputs "$bootstrap_outputs"
  guard_verify_azure_context_and_boundary
  export TF_DATA_DIR="$release_root/pitr-terraform-data"
  guard_backend_init >/dev/null
  probe_state="$(mktemp /run/cosmas-pitr-state.XXXXXX)"
  guard_pull_state "$probe_state"
  guard_validate_environment_state "$probe_state"
  jq -e --slurpfile evidence "$PITR_NETWORK_EVIDENCE" '
    .lineage == $evidence[0].state.lineage and .serial == $evidence[0].state.serial
  ' "$probe_state" >/dev/null || die "re-probe the protected network after the workload state changed before PITR"
  [[ "$GUARD_STATE_SHA256" == "$(jq -er '.state.sha256' "$PITR_NETWORK_EVIDENCE")" ]] || die "PITR requires live network evidence for the exact current state"
  probe_outputs="$(mktemp /run/cosmas-pitr-outputs.XXXXXX)"
  "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
  chmod 0600 "$probe_outputs"
  PITR_API_DIGEST="$(jq -er '.images.api.digest' "$build_root/build-evidence.json")"
  PITR_WEB_DIGEST="$(jq -er '.images.web.digest' "$build_root/build-evidence.json")"
  PITR_REGISTRY="$(jq -er '.registry.login_server' "$build_root/build-evidence.json")"
  PITR_API_IMAGE="$PITR_REGISTRY/cosmas-os@$PITR_API_DIGEST"
  PITR_WEB_IMAGE="$PITR_REGISTRY/cosmas-os-web@$PITR_WEB_DIGEST"
  PITR_SOURCE_SERVER_ID="$(jq -er '.postgres_resource_id.value | strings' "$probe_outputs")"
  PITR_SOURCE_FQDN="$(jq -er '.postgres_private_fqdn.value | strings' "$probe_outputs")"
  PITR_POSTGRES_SUBNET_ID="$(jq -er '.postgres_subnet_id.value | strings' "$probe_outputs")"
  PITR_DNS_ZONE_ID="$(jq -er '.postgres_private_dns_zone_id.value | strings' "$probe_outputs")"
  PITR_LOCATION="$(jq -er '.location.value | strings | ascii_downcase' "$probe_outputs")"
  PITR_KEY_VAULT_URI="$(jq -er '.key_vault_uri.value | strings | select(startswith("https://"))' "$probe_outputs")"
  PITR_API_ID="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.App/containerApps/ca-api-cosmas-beta-$GUARD_BETA_ID"
  PITR_WORKER_ID="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.App/containerApps/ca-worker-cosmas-beta-$GUARD_BETA_ID"
  PITR_DATABASE_JOB_ID="$(jq -er '.database_preparation_job_resource_id.value | strings' "$probe_outputs")"
  PITR_ACCEPTANCE_JOB_ID="$(jq -er '.runtime_acceptance_job_resource_id.value | strings' "$probe_outputs")"
  PITR_ROOT="$release_root/executions/pitr"
  PITR_FREEZE_STATE="$PITR_ROOT/freeze-state.private.json"
  PITR_FREEZE_EVIDENCE="$PITR_ROOT/freeze-attestation.json"
  PITR_MANIFEST="$PITR_ROOT/manifest.private.json"
  PITR_STATE="$PITR_ROOT/state.private.json"
  PITR_SCRIPT="$repository_root/infra/beta/pitr_acceptance.py"
  jq -e \
    --arg api_image "$PITR_API_IMAGE" --arg web_image "$PITR_WEB_IMAGE" \
    --arg source_id "${PITR_SOURCE_SERVER_ID,,}" --arg subnet_id "${PITR_POSTGRES_SUBNET_ID,,}" \
    --arg dns_id "${PITR_DNS_ZONE_ID,,}" '
      .deployment_mode.value == "synthetic_lab" and .data_classification.value == "synthetic-only" and
      .runtime_data_mode.value == "synthetic" and .workloads_enabled.value == true and
      .runtime_acceptance_job_enabled.value == true and
      .image_reference.value == $api_image and .web_image_reference.value == $web_image and
      (.postgres_resource_id.value | ascii_downcase) == $source_id and
      (.postgres_subnet_id.value | ascii_downcase) == $subnet_id and
      (.postgres_private_dns_zone_id.value | ascii_downcase) == $dns_id
    ' "$probe_outputs" >/dev/null || die "PITR is restricted to the exact deployed synthetic workload and accepted immutable images"
  [[ -f "$PITR_SCRIPT" && ! -L "$PITR_SCRIPT" ]] || die "committed PITR acceptance primitive is unavailable"
  git -C "$repository_root" ls-files --error-unmatch infra/beta/pitr_acceptance.py >/dev/null 2>&1 || die "PITR primitive is not part of the approved commit"
  install -d -o root -g root -m 0700 "$PITR_ROOT" "$PITR_ROOT/evidence"
}

pitr_get_live_topology() {
  local target_dir="$1"
  local resource
  install -d -o root -g root -m 0700 "$target_dir"
  az rest --method get --url "https://management.azure.com${PITR_API_ID}?api-version=2024-03-01" --only-show-errors --output json >"$target_dir/api.json" || die "cannot read exact D3 API while guarding PITR"
  az rest --method get --url "https://management.azure.com${PITR_WORKER_ID}?api-version=2024-03-01" --only-show-errors --output json >"$target_dir/worker.json" || die "cannot read exact D3 worker while guarding PITR"
  az rest --method get --url "https://management.azure.com${PITR_API_ID}/revisions?api-version=2024-03-01" --only-show-errors --output json >"$target_dir/api-revisions.json" || die "cannot enumerate exact D3 API revisions"
  az rest --method get --url "https://management.azure.com${PITR_WORKER_ID}/revisions?api-version=2024-03-01" --only-show-errors --output json >"$target_dir/worker-revisions.json" || die "cannot enumerate exact D3 worker revisions"
  for resource in database acceptance; do
    if [[ "$resource" == "database" ]]; then
      job_id="$PITR_DATABASE_JOB_ID"
    else
      job_id="$PITR_ACCEPTANCE_JOB_ID"
    fi
    az rest --method get --url "https://management.azure.com${job_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$target_dir/$resource-job.json" || die "cannot read exact manual $resource job while guarding PITR"
    az rest --method get --url "https://management.azure.com${job_id}/executions?api-version=2023-11-02-preview" --only-show-errors --output json >"$target_dir/$resource-executions.json" || die "cannot enumerate exact manual $resource job executions while guarding PITR"
  done
  chmod 0600 "$target_dir"/*.json
  jq -e --arg id "${PITR_API_ID,,}" --arg image "$PITR_API_IMAGE" '
    (.id | ascii_downcase) == $id and .properties.configuration.activeRevisionsMode == "Single" and
    (.properties.template.containers | length) == 1 and .properties.template.containers[0].name == "api" and
    .properties.template.containers[0].image == $image
  ' "$target_dir/api.json" >/dev/null || die "live API differs from the exact single-revision immutable-image PITR boundary"
  jq -e --arg id "${PITR_WORKER_ID,,}" --arg image "$PITR_API_IMAGE" '
    (.id | ascii_downcase) == $id and .properties.configuration.activeRevisionsMode == "Single" and
    (.properties.template.containers | length) == 1 and .properties.template.containers[0].name == "worker" and
    .properties.template.containers[0].image == $image and
    .properties.template.scale.minReplicas == 1 and .properties.template.scale.maxReplicas == 1
  ' "$target_dir/worker.json" >/dev/null || die "live worker differs from the exact one-replica immutable-image PITR boundary"
  for resource in database acceptance; do
    jq -e '.properties.configuration.triggerType == "Manual"' "$target_dir/$resource-job.json" >/dev/null || die "a PITR-adjacent job is not manual-only"
    jq -e '[.value[]? | select((.properties.status // "") as $status | ($status == "Running" or $status == "Processing" or $status == "Starting" or $status == "Waiting" or $status == "Queued" or $status == "Pending"))] | length == 0' "$target_dir/$resource-executions.json" >/dev/null || die "a manual database/runtime job is active; PITR write freeze is not exclusive"
  done
}

pitr_validate_freeze_state() {
  local expected_hash
  [[ -f "$PITR_FREEZE_STATE" && ! -L "$PITR_FREEZE_STATE" && "$(stat -c '%a' "$PITR_FREEZE_STATE")" == "600" && "$(stat -c '%u' "$PITR_FREEZE_STATE")" == "0" ]] || die "PITR writer-freeze state is unavailable or unsafe"
  expected_hash="$(jq -er '.freeze_state_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$PITR_FREEZE_STATE")" || die "PITR writer-freeze state hash is invalid"
  [[ "$(jq -cS 'del(.freeze_state_sha256)' "$PITR_FREEZE_STATE" | sha256sum | awk '{print $1}')" == "$expected_hash" ]] || die "PITR writer-freeze state was modified"
  jq -e \
    --arg source_sha "$source_sha" --arg release_id "$release_id" --arg box_id "$GUARD_BOX_ID" \
    --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
    --arg api_id "${PITR_API_ID,,}" --arg worker_id "${PITR_WORKER_ID,,}" --arg api_image "$PITR_API_IMAGE" '
      .schema_version == 1 and .contract == "cosmas-os-d3-pitr-writer-freeze-state-v1" and
      .source_sha == $source_sha and .release_id == $release_id and .box_id == $box_id and
      .state == {lineage: $lineage, serial: $serial, sha256: $state_sha256} and
      (.writers.api.resource_id | ascii_downcase) == $api_id and
      (.writers.worker.resource_id | ascii_downcase) == $worker_id and
      .writers.api.image == $api_image and .writers.worker.image == $api_image and
      (.writers.api.revision | strings | test("^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$")) and
      (.writers.worker.revision | strings | test("^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$")) and
      (.freeze_requested_at | strings | test("Z$")) and (.quiet_window_end_utc | strings | test("Z$")) and
      ((.phase == "freezing" and .quiet_window_start_utc == null) or
       ((.phase == "frozen" or .phase == "resumed") and (.quiet_window_start_utc | strings | test("Z$"))))
    ' "$PITR_FREEZE_STATE" >/dev/null || die "PITR writer-freeze state is not bound to this exact source/release/state/workload"
}

pitr_set_freeze_phase() {
  local new_phase="$1"
  local changed_at_field="$2"
  local changed_at
  local temp_file
  [[ "$new_phase" == "frozen" || "$new_phase" == "resumed" ]] || die "invalid PITR writer-freeze phase transition"
  changed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  temp_file="$(mktemp "$PITR_ROOT/.freeze-state.XXXXXX")"
  jq -cS --arg phase "$new_phase" --arg field "$changed_at_field" --arg changed_at "$changed_at" '
    del(.freeze_state_sha256) | .phase = $phase | .[$field] = $changed_at |
    if $phase == "frozen" then .quiet_window_start_utc = $changed_at else . end
  ' "$PITR_FREEZE_STATE" >"$temp_file"
  freeze_hash="$(sha256sum "$temp_file" | awk '{print $1}')"
  jq -S --arg hash "$freeze_hash" '. + {freeze_state_sha256: $hash}' "$temp_file" >"$temp_file.complete"
  chmod 0600 "$temp_file.complete"
  mv -f -- "$temp_file.complete" "$PITR_FREEZE_STATE"
  rm -f -- "$temp_file"
  pitr_validate_freeze_state
}

pitr_assert_writers_frozen() {
  local target_dir="$1"
  local api_revision
  local worker_revision
  pitr_get_live_topology "$target_dir"
  api_revision="$(jq -er '.writers.api.revision' "$PITR_FREEZE_STATE")"
  worker_revision="$(jq -er '.writers.worker.revision' "$PITR_FREEZE_STATE")"
  guard_validate_pitr_revision_set "$target_dir/api-revisions.json" "$api_revision" "$PITR_API_IMAGE" frozen api
  guard_validate_pitr_revision_set "$target_dir/worker-revisions.json" "$worker_revision" "$PITR_API_IMAGE" frozen worker
}

pitr_resume_exact_writers() {
  local target_dir="$1"
  local api_revision
  local worker_revision
  local resumed=false
  api_revision="$(jq -er '.writers.api.revision' "$PITR_FREEZE_STATE")"
  worker_revision="$(jq -er '.writers.worker.revision' "$PITR_FREEZE_STATE")"
  pitr_get_live_topology "$target_dir/pre-resume"
  for app_contract in "api|$PITR_API_ID|$api_revision" "worker|$PITR_WORKER_ID|$worker_revision"; do
    IFS='|' read -r app_kind app_id revision_name <<<"$app_contract"
    jq -e --arg revision "$revision_name" '
      ([.value[] | select(.properties.active == true and .name != $revision)] | length) == 0 and
      ([.value[] | select(.name == $revision)] | length) == 1
    ' "$target_dir/pre-resume/$app_kind-revisions.json" >/dev/null || die "an unexpected $app_kind revision prevents exact PITR resume"
    if ! jq -e --arg revision "$revision_name" 'any(.value[]; .name == $revision and .properties.active == true)' "$target_dir/pre-resume/$app_kind-revisions.json" >/dev/null; then
      az rest --method post --url "https://management.azure.com${app_id}/revisions/${revision_name}/activate?api-version=2024-03-01" --body '{}' --only-show-errors --output none || die "cannot reactivate the exact frozen $app_kind revision"
    fi
  done
  for _ in $(seq 1 60); do
    pitr_get_live_topology "$target_dir/resume"
    if guard_validate_pitr_revision_set "$target_dir/resume/api-revisions.json" "$api_revision" "$PITR_API_IMAGE" running api >/dev/null 2>&1 &&
      guard_validate_pitr_revision_set "$target_dir/resume/worker-revisions.json" "$worker_revision" "$PITR_API_IMAGE" running worker >/dev/null 2>&1; then
      resumed=true
      break
    fi
    sleep 10
  done
  [[ "$resumed" == "true" ]] || die "exact frozen API/worker revisions did not become active with healthy replica counts"
  api_health_url="$(jq -er '.api_health_url.value | strings | select(startswith("https://"))' "$probe_outputs")" || die "exact API health URL is missing"
  curl --silent --show-error --fail --max-time 15 "$api_health_url" >/dev/null || die "reactivated exact API revision did not pass its public health check"
}

prepare_live_acceptance_context() {
  validate_source
  verify_pinned_toolchain
  bind_release_to_source
  verify_release_network_evidence
  LIVE_NETWORK_EVIDENCE="$VERIFIED_NETWORK_EVIDENCE"
  verify_release_build_evidence
  fresh_managed_identity_login
  # shellcheck source=deployment-guard-lib.sh
  source "$repository_root/infra/beta/deployment-guard-lib.sh"
  GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
  guard_find_terraform
  guard_source_metadata "$repository_root"
  guard_load_bootstrap_outputs "$bootstrap_outputs"
  guard_verify_azure_context_and_boundary
  export TF_DATA_DIR="$release_root/$stage-terraform-data"
  guard_backend_init >/dev/null
  probe_state="$(mktemp /run/cosmas-live-acceptance-state.XXXXXX)"
  guard_pull_state "$probe_state"
  guard_validate_environment_state "$probe_state"
  jq -e --slurpfile evidence "$LIVE_NETWORK_EVIDENCE" '
    .lineage == $evidence[0].state.lineage and .serial == $evidence[0].state.serial
  ' "$probe_state" >/dev/null || die "re-probe the protected network after the workload state changed"
  [[ "$GUARD_STATE_SHA256" == "$(jq -er '.state.sha256' "$LIVE_NETWORK_EVIDENCE")" ]] || die "live acceptance requires network evidence for the exact current state"
  probe_outputs="$(mktemp /run/cosmas-live-acceptance-outputs.XXXXXX)"
  "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
  chmod 0600 "$probe_outputs"
  LIVE_API_DIGEST="$(jq -er '.images.api.digest' "$build_root/build-evidence.json")"
  LIVE_WEB_DIGEST="$(jq -er '.images.web.digest' "$build_root/build-evidence.json")"
  LIVE_REGISTRY="$(jq -er '.registry.login_server' "$build_root/build-evidence.json")"
  LIVE_API_IMAGE="$LIVE_REGISTRY/cosmas-os@$LIVE_API_DIGEST"
  LIVE_WEB_IMAGE="$LIVE_REGISTRY/cosmas-os-web@$LIVE_WEB_DIGEST"
  jq -e --arg api_image "$LIVE_API_IMAGE" --arg web_image "$LIVE_WEB_IMAGE" '
    .deployment_mode.value == "synthetic_lab" and .data_classification.value == "synthetic-only" and
    .runtime_data_mode.value == "synthetic" and .workloads_enabled.value == true and
    .image_reference.value == $api_image and .web_image_reference.value == $web_image and
    (.runtime_identity_resource_id.value | strings | startswith("/subscriptions/")) and
    (.api_origin.value | strings | test("^https://[^/?#]+$")) and
    (.web_health_url.value | strings | test("^https://[^?#]+/healthz$"))
  ' "$probe_outputs" >/dev/null || die "live workload outputs differ from the exact synthetic immutable-image acceptance boundary"
}

recovery_no_drift_review() {
  local phase="$1"
  local recovery_root="$2"
  local plan_file="$recovery_root/$phase-no-drift.tfplan"
  local review_file="$recovery_root/$phase-no-drift-review.json"
  local log_file="$recovery_root/$phase-no-drift.private.log"
  local workload_vars="$release_root/stages/workloads/environment.tfvars.json"
  [[ "$phase" == "pre" || "$phase" == "forward" ]] || die "release-recovery no-drift phase is invalid"
  [[ -f "$workload_vars" && ! -L "$workload_vars" && "$(stat -c '%a' "$workload_vars")" == "600" && "$(stat -c '%u' "$workload_vars")" == "0" ]] || die "exact protected workload variables are unavailable for release recovery"
  jq -e --arg api "${LIVE_API_DIGEST#sha256:}" --arg web "${LIVE_WEB_DIGEST#sha256:}" '
    .deploy_workloads == true and .image_digest == $api and .web_image_digest == $web
  ' "$workload_vars" >/dev/null || die "workload variables do not declare the exact current release digests"
  if [[ ! -e "$review_file" && ! -L "$review_file" ]]; then
    [[ ! -e "$plan_file" && ! -L "$plan_file" ]] || die "orphaned release-recovery plan requires manual review"
    if ! bash "$repository_root/infra/beta/subsequent-environment-plan.sh" \
      --bootstrap-outputs "$bootstrap_outputs" \
      --var-file "$workload_vars" \
      --plan-out "$plan_file" \
      --review-out "$review_file" >"$log_file" 2>&1; then
      die "release-recovery no-drift plan failed; private diagnostics remain root-only on the runner"
    fi
    rm -f -- "$log_file" "$plan_file"
  fi
  [[ -f "$review_file" && ! -L "$review_file" && "$(stat -c '%a' "$review_file")" == "600" && "$(stat -c '%u' "$review_file")" == "0" ]] || die "release-recovery no-drift review is unavailable or unsafe"
  jq -e --arg source_sha "$source_sha" --arg api "$LIVE_API_IMAGE" --arg web "$LIVE_WEB_IMAGE" '
    .schema_version == 1 and .phase == "subsequent" and .source_sha == $source_sha and
    .critical_planned_values.workloads_enabled == true and
    .critical_planned_values.image_reference == $api and
    .critical_planned_values.web_image_reference == $web and
    ([.managed_actions[]? | select(.actions != ["no-op"])] | length) == 0
  ' "$review_file" >/dev/null || die "release recovery did not return the exact Terraform workload to zero drift"
  sha256sum "$review_file" | awk '{print $1}'
}

case "$operation" in
  stage-source)
    [[ "$stage" == "source" ]] || die "stage-source requires stage=source"
    for command_name in git ssh ssh-keygen jq base64; do
      command -v "$command_name" >/dev/null 2>&1 || die "$command_name is required"
    done
    jq -e '
      type == "object" and
      (.deploy_key_base64 | strings | test("^[A-Za-z0-9+/=]+$")) and
      (.known_hosts_base64 | strings | test("^[A-Za-z0-9+/=]+$")) and
      (keys | sort) == (["deploy_key_base64", "known_hosts_base64"] | sort)
    ' "$payload_file" >/dev/null || die "source payload has an invalid shape"
    deploy_key_file="$(mktemp /run/cosmas-github-deploy-key.XXXXXX)"
    known_hosts_file="$(mktemp /run/cosmas-github-known-hosts.XXXXXX)"
    jq -er '.deploy_key_base64' "$payload_file" | base64 --decode >"$deploy_key_file" || die "deploy key could not be decoded"
    jq -er '.known_hosts_base64' "$payload_file" | base64 --decode >"$known_hosts_file" || die "known-hosts data could not be decoded"
    chmod 0600 "$deploy_key_file" "$known_hosts_file"
    ssh-keygen -y -f "$deploy_key_file" >/dev/null 2>&1 || die "protected deploy key is not a valid private SSH key"
    [[ "$(grep -cve '^[[:space:]]*$' "$known_hosts_file")" == "1" ]] || die "known-hosts file must contain exactly one reviewed key"
    grep -Eq '^\[ssh\.github\.com\]:443[[:space:]]+ssh-ed25519[[:space:]]+[A-Za-z0-9+/=]+([[:space:]]|$)' "$known_hosts_file" || die "known-hosts entry must pin GitHub SSH on port 443 with Ed25519"
    if [[ -e "$repository_root" || -L "$repository_root" ]]; then
      validate_source
      printf '%s\n' "D3 protected runner already has the exact clean approved source"
      exit 0
    fi
    install -d -o root -g root -m 0700 /opt/cosmas-os /opt/cosmas-os/releases
    source_staging="$(mktemp -d /opt/cosmas-os/source.XXXXXX)"
    chmod 0700 "$source_staging"
    git -C "$source_staging" init --quiet
    git -C "$source_staging" remote add origin ssh://git@ssh.github.com:443/CosmaNeura/cosmaneura-os.git
    GIT_SSH_COMMAND="ssh -i $deploy_key_file -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$known_hosts_file -p 443" \
      git -C "$source_staging" fetch --quiet --depth=1 origin "$source_sha"
    git -C "$source_staging" checkout --quiet --detach "$source_sha"
    [[ "$(git -C "$source_staging" rev-parse --verify HEAD)" == "$source_sha" ]] || die "GitHub did not return the approved source commit"
    git -C "$source_staging" remote set-url --push origin DISABLED
    [[ -z "$(git -C "$source_staging" status --porcelain=v1 --untracked-files=all)" ]] || die "new source checkout is not clean"
    mv -- "$source_staging" "$repository_root"
    source_staging=""
    validate_source
    printf '%s\n' "D3 protected runner staged the exact approved source over ssh.github.com:443 and removed its private deploy key"
    ;;
  stage-vars)
    [[ "$stage" != "source" ]] || die "stage-vars requires an environment stage"
    validate_source
    bind_release_to_source
    jq -e 'type == "object"' "$payload_file" >/dev/null || die "environment tfvars payload must be a JSON object"
    case "$stage" in
      database)
        verify_release_network_evidence
        verify_release_build_evidence
        expected_network_reference="runner-network:sha256:$(jq -er '.evidence_payload_sha256' "$VERIFIED_NETWORK_EVIDENCE")"
        expected_api_digest="$(jq -er '.images.api.digest | sub("^sha256:"; "")' "$build_root/build-evidence.json")"
        jq -e '
          .enable_database_preparation_job == true and .deploy_workloads == false and
          (.database_preparation_image_digest | strings | test("^[0-9a-f]{64}$")) and
          (.runtime_database_url | strings | startswith("postgresql+psycopg://"))
        ' "$payload_file" >/dev/null || die "database stage must enable only the preparation job with an immutable image and runtime database URL"
        jq -e --arg expected "$expected_network_reference" '.runner_live_network_evidence_reference == $expected' "$payload_file" >/dev/null || die "database tfvars do not bind the live runner-network evidence from this release"
        jq -e --arg expected "$expected_api_digest" '.database_preparation_image_digest == $expected' "$payload_file" >/dev/null || die "database tfvars do not bind the accepted API image digest from this release"
        ;;
      workloads)
        verify_release_network_evidence
        verify_release_build_evidence
        expected_network_reference="runner-network:sha256:$(jq -er '.evidence_payload_sha256' "$VERIFIED_NETWORK_EVIDENCE")"
        expected_api_digest="$(jq -er '.images.api.digest | sub("^sha256:"; "")' "$build_root/build-evidence.json")"
        expected_web_digest="$(jq -er '.images.web.digest | sub("^sha256:"; "")' "$build_root/build-evidence.json")"
        jq -e '
          .enable_database_preparation_job == true and .deploy_workloads == true and
          (.image_digest | strings | test("^[0-9a-f]{64}$")) and
          (.web_image_digest | strings | test("^[0-9a-f]{64}$")) and
          (.database_preparation_attestation | type == "object")
        ' "$payload_file" >/dev/null || die "workload stage must retain database preparation and provide immutable images plus structured attestation"
        jq -e --arg expected "$expected_network_reference" '.runner_live_network_evidence_reference == $expected' "$payload_file" >/dev/null || die "workload tfvars do not bind the live runner-network evidence from this release"
        jq -e --arg api "$expected_api_digest" --arg web "$expected_web_digest" '.image_digest == $api and .web_image_digest == $web' "$payload_file" >/dev/null || die "workload tfvars do not bind both accepted image digests from this release"
        database_execution_id="$(jq -er '.database_preparation_attestation.execution_id | strings' "$payload_file")"
        database_execution_name="${database_execution_id##*/}"
        [[ "$database_execution_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$ ]] || die "workload database-preparation execution ID is invalid"
        database_attestation_file="$release_root/executions/database/$database_execution_name/attestation.json"
        [[ -f "$database_attestation_file" && ! -L "$database_attestation_file" && "$(stat -c '%a' "$database_attestation_file")" == "600" && "$(stat -c '%u' "$database_attestation_file")" == "0" ]] || die "workload stage has no protected attestation for the exact database execution"
        database_attestation_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$database_attestation_file")" || die "stored database attestation hash is invalid"
        [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$database_attestation_file" | sha256sum | awk '{print $1}')" == "$database_attestation_hash" ]] || die "stored database attestation was modified"
        jq -e \
          --arg source_sha "$source_sha" \
          --arg release_id "$release_id" \
          --arg lineage "$(jq -er '.state.lineage' "$VERIFIED_NETWORK_EVIDENCE")" \
          --argjson serial "$(jq -er '.state.serial' "$VERIFIED_NETWORK_EVIDENCE")" \
          --arg api "$expected_api_digest" \
          --slurpfile staged "$payload_file" '
            .schema_version == 1 and .evidence_type == "protected-runner-database-preparation" and
            .source_sha == $source_sha and .release_id == $release_id and
            .state.lineage == $lineage and .state.serial == $serial and
            .database_preparation_attestation == $staged[0].database_preparation_attestation and
            .database_preparation_attestation.image_digest == $api
          ' "$database_attestation_file" >/dev/null || die "workload database attestation is not bound to this source/release/state/image"
        ;;
    esac
    install -d -o root -g root -m 0700 "$stage_root"
    [[ ! -e "$stage_root/environment.tfvars.json" && ! -L "$stage_root/environment.tfvars.json" ]] || die "stage variable file already exists; do not overwrite a reviewed stage"
    install -o root -g root -m 0600 "$payload_file" "$stage_root/environment.tfvars.json"
    printf '%s\n' "D3 protected runner stored the private $stage tfvars without returning their contents"
    ;;
  probe-network)
    [[ "$stage" == "network" ]] || die "probe-network requires stage=network"
    validate_source
    verify_pinned_toolchain
    bind_release_to_source
    fresh_managed_identity_login
    # shellcheck source=deployment-guard-lib.sh
    source "$repository_root/infra/beta/deployment-guard-lib.sh"
    GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
    guard_find_terraform
    guard_source_metadata "$repository_root"
    guard_load_bootstrap_outputs "$bootstrap_outputs"
    guard_verify_azure_context_and_boundary
    guard_state_exists || die "environment state does not exist; apply the foundation before the live network probe"
    export TF_DATA_DIR="$release_root/network-terraform-data"
    guard_backend_init >/dev/null
    probe_state="$(mktemp /run/cosmas-network-state.XXXXXX)"
    guard_pull_state "$probe_state"
    guard_validate_environment_state "$probe_state"
    network_generation="${GUARD_STATE_LINEAGE,,}-${GUARD_STATE_SERIAL}.json"
    network_evidence_dir="$release_root/network-evidence"
    network_evidence_file="$network_evidence_dir/$network_generation"
    install -d -o root -g root -m 0700 "$network_evidence_dir"
    [[ ! -e "$network_evidence_file" && ! -L "$network_evidence_file" ]] || die "live network evidence already exists for this exact state generation"
    probe_outputs="$(mktemp /run/cosmas-network-outputs.XXXXXX)"
    "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
    chmod 0600 "$probe_outputs"

    acr_host="$(jq -er '.acr_login_server.value | strings' "$probe_outputs")"
    registry_posture="$(jq -er '.registry_network_posture.value | strings' "$probe_outputs")"
    registry_exception_hash="$(jq -r '.registry_public_exception_reference_sha256.value // ""' "$probe_outputs")"
    postgres_host="$(jq -er '.postgres_private_fqdn.value | strings' "$probe_outputs")"
    redis_host="$(jq -er '.redis_private_hostname.value | strings' "$probe_outputs")"
    key_vault_host="$(jq -er '.key_vault_uri.value | strings' "$probe_outputs")"
    key_vault_host="${key_vault_host#https://}"
    key_vault_host="${key_vault_host%%/*}"
    blob_host="$(jq -er '.blob_account_url.value | strings' "$probe_outputs")"
    blob_host="${blob_host#https://}"
    blob_host="${blob_host%%/*}"
    state_blob_host="${GUARD_STATE_STORAGE_ACCOUNT}.blob.core.windows.net"
    acr_id="$(jq -er '.acr_resource_id.value | strings' "$probe_outputs")"
    postgres_id="$(jq -er '.postgres_resource_id.value | strings' "$probe_outputs")"
    redis_id="$(jq -er '.redis_resource_id.value | strings' "$probe_outputs")"
    key_vault_id="$(jq -er '.key_vault_resource_id.value | strings' "$probe_outputs")"
    blob_id="$(jq -er '.blob_storage_account_id.value | strings' "$probe_outputs")"
    private_endpoint_subnet_id="$(jq -er '.private_endpoint_subnet_id.value | strings' "$probe_outputs")"
    postgres_subnet_id="$(jq -er '.postgres_subnet_id.value | strings' "$probe_outputs")"
    acr_private_endpoint_id="$(jq -r '.acr_private_endpoint_id.value // ""' "$probe_outputs")"
    key_vault_private_endpoint_id="$(jq -er '.key_vault_private_endpoint_id.value | strings' "$probe_outputs")"
    redis_private_endpoint_id="$(jq -er '.redis_private_endpoint_id.value | strings' "$probe_outputs")"
    blob_private_endpoint_id="$(jq -er '.blob_private_endpoint_id.value | strings' "$probe_outputs")"
    workload_prefix="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/"
    for resource_id in "$acr_id" "$postgres_id" "$redis_id" "$key_vault_id" "$blob_id"; do
      [[ "${resource_id,,}" == "${workload_prefix,,}"* ]] || die "network probe resource ID is outside the exact workload resource group"
    done
    [[ "${private_endpoint_subnet_id,,}" == "${workload_prefix,,}microsoft.network/virtualnetworks/"*"/subnets/snet-private-endpoints" ]] || die "workload private-endpoint subnet output is outside the exact workload boundary"
    [[ "${postgres_subnet_id,,}" == "${workload_prefix,,}microsoft.network/virtualnetworks/"*"/subnets/snet-postgres" ]] || die "PostgreSQL delegated subnet output is outside the exact workload boundary"

    acr_json="$(az acr show --ids "$acr_id" --only-show-errors --output json)" || die "cannot read ACR public-network posture"
    postgres_json="$(az postgres flexible-server show --ids "$postgres_id" --only-show-errors --output json)" || die "cannot read PostgreSQL public-network posture"
    key_vault_json="$(az keyvault show --ids "$key_vault_id" --only-show-errors --output json)" || die "cannot read Key Vault public-network posture"
    redis_json="$(az resource show --ids "$redis_id" --only-show-errors --output json)" || die "cannot read Managed Redis public-network posture"
    blob_json="$(az storage account show --ids "$blob_id" --only-show-errors --output json)" || die "cannot read workload Blob public-network posture"
    state_blob_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$GUARD_STATE_STORAGE_ACCOUNT"
    state_blob_json="$(az storage account show --ids "$state_blob_id" --only-show-errors --output json)" || die "cannot read state Blob public-network posture"
    if [[ "$registry_posture" == "private" ]]; then
      jq -e '.publicNetworkAccess == "Disabled" and .adminUserEnabled == false' <<<"$acr_json" >/dev/null || die "private ACR public access or admin credentials are enabled"
      [[ -z "$registry_exception_hash" ]] || die "private ACR unexpectedly carries a public-exception reference"
      [[ -n "$acr_private_endpoint_id" ]] || die "private ACR is missing its exact private-endpoint output"
      acr_addresses="$(probe_exact_private_endpoint "$acr_host" 443 "$acr_private_endpoint_id" "$acr_id" "$private_endpoint_subnet_id")"
      acr_all_private=true
      acr_public_disabled=true
    elif [[ "$registry_posture" == "synthetic_public_exception" && "$GUARD_DEPLOYMENT_MODE" == "synthetic_lab" ]]; then
      jq -e '.publicNetworkAccess == "Enabled" and .adminUserEnabled == false' <<<"$acr_json" >/dev/null || die "synthetic public-exception ACR does not have exact enabled/admin-disabled posture"
      [[ "$registry_exception_hash" =~ ^[0-9a-f]{64}$ ]] || die "synthetic public-exception ACR lacks a hashed reviewed exception reference"
      acr_addresses="$(probe_public_endpoint "$acr_host" 443)"
      acr_all_private=false
      acr_public_disabled=false
    else
      die "registry posture is inconsistent with the bootstrap-bound deployment mode"
    fi
    jq -e '.network.publicNetworkAccess == "Disabled"' <<<"$postgres_json" >/dev/null || die "PostgreSQL public access is enabled"
    jq -e '
      .properties.publicNetworkAccess == "Disabled" and
      .properties.networkAcls.bypass == "None" and
      .properties.networkAcls.defaultAction == "Deny"
    ' <<<"$key_vault_json" >/dev/null || die "Key Vault public access or trusted-services bypass is enabled"
    jq -e '.properties.publicNetworkAccess == "Disabled"' <<<"$redis_json" >/dev/null || die "Managed Redis public access is enabled"
    jq -e '.publicNetworkAccess == "Disabled" and .allowSharedKeyAccess == false' <<<"$blob_json" >/dev/null || die "workload Blob public/shared-key access is enabled"
    jq -e '.publicNetworkAccess == "Disabled" and .allowSharedKeyAccess == false and .defaultToOAuthAuthentication == true' <<<"$state_blob_json" >/dev/null || die "state Blob public/shared-key access is enabled"
    jq -e --arg subnet_id "${postgres_subnet_id,,}" '(.delegatedSubnetResourceId | ascii_downcase) == $subnet_id' <<<"$postgres_json" >/dev/null || die "PostgreSQL server is outside the exact delegated subnet"

    postgres_addresses="$(probe_exact_delegated_subnet "$postgres_host" 5432 "$postgres_subnet_id")"
    key_vault_addresses="$(probe_exact_private_endpoint "$key_vault_host" 443 "$key_vault_private_endpoint_id" "$key_vault_id" "$private_endpoint_subnet_id")"
    redis_addresses="$(probe_exact_private_endpoint "$redis_host" 10000 "$redis_private_endpoint_id" "$redis_id" "$private_endpoint_subnet_id")"
    blob_addresses="$(probe_exact_private_endpoint "$blob_host" 443 "$blob_private_endpoint_id" "$blob_id" "$private_endpoint_subnet_id")"
    state_blob_addresses="$(probe_exact_private_endpoint "$state_blob_host" 443 "$GUARD_STATE_BLOB_PRIVATE_ENDPOINT_ID" "$state_blob_id" "$GUARD_STATE_PRIVATE_ENDPOINT_SUBNET_ID")"
    probe_payload="$(mktemp /run/cosmas-network-evidence-payload.XXXXXX)"
    jq -cS -n \
      --arg probed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg source_sha "$source_sha" \
      --arg release_id "$release_id" \
      --arg runner_id "$(jq -er '.runner_vm_name.value' "$bootstrap_outputs" | sed "s|^|/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_STATE_RESOURCE_GROUP/providers/Microsoft.Compute/virtualMachines/|")" \
      --arg runner_subnet_id "$GUARD_RUNNER_SUBNET_ID" \
      --arg box_id "$GUARD_BOX_ID" \
      --arg deployment_mode "$GUARD_DEPLOYMENT_MODE" \
      --arg registry_posture "$registry_posture" \
      --arg registry_exception_hash "$registry_exception_hash" \
      --arg lineage "$GUARD_STATE_LINEAGE" \
      --argjson serial "$GUARD_STATE_SERIAL" \
      --arg state_sha256 "$GUARD_STATE_SHA256" \
      --arg acr_id "$acr_id" --arg acr_attachment_id "$acr_private_endpoint_id" --arg acr_host "$acr_host" --argjson acr_addresses "$acr_addresses" --argjson acr_all_private "$acr_all_private" --argjson acr_public_disabled "$acr_public_disabled" \
      --arg postgres_id "$postgres_id" --arg postgres_attachment_id "$postgres_subnet_id" --arg postgres_host "$postgres_host" --argjson postgres_addresses "$postgres_addresses" \
      --arg key_vault_id "$key_vault_id" --arg key_vault_attachment_id "$key_vault_private_endpoint_id" --arg key_vault_host "$key_vault_host" --argjson key_vault_addresses "$key_vault_addresses" \
      --arg redis_id "$redis_id" --arg redis_attachment_id "$redis_private_endpoint_id" --arg redis_host "$redis_host" --argjson redis_addresses "$redis_addresses" \
      --arg blob_id "$blob_id" --arg blob_attachment_id "$blob_private_endpoint_id" --arg blob_host "$blob_host" --argjson blob_addresses "$blob_addresses" \
      --arg state_blob_id "$state_blob_id" \
      --arg state_blob_attachment_id "$GUARD_STATE_BLOB_PRIVATE_ENDPOINT_ID" \
      --arg state_blob_host "$state_blob_host" --argjson state_blob_addresses "$state_blob_addresses" '
        {
          schema_version: 1,
          evidence_type: "protected-runner-live-network",
          probed_at: $probed_at,
          source_sha: $source_sha,
          release_id: $release_id,
          runner: {resource_id: $runner_id, subnet_id: $runner_subnet_id},
          boundary: {box_id: $box_id, deployment_mode: $deployment_mode},
          registry: {
            posture: $registry_posture,
            public_exception_reference_sha256: (if $registry_exception_hash == "" then null else $registry_exception_hash end)
          },
          state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
          endpoints: [
            {kind: "acr", resource_id: $acr_id, network_attachment_id: (if $registry_posture == "private" then $acr_attachment_id else null end), hostname: $acr_host, port: 443, resolved_address_count: $acr_addresses, all_addresses_private: $acr_all_private, tcp_reachable: true, public_network_access_disabled: $acr_public_disabled, exact_resource_address_match: true},
            {kind: "postgres", resource_id: $postgres_id, network_attachment_id: $postgres_attachment_id, hostname: $postgres_host, port: 5432, resolved_address_count: $postgres_addresses, all_addresses_private: true, tcp_reachable: true, public_network_access_disabled: true, exact_resource_address_match: true},
            {kind: "key_vault", resource_id: $key_vault_id, network_attachment_id: $key_vault_attachment_id, hostname: $key_vault_host, port: 443, resolved_address_count: $key_vault_addresses, all_addresses_private: true, tcp_reachable: true, public_network_access_disabled: true, trusted_services_bypass_disabled: true, exact_resource_address_match: true},
            {kind: "managed_redis", resource_id: $redis_id, network_attachment_id: $redis_attachment_id, hostname: $redis_host, port: 10000, resolved_address_count: $redis_addresses, all_addresses_private: true, tcp_reachable: true, public_network_access_disabled: true, exact_resource_address_match: true},
            {kind: "workload_blob", resource_id: $blob_id, network_attachment_id: $blob_attachment_id, hostname: $blob_host, port: 443, resolved_address_count: $blob_addresses, all_addresses_private: true, tcp_reachable: true, public_network_access_disabled: true, exact_resource_address_match: true},
            {kind: "state_blob", resource_id: $state_blob_id, network_attachment_id: $state_blob_attachment_id, hostname: $state_blob_host, port: 443, resolved_address_count: $state_blob_addresses, all_addresses_private: true, tcp_reachable: true, public_network_access_disabled: true, exact_resource_address_match: true}
          ]
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    network_evidence_tmp="$(mktemp "$network_evidence_dir/.network-evidence.XXXXXX")"
    jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$network_evidence_tmp"
    chmod 0600 "$network_evidence_tmp"
    jq -e --arg hash "$evidence_hash" '.schema_version == 1 and .evidence_payload_sha256 == $hash' "$network_evidence_tmp" >/dev/null || die "generated network evidence is invalid"
    ln -- "$network_evidence_tmp" "$network_evidence_file" || die "network evidence generation appeared concurrently"
    rm -f -- "$network_evidence_tmp"
    network_evidence_tmp=""
    network_pointer_tmp="$(mktemp "$release_root/network-evidence.current.XXXXXX")"
    printf '%s\n' "$network_generation" >"$network_pointer_tmp"
    chmod 0600 "$network_pointer_tmp"
    mv -f -- "$network_pointer_tmp" "$release_root/network-evidence.current"
    network_pointer_tmp=""
    emit_sanitized_artifact "$network_evidence_file"
    ;;
  build-push)
    [[ "$stage" == "images" ]] || die "build-push requires stage=images"
    validate_source
    verify_pinned_toolchain
    bind_release_to_source
    verify_release_network_evidence
    network_evidence_file="$VERIFIED_NETWORK_EVIDENCE"
    install -d -o root -g root -m 0700 "$runner_root/builds" "$build_root"
    jq -e '
      type == "object" and
      .vite_cosmas_env == "early_adopter_beta" and
      (.vite_clerk_publishable_key | strings | test("^pk_live_[^[:space:]]+$")) and
      (.vite_api_base | strings | test("^https://[^/?#]+$")) and
      (keys | sort) == (["vite_api_base", "vite_clerk_publishable_key", "vite_cosmas_env"] | sort)
    ' "$payload_file" >/dev/null || die "build payload must contain only the exact public D3 web build arguments"
    fresh_managed_identity_login
    # shellcheck source=deployment-guard-lib.sh
    source "$repository_root/infra/beta/deployment-guard-lib.sh"
    GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
    guard_find_terraform
    guard_source_metadata "$repository_root"
    guard_load_bootstrap_outputs "$bootstrap_outputs"
    guard_verify_azure_context_and_boundary
    export TF_DATA_DIR="$release_root/build-terraform-data"
    guard_backend_init >/dev/null
    probe_state="$(mktemp /run/cosmas-build-state.XXXXXX)"
    guard_pull_state "$probe_state"
    guard_validate_environment_state "$probe_state"
    jq -e --slurpfile evidence "$network_evidence_file" '
      .lineage == $evidence[0].state.lineage and
      .serial == $evidence[0].state.serial
    ' "$probe_state" >/dev/null || die "live network evidence is stale for the state used by this build"
    probe_outputs="$(mktemp /run/cosmas-build-outputs.XXXXXX)"
    "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
    chmod 0600 "$probe_outputs"
    api_origin="$(jq -er '.api_origin.value | strings' "$probe_outputs")"
    jq -e --arg api_origin "$api_origin" '.vite_api_base == $api_origin' "$payload_file" >/dev/null || die "web build API origin differs from the exact foundation output"
    acr_host="$(jq -er '.acr_login_server.value | strings' "$probe_outputs")"
    acr_id="$(jq -er '.acr_resource_id.value | strings' "$probe_outputs")"
    acr_name="${acr_host%%.*}"
    [[ "$acr_host" == "$acr_name.azurecr.io" && "$acr_name" =~ ^[a-z0-9]{5,50}$ ]] || die "foundation ACR login server is invalid"
    [[ "${acr_id,,}" == "/subscriptions/${subscription_id,,}/resourcegroups/$(jq -er '.workload_resource_group_name.value | ascii_downcase' "$bootstrap_outputs")/providers/microsoft.containerregistry/registries/$acr_name" ]] || die "foundation ACR is outside the exact D3 resource group"
    acr_json="$(az acr show --ids "$acr_id" --only-show-errors --output json)" || die "cannot read exact D3 ACR"
    jq -e --arg id "${acr_id,,}" --arg host "$acr_host" '
      (.id | ascii_downcase) == $id and .loginServer == $host and .adminUserEnabled == false
    ' <<<"$acr_json" >/dev/null || die "ACR identity/login/admin boundary differs from the foundation state"

    api_repository="cosmas-os"
    web_repository="cosmas-os-web"
    immutable_tag="git-$source_sha"
    public_config_hash="$(jq -cS '{vite_cosmas_env, vite_clerk_publishable_key, vite_api_base}' "$payload_file" | sha256sum | awk '{print $1}')"
    if [[ -e "$build_root/build-evidence.json" || -L "$build_root/build-evidence.json" ]]; then
      verify_release_build_evidence
      jq -e --arg expected "$public_config_hash" '.public_web_build_config_sha256 == $expected' "$build_root/build-evidence.json" >/dev/null || die "accepted source build used different public web build inputs"
      accepted_api_digest="$(jq -er '.images.api.digest' "$build_root/build-evidence.json")"
      accepted_web_digest="$(jq -er '.images.web.digest' "$build_root/build-evidence.json")"
      [[ "$(acr_tag_digest_or_absent "$acr_name" "$api_repository" "$immutable_tag")" == "$accepted_api_digest" ]] || die "accepted API source tag no longer resolves to its evidence-bound digest"
      [[ "$(acr_tag_digest_or_absent "$acr_name" "$web_repository" "$immutable_tag")" == "$accepted_web_digest" ]] || die "accepted web source tag no longer resolves to its evidence-bound digest"
      guard_lock_and_verify_acr_immutable_tag "$acr_name" "$api_repository" "$immutable_tag" "$accepted_api_digest"
      guard_lock_and_verify_acr_immutable_tag "$acr_name" "$web_repository" "$immutable_tag" "$accepted_web_digest"
      emit_sanitized_artifact "$build_root/build-evidence.json"
      exit 0
    fi

    docker_config_dir="$(mktemp -d /run/cosmas-docker-session.XXXXXX)"
    chmod 0700 "$docker_config_dir"
    export DOCKER_CONFIG="$docker_config_dir"
    acr_token="$(az acr login --name "$acr_name" --expose-token --query accessToken --output tsv --only-show-errors)" || die "cannot obtain an ephemeral ACR data-plane token"
    [[ -n "$acr_token" ]] || die "ACR returned an empty data-plane token"
    printf '%s' "$acr_token" | docker login "$acr_host" --username 00000000-0000-0000-0000-000000000000 --password-stdin >/dev/null 2>&1 || die "ephemeral ACR Docker login failed"
    unset acr_token

    api_image="$acr_host/$api_repository:$immutable_tag"
    web_image="$acr_host/$web_repository:$immutable_tag"
    build_log="$build_root/build.private.log"
    api_scan="$build_root/api-trivy.json"
    web_scan="$build_root/web-trivy.json"
    ensure_docker_platform_isolation "$build_log"
    [[ "$(head -n 1 "$repository_root/Dockerfile")" != '# syntax='* && "$(head -n 1 "$repository_root/Dockerfile.web")" != '# syntax='* ]] || die "mutable remote Dockerfile frontends are forbidden"
    grep -Eq '^RUN --network=none .*pip install .*--no-index' "$repository_root/Dockerfile" || die "API dependency installation is not forced offline"
    grep -Eq '^RUN --network=none pnpm install .*--offline' "$repository_root/Dockerfile.web" || die "web dependency installation is not forced offline"
    grep -Eq '^RUN --network=none pnpm run build:beta' "$repository_root/Dockerfile.web" || die "web lifecycle/build scripts are not forced offline"
    api_existing_digest="$(acr_tag_digest_or_absent "$acr_name" "$api_repository" "$immutable_tag")"
    web_existing_digest="$(acr_tag_digest_or_absent "$acr_name" "$web_repository" "$immutable_tag")"

    if [[ -z "$api_existing_digest" ]]; then
      if ! docker buildx build --load \
        --platform linux/amd64 \
        --network bridge \
        --no-cache \
        --label "org.opencontainers.image.revision=$source_sha" \
        --label "com.cosmaneura.cosmas-os.image-kind=api" \
        --file "$repository_root/Dockerfile" \
        --tag "$api_image" \
        "$repository_root" >>"$build_log" 2>&1; then
        die "API image build failed; diagnostics remain root-only on the runner"
      fi
      if ! trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --format json --output "$api_scan" "$api_image" >>"$build_log" 2>&1; then
        die "API image failed the pre-push HIGH/CRITICAL Trivy gate; private report remains on the runner"
      fi
      docker push "$api_image" >>"$build_log" 2>&1 || die "API immutable-tag push failed; no accepted evidence was created"
      api_existing_digest="$(acr_tag_digest_or_absent "$acr_name" "$api_repository" "$immutable_tag")"
    fi
    if [[ -z "$web_existing_digest" ]]; then
      if ! docker buildx build --load \
        --platform linux/amd64 \
        --network bridge \
        --no-cache \
        --label "org.opencontainers.image.revision=$source_sha" \
        --label "com.cosmaneura.cosmas-os.image-kind=web" \
        --label "com.cosmaneura.cosmas-os.public-config-sha256=$public_config_hash" \
        --file "$repository_root/Dockerfile.web" \
        --tag "$web_image" \
        --build-arg VITE_COSMAS_ENV=early_adopter_beta \
        --build-arg "VITE_CLERK_PUBLISHABLE_KEY=$(jq -er '.vite_clerk_publishable_key' "$payload_file")" \
        --build-arg "VITE_API_BASE=$api_origin" \
        "$repository_root" >>"$build_log" 2>&1; then
        die "web image build failed; diagnostics remain root-only on the runner"
      fi
      if ! trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --format json --output "$web_scan" "$web_image" >>"$build_log" 2>&1; then
        die "web image failed the pre-push HIGH/CRITICAL Trivy gate; private report remains on the runner"
      fi
      docker push "$web_image" >>"$build_log" 2>&1 || die "web immutable-tag push failed; no accepted evidence was created"
      web_existing_digest="$(acr_tag_digest_or_absent "$acr_name" "$web_repository" "$immutable_tag")"
    fi

    api_digest="$api_existing_digest"
    web_digest="$web_existing_digest"
    [[ "$api_digest" =~ ^sha256:[0-9a-f]{64}$ && "$web_digest" =~ ^sha256:[0-9a-f]{64}$ ]] || die "immutable ACR source-tag digest readback is invalid"
    api_exact_image="$acr_host/$api_repository@$api_digest"
    web_exact_image="$acr_host/$web_repository@$web_digest"
    docker pull "$api_exact_image" >>"$build_log" 2>&1 || die "cannot pull the exact API digest for provenance verification"
    docker pull "$web_exact_image" >>"$build_log" 2>&1 || die "cannot pull the exact web digest for provenance verification"
    docker image inspect "$api_exact_image" --format '{{json .Config.Labels}}' | jq -e \
      --arg source_sha "$source_sha" \
      '."org.opencontainers.image.revision" == $source_sha and ."com.cosmaneura.cosmas-os.image-kind" == "api"' >/dev/null || die "API source tag lacks exact immutable source provenance labels"
    docker image inspect "$web_exact_image" --format '{{json .Config.Labels}}' | jq -e \
      --arg source_sha "$source_sha" --arg config_sha256 "$public_config_hash" \
      '."org.opencontainers.image.revision" == $source_sha and ."com.cosmaneura.cosmas-os.image-kind" == "web" and ."com.cosmaneura.cosmas-os.public-config-sha256" == $config_sha256' >/dev/null || die "web source tag lacks exact source/public-config provenance labels"
    docker run --rm --network none "$api_exact_image" python -m cosmas_os.cli --help >>"$build_log" 2>&1 || die "API image does not expose the reviewed module CLI"
    docker run --rm --network none "$api_exact_image" python -c 'from cosmas_os.application.database_preparation import DATABASE_PREPARATION_CONTRACT; assert DATABASE_PREPARATION_CONTRACT == "cosmas-os-d3-database-preparation-v1"' >>"$build_log" 2>&1 || die "API image does not contain the reviewed database-preparation contract"
    docker run --rm --network none "$api_exact_image" python -c 'from psycopg.conninfo import conninfo_to_dict; values=conninfo_to_dict("postgresql://u:p@example.invalid/cosmas_os?sslmode=verify-full&sslrootcert=system"); assert values["sslmode"] == "verify-full" and values["sslrootcert"] == "system"' >>"$build_log" 2>&1 || die "API image cannot apply the reviewed system-CA PostgreSQL TLS contract"
    if ! trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --format json --output "$api_scan" "$api_exact_image" >>"$build_log" 2>&1; then
      die "exact API registry digest failed the HIGH/CRITICAL Trivy gate; private report remains on the runner"
    fi
    if ! trivy image --quiet --scanners vuln --severity HIGH,CRITICAL --exit-code 1 --format json --output "$web_scan" "$web_exact_image" >>"$build_log" 2>&1; then
      die "exact web registry digest failed the HIGH/CRITICAL Trivy gate; private report remains on the runner"
    fi
    chmod 0600 "$api_scan" "$web_scan" "$build_log"
    api_vulnerability_count="$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH" or .Severity == "CRITICAL")] | length' "$api_scan")"
    web_vulnerability_count="$(jq '[.Results[]?.Vulnerabilities[]? | select(.Severity == "HIGH" or .Severity == "CRITICAL")] | length' "$web_scan")"
    (( api_vulnerability_count == 0 && web_vulnerability_count == 0 )) || die "exact registry digests contain HIGH/CRITICAL vulnerabilities"
    [[ "$(acr_tag_digest_or_absent "$acr_name" "$api_repository" "$immutable_tag")" == "$api_digest" ]] || die "API source tag changed during exact-digest verification"
    [[ "$(acr_tag_digest_or_absent "$acr_name" "$web_repository" "$immutable_tag")" == "$web_digest" ]] || die "web source tag changed during exact-digest verification"
    guard_lock_and_verify_acr_immutable_tag "$acr_name" "$api_repository" "$immutable_tag" "$api_digest"
    guard_lock_and_verify_acr_immutable_tag "$acr_name" "$web_repository" "$immutable_tag" "$web_digest"
    docker logout "$acr_host" >/dev/null 2>&1 || true

    probe_payload="$(mktemp /run/cosmas-build-evidence-payload.XXXXXX)"
    jq -cS -n \
      --arg built_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg source_sha "$source_sha" --arg release_id "$release_id" --arg box_id "$GUARD_BOX_ID" \
      --arg state_lineage "$GUARD_STATE_LINEAGE" --argjson state_serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
      --arg acr_id "$acr_id" --arg acr_host "$acr_host" \
      --arg api_tag "$api_repository:$immutable_tag" --arg api_digest "$api_digest" \
      --arg web_tag "$web_repository:$immutable_tag" --arg web_digest "$web_digest" \
      --arg api_dockerfile_sha256 "$(sha256sum "$repository_root/Dockerfile" | awk '{print $1}')" \
      --arg web_dockerfile_sha256 "$(sha256sum "$repository_root/Dockerfile.web" | awk '{print $1}')" \
      --arg public_config_sha256 "$public_config_hash" \
      --arg trivy_version "$(trivy --version | awk 'NR == 1 {print $2}')" \
      --arg api_scan_sha256 "$(sha256sum "$api_scan" | awk '{print $1}')" \
      --arg web_scan_sha256 "$(sha256sum "$web_scan" | awk '{print $1}')" '
        {
          schema_version: 1,
          evidence_type: "protected-runner-build-push",
          built_at: $built_at,
          source_sha: $source_sha,
          build_release_id: $release_id,
          box_id: $box_id,
          state: {lineage: $state_lineage, serial: $state_serial, sha256: $state_sha256},
          registry: {resource_id: $acr_id, login_server: $acr_host, admin_user_enabled: false},
          build_isolation: {platform: "linux/amd64", network: "bridge", host_network_forbidden: true, container_to_azure_platform_endpoints_blocked_and_probed: true},
          public_web_build_config_sha256: $public_config_sha256,
          images: {
            api: {tag: $api_tag, digest: $api_digest, tag_write_delete_locked: true, manifest_write_delete_locked: true, dockerfile_sha256: $api_dockerfile_sha256, trivy_version: $trivy_version, trivy_report_sha256: $api_scan_sha256, high_critical_vulnerabilities: 0},
            web: {tag: $web_tag, digest: $web_digest, tag_write_delete_locked: true, manifest_write_delete_locked: true, dockerfile_sha256: $web_dockerfile_sha256, trivy_version: $trivy_version, trivy_report_sha256: $web_scan_sha256, high_critical_vulnerabilities: 0}
          }
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    build_evidence_tmp="$(mktemp "$build_root/.build-evidence.XXXXXX")"
    jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$build_evidence_tmp"
    chmod 0600 "$build_evidence_tmp"
    jq -e --arg hash "$evidence_hash" '.schema_version == 1 and .evidence_payload_sha256 == $hash' "$build_evidence_tmp" >/dev/null || die "generated build evidence is invalid"
    ln -- "$build_evidence_tmp" "$build_root/build-evidence.json" || die "accepted build evidence appeared concurrently"
    rm -f -- "$build_evidence_tmp"
    build_evidence_tmp=""
    rm -f -- "$build_log"
    emit_sanitized_artifact "$build_root/build-evidence.json"
    ;;
  database-prepare)
    [[ "$stage" == "database" ]] || die "database-prepare requires stage=database"
    validate_source
    verify_pinned_toolchain
    bind_release_to_source
    verify_release_network_evidence
    network_evidence_file="$VERIFIED_NETWORK_EVIDENCE"
    verify_release_build_evidence
    jq -e 'type == "object" and length == 0' "$payload_file" >/dev/null || die "database-prepare accepts no protected input values"
    fresh_managed_identity_login
    # shellcheck source=deployment-guard-lib.sh
    source "$repository_root/infra/beta/deployment-guard-lib.sh"
    GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
    guard_find_terraform
    guard_source_metadata "$repository_root"
    guard_load_bootstrap_outputs "$bootstrap_outputs"
    guard_verify_azure_context_and_boundary
    export TF_DATA_DIR="$release_root/database-execution-terraform-data"
    guard_backend_init >/dev/null
    probe_state="$(mktemp /run/cosmas-database-execution-state.XXXXXX)"
    guard_pull_state "$probe_state"
    guard_validate_environment_state "$probe_state"
    jq -e --slurpfile evidence "$network_evidence_file" '
      .lineage == $evidence[0].state.lineage and
      .serial == $evidence[0].state.serial
    ' "$probe_state" >/dev/null || die "re-probe the protected network after the database-stage apply before starting the job"
    [[ "$GUARD_STATE_SHA256" == "$(jq -er '.state.sha256' "$network_evidence_file")" ]] || die "re-probe the protected network after the database-stage state changed"
    probe_outputs="$(mktemp /run/cosmas-database-execution-outputs.XXXXXX)"
    "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
    chmod 0600 "$probe_outputs"
    job_id="$(jq -er '.database_preparation_job_resource_id.value | strings' "$probe_outputs")"
    job_name="$(jq -er '.database_preparation_job_name.value | strings' "$probe_outputs")"
    job_image="$(jq -er '.database_preparation_image_reference.value | strings' "$probe_outputs")"
    job_identity_id="$(jq -er '.database_preparation_identity_resource_id.value | strings' "$probe_outputs")"
    container_environment_id="$(jq -er '.container_app_environment_resource_id.value | strings' "$probe_outputs")"
    database_server_id="$(jq -er '.postgres_resource_id.value | strings' "$probe_outputs")"
    expected_api_digest="$(jq -er '.images.api.digest' "$build_root/build-evidence.json")"
    expected_job_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.App/jobs/$job_name"
    [[ "${job_id,,}" == "${expected_job_id,,}" ]] || die "database-preparation job is outside the exact D3 resource group"
    [[ "$job_image" == "$(jq -er '.registry.login_server' "$build_root/build-evidence.json")/cosmas-os@$expected_api_digest" ]] || die "database-preparation job does not use the accepted API digest"
    operation_temp_dir="$(mktemp -d /run/cosmas-database-execution.XXXXXX)"
    chmod 0700 "$operation_temp_dir"
    az rest --method get --url "https://management.azure.com${job_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/job.json" || die "cannot read exact database-preparation job"
    chmod 0600 "$operation_temp_dir/job.json"
    jq -e \
      --arg job_id "${job_id,,}" \
      --arg image "$job_image" \
      --arg identity_id "${job_identity_id,,}" \
      --arg environment_id "${container_environment_id,,}" '
      (.id | ascii_downcase) == $job_id and
      (.properties.environmentId | ascii_downcase) == $environment_id and
      .identity.type == "UserAssigned" and
      ((.identity.userAssignedIdentities | keys | map(ascii_downcase)) == [$identity_id]) and
      .properties.configuration.triggerType == "Manual" and
      .properties.configuration.replicaTimeout == 900 and
      .properties.configuration.replicaRetryLimit == 0 and
      .properties.configuration.manualTriggerConfig.parallelism == 1 and
      .properties.configuration.manualTriggerConfig.replicaCompletionCount == 1 and
      (.properties.configuration.registries | length) == 1 and
      (.properties.configuration.registries[0].identity | ascii_downcase) == $identity_id and
      (.properties.template.containers | length) == 1 and
      .properties.template.containers[0].name == "database-preparation" and
      .properties.template.containers[0].image == $image and
      .properties.template.containers[0].command == ["python", "-m", "cosmas_os.cli"] and
      .properties.template.containers[0].args == ["prepare-beta-database", "--confirm-forward-only"] and
      ([.properties.template.containers[0].env[] | {name, secretRef}] | sort_by(.name)) == ([
        {name: "COSMAS_ENV", secretRef: null},
        {name: "DATABASE_ADMIN_URL", secretRef: "database-admin-url"},
        {name: "DATABASE_URL", secretRef: "database-runtime-url"}
      ] | sort_by(.name)) and
      ([.properties.configuration.secrets[].name] | sort) == (["database-admin-url", "database-runtime-url"] | sort)
    ' "$operation_temp_dir/job.json" >/dev/null || die "live database-preparation job differs from the reviewed manual exact-digest contract"
    az rest --method post --url "https://management.azure.com${job_id}/listSecrets?api-version=2023-11-02-preview" --body '{}' --only-show-errors --output json >"$operation_temp_dir/job-secrets.json" || die "cannot verify the exact private database-preparation targets"
    chmod 0600 "$operation_temp_dir/job-secrets.json"
    python3 - "$operation_temp_dir/job-secrets.json" "$probe_outputs" <<'PY' || die "database-preparation secrets do not target the exact dedicated database with verified system trust"
import json
import sys
from urllib.parse import parse_qs, unquote, urlparse

secrets = json.load(open(sys.argv[1], encoding="utf-8"))
outputs = json.load(open(sys.argv[2], encoding="utf-8"))
values = {item.get("name"): item.get("value") for item in secrets.get("value", [])}
if set(values) != {"database-admin-url", "database-runtime-url"}:
    raise SystemExit(1)
expected_host = outputs["postgres_private_fqdn"]["value"].lower()
parsed = {}
for name, value in values.items():
    if not isinstance(value, str) or "\n" in value or "\r" in value or "\x00" in value:
        raise SystemExit(1)
    url = urlparse(value)
    query = parse_qs(url.query, keep_blank_values=True)
    if (
        url.scheme != "postgresql+psycopg"
        or (url.hostname or "").lower() != expected_host
        or url.port != 5432
        or url.path != "/cosmas_os"
        or query.get("sslmode") != ["verify-full"]
        or query.get("sslrootcert") != ["system"]
        or not url.username
        or not url.password
    ):
        raise SystemExit(1)
    parsed[name] = unquote(url.username)
if parsed["database-admin-url"] == parsed["database-runtime-url"]:
    raise SystemExit(1)
PY
    az rest --method post --url "https://management.azure.com${job_id}/start?api-version=2023-11-02-preview" --body '{}' --only-show-errors --output json >"$operation_temp_dir/start.json" || die "database-preparation execution did not start"
    chmod 0600 "$operation_temp_dir/start.json"
    execution_name="$(jq -er '.name | strings | select(test("^[a-z0-9][a-z0-9-]{2,255}$"))' "$operation_temp_dir/start.json")" || die "database-preparation start response lacks an exact execution name"
    execution_id="$job_id/executions/$execution_name"
    jq -e --arg execution_id "${execution_id,,}" '(.id | ascii_downcase) == $execution_id' "$operation_temp_dir/start.json" >/dev/null || die "database-preparation start response is outside the exact job"
    execution_succeeded=false
    for _ in $(seq 1 120); do
      az rest --method get --url "https://management.azure.com${execution_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/execution.json" 2>/dev/null || true
      execution_status="$(jq -r '.properties.status // ""' "$operation_temp_dir/execution.json" 2>/dev/null || true)"
      if [[ "$execution_status" == "Succeeded" ]]; then
        execution_succeeded=true
        break
      fi
      [[ "$execution_status" != "Failed" && "$execution_status" != "Stopped" && "$execution_status" != "Degraded" ]] || die "database-preparation execution failed; private diagnostics remain in Azure"
      sleep 10
    done
    [[ "$execution_succeeded" == "true" ]] || die "database-preparation execution did not succeed within twenty minutes"

    az rest --method get --url "https://management.azure.com${job_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/job-for-logs.json" || die "cannot read database job log endpoint"
    event_stream_endpoint="$(jq -er '.properties.eventStreamEndpoint | strings | select(startswith("https://")) | split("/subscriptions/")[0]' "$operation_temp_dir/job-for-logs.json")" || die "database job has no HTTPS event-stream endpoint"
    az rest --method post --url "https://management.azure.com${job_id}/getAuthToken?api-version=2023-11-02-preview" --body '{}' --only-show-errors --output json >"$operation_temp_dir/log-token.json" || die "cannot obtain ephemeral database-job log token"
    log_token="$(jq -er '.properties.token | strings | select(test("^[A-Za-z0-9._~-]+$"))' "$operation_temp_dir/log-token.json")" || die "database-job log token is invalid"
    az rest --method get --url "https://management.azure.com${execution_id}/replicas?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/replicas.json" || die "cannot list exact database-job execution replicas"
    [[ "$(jq '.value | length' "$operation_temp_dir/replicas.json")" -eq 1 ]] || die "database-preparation execution did not have exactly one replica"
    replica_name="$(jq -er '.value[0].name | strings | select(test("^[A-Za-z0-9._-]+$"))' "$operation_temp_dir/replicas.json")" || die "database-preparation replica name is invalid"
    log_url="$event_stream_endpoint/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/jobs/$job_name/executions/$execution_name/replicas/$replica_name/containers/database-preparation/logstream?follow=false&tailLines=50&output=json"
    [[ "$log_url" == https://* ]] || die "database-job log URL is not HTTPS"
    curl_config_file="$operation_temp_dir/curl.conf"
    printf 'silent\nshow-error\nfail\nmax-time = 30\nheader = "Authorization: Bearer %s"\n' "$log_token" >"$curl_config_file"
    chmod 0600 "$curl_config_file"
    unset log_token
    evidence_found=false
    for _ in $(seq 1 60); do
      if curl --config "$curl_config_file" "$log_url" >"$operation_temp_dir/logstream.private" 2>/dev/null &&
        python3 - "$operation_temp_dir/logstream.private" "$operation_temp_dir/job-evidence.json" <<'PY'
import json
import sys

source, destination = sys.argv[1:]
expected_keys = {
    "audit_delete_denied", "audit_update_denied", "contract", "evidence_sha256",
    "runtime_ddl_denied", "runtime_role_non_admin", "schema_at_expected_head",
    "schema_revision", "status",
}
found = []

def visit(value):
    if isinstance(value, dict):
        if set(value) == expected_keys and value.get("contract") == "cosmas-os-d3-database-preparation-v1":
            found.append(value)
        for child in value.values():
            visit(child)
    elif isinstance(value, list):
        for child in value:
            visit(child)
    elif isinstance(value, str):
        normalized = value.replace("\\u0022", '"').replace("\\u002B", "+").replace("\\u0027", "'")
        start, end = normalized.find("{"), normalized.rfind("}")
        if 0 <= start < end:
            try:
                visit(json.loads(normalized[start : end + 1]))
            except json.JSONDecodeError:
                pass

raw = open(source, encoding="utf-8", errors="strict").read()
for line in raw.splitlines():
    visit(line)
    try:
        visit(json.loads(line))
    except json.JSONDecodeError:
        pass
unique = {json.dumps(item, sort_keys=True, separators=(",", ":")): item for item in found}
if len(unique) != 1:
    raise SystemExit(1)
with open(destination, "w", encoding="utf-8") as handle:
    handle.write(next(iter(unique)))
PY
      then
        evidence_found=true
        break
      fi
      sleep 5
    done
    [[ "$evidence_found" == "true" ]] || die "exact sanitized database-preparation evidence was not available from the succeeded execution"
    chmod 0600 "$operation_temp_dir/job-evidence.json"
    jq -e '
      .contract == "cosmas-os-d3-database-preparation-v1" and .status == "ready" and
      .schema_revision == "0002_external_identities" and
      .schema_at_expected_head == true and .runtime_role_non_admin == true and
      .runtime_ddl_denied == true and .audit_update_denied == true and .audit_delete_denied == true and
      (.evidence_sha256 | strings | test("^[0-9a-f]{64}$"))
    ' "$operation_temp_dir/job-evidence.json" >/dev/null || die "database-preparation evidence did not prove the complete contract"
    database_evidence_hash="$(jq -cS 'del(.evidence_sha256)' "$operation_temp_dir/job-evidence.json" | sha256sum | awk '{print $1}')"
    [[ "$(jq -er '.evidence_sha256' "$operation_temp_dir/job-evidence.json")" == "$database_evidence_hash" ]] || die "database-preparation evidence self-hash is invalid"
    execution_root="$release_root/executions/database/$execution_name"
    [[ ! -e "$execution_root" && ! -L "$execution_root" ]] || die "database-preparation execution evidence already exists"
    install -d -o root -g root -m 0700 "$execution_root"
    probe_payload="$(mktemp /run/cosmas-database-attestation.XXXXXX)"
    jq -cS -n \
      --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg source_sha "$source_sha" --arg release_id "$release_id" --arg box_id "$GUARD_BOX_ID" \
      --arg image_digest "${expected_api_digest#sha256:}" --arg schema_revision "0002_external_identities" \
      --arg evidence_sha256 "$database_evidence_hash" --arg execution_id "$execution_id" \
      --arg database_server_id "$database_server_id" \
      --arg state_lineage "$GUARD_STATE_LINEAGE" --argjson state_serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" '
        {
          schema_version: 1,
          evidence_type: "protected-runner-database-preparation",
          completed_at: $completed_at,
          source_sha: $source_sha,
          release_id: $release_id,
          state: {lineage: $state_lineage, serial: $state_serial, sha256: $state_sha256},
          database_preparation_attestation: {
            image_digest: $image_digest,
            schema_revision: $schema_revision,
            evidence_sha256: $evidence_sha256,
            execution_id: $execution_id,
            box_id: $box_id,
            database_server_id: $database_server_id
          }
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    database_evidence_tmp="$(mktemp "$execution_root/.attestation.XXXXXX")"
    jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$database_evidence_tmp"
    chmod 0600 "$database_evidence_tmp"
    jq -e --arg hash "$evidence_hash" '.schema_version == 1 and .evidence_payload_sha256 == $hash' "$database_evidence_tmp" >/dev/null || die "generated database-preparation attestation is invalid"
    ln -- "$database_evidence_tmp" "$execution_root/attestation.json" || die "database-preparation attestation appeared concurrently"
    rm -f -- "$database_evidence_tmp"
    database_evidence_tmp=""
    database_pointer_tmp="$(mktemp "$release_root/.database-attestation.current.XXXXXX")"
    printf '%s\n' "$execution_name" >"$database_pointer_tmp"
    chmod 0600 "$database_pointer_tmp"
    mv -f -- "$database_pointer_tmp" "$release_root/database-attestation.current"
    database_pointer_tmp=""
    emit_sanitized_artifact "$execution_root/attestation.json"
    ;;
  runtime-acceptance)
    [[ "$stage" == "acceptance" ]] || die "runtime-acceptance requires stage=acceptance"
    validate_source
    verify_pinned_toolchain
    bind_release_to_source
    verify_release_network_evidence
    network_evidence_file="$VERIFIED_NETWORK_EVIDENCE"
    verify_release_build_evidence
    jq -e '
      type == "object" and
      (.acceptance_phase == "runtime" or .acceptance_phase == "workflow-baseline" or
       .acceptance_phase == "workflow-verify" or .acceptance_phase == "purge-setup" or
       .acceptance_phase == "purge-verify") and
      (if (.acceptance_phase == "workflow-verify" or .acceptance_phase == "purge-verify")
       then (keys | sort) == (["acceptance_phase", "prior_attestation"] | sort) and (.prior_attestation | type == "object")
       else keys == ["acceptance_phase"] end)
    ' "$payload_file" >/dev/null || die "runtime-acceptance protected payload is invalid"
    acceptance_phase="$(jq -er '.acceptance_phase' "$payload_file")"
    fresh_managed_identity_login
    # shellcheck source=deployment-guard-lib.sh
    source "$repository_root/infra/beta/deployment-guard-lib.sh"
    GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
    guard_find_terraform
    guard_source_metadata "$repository_root"
    guard_load_bootstrap_outputs "$bootstrap_outputs"
    guard_verify_azure_context_and_boundary
    export TF_DATA_DIR="$release_root/runtime-acceptance-terraform-data"
    guard_backend_init >/dev/null
    probe_state="$(mktemp /run/cosmas-runtime-acceptance-state.XXXXXX)"
    guard_pull_state "$probe_state"
    guard_validate_environment_state "$probe_state"
    jq -e --slurpfile evidence "$network_evidence_file" '
      .lineage == $evidence[0].state.lineage and
      .serial == $evidence[0].state.serial
    ' "$probe_state" >/dev/null || die "re-probe the protected network after the workload apply before runtime acceptance"
    [[ "$GUARD_STATE_SHA256" == "$(jq -er '.state.sha256' "$network_evidence_file")" ]] || die "re-probe the protected network after the workload state changed"
    probe_outputs="$(mktemp /run/cosmas-runtime-acceptance-outputs.XXXXXX)"
    "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
    chmod 0600 "$probe_outputs"
    expected_api_digest="$(jq -er '.images.api.digest' "$build_root/build-evidence.json")"
    acr_host="$(jq -er '.registry.login_server' "$build_root/build-evidence.json")"
    job_id="$(jq -er '.runtime_acceptance_job_resource_id.value | strings' "$probe_outputs")"
    job_name="$(jq -er '.runtime_acceptance_job_name.value | strings' "$probe_outputs")"
    runtime_identity_id="$(jq -er '.runtime_identity_resource_id.value | strings' "$probe_outputs")"
    runtime_identity_client_id="$(jq -er '.runtime_identity_client_id.value | strings | ascii_downcase | select(test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))' "$probe_outputs")"
    container_environment_id="$(jq -er '.container_app_environment_resource_id.value | strings' "$probe_outputs")"
    expected_job_id="/subscriptions/$GUARD_SUBSCRIPTION_ID/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.App/jobs/$job_name"
    expected_image="$acr_host/cosmas-os@$expected_api_digest"
    [[ "${job_id,,}" == "${expected_job_id,,}" ]] || die "runtime-acceptance job is outside the exact D3 resource group"
    jq -e --arg expected_image "$expected_image" '
      .workloads_enabled.value == true and
      .runtime_acceptance_job_enabled.value == true and
      .deployment_mode.value == "synthetic_lab" and
      .runtime_data_mode.value == "synthetic" and
      .image_reference.value == $expected_image and
      (.blob_container_name.value | strings | test("^[a-z0-9-]{3,63}$"))
    ' "$probe_outputs" >/dev/null || die "live workloads are not the exact synthetic runtime-acceptance target"

    prior_state_json=""
    if [[ "$acceptance_phase" == "workflow-verify" || "$acceptance_phase" == "purge-verify" ]]; then
      prior_phase="workflow-baseline"
      prior_contract="cosmas-os-d3-workflow-acceptance-v1"
      prior_stage="baseline"
      [[ "$acceptance_phase" != "purge-verify" ]] || {
        prior_phase="purge-setup"
        prior_contract="cosmas-os-d3-physical-purge-acceptance-v1"
        prior_stage="setup"
      }
      prior_wrapper_hash="$(jq -er '.prior_attestation.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$payload_file")" || die "prior acceptance attestation hash is invalid"
      [[ "$(jq -cS '.prior_attestation | del(.evidence_payload_sha256)' "$payload_file" | sha256sum | awk '{print $1}')" == "$prior_wrapper_hash" ]] || die "prior acceptance attestation was modified"
      jq -e \
        --arg source_sha "$source_sha" --arg release_id "$release_id" \
        --arg phase "$prior_phase" --arg contract "$prior_contract" --arg stage "$prior_stage" \
        --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" \
        --arg state_sha256 "$GUARD_STATE_SHA256" --arg image_digest "$expected_api_digest" \
        --arg identity_id "${runtime_identity_id,,}" --arg client_id "$runtime_identity_client_id" '
          .prior_attestation.schema_version == 1 and
          .prior_attestation.evidence_type == "protected-runner-runtime-acceptance" and
          .prior_attestation.source_sha == $source_sha and .prior_attestation.release_id == $release_id and
          .prior_attestation.acceptance_phase == $phase and
          .prior_attestation.state == {lineage: $lineage, serial: $serial, sha256: $state_sha256} and
          .prior_attestation.workload.api_image_digest == $image_digest and
          (.prior_attestation.workload.runtime_identity_resource_id | ascii_downcase) == $identity_id and
          .prior_attestation.workload.runtime_identity_client_id == $client_id and
          .prior_attestation.acceptance_output.contract == $contract and
          .prior_attestation.acceptance_output.stage == $stage and
          .prior_attestation.acceptance_output.status == "ready_for_browser"
        ' "$payload_file" >/dev/null || die "prior acceptance state is not bound to this source/release/state/image/runtime identity"
      prior_state_hash="$(jq -cS '.prior_attestation.acceptance_output | del(.evidence_sha256)' "$payload_file" | sha256sum | awk '{print $1}')"
      [[ "$(jq -er '.prior_attestation.acceptance_output.evidence_sha256' "$payload_file")" == "$prior_state_hash" ]] || die "prior acceptance state self-hash is invalid"
      prior_state_json="$(jq -cS '.prior_attestation.acceptance_output' "$payload_file")"
      (( ${#prior_state_json} <= 16384 )) || die "prior acceptance state exceeds the bounded 16 KiB limit"
    fi

    operation_temp_dir="$(mktemp -d /run/cosmas-runtime-acceptance.XXXXXX)"
    chmod 0700 "$operation_temp_dir"
    az rest --method get --url "https://management.azure.com${job_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/job.json" || die "cannot read exact runtime-acceptance job"
    chmod 0600 "$operation_temp_dir/job.json"
    key_vault_uri="$(jq -er '.key_vault_uri.value | strings | select(test("^https://[^/?#]+/$"))' "$probe_outputs")"
    jq -e \
      --arg job_id "${job_id,,}" \
      --arg image "$expected_image" \
      --arg identity_id "${runtime_identity_id,,}" \
      --arg client_id "$runtime_identity_client_id" \
      --arg environment_id "${container_environment_id,,}" \
      --arg box_id "$(jq -er '.box_id.value' "$probe_outputs")" \
      --arg web_origin "$(jq -er '.web_origin.value | strings' "$probe_outputs")" \
      --arg clerk_org "$(jq -er '.clerk_organization_id.value | strings' "$probe_outputs")" \
      --arg clerk_issuer "$(jq -er '.clerk_issuer_url.value | strings' "$probe_outputs")" \
      --arg clerk_jwks "$(jq -er '.clerk_jwks_url.value | strings' "$probe_outputs")" \
      --arg clerk_audience "$(jq -er '.clerk_audience.value | strings' "$probe_outputs")" \
      --arg blob_url "$(jq -er '.blob_account_url.value | strings' "$probe_outputs")" \
      --arg blob_container "$(jq -er '.blob_container_name.value | strings' "$probe_outputs")" \
      --arg database_secret "${key_vault_uri}secrets/database-url" \
      --arg redis_secret "${key_vault_uri}secrets/redis-url" \
      --arg evidence_secret "${key_vault_uri}secrets/human-deploy-evidence-reference" \
      --arg hmac_secret "${key_vault_uri}secrets/runtime-acceptance-hmac-key" '
        def env($name): first(.properties.template.containers[0].env[] | select(.name == $name));
        (.id | ascii_downcase) == $job_id and
        (.properties.environmentId | ascii_downcase) == $environment_id and
        .identity.type == "UserAssigned" and
        ((.identity.userAssignedIdentities | keys | map(ascii_downcase)) == [$identity_id]) and
        .properties.configuration.triggerType == "Manual" and
        .properties.configuration.replicaTimeout == 900 and
        .properties.configuration.replicaRetryLimit == 0 and
        .properties.configuration.manualTriggerConfig.parallelism == 1 and
        .properties.configuration.manualTriggerConfig.replicaCompletionCount == 1 and
        (.properties.configuration.registries | length) == 1 and
        (.properties.configuration.registries[0].identity | ascii_downcase) == $identity_id and
        (.properties.configuration.secrets | length) == 4 and
        ([.properties.configuration.secrets[] | {name, identity: (.identity | ascii_downcase), keyVaultUrl}] | sort_by(.name)) == ([
          {name: "acceptance-hmac-key", identity: $identity_id, keyVaultUrl: $hmac_secret},
          {name: "database-url", identity: $identity_id, keyVaultUrl: $database_secret},
          {name: "human-deploy-evidence-reference", identity: $identity_id, keyVaultUrl: $evidence_secret},
          {name: "redis-url", identity: $identity_id, keyVaultUrl: $redis_secret}
        ] | sort_by(.name)) and
        (.properties.template.containers | length) == 1 and
        .properties.template.containers[0].name == "runtime-acceptance" and
        .properties.template.containers[0].image == $image and
        .properties.template.containers[0].command == ["python", "-m", "cosmas_os.cli"] and
        .properties.template.containers[0].args == ["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"] and
        (.properties.template.containers[0].env | length) == 21 and
        env("COSMAS_ENV") == {name: "COSMAS_ENV", value: "early_adopter_beta"} and
        env("DATA_MODE") == {name: "DATA_MODE", value: "synthetic"} and
        env("AUTH_MODE") == {name: "AUTH_MODE", value: "clerk_jwt"} and
        env("CORS_ALLOWED_ORIGINS") == {name: "CORS_ALLOWED_ORIGINS", value: $web_origin} and
        env("SYNTH_SEED") == {name: "SYNTH_SEED", value: "false"} and
        env("BLOB_BACKEND") == {name: "BLOB_BACKEND", value: "azure"} and
        env("BETA_BOX_ID") == {name: "BETA_BOX_ID", value: $box_id} and
        env("CLERK_ORGANIZATION_ID") == {name: "CLERK_ORGANIZATION_ID", value: $clerk_org} and
        env("CLERK_ISSUER") == {name: "CLERK_ISSUER", value: $clerk_issuer} and
        env("CLERK_JWKS_URL") == {name: "CLERK_JWKS_URL", value: $clerk_jwks} and
        env("CLERK_AUDIENCE") == {name: "CLERK_AUDIENCE", value: $clerk_audience} and
        env("CLERK_AUTHORIZED_PARTIES") == {name: "CLERK_AUTHORIZED_PARTIES", value: $web_origin} and
        env("AZURE_CLIENT_ID") == {name: "AZURE_CLIENT_ID", value: $client_id} and
        env("EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID") == {name: "EXPECTED_RUNTIME_MANAGED_IDENTITY_CLIENT_ID", value: $client_id} and
        env("COSMAS_ACCEPTANCE_HMAC_KEY") == {name: "COSMAS_ACCEPTANCE_HMAC_KEY", secretRef: "acceptance-hmac-key"} and
        env("HUMAN_DEPLOY_EVIDENCE_REF") == {name: "HUMAN_DEPLOY_EVIDENCE_REF", secretRef: "human-deploy-evidence-reference"} and
        env("DATABASE_URL") == {name: "DATABASE_URL", secretRef: "database-url"} and
        env("REDIS_URL") == {name: "REDIS_URL", secretRef: "redis-url"} and
        env("AZURE_STORAGE_ACCOUNT_URL") == {name: "AZURE_STORAGE_ACCOUNT_URL", value: $blob_url} and
        env("AZURE_BLOB_CONTAINER") == {name: "AZURE_BLOB_CONTAINER", value: $blob_container} and
        env("SYNC_WORKER") == {name: "SYNC_WORKER", value: "false"}
      ' "$operation_temp_dir/job.json" >/dev/null || die "live runtime-acceptance job differs from the reviewed exact-digest/runtime-UAMI contract"

    jq -n \
      --arg phase "$acceptance_phase" \
      --arg prior_state_json "$prior_state_json" \
      --slurpfile job "$operation_temp_dir/job.json" '
        ($job[0].properties.template.containers[0]) as $container |
        def base_env: $container.env;
        def direct($args): {
          name: $container.name,
          image: $container.image,
          resources: $container.resources,
          command: ["python", "-m", "cosmas_os.cli"],
          args: $args,
          env: base_env
        };
        def verify($args): {
          name: $container.name,
          image: $container.image,
          resources: $container.resources,
          command: ["python", "-m", "cosmas_os.cli"],
          args: $args,
          env: (base_env + [{name: "COSMAS_ACCEPTANCE_STATE", value: $prior_state_json}])
        };
        {template: {containers: [
          if $phase == "runtime" then
            direct(["verify-beta-runtime", "--confirm-synthetic-only", "--confirm-runtime-uami"])
          elif $phase == "workflow-baseline" then
            direct(["baseline-beta-workflow-acceptance", "--confirm-synthetic-only", "--confirm-async-worker"])
          elif $phase == "workflow-verify" then
            verify(["verify-beta-workflow-acceptance", "--confirm-synthetic-only", "--confirm-browser-complete"])
          elif $phase == "purge-setup" then
            direct(["prepare-beta-purge-acceptance", "--confirm-synthetic-only", "--confirm-runtime-uami"])
          elif $phase == "purge-verify" then
            verify(["verify-beta-purge-acceptance", "--confirm-synthetic-only", "--confirm-runtime-uami", "--confirm-browser-complete"])
          else error("unreviewed acceptance phase") end
        ]}}
      ' >"$operation_temp_dir/start-request.json" || die "cannot construct the enumerated runtime-acceptance execution override"
    chmod 0600 "$operation_temp_dir/start-request.json"
    az rest --method post --url "https://management.azure.com${job_id}/start?api-version=2023-11-02-preview" --body @"$operation_temp_dir/start-request.json" --only-show-errors --output json >"$operation_temp_dir/start.json" || die "runtime-acceptance execution did not start"
    chmod 0600 "$operation_temp_dir/start.json"
    execution_name="$(jq -er '.name | strings | select(test("^[a-z0-9][a-z0-9-]{2,255}$"))' "$operation_temp_dir/start.json")" || die "runtime-acceptance start response lacks an exact execution name"
    execution_id="$job_id/executions/$execution_name"
    jq -e --arg execution_id "${execution_id,,}" '(.id | ascii_downcase) == $execution_id' "$operation_temp_dir/start.json" >/dev/null || die "runtime-acceptance start response is outside the exact job"
    execution_succeeded=false
    for _ in $(seq 1 120); do
      az rest --method get --url "https://management.azure.com${execution_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/execution.json" 2>/dev/null || true
      execution_status="$(jq -r '.properties.status // ""' "$operation_temp_dir/execution.json" 2>/dev/null || true)"
      if [[ "$execution_status" == "Succeeded" ]]; then
        execution_succeeded=true
        break
      fi
      [[ "$execution_status" != "Failed" && "$execution_status" != "Stopped" && "$execution_status" != "Degraded" ]] || die "runtime-acceptance execution failed; private diagnostics remain in Azure"
      sleep 10
    done
    [[ "$execution_succeeded" == "true" ]] || die "runtime-acceptance execution did not succeed within twenty minutes"
    jq -e --slurpfile requested "$operation_temp_dir/start-request.json" \
      --arg execution_id "${execution_id,,}" '
        (.id | ascii_downcase) == $execution_id and .properties.status == "Succeeded" and
        ((.properties.template.initContainers // []) | length) == 0 and
        (.properties.template.containers | length) == 1 and
        ([.properties.template.containers[0] | {
          name, image, command, args,
          env: ((.env // []) | sort_by(.name)),
          resources
        }]) == ([$requested[0].template.containers[0] | {
          name, image, command, args,
          env: ((.env // []) | sort_by(.name)),
          resources
        }])
      ' "$operation_temp_dir/execution.json" >/dev/null || die "realized runtime-acceptance execution differs from the exact reviewed image/command/args/environment override"

    az rest --method get --url "https://management.azure.com${job_id}?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/job-for-logs.json" || die "cannot read runtime-acceptance job log endpoint"
    event_stream_endpoint="$(jq -er '.properties.eventStreamEndpoint | strings | select(startswith("https://")) | split("/subscriptions/")[0]' "$operation_temp_dir/job-for-logs.json")" || die "runtime-acceptance job has no HTTPS event-stream endpoint"
    az rest --method post --url "https://management.azure.com${job_id}/getAuthToken?api-version=2023-11-02-preview" --body '{}' --only-show-errors --output json >"$operation_temp_dir/log-token.json" || die "cannot obtain ephemeral runtime-acceptance log token"
    log_token="$(jq -er '.properties.token | strings | select(test("^[A-Za-z0-9._~-]+$"))' "$operation_temp_dir/log-token.json")" || die "runtime-acceptance log token is invalid"
    az rest --method get --url "https://management.azure.com${execution_id}/replicas?api-version=2023-11-02-preview" --only-show-errors --output json >"$operation_temp_dir/replicas.json" || die "cannot list exact runtime-acceptance execution replicas"
    [[ "$(jq '.value | length' "$operation_temp_dir/replicas.json")" -eq 1 ]] || die "runtime-acceptance execution did not have exactly one replica"
    replica_name="$(jq -er '.value[0].name | strings | select(test("^[A-Za-z0-9._-]+$"))' "$operation_temp_dir/replicas.json")" || die "runtime-acceptance replica name is invalid"
    log_url="$event_stream_endpoint/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/jobs/$job_name/executions/$execution_name/replicas/$replica_name/containers/runtime-acceptance/logstream?follow=false&tailLines=50&output=json"
    [[ "$log_url" == https://* ]] || die "runtime-acceptance log URL is not HTTPS"
    curl_config_file="$operation_temp_dir/curl.conf"
    printf 'silent\nshow-error\nfail\nmax-time = 30\nheader = "Authorization: Bearer %s"\n' "$log_token" >"$curl_config_file"
    chmod 0600 "$curl_config_file"
    unset log_token
    evidence_found=false
    for _ in $(seq 1 60); do
      if curl --config "$curl_config_file" "$log_url" >"$operation_temp_dir/logstream.private" 2>/dev/null &&
        python3 - "$operation_temp_dir/logstream.private" "$operation_temp_dir/job-evidence.json" "$acceptance_phase" <<'PY'
import json
import sys

source, destination, phase = sys.argv[1:]
contracts = {
    "runtime": (
        "cosmas-os-d3-runtime-acceptance-v2",
        {
            "blob_backend", "blob_current_representation_absent_after_delete",
            "blob_version_representations_absent_after_delete",
            "blob_snapshot_representations_absent_after_delete",
            "blob_deleted_representations_absent_after_delete",
            "blob_recoverable_absence_verified", "blob_write_read_sha_match",
            "completed_at", "contract", "data_mode", "database_insert_read_rolled_back",
            "database_schema_at_expected_head", "database_schema_revision", "environment",
            "evidence_sha256", "redis_cleanup_confirmed", "redis_round_trip", "status",
            "sync_worker_disabled", "user_assigned_managed_identity",
        },
    ),
    "workflow-baseline": (
        "cosmas-os-d3-workflow-acceptance-v1",
        {
            "contract", "stage", "status", "issued_at", "expires_at", "state_mac",
            "evidence_sha256", "ticket_handle", "pending_ticket_count",
            "approval_decision_count", "operation_count", "approval_audit_count",
            "success_audit_count",
        },
    ),
    "workflow-verify": (
        "cosmas-os-d3-workflow-acceptance-v1",
        {
            "contract", "stage", "status", "completed_at", "state_bound",
            "async_dispatch_configured", "current_revision_valid", "approval_decision_delta",
            "durable_operation_delta", "worker_attempted", "operation_succeeded",
            "fake_notify_receipt_verified", "ticket_sent", "approval_audit_delta",
            "success_audit_delta", "approval_precedes_worker_success", "evidence_sha256",
        },
    ),
    "purge-setup": (
        "cosmas-os-d3-physical-purge-acceptance-v1",
        {
            "contract", "stage", "status", "issued_at", "expires_at", "state_mac",
            "evidence_sha256", "artifact_handle", "due_unpurged_artifact_count",
            "purge_audit_count", "blob_current_representation_readable",
        },
    ),
    "purge-verify": (
        "cosmas-os-d3-physical-purge-acceptance-v1",
        {
            "contract", "stage", "status", "completed_at", "state_bound",
            "owner_authorized_purge_observed", "owner_authority_verified", "application_tombstone_verified",
            "purge_receipt_verified", "purge_audit_delta", "blob_current_representation_absent",
            "blob_version_representations_absent", "blob_snapshot_representations_absent",
            "blob_deleted_representations_absent", "blob_recoverable_absence_verified",
            "due_unpurged_probe_count", "evidence_sha256",
        },
    ),
}
if phase not in contracts:
    raise SystemExit(1)
expected_contract, expected_keys = contracts[phase]
found = []

def visit(value):
    if isinstance(value, dict):
        if set(value) == expected_keys and value.get("contract") == expected_contract:
            found.append(value)
        for child in value.values():
            visit(child)
    elif isinstance(value, list):
        for child in value:
            visit(child)
    elif isinstance(value, str):
        normalized = value.replace("\\u0022", '"').replace("\\u002B", "+").replace("\\u0027", "'")
        start, end = normalized.find("{"), normalized.rfind("}")
        if 0 <= start < end:
            try:
                visit(json.loads(normalized[start : end + 1]))
            except json.JSONDecodeError:
                pass

raw = open(source, encoding="utf-8", errors="strict").read()
for line in raw.splitlines():
    visit(line)
    try:
        visit(json.loads(line))
    except json.JSONDecodeError:
        pass
unique = {json.dumps(item, sort_keys=True, separators=(",", ":")): item for item in found}
if len(unique) != 1:
    raise SystemExit(1)
with open(destination, "w", encoding="utf-8") as handle:
    handle.write(next(iter(unique)))
PY
      then
        evidence_found=true
        break
      fi
      sleep 5
    done
    [[ "$evidence_found" == "true" ]] || die "exact sanitized runtime-acceptance evidence was not available from the succeeded execution"
    chmod 0600 "$operation_temp_dir/job-evidence.json"
    jq -e --arg phase "$acceptance_phase" '
      (.evidence_sha256 | strings | test("^[0-9a-f]{64}$")) and
      if $phase == "runtime" then
        .contract == "cosmas-os-d3-runtime-acceptance-v2" and .status == "ready" and
        .environment == "early_adopter_beta" and .data_mode == "synthetic" and
        .blob_backend == "azure" and .sync_worker_disabled == true and
        .user_assigned_managed_identity == true and
        .blob_write_read_sha_match == true and
        .blob_current_representation_absent_after_delete == true and
        .blob_version_representations_absent_after_delete == true and
        .blob_snapshot_representations_absent_after_delete == true and
        .blob_deleted_representations_absent_after_delete == true and
        .blob_recoverable_absence_verified == true and
        .redis_round_trip == true and .redis_cleanup_confirmed == true and
        .database_schema_revision == "0002_external_identities" and
        .database_schema_at_expected_head == true and .database_insert_read_rolled_back == true
      elif $phase == "workflow-baseline" then
        .contract == "cosmas-os-d3-workflow-acceptance-v1" and .stage == "baseline" and
        .status == "ready_for_browser" and (.state_mac | test("^[0-9a-f]{64}$")) and
        (.ticket_handle | test("^[0-9a-f]{64}$")) and
        .pending_ticket_count == 1 and .approval_decision_count == 0 and
        .operation_count == 0 and .approval_audit_count == 0 and .success_audit_count == 0
      elif $phase == "workflow-verify" then
        .contract == "cosmas-os-d3-workflow-acceptance-v1" and .stage == "post_browser" and
        .status == "verified" and .state_bound == true and .async_dispatch_configured == true and
        .current_revision_valid == true and .approval_decision_delta == 1 and
        .durable_operation_delta == 1 and .worker_attempted == true and
        .operation_succeeded == true and .fake_notify_receipt_verified == true and
        .ticket_sent == true and .approval_audit_delta == 1 and .success_audit_delta == 1 and
        .approval_precedes_worker_success == true
      elif $phase == "purge-setup" then
        .contract == "cosmas-os-d3-physical-purge-acceptance-v1" and .stage == "setup" and
        .status == "ready_for_browser" and (.state_mac | test("^[0-9a-f]{64}$")) and
        (.artifact_handle | test("^[0-9a-f]{64}$")) and
        .due_unpurged_artifact_count == 1 and .purge_audit_count == 0 and
        .blob_current_representation_readable == true
      elif $phase == "purge-verify" then
        .contract == "cosmas-os-d3-physical-purge-acceptance-v1" and .stage == "post_browser" and
        .status == "verified" and .state_bound == true and .owner_authorized_purge_observed == true and
        .owner_authority_verified == true and .application_tombstone_verified == true and
        .purge_receipt_verified == true and .purge_audit_delta == 1 and
        .blob_current_representation_absent == true and
        .blob_version_representations_absent == true and
        .blob_snapshot_representations_absent == true and
        .blob_deleted_representations_absent == true and
        .blob_recoverable_absence_verified == true and .due_unpurged_probe_count == 0
      else false end
    ' "$operation_temp_dir/job-evidence.json" >/dev/null || die "runtime-acceptance evidence did not prove the exact requested synthetic contract"
    runtime_evidence_hash="$(jq -cS 'del(.evidence_sha256)' "$operation_temp_dir/job-evidence.json" | sha256sum | awk '{print $1}')"
    [[ "$(jq -er '.evidence_sha256' "$operation_temp_dir/job-evidence.json")" == "$runtime_evidence_hash" ]] || die "runtime-acceptance evidence self-hash is invalid"
    execution_root="$release_root/executions/runtime-acceptance/$acceptance_phase/$execution_name"
    [[ ! -e "$execution_root" && ! -L "$execution_root" ]] || die "runtime-acceptance execution evidence already exists"
    install -d -o root -g root -m 0700 "$execution_root"
    probe_payload="$(mktemp /run/cosmas-runtime-acceptance-attestation.XXXXXX)"
    jq -cS -n \
      --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg source_sha "$source_sha" --arg release_id "$release_id" --arg box_id "$GUARD_BOX_ID" \
      --arg acceptance_phase "$acceptance_phase" \
      --arg execution_id "$execution_id" --arg job_id "$job_id" \
      --arg image_digest "$expected_api_digest" --arg runtime_identity_id "$runtime_identity_id" \
      --arg runtime_identity_client_id "$runtime_identity_client_id" \
      --arg runtime_evidence_sha256 "$runtime_evidence_hash" \
      --arg state_lineage "$GUARD_STATE_LINEAGE" --argjson state_serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
      --slurpfile acceptance_output "$operation_temp_dir/job-evidence.json" '
        {
          schema_version: 1,
          evidence_type: "protected-runner-runtime-acceptance",
          completed_at: $completed_at,
          source_sha: $source_sha,
          release_id: $release_id,
          acceptance_phase: $acceptance_phase,
          state: {lineage: $state_lineage, serial: $state_serial, sha256: $state_sha256},
          execution: {job_id: $job_id, execution_id: $execution_id},
          workload: {
            box_id: $box_id,
            deployment_mode: "synthetic_lab",
            api_image_digest: $image_digest,
            runtime_identity_resource_id: $runtime_identity_id,
            runtime_identity_client_id: $runtime_identity_client_id
          },
          acceptance_output_sha256: $runtime_evidence_sha256,
          acceptance_output: $acceptance_output[0],
          secrets_returned: false
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    runtime_acceptance_evidence_tmp="$(mktemp "$execution_root/.attestation.XXXXXX")"
    jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$runtime_acceptance_evidence_tmp"
    chmod 0600 "$runtime_acceptance_evidence_tmp"
    jq -e --arg hash "$evidence_hash" '.schema_version == 1 and .evidence_payload_sha256 == $hash' "$runtime_acceptance_evidence_tmp" >/dev/null || die "generated runtime-acceptance attestation is invalid"
    ln -- "$runtime_acceptance_evidence_tmp" "$execution_root/attestation.json" || die "runtime-acceptance attestation appeared concurrently"
    rm -f -- "$runtime_acceptance_evidence_tmp"
    runtime_acceptance_evidence_tmp=""
    runtime_acceptance_pointer_tmp="$(mktemp "$release_root/.runtime-acceptance.$acceptance_phase.current.XXXXXX")"
    printf '%s\n' "$execution_name" >"$runtime_acceptance_pointer_tmp"
    chmod 0600 "$runtime_acceptance_pointer_tmp"
    mv -f -- "$runtime_acceptance_pointer_tmp" "$release_root/runtime-acceptance.$acceptance_phase.current"
    runtime_acceptance_pointer_tmp=""
    emit_sanitized_artifact "$execution_root/attestation.json"
    ;;
  domain-verification)
    [[ "$stage" == "domain" ]] || die "domain-verification requires stage=domain"
    jq -e 'type == "object" and length == 0' "$payload_file" >/dev/null || die "domain-verification does not accept an input payload"
    prepare_live_acceptance_context
    jq -e '
      .workloads_enabled.value == true and
      (.web_custom_domain.value | strings | test("^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$")) and
      .web_custom_domain.value != "app.cosmaneura.com" and
      .web_custom_domain.value != "staging-app.cosmaneura.com" and
      .web_custom_domain.value != "chat.cosmaneura.com" and
      .web_custom_domain.value != "staging-chat.cosmaneura.com" and
      .web_origin.value == ("https://" + .web_custom_domain.value) and
      .web_custom_domain_binding_enabled.value == false and
      (.web_default_fqdn.value | strings | test("^[a-z0-9.-]+\\.azurecontainerapps\\.io$")) and
      .web_fqdn.value == .web_default_fqdn.value and
      .web_custom_domain_verification_id.sensitive == true and
      (.web_custom_domain_verification_id.value | strings | test("^[A-Za-z0-9._~=-]{8,512}$"))
    ' "$probe_outputs" >/dev/null || die "custom-domain outputs are absent, already bound, reserved, or outside the exact reviewed web app"
    domain_root="$release_root/executions/domain-verification"
    domain_evidence_file="$domain_root/attestation.json"
    install -d -o root -g root -m 0700 "$domain_root"
    if [[ -e "$domain_evidence_file" || -L "$domain_evidence_file" ]]; then
      [[ -f "$domain_evidence_file" && ! -L "$domain_evidence_file" && "$(stat -c '%a' "$domain_evidence_file")" == "600" && "$(stat -c '%u' "$domain_evidence_file")" == "0" ]] || die "stored domain-verification evidence is unsafe"
      guard_validate_domain_verification_artifact "$domain_evidence_file" "$source_sha" "$release_id"
      jq -e \
        --arg lineage "$GUARD_STATE_LINEAGE" \
        --argjson serial "$GUARD_STATE_SERIAL" \
        --arg state_sha256 "$GUARD_STATE_SHA256" '
          .state == {lineage: $lineage, serial: $serial, sha256: $state_sha256}
        ' "$domain_evidence_file" >/dev/null || die "stored domain-verification evidence belongs to a different environment state"
      emit_sanitized_artifact "$domain_evidence_file"
      exit 0
    fi
    probe_payload="$(mktemp /run/cosmas-domain-verification.XXXXXX)"
    jq -cS -n \
      --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg source_sha "$source_sha" \
      --arg release_id "$release_id" \
      --arg lineage "$GUARD_STATE_LINEAGE" \
      --argjson serial "$GUARD_STATE_SERIAL" \
      --arg state_sha256 "$GUARD_STATE_SHA256" \
      --slurpfile outputs "$probe_outputs" '
        ($outputs[0].web_custom_domain.value) as $hostname |
        {
          schema_version: 1,
          evidence_type: "protected-runner-domain-verification",
          completed_at: $completed_at,
          source_sha: $source_sha,
          release_id: $release_id,
          state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
          selected_hostname: $hostname,
          cname_record: {type: "CNAME", name: $hostname, target: $outputs[0].web_default_fqdn.value},
          asuid_txt_record: {type: "TXT", name: ("asuid." + $hostname), value: $outputs[0].web_custom_domain_verification_id.value},
          public_dns_material_only: true,
          secrets_returned: false
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    domain_verification_evidence_tmp="$(mktemp "$domain_root/.attestation.XXXXXX")"
    jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$domain_verification_evidence_tmp"
    chmod 0600 "$domain_verification_evidence_tmp"
    guard_validate_domain_verification_artifact "$domain_verification_evidence_tmp" "$source_sha" "$release_id"
    ln -- "$domain_verification_evidence_tmp" "$domain_evidence_file" || die "domain-verification evidence appeared concurrently"
    rm -f -- "$domain_verification_evidence_tmp"
    domain_verification_evidence_tmp=""
    emit_sanitized_artifact "$domain_evidence_file"
    ;;
  alert-delivery)
    [[ "$stage" == "alert" ]] || die "alert-delivery requires stage=alert"
    validate_source
    verify_pinned_toolchain
    bind_release_to_source
    verify_release_network_evidence
    network_evidence_file="$VERIFIED_NETWORK_EVIDENCE"
    jq -e '
      type == "object" and
      ((.alert_phase == "send" and keys == ["alert_phase"]) or
       (.alert_phase == "confirm" and
        (keys | sort) == (["alert_phase", "confirmation", "prior_attestation"] | sort) and
        (.prior_attestation | type == "object") and
        (.confirmation | type == "object") and
        (.confirmation | keys | sort) == (["challenge", "confirmed_at", "confirmation_reference", "owner_assertion", "schema_version", "send_evidence_sha256"] | sort) and
        .confirmation.schema_version == 1 and
        .confirmation.owner_assertion == "I CONFIRM RECEIPT OF THE D3 ALERT TEST" and
        (.confirmation.challenge | strings | test("^[0-9a-f]{64}$")) and
        (.confirmation.send_evidence_sha256 | strings | test("^[0-9a-f]{64}$")) and
        (.confirmation.confirmed_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.confirmation.confirmation_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
        (.confirmation.confirmation_reference | contains("@") | not)))
    ' "$payload_file" >/dev/null || die "alert-delivery protected payload is invalid"
    alert_phase="$(jq -er '.alert_phase | select(. == "send" or . == "confirm")' "$payload_file")"
    fresh_managed_identity_login
    # shellcheck source=deployment-guard-lib.sh
    source "$repository_root/infra/beta/deployment-guard-lib.sh"
    GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
    guard_find_terraform
    guard_source_metadata "$repository_root"
    guard_load_bootstrap_outputs "$bootstrap_outputs"
    guard_verify_azure_context_and_boundary
    export TF_DATA_DIR="$release_root/alert-delivery-terraform-data"
    guard_backend_init >/dev/null
    probe_state="$(mktemp /run/cosmas-alert-delivery-state.XXXXXX)"
    guard_pull_state "$probe_state"
    guard_validate_environment_state "$probe_state"
    jq -e --slurpfile evidence "$network_evidence_file" '
      .lineage == $evidence[0].state.lineage and
      .serial == $evidence[0].state.serial
    ' "$probe_state" >/dev/null || die "re-probe the protected network after the workload apply before testing alert delivery"
    [[ "$GUARD_STATE_SHA256" == "$(jq -er '.state.sha256' "$network_evidence_file")" ]] || die "re-probe the protected network after the workload state changed"
    probe_outputs="$(mktemp /run/cosmas-alert-delivery-outputs.XXXXXX)"
    "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
    chmod 0600 "$probe_outputs"

    action_group_id="$(jq -er '.workload_health_action_group_id.value | strings' "$probe_outputs")"
    api_alert_id="$(jq -er '.api_unavailable_metric_alert_id.value | strings' "$probe_outputs")"
    worker_alert_id="$(jq -er '.worker_unavailable_metric_alert_id.value | strings' "$probe_outputs")"
    action_group_name="ag-cosmas-beta-$GUARD_BETA_ID"
    api_alert_name="alert-cosmas-beta-api-unavailable-$GUARD_BETA_ID"
    worker_alert_name="alert-cosmas-beta-worker-unavailable-$GUARD_BETA_ID"
    expected_action_group_id="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.Insights/actionGroups/$action_group_name"
    expected_api_alert_id="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.Insights/metricAlerts/$api_alert_name"
    expected_worker_alert_id="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.Insights/metricAlerts/$worker_alert_name"
    expected_api_scope="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.App/containerApps/ca-api-cosmas-beta-$GUARD_BETA_ID"
    expected_worker_scope="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.App/containerApps/ca-worker-cosmas-beta-$GUARD_BETA_ID"
    [[ "${action_group_id,,}" == "${expected_action_group_id,,}" ]] || die "workload Action Group output escaped the exact D3 resource boundary"
    [[ "${api_alert_id,,}" == "${expected_api_alert_id,,}" && "${worker_alert_id,,}" == "${expected_worker_alert_id,,}" ]] || die "workload metric-alert outputs escaped the exact D3 resource boundary"
    jq -e '
      .workloads_enabled.value == true and
      (.workload_health_action_group_id.value | strings) and
      (.api_unavailable_metric_alert_id.value | strings) and
      (.worker_unavailable_metric_alert_id.value | strings)
    ' "$probe_outputs" >/dev/null || die "workload health alerts are not enabled in the exact current state"

    operation_temp_dir="$(mktemp -d /run/cosmas-alert-delivery.XXXXXX)"
    chmod 0700 "$operation_temp_dir"
    az rest --method get --url "https://management.azure.com${action_group_id}?api-version=2024-10-01-preview" --only-show-errors --output json >"$operation_temp_dir/action-group.json" || die "cannot read exact D3 workload Action Group"
    az rest --method get --url "https://management.azure.com${api_alert_id}?api-version=2018-03-01" --only-show-errors --output json >"$operation_temp_dir/api-alert.json" || die "cannot read exact D3 API metric alert"
    az rest --method get --url "https://management.azure.com${worker_alert_id}?api-version=2018-03-01" --only-show-errors --output json >"$operation_temp_dir/worker-alert.json" || die "cannot read exact D3 worker metric alert"
    chmod 0600 "$operation_temp_dir/action-group.json" "$operation_temp_dir/api-alert.json" "$operation_temp_dir/worker-alert.json"
    jq -e \
      --arg id "${action_group_id,,}" --arg name "$action_group_name" \
      --arg mode "$GUARD_DEPLOYMENT_MODE" --arg classification "$GUARD_DATA_CLASSIFICATION" --arg box "$GUARD_BOX_ID" '
        (.id | ascii_downcase) == $id and .name == $name and (.location | ascii_downcase) == "global" and
        .tags == {
          track: "B", product: "cosmas-os", env: "early_adopter_beta",
          deployment_mode: $mode, data_classification: $classification,
          registry_posture: .tags.registry_posture,
          box_scope: "dedicated", box_id: $box, connectors: "dark", managed: "terraform"
        } and
        (.tags.registry_posture == "private" or .tags.registry_posture == "synthetic_public_exception") and
        .properties.enabled == true and .properties.groupShortName == "cosmasbeta" and
        (.properties.emailReceivers | length) == 1 and
        .properties.emailReceivers[0].name == "d3-owner" and
        .properties.emailReceivers[0].useCommonAlertSchema == true and
        (.properties.emailReceivers[0].emailAddress | strings | test("^[^@[:space:]]+@[^@[:space:]]+\\.[^@[:space:]]+$")) and
        ([
          .properties.armRoleReceivers, .properties.automationRunbookReceivers,
          .properties.azureAppPushReceivers, .properties.azureFunctionReceivers,
          .properties.eventHubReceivers, .properties.incidentReceivers,
          .properties.itsmReceivers, .properties.logicAppReceivers,
          .properties.smsReceivers, .properties.voiceReceivers,
          .properties.webhookReceivers
        ] | all((. // []) | length == 0))
      ' "$operation_temp_dir/action-group.json" >/dev/null || die "live workload Action Group differs from the exact email-only PHI-safe D3 contract"

    for alert_contract in "api|$api_alert_id|$expected_api_scope|PHI-safe D3 API availability alert: average active replicas below one.|$operation_temp_dir/api-alert.json" "worker|$worker_alert_id|$expected_worker_scope|PHI-safe D3 worker availability alert: average active replicas below one.|$operation_temp_dir/worker-alert.json"; do
      IFS='|' read -r alert_kind expected_alert_id expected_scope expected_description alert_file <<<"$alert_contract"
      jq -e \
        --arg id "${expected_alert_id,,}" --arg scope "${expected_scope,,}" --arg action_group "${action_group_id,,}" \
        --arg description "$expected_description" --arg mode "$GUARD_DEPLOYMENT_MODE" \
        --arg classification "$GUARD_DATA_CLASSIFICATION" --arg box "$GUARD_BOX_ID" '
          (.id | ascii_downcase) == $id and
          .location == "global" and .properties.description == $description and
          .properties.severity == 1 and .properties.enabled == true and
          .properties.autoMitigate == true and .properties.evaluationFrequency == "PT1M" and
          .properties.windowSize == "PT5M" and
          ((.properties.scopes | map(ascii_downcase)) == [$scope]) and
          .properties.targetResourceType == "Microsoft.App/containerApps" and
          (.properties.criteria["odata.type"] == "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria" or
           .properties.criteria.odataType == "Microsoft.Azure.Monitor.SingleResourceMultipleMetricCriteria") and
          (.properties.criteria.allOf | length) == 1 and
          .properties.criteria.allOf[0].metricName == "Replicas" and
          .properties.criteria.allOf[0].metricNamespace == "Microsoft.App/containerApps" and
          .properties.criteria.allOf[0].operator == "LessThan" and
          .properties.criteria.allOf[0].threshold == 1 and
          .properties.criteria.allOf[0].timeAggregation == "Average" and
          .properties.criteria.allOf[0].skipMetricValidation == false and
          (.properties.actions | length) == 1 and
          (.properties.actions[0].actionGroupId | ascii_downcase) == $action_group and
          .tags == {
            track: "B", product: "cosmas-os", env: "early_adopter_beta",
            deployment_mode: $mode, data_classification: $classification,
            registry_posture: .tags.registry_posture,
            box_scope: "dedicated", box_id: $box, connectors: "dark", managed: "terraform"
          } and
          (.tags.registry_posture == "private" or .tags.registry_posture == "synthetic_public_exception")
        ' "$alert_file" >/dev/null || die "live $alert_kind metric alert differs from the exact PHI-safe replica-health contract"
    done

    alert_root="$release_root/executions/alert-delivery"
    install -d -o root -g root -m 0700 "$alert_root"
    alert_delivery_file="$alert_root/$alert_phase-attestation.json"
    confirmation_reference_hash=""
    confirmation_assertion_hash=""
    if [[ "$alert_phase" == "confirm" ]]; then
      prior_evidence_hash="$(jq -er '.prior_attestation.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$payload_file")" || die "prior alert-delivery evidence hash is invalid"
      [[ "$(jq -cS '.prior_attestation | del(.evidence_payload_sha256)' "$payload_file" | sha256sum | awk '{print $1}')" == "$prior_evidence_hash" ]] || die "prior alert-delivery evidence was modified"
      stored_send_file="$alert_root/send-attestation.json"
      [[ -f "$stored_send_file" && ! -L "$stored_send_file" && "$(stat -c '%a' "$stored_send_file")" == "600" && "$(stat -c '%u' "$stored_send_file")" == "0" ]] || die "protected alert send evidence is unavailable or unsafe"
      [[ "$(jq -er '.evidence_payload_sha256' "$stored_send_file")" == "$prior_evidence_hash" ]] || die "owner confirmation does not reference the protected runner's exact send evidence"
      cmp -s <(jq -cS . "$stored_send_file") <(jq -cS '.prior_attestation' "$payload_file") || die "owner confirmation supplied a forged or modified alert send artifact"
      jq -e \
        --arg source_sha "$source_sha" --arg release_id "$release_id" \
        --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
        --arg action_group_id "${action_group_id,,}" --arg api_alert_id "${api_alert_id,,}" --arg worker_alert_id "${worker_alert_id,,}" '
          .prior_attestation.schema_version == 1 and
          .prior_attestation.evidence_type == "protected-runner-alert-delivery" and
          .prior_attestation.alert_phase == "send" and
          .prior_attestation.source_sha == $source_sha and .prior_attestation.release_id == $release_id and
          .prior_attestation.state == {lineage: $lineage, serial: $serial, sha256: $state_sha256} and
          (.prior_attestation.action_group.resource_id | ascii_downcase) == $action_group_id and
          (.prior_attestation.metric_alerts.api.resource_id | ascii_downcase) == $api_alert_id and
          (.prior_attestation.metric_alerts.worker.resource_id | ascii_downcase) == $worker_alert_id and
          .prior_attestation.notification_test == {
            alert_type: "metricstaticthreshold", azure_operation_completed: true,
            email_action_count: 1, email_action_succeeded: true,
            delivery_confirmed_by_owner: false
          } and
          (.prior_attestation.confirmation_challenge | strings | test("^[0-9a-f]{64}$")) and
          (.prior_attestation.notification_operation_sha256 | strings | test("^[0-9a-f]{64}$")) and
          .prior_attestation.recipient_address_returned == false and
          .prior_attestation.secrets_returned == false
        ' "$payload_file" >/dev/null || die "prior alert send evidence is not bound to this source/release/state/Action Group"
      jq -e --arg send_hash "$prior_evidence_hash" '
        .confirmation.challenge == .prior_attestation.confirmation_challenge and
        .confirmation.send_evidence_sha256 == $send_hash
      ' "$payload_file" >/dev/null || die "owner alert assertion does not bind the unpredictable send challenge and exact send evidence"
      python3 - "$payload_file" <<'PY' || die "owner alert assertion timestamp is outside the bounded four-hour confirmation window"
from datetime import UTC, datetime, timedelta
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
sent = datetime.strptime(value["prior_attestation"]["completed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
confirmed = datetime.strptime(value["confirmation"]["confirmed_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
now = datetime.now(UTC)
if confirmed < sent or confirmed > sent + timedelta(hours=4) or confirmed > now + timedelta(minutes=5) or confirmed < now - timedelta(hours=4):
    raise SystemExit(1)
PY
      confirmation_reference_hash="$(jq -j '.confirmation.confirmation_reference' "$payload_file" | sha256sum | awk '{print $1}')"
      confirmation_assertion_hash="$(jq -cS '.confirmation' "$payload_file" | sha256sum | awk '{print $1}')"
    fi

    if [[ -e "$alert_delivery_file" || -L "$alert_delivery_file" ]]; then
      [[ -f "$alert_delivery_file" && ! -L "$alert_delivery_file" && "$(stat -c '%a' "$alert_delivery_file")" == "600" && "$(stat -c '%u' "$alert_delivery_file")" == "0" ]] || die "existing alert-delivery attestation is unsafe"
      stored_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$alert_delivery_file")" || die "existing alert-delivery attestation hash is invalid"
      [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$alert_delivery_file" | sha256sum | awk '{print $1}')" == "$stored_hash" ]] || die "existing alert-delivery attestation was modified"
      jq -e \
        --arg source_sha "$source_sha" --arg release_id "$release_id" --arg phase "$alert_phase" \
        --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
        --arg confirmation_hash "$confirmation_reference_hash" --arg assertion_hash "$confirmation_assertion_hash" '
          .schema_version == 1 and .evidence_type == "protected-runner-alert-delivery" and
          .source_sha == $source_sha and .release_id == $release_id and .alert_phase == $phase and
          .state == {lineage: $lineage, serial: $serial, sha256: $state_sha256} and
          (if $phase == "confirm" then
             .delivery_confirmation_reference_sha256 == $confirmation_hash and
             .owner_confirmation_assertion_sha256 == $assertion_hash
           else true end)
        ' "$alert_delivery_file" >/dev/null || die "existing alert-delivery attestation is not the exact requested evidence"
    else
      if [[ "$alert_phase" == "send" ]]; then
        jq -cS '{
          alertType: "metricstaticthreshold",
          emailReceivers: [.properties.emailReceivers[0] | {name, emailAddress, useCommonAlertSchema}]
        }' "$operation_temp_dir/action-group.json" >"$operation_temp_dir/notification-request.json"
        chmod 0600 "$operation_temp_dir/notification-request.json"
        az account get-access-token --resource https://management.azure.com/ --query accessToken --output tsv >"$operation_temp_dir/arm-token" 2>/dev/null || die "cannot obtain an ephemeral ARM token for the Action Group delivery test"
        chmod 0600 "$operation_temp_dir/arm-token"
        arm_token="$(cat "$operation_temp_dir/arm-token")"
        [[ "$arm_token" =~ ^[A-Za-z0-9._~-]+$ ]] || die "ephemeral ARM token has an invalid shape"
        curl_config_file="$operation_temp_dir/curl.conf"
        printf 'silent\nshow-error\nfail-with-body\nmax-time = 30\nheader = "Authorization: Bearer %s"\nheader = "Content-Type: application/json"\nheader = "Accept: application/json"\n' "$arm_token" >"$curl_config_file"
        chmod 0600 "$curl_config_file"
        unset arm_token
        rm -f -- "$operation_temp_dir/arm-token"
        notification_url="https://management.azure.com${action_group_id}/createNotifications?api-version=2024-10-01-preview"
        notification_status="$(curl --config "$curl_config_file" --request POST --data-binary "@$operation_temp_dir/notification-request.json" --dump-header "$operation_temp_dir/notification-headers" --output "$operation_temp_dir/notification-response.json" --write-out '%{http_code}' "$notification_url" 2>/dev/null)" || die "Azure Action Group delivery test request failed"
        [[ "$notification_status" == "200" || "$notification_status" == "202" ]] || die "Azure Action Group delivery test returned an unexpected status"
        notification_completed=false
        if [[ -s "$operation_temp_dir/notification-response.json" ]] && jq -e '(.state | ascii_downcase) == "completed"' "$operation_temp_dir/notification-response.json" >/dev/null 2>&1; then
          notification_completed=true
        else
          notification_location="$(awk 'BEGIN {IGNORECASE=1} /^location:/ {sub(/^[^:]*:[[:space:]]*/, ""); sub(/\r$/, ""); print; exit}' "$operation_temp_dir/notification-headers")"
          location_prefix="https://management.azure.com/subscriptions/${subscription_id}/"
          [[ "${notification_location,,}" == "${location_prefix,,}"* && "$notification_location" != *"@"* && "$notification_location" != *"#"* ]] || die "Action Group test returned an unsafe or cross-subscription polling location"
          for _ in $(seq 1 60); do
            notification_status="$(curl --config "$curl_config_file" --request GET --output "$operation_temp_dir/notification-response.json" --write-out '%{http_code}' "$notification_location" 2>/dev/null)" || die "Action Group delivery-test polling failed"
            [[ "$notification_status" == "200" || "$notification_status" == "202" ]] || die "Action Group delivery-test poll returned an unexpected status"
            if [[ "$notification_status" == "200" ]] && jq -e '(.state | ascii_downcase) == "completed"' "$operation_temp_dir/notification-response.json" >/dev/null 2>&1; then
              notification_completed=true
              break
            fi
            if [[ "$notification_status" == "200" ]]; then
              jq -e '((.state // "") | ascii_downcase) == "created" or ((.state // "") | ascii_downcase) == "started" or ((.state // "") | ascii_downcase) == "running"' "$operation_temp_dir/notification-response.json" >/dev/null 2>&1 || die "Action Group delivery test entered a non-success terminal state"
            fi
            sleep 10
          done
        fi
        [[ "$notification_completed" == "true" ]] || die "Action Group delivery test did not complete within ten minutes"
        jq -e '
          (.state | ascii_downcase) == "completed" and
          (.actionDetails | length) == 1 and
          ((.actionDetails[0].MechanismType // .actionDetails[0].mechanismType // "") | ascii_downcase) == "email" and
          ((.actionDetails[0].Status // .actionDetails[0].status // "") | ascii_downcase) == "succeeded"
        ' "$operation_temp_dir/notification-response.json" >/dev/null || die "Action Group test did not prove exactly one succeeded email action"
        confirmation_challenge="$(dd if=/dev/urandom bs=32 count=1 status=none | sha256sum | awk '{print $1}')"
        [[ "$confirmation_challenge" =~ ^[0-9a-f]{64}$ ]] || die "cannot generate an unpredictable alert confirmation challenge"
        notification_operation_sha256="$(jq -cS -n \
          --arg request_sha256 "$(sha256sum "$operation_temp_dir/notification-request.json" | awk '{print $1}')" \
          --arg response_sha256 "$(sha256sum "$operation_temp_dir/notification-response.json" | awk '{print $1}')" \
          --arg http_status "$notification_status" \
          '{request_sha256: $request_sha256, response_sha256: $response_sha256, final_http_status: $http_status}' | sha256sum | awk '{print $1}')"
        probe_payload="$(mktemp /run/cosmas-alert-delivery-attestation.XXXXXX)"
        jq -cS -n \
          --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
          --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
          --arg box_id "$GUARD_BOX_ID" --arg deployment_mode "$GUARD_DEPLOYMENT_MODE" \
          --arg action_group_id "$action_group_id" --arg api_alert_id "$api_alert_id" --arg api_scope "$expected_api_scope" \
          --arg worker_alert_id "$worker_alert_id" --arg worker_scope "$expected_worker_scope" \
          --arg confirmation_challenge "$confirmation_challenge" --arg notification_operation_sha256 "$notification_operation_sha256" '
            {
              schema_version: 1,
              evidence_type: "protected-runner-alert-delivery",
              alert_phase: "send",
              completed_at: $completed_at,
              source_sha: $source_sha,
              release_id: $release_id,
              state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
              boundary: {box_id: $box_id, deployment_mode: $deployment_mode},
              action_group: {
                resource_id: $action_group_id, enabled: true, email_receiver_count: 1,
                common_alert_schema: true, email_only: true
              },
              metric_alerts: {
                api: {resource_id: $api_alert_id, scope: $api_scope, replicas_below_one: true},
                worker: {resource_id: $worker_alert_id, scope: $worker_scope, replicas_below_one: true}
              },
              notification_test: {
                alert_type: "metricstaticthreshold", azure_operation_completed: true,
                email_action_count: 1, email_action_succeeded: true,
                delivery_confirmed_by_owner: false
              },
              confirmation_challenge: $confirmation_challenge,
              notification_operation_sha256: $notification_operation_sha256,
              recipient_address_returned: false,
              secrets_returned: false
            }
          ' >"$probe_payload"
      else
        probe_payload="$(mktemp /run/cosmas-alert-delivery-confirmation.XXXXXX)"
        jq -cS -n \
          --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
          --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
          --arg box_id "$GUARD_BOX_ID" --arg deployment_mode "$GUARD_DEPLOYMENT_MODE" \
          --arg action_group_id "$action_group_id" --arg send_evidence_sha256 "$prior_evidence_hash" \
          --arg delivery_confirmation_reference_sha256 "$confirmation_reference_hash" \
          --arg owner_confirmation_assertion_sha256 "$confirmation_assertion_hash" \
          --arg confirmation_challenge "$(jq -er '.confirmation.challenge' "$payload_file")" \
          --arg confirmed_at "$(jq -er '.confirmation.confirmed_at' "$payload_file")" '
            {
              schema_version: 1,
              evidence_type: "protected-runner-alert-delivery",
              alert_phase: "confirm",
              completed_at: $completed_at,
              source_sha: $source_sha,
              release_id: $release_id,
              state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
              boundary: {box_id: $box_id, deployment_mode: $deployment_mode},
              action_group: {resource_id: $action_group_id, enabled: true, email_only: true},
              send_evidence_sha256: $send_evidence_sha256,
              confirmation_challenge: $confirmation_challenge,
              owner_confirmed_at: $confirmed_at,
              delivery_confirmation_reference_sha256: $delivery_confirmation_reference_sha256,
              owner_confirmation_assertion_sha256: $owner_confirmation_assertion_sha256,
              delivery_confirmed_by_owner: true,
              recipient_address_returned: false,
              secrets_returned: false
            }
          ' >"$probe_payload"
      fi
      evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
      alert_delivery_evidence_tmp="$(mktemp "$alert_root/.$alert_phase-attestation.XXXXXX")"
      jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$alert_delivery_evidence_tmp"
      chmod 0600 "$alert_delivery_evidence_tmp"
      jq -e --arg hash "$evidence_hash" '.schema_version == 1 and .evidence_payload_sha256 == $hash and .recipient_address_returned == false and .secrets_returned == false' "$alert_delivery_evidence_tmp" >/dev/null || die "generated alert-delivery evidence is invalid"
      ln -- "$alert_delivery_evidence_tmp" "$alert_delivery_file" || die "alert-delivery evidence appeared concurrently"
      rm -f -- "$alert_delivery_evidence_tmp"
      alert_delivery_evidence_tmp=""
    fi
    emit_sanitized_artifact "$alert_delivery_file"
    ;;
  pitr-freeze|pitr-manifest|pitr-start|pitr-complete|pitr-cleanup|pitr-resume)
    [[ "$stage" == "pitr" ]] || die "$operation requires stage=pitr"
    pitr_phase="${operation#pitr-}"
    jq -e --arg phase "$pitr_phase" '
      type == "object" and .pitr_phase == $phase and
      if $phase == "freeze" then
        keys == ["pitr_phase", "quiet_window_end_utc"] and
        (.quiet_window_end_utc | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))
      elif $phase == "manifest" then
        keys == ["pitr_phase", "restore_time_utc"] and
        (.restore_time_utc | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"))
      elif $phase == "resume" then
        (keys | sort) == (["owner_approval", "pitr_phase"] | sort) and
        (.owner_approval | type == "object") and
        (.owner_approval | keys | sort) == (["approved_at", "confirmation", "freeze_evidence_sha256", "reviewer_reference", "schema_version"] | sort) and
        .owner_approval.schema_version == 1 and .owner_approval.confirmation == "RESUME D3 WRITERS"
      else
        (keys | sort) == (["owner_approval", "pitr_phase"] | sort) and
        (.owner_approval | type == "object") and
        (.owner_approval | keys | sort) == (["approved_at", "confirmation", "manifest_sha256", "reviewer_reference", "schema_version"] | sort) and
        .owner_approval.schema_version == 1 and .owner_approval.confirmation == "AUTHORIZE D3 BILLABLE PITR"
      end
    ' "$payload_file" >/dev/null || die "protected PITR payload is invalid"
    prepare_pitr_context
    operation_temp_dir="$(mktemp -d /run/cosmas-pitr-operation.XXXXXX)"
    chmod 0700 "$operation_temp_dir"

    if [[ "$pitr_phase" == "freeze" ]]; then
      quiet_window_end="$(jq -er '.quiet_window_end_utc' "$payload_file")"
      python3 - "$quiet_window_end" <<'PY' || die "PITR quiet-window end must be 20 minutes to 4 hours in the future"
from datetime import UTC, datetime, timedelta
import sys

end = datetime.strptime(sys.argv[1], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
remaining = end - datetime.now(UTC)
if remaining < timedelta(minutes=20) or remaining > timedelta(hours=4):
    raise SystemExit(1)
PY
      pitr_get_live_topology "$operation_temp_dir/topology"
      if [[ ! -e "$PITR_FREEZE_STATE" && ! -L "$PITR_FREEZE_STATE" ]]; then
        api_revision="$(jq -er --arg image "$PITR_API_IMAGE" '
          [.value[] | select(.properties.active == true and .properties.template.containers[0].image == $image and (.properties.replicas // 0) >= 1)] |
          if length == 1 then .[0].name else error("not one active exact API revision") end
        ' "$operation_temp_dir/topology/api-revisions.json")" || die "PITR freeze requires exactly one active healthy API revision at the accepted digest"
        worker_revision="$(jq -er --arg image "$PITR_API_IMAGE" '
          [.value[] | select(.properties.active == true and .properties.template.containers[0].image == $image and (.properties.replicas // 0) == 1)] |
          if length == 1 then .[0].name else error("not one active exact worker revision") end
        ' "$operation_temp_dir/topology/worker-revisions.json")" || die "PITR freeze requires exactly one active one-replica worker revision at the accepted digest"
        [[ "$api_revision" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$ && "$worker_revision" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$ ]] || die "active writer revision names are invalid"
        freeze_payload="$(mktemp "$PITR_ROOT/.freeze-state-payload.XXXXXX")"
        jq -cS -n \
          --arg requested_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg quiet_window_end_utc "$quiet_window_end" \
          --arg source_sha "$source_sha" --arg release_id "$release_id" --arg box_id "$GUARD_BOX_ID" \
          --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
          --arg api_id "$PITR_API_ID" --arg api_revision "$api_revision" --arg api_image "$PITR_API_IMAGE" \
          --arg worker_id "$PITR_WORKER_ID" --arg worker_revision "$worker_revision" '
            {
              schema_version: 1, contract: "cosmas-os-d3-pitr-writer-freeze-state-v1", phase: "freezing",
              source_sha: $source_sha, release_id: $release_id, box_id: $box_id,
              state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
              freeze_requested_at: $requested_at,
              quiet_window_start_utc: null, quiet_window_end_utc: $quiet_window_end_utc,
              writers: {
                api: {resource_id: $api_id, revision: $api_revision, image: $api_image},
                worker: {resource_id: $worker_id, revision: $worker_revision, image: $api_image}
              }
            }
          ' >"$freeze_payload"
        freeze_hash="$(sha256sum "$freeze_payload" | awk '{print $1}')"
        freeze_complete="$(mktemp "$PITR_ROOT/.freeze-state-complete.XXXXXX")"
        jq -S --arg hash "$freeze_hash" '. + {freeze_state_sha256: $hash}' "$freeze_payload" >"$freeze_complete"
        chmod 0600 "$freeze_complete"
        ln -- "$freeze_complete" "$PITR_FREEZE_STATE" || die "PITR writer-freeze state appeared concurrently"
        rm -f -- "$freeze_payload" "$freeze_complete"
      fi
      pitr_validate_freeze_state
      [[ "$(jq -er '.phase' "$PITR_FREEZE_STATE")" != "resumed" ]] || die "this release already completed its PITR writer-freeze cycle; use a new release ID"
      [[ "$(jq -er '.quiet_window_end_utc' "$PITR_FREEZE_STATE")" == "$quiet_window_end" ]] || die "PITR freeze retry changed the immutable quiet-window end"
      api_revision="$(jq -er '.writers.api.revision' "$PITR_FREEZE_STATE")"
      worker_revision="$(jq -er '.writers.worker.revision' "$PITR_FREEZE_STATE")"
      for app_contract in "api|$PITR_API_ID|$api_revision|$operation_temp_dir/topology/api-revisions.json" "worker|$PITR_WORKER_ID|$worker_revision|$operation_temp_dir/topology/worker-revisions.json"; do
        IFS='|' read -r app_kind app_id revision_name revisions_file <<<"$app_contract"
        jq -e --arg revision "$revision_name" '
          ([.value[] | select(.properties.active == true and .name != $revision)] | length) == 0 and
          ([.value[] | select(.name == $revision)] | length) == 1
        ' "$revisions_file" >/dev/null || die "an unexpected $app_kind revision prevents the exact PITR freeze"
        if jq -e --arg revision "$revision_name" 'any(.value[]; .name == $revision and .properties.active == true)' "$revisions_file" >/dev/null; then
          az rest --method post --url "https://management.azure.com${app_id}/revisions/${revision_name}/deactivate?api-version=2024-03-01" --body '{}' --only-show-errors --output none || die "cannot deactivate the exact $app_kind writer revision"
        fi
      done
      writers_frozen=false
      for _ in $(seq 1 60); do
        pitr_get_live_topology "$operation_temp_dir/frozen"
        if jq -e '([.value[] | select(.properties.active == true)] | length) == 0 and ([.value[] | (.properties.replicas // 0)] | add // 0) == 0' "$operation_temp_dir/frozen/api-revisions.json" >/dev/null &&
          jq -e '([.value[] | select(.properties.active == true)] | length) == 0 and ([.value[] | (.properties.replicas // 0)] | add // 0) == 0' "$operation_temp_dir/frozen/worker-revisions.json" >/dev/null; then
          writers_frozen=true
          break
        fi
        sleep 10
      done
      [[ "$writers_frozen" == "true" ]] || die "API/worker revisions did not reach zero active replicas within ten minutes"
      pitr_assert_writers_frozen "$operation_temp_dir/final-frozen"
      [[ "$(jq -er '.phase' "$PITR_FREEZE_STATE")" == "frozen" ]] || pitr_set_freeze_phase frozen frozen_at
      if [[ ! -e "$PITR_FREEZE_EVIDENCE" && ! -L "$PITR_FREEZE_EVIDENCE" ]]; then
        probe_payload="$(mktemp /run/cosmas-pitr-freeze-evidence.XXXXXX)"
        jq -cS -n \
          --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
          --arg box_id "$GUARD_BOX_ID" --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
          --arg quiet_start "$(jq -er '.quiet_window_start_utc' "$PITR_FREEZE_STATE")" --arg quiet_end "$(jq -er '.quiet_window_end_utc' "$PITR_FREEZE_STATE")" \
          --arg freeze_state_sha256 "$(jq -er '.freeze_state_sha256' "$PITR_FREEZE_STATE")" '
            {
              schema_version: 1, evidence_type: "protected-runner-pitr", pitr_phase: "freeze",
              completed_at: $completed_at, source_sha: $source_sha, release_id: $release_id,
              state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
              boundary: {box_id: $box_id, deployment_mode: "synthetic_lab", data_classification: "synthetic-only"},
              quiet_window: {start_utc: $quiet_start, end_utc: $quiet_end},
              pitr_status: "writers_frozen",
              writer_freeze: {
                freeze_state_sha256: $freeze_state_sha256,
                exact_api_revision_inactive: true, exact_worker_revision_inactive: true,
                active_api_replicas: 0, active_worker_replicas: 0,
                database_preparation_job_idle: true, runtime_acceptance_job_idle: true
              },
              writers_resumed: false, secrets_returned: false
            }
          ' >"$probe_payload"
        evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
        evidence_tmp="$(mktemp "$PITR_ROOT/.freeze-attestation.XXXXXX")"
        jq -S --arg hash "$evidence_hash" '. + {evidence_payload_sha256: $hash}' "$probe_payload" >"$evidence_tmp"
        chmod 0600 "$evidence_tmp"
        ln -- "$evidence_tmp" "$PITR_FREEZE_EVIDENCE" || die "PITR writer-freeze evidence appeared concurrently"
        rm -f -- "$evidence_tmp"
      fi
      stored_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$PITR_FREEZE_EVIDENCE")" || die "PITR writer-freeze evidence hash is invalid"
      [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$PITR_FREEZE_EVIDENCE" | sha256sum | awk '{print $1}')" == "$stored_hash" ]] || die "PITR writer-freeze evidence was modified"
      emit_sanitized_artifact "$PITR_FREEZE_EVIDENCE"
      exit 0
    fi

    pitr_validate_freeze_state
    if [[ "$pitr_phase" == "resume" ]]; then
      [[ "$(jq -er '.phase' "$PITR_FREEZE_STATE")" == "frozen" || "$(jq -er '.phase' "$PITR_FREEZE_STATE")" == "resumed" ]] || die "PITR writer state cannot be resumed from its current phase"
    else
      [[ "$(jq -er '.phase' "$PITR_FREEZE_STATE")" == "frozen" ]] || die "PITR writers are not in the exact protected frozen phase"
      pitr_assert_writers_frozen "$operation_temp_dir/current-frozen"
    fi
    [[ -f "$PITR_FREEZE_EVIDENCE" && ! -L "$PITR_FREEZE_EVIDENCE" && "$(stat -c '%a' "$PITR_FREEZE_EVIDENCE")" == "600" && "$(stat -c '%u' "$PITR_FREEZE_EVIDENCE")" == "0" ]] || die "PITR writer-freeze evidence is unavailable or unsafe"
    freeze_evidence_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$PITR_FREEZE_EVIDENCE")" || die "PITR writer-freeze evidence hash is invalid"
    [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$PITR_FREEZE_EVIDENCE" | sha256sum | awk '{print $1}')" == "$freeze_evidence_hash" ]] || die "PITR writer-freeze evidence was modified"

    if [[ "$pitr_phase" == "resume" ]]; then
      jq -e --arg freeze_hash "$freeze_evidence_hash" '
        .owner_approval.schema_version == 1 and .owner_approval.confirmation == "RESUME D3 WRITERS" and
        .owner_approval.freeze_evidence_sha256 == $freeze_hash and
        (.owner_approval.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
        (.owner_approval.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
        (.owner_approval.reviewer_reference | contains("@") | not)
      ' "$payload_file" >/dev/null || die "PITR resume assertion is not bound to the exact writer freeze"
      python3 - "$payload_file" <<'PY' || die "PITR resume assertion timestamp is outside its bounded four-hour window"
from datetime import UTC, datetime, timedelta
import json
import sys

approved = datetime.strptime(json.load(open(sys.argv[1], encoding="utf-8"))["owner_approval"]["approved_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
now = datetime.now(UTC)
if approved > now + timedelta(minutes=5) or approved < now - timedelta(hours=4):
    raise SystemExit(1)
PY
      if [[ -e "$PITR_MANIFEST" || -L "$PITR_MANIFEST" ]]; then
        terminal_pointer=""
        for terminal_phase in complete cleanup; do
          terminal_phase_pointer="$PITR_ROOT/evidence/$terminal_phase.current"
          if [[ -f "$terminal_phase_pointer" && ! -L "$terminal_phase_pointer" ]]; then
            terminal_name="$(cat "$terminal_phase_pointer")"
            [[ "$terminal_name" =~ ^[0-9a-f]{64}\.json$ ]] || die "PITR terminal evidence pointer is invalid"
            terminal_file="$PITR_ROOT/evidence/$terminal_name"
            terminal_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$terminal_file" 2>/dev/null || true)"
            if [[ "$terminal_hash" =~ ^[0-9a-f]{64}$ && "$(jq -cS 'del(.evidence_payload_sha256)' "$terminal_file" | sha256sum | awk '{print $1}')" == "$terminal_hash" ]] &&
              jq -e '(.pitr_phase == "complete" and .pitr_status == "verified") or (.pitr_phase == "cleanup" and .pitr_status == "cleaned")' "$terminal_file" >/dev/null 2>&1; then
              terminal_pointer="$terminal_file"
            fi
          fi
        done
        [[ -n "$terminal_pointer" ]] || die "PITR resume requires verified completion or proved cleanup after a manifest exists"
      fi
      pitr_resume_exact_writers "$operation_temp_dir"
      pitr_set_freeze_phase resumed resumed_at
      owner_approval_sha256="$(jq -cS '.owner_approval' "$payload_file" | sha256sum | awk '{print $1}')"
      probe_payload="$(mktemp /run/cosmas-pitr-resume-evidence.XXXXXX)"
      jq -cS -n \
        --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
        --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
        --arg freeze_evidence_sha256 "$freeze_evidence_hash" --arg owner_approval_sha256 "$owner_approval_sha256" '
          {
            schema_version: 1, evidence_type: "protected-runner-pitr", pitr_phase: "resume",
            pitr_status: "writers_resumed", completed_at: $completed_at,
            source_sha: $source_sha, release_id: $release_id,
            state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
            freeze_evidence_sha256: $freeze_evidence_sha256,
            owner_approval_sha256: $owner_approval_sha256,
            exact_api_revision_reactivated: true, exact_worker_revision_reactivated: true,
            api_health_verified: true, writers_resumed: true, secrets_returned: false
          }
        ' >"$probe_payload"
    else
      if [[ "$pitr_phase" == "manifest" ]]; then
        jq -e 'keys == ["pitr_phase", "restore_time_utc"]' "$payload_file" >/dev/null || die "PITR manifest accepts only the exact restore timestamp"
        [[ ! -e "$PITR_MANIFEST" && ! -L "$PITR_MANIFEST" ]] || die "PITR manifest already exists; retrieve it or use a new release"
        pitr_restore_time="$(jq -er '.restore_time_utc' "$payload_file")"
        owner_approval_sha256=""
      else
        [[ -f "$PITR_MANIFEST" && ! -L "$PITR_MANIFEST" && "$(stat -c '%a' "$PITR_MANIFEST")" == "400" && "$(stat -c '%u' "$PITR_MANIFEST")" == "0" ]] || die "approved private PITR manifest is unavailable or unsafe"
        manifest_sha256="$(jq -er '.manifest_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$PITR_MANIFEST")" || die "private PITR manifest hash is invalid"
        [[ "$(jq -cS 'del(.manifest_sha256)' "$PITR_MANIFEST" | sha256sum | awk '{print $1}')" == "$manifest_sha256" ]] || die "private PITR manifest was modified"
        jq -e --arg manifest_sha256 "$manifest_sha256" '
          .owner_approval.schema_version == 1 and
          .owner_approval.confirmation == "AUTHORIZE D3 BILLABLE PITR" and
          .owner_approval.manifest_sha256 == $manifest_sha256 and
          (.owner_approval.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
          (.owner_approval.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
          (.owner_approval.reviewer_reference | contains("@") | not)
        ' "$payload_file" >/dev/null || die "PITR owner approval does not bind the exact private manifest"
        python3 - "$payload_file" "$PITR_MANIFEST" "$pitr_phase" <<'PY' || die "PITR owner approval timestamp is invalid for this phase"
from datetime import UTC, datetime, timedelta
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
manifest = json.load(open(sys.argv[2], encoding="utf-8"))
phase = sys.argv[3]
approved = datetime.strptime(payload["owner_approval"]["approved_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
created = datetime.strptime(manifest["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
now = datetime.now(UTC)
if approved < created or approved > now + timedelta(minutes=5) or (phase == "start" and now - approved > timedelta(hours=4)):
    raise SystemExit(1)
PY
        owner_approval_sha256="$(jq -cS '.owner_approval' "$payload_file" | sha256sum | awk '{print $1}')"
        pitr_restore_time="$(jq -er '.restore.point_in_time_utc' "$PITR_MANIFEST")"
      fi
      export COSMAS_PITR_OPERATION="$pitr_phase"
      export COSMAS_PITR_SUBSCRIPTION_ID="${subscription_id,,}"
      export COSMAS_PITR_RESOURCE_GROUP="$GUARD_WORKLOAD_RESOURCE_GROUP"
      export COSMAS_PITR_LOCATION="$PITR_LOCATION"
      export COSMAS_PITR_SOURCE_SERVER_ID="$PITR_SOURCE_SERVER_ID"
      export COSMAS_PITR_SOURCE_FQDN="$PITR_SOURCE_FQDN"
      export COSMAS_PITR_POSTGRES_SUBNET_ID="$PITR_POSTGRES_SUBNET_ID"
      export COSMAS_PITR_PRIVATE_DNS_ZONE_ID="$PITR_DNS_ZONE_ID"
      export COSMAS_PITR_SOURCE_SHA="$source_sha"
      export COSMAS_PITR_RELEASE_ID="$release_id"
      export COSMAS_PITR_API_IMAGE_DIGEST="${PITR_API_DIGEST#sha256:}"
      export COSMAS_PITR_WEB_IMAGE_DIGEST="${PITR_WEB_DIGEST#sha256:}"
      export COSMAS_PITR_FINGERPRINT_IMAGE="$PITR_API_IMAGE"
      export COSMAS_PITR_BOX_ID="$GUARD_BOX_ID"
      COSMAS_PITR_QUIET_WINDOW_START_UTC="$(jq -er '.quiet_window_start_utc' "$PITR_FREEZE_STATE")"
      COSMAS_PITR_QUIET_WINDOW_END_UTC="$(jq -er '.quiet_window_end_utc' "$PITR_FREEZE_STATE")"
      export COSMAS_PITR_QUIET_WINDOW_START_UTC COSMAS_PITR_QUIET_WINDOW_END_UTC
      export COSMAS_PITR_WRITE_FREEZE_EVIDENCE_SHA256="$freeze_evidence_hash"
      export COSMAS_PITR_MANIFEST_PATH="$PITR_MANIFEST"
      export COSMAS_PITR_RESTORE_TIME_UTC="$pitr_restore_time"
      export COSMAS_PITR_POLL_ATTEMPTS=60
      export COSMAS_PITR_POLL_INTERVAL_SECONDS=10
      if [[ "$pitr_phase" != "manifest" ]]; then
        export COSMAS_PITR_APPROVED_MANIFEST_SHA256="$manifest_sha256"
      fi
      if [[ "$pitr_phase" == "start" || "$pitr_phase" == "complete" ]]; then
        ensure_docker_platform_isolation "$operation_temp_dir/docker-isolation.private.log"
        pitr_database_url_file="$(mktemp /run/cosmas-pitr-database-url.XXXXXX)"
        chmod 0600 "$pitr_database_url_file"
        az keyvault secret show --id "${PITR_KEY_VAULT_URI%/}/secrets/database-url" --query value --output tsv --only-show-errors >"$pitr_database_url_file" 2>"$operation_temp_dir/key-vault.private.log" || die "cannot obtain the private runtime database URL for PITR fingerprinting"
        [[ -s "$pitr_database_url_file" && "$(wc -l <"$pitr_database_url_file" | tr -d ' ')" == "1" ]] || die "runtime database URL secret has an invalid shape"
        export COSMAS_PITR_STATE_PATH="$PITR_STATE"
        export COSMAS_PITR_DATABASE_URL_FILE="$pitr_database_url_file"
      fi
      private_result_file="$operation_temp_dir/pitr-output.json"
      set +e
      python3 "$PITR_SCRIPT" >"$private_result_file" 2>"$operation_temp_dir/pitr.private.log"
      pitr_status_code=$?
      set -e
      [[ "$pitr_status_code" == 0 || "$pitr_status_code" == 1 || "$pitr_status_code" == 2 ]] || die "PITR primitive returned an invalid status"
      [[ "$(wc -l <"$private_result_file" | tr -d ' ')" == "1" && "$(wc -c <"$private_result_file")" -le 16384 ]] || die "PITR primitive did not return exactly one bounded sanitized record"
      jq -e --arg phase "$pitr_phase" '
        type == "object" and .schema_version == 1 and .contract == "cosmas-os-d3-pitr-acceptance-v1" and
        .operation == $phase and (.status | strings) and
        (.evidence_sha256 | strings | test("^[0-9a-f]{64}$"))
      ' "$private_result_file" >/dev/null || die "PITR primitive returned an invalid sanitized contract"
      pitr_output_hash="$(jq -cS 'del(.evidence_sha256)' "$private_result_file" | sha256sum | awk '{print $1}')"
      [[ "$(jq -er '.evidence_sha256' "$private_result_file")" == "$pitr_output_hash" ]] || die "PITR primitive evidence self-hash is invalid"
      pitr_status="$(jq -er '.status' "$private_result_file")"
      case "$pitr_phase:$pitr_status_code:$pitr_status" in
        manifest:0:ready_for_owner_approval|start:0:restore_started|complete:0:verified|complete:1:failed|complete:2:restore_pending|complete:2:cleanup_pending|cleanup:0:cleaned|cleanup:2:cleanup_pending|cleanup:1:failed) ;;
        *) die "PITR primitive exit status and sanitized state are inconsistent" ;;
      esac
      writers_resumed=false
      probe_payload="$(mktemp /run/cosmas-pitr-evidence.XXXXXX)"
      jq -cS -n \
        --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
        --arg pitr_phase "$pitr_phase" --arg pitr_status "$pitr_status" --arg pitr_output_sha256 "$pitr_output_hash" \
        --arg pitr_script_sha256 "$(sha256sum "$PITR_SCRIPT" | awk '{print $1}')" --arg freeze_evidence_sha256 "$freeze_evidence_hash" \
        --arg owner_approval_sha256 "$owner_approval_sha256" --argjson writers_resumed "$writers_resumed" \
        --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
        --slurpfile pitr_output "$private_result_file" '
          {
            schema_version: 1, evidence_type: "protected-runner-pitr", pitr_phase: $pitr_phase,
            pitr_status: $pitr_status, completed_at: $completed_at,
            source_sha: $source_sha, release_id: $release_id,
            state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
            freeze_evidence_sha256: $freeze_evidence_sha256,
            owner_approval_sha256: (if $owner_approval_sha256 == "" then null else $owner_approval_sha256 end),
            pitr_script_sha256: $pitr_script_sha256,
            pitr_output_sha256: $pitr_output_sha256,
            pitr_output: $pitr_output[0],
            writers_resumed: $writers_resumed,
            secrets_returned: false
          }
        ' >"$probe_payload"
    fi

    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    pitr_evidence_tmp="$(mktemp "$PITR_ROOT/evidence/.attestation.XXXXXX")"
    jq -S --arg hash "$evidence_hash" '. + {evidence_payload_sha256: $hash}' "$probe_payload" >"$pitr_evidence_tmp"
    chmod 0600 "$pitr_evidence_tmp"
    pitr_evidence_name="$evidence_hash.json"
    ln -- "$pitr_evidence_tmp" "$PITR_ROOT/evidence/$pitr_evidence_name" || die "PITR evidence appeared concurrently"
    rm -f -- "$pitr_evidence_tmp"
    pitr_pointer_tmp="$(mktemp "$PITR_ROOT/evidence/.$pitr_phase.current.XXXXXX")"
    printf '%s\n' "$pitr_evidence_name" >"$pitr_pointer_tmp"
    chmod 0600 "$pitr_pointer_tmp"
    mv -f -- "$pitr_pointer_tmp" "$PITR_ROOT/evidence/$pitr_phase.current"
    emit_sanitized_artifact "$PITR_ROOT/evidence/$pitr_evidence_name"
    ;;
  release-rollback|release-forward)
    [[ "$stage" == "recovery" ]] || die "$operation requires stage=recovery"
    recovery_phase="${operation#release-}"
    jq -e --arg phase "$recovery_phase" --arg source_sha "$source_sha" --arg release_id "$release_id" '
      type == "object" and
      (keys | sort) == (["owner_approval", "prior_release_id", "prior_source_sha", "recovery_phase"] | sort) and
      .recovery_phase == $phase and
      (.prior_source_sha | strings | test("^[0-9a-f]{40}$")) and .prior_source_sha != $source_sha and
      (.prior_release_id | strings | test("^[a-z0-9][a-z0-9-]{2,31}$")) and .prior_release_id != $release_id and
      (.owner_approval | type == "object") and
      (.owner_approval | keys | sort) == (["approved_at", "confirmation", "contract", "current", "prior", "reviewer_reference", "schema_version"] | sort) and
      .owner_approval.schema_version == 1 and
      .owner_approval.contract == "cosmas-os-d3-release-recovery-approval-v1" and
      .owner_approval.confirmation == "AUTHORIZE D3 IMMUTABLE DIGEST ROLLBACK AND FORWARD RECOVERY" and
      .owner_approval.current.source_sha == $source_sha and .owner_approval.current.release_id == $release_id and
      .owner_approval.prior.source_sha == .prior_source_sha and .owner_approval.prior.release_id == .prior_release_id and
      (.owner_approval.current.api_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.owner_approval.current.web_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.owner_approval.prior.api_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      (.owner_approval.prior.web_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
      .owner_approval.current.api_digest != .owner_approval.prior.api_digest and
      .owner_approval.current.web_digest != .owner_approval.prior.web_digest and
      (.owner_approval.approved_at | strings | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")) and
      (.owner_approval.reviewer_reference | strings | test("^[A-Za-z0-9][A-Za-z0-9._:/ -]{2,511}$")) and
      (.owner_approval.reviewer_reference | contains("@") | not)
    ' "$payload_file" >/dev/null || die "protected release-recovery payload is invalid"
    python3 - "$payload_file" <<'PY' || die "release-recovery owner approval is outside its bounded four-hour window"
import datetime
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))["owner_approval"]["approved_at"]
approved = datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC)
now = datetime.datetime.now(datetime.UTC)
if approved > now + datetime.timedelta(minutes=5) or approved < now - datetime.timedelta(hours=4):
    raise SystemExit(1)
PY
    prepare_live_acceptance_context
    prior_source_sha="$(jq -er '.prior_source_sha' "$payload_file")"
    prior_release_id="$(jq -er '.prior_release_id' "$payload_file")"
    prior_repository_root="/opt/cosmas-os/releases/$prior_source_sha"
    prior_release_root="$runner_root/releases/$prior_release_id"
    prior_build_root="$runner_root/builds/$prior_source_sha"
    prior_build_evidence="$prior_build_root/build-evidence.json"
    [[ -d "$prior_repository_root/.git" && ! -L "$prior_repository_root" && "$(stat -c '%u' "$prior_repository_root")" == "0" ]] || die "approved prior source is not staged safely on the protected runner"
    [[ "$(git -C "$prior_repository_root" rev-parse --verify HEAD)" == "$prior_source_sha" ]] || die "staged prior source differs from the owner-approved commit"
    [[ -z "$(git -C "$prior_repository_root" status --porcelain=v1 --untracked-files=all)" ]] || die "staged prior source checkout is not clean"
    [[ "$(git -C "$prior_repository_root" remote get-url origin)" == "ssh://git@ssh.github.com:443/CosmaNeura/cosmaneura-os.git" ]] || die "staged prior source origin is invalid"
    [[ -f "$prior_release_root/source-sha" && ! -L "$prior_release_root/source-sha" && "$(cat "$prior_release_root/source-sha")" == "$prior_source_sha" ]] || die "prior release ID is not bound to its approved source commit"
    [[ -f "$prior_build_evidence" && ! -L "$prior_build_evidence" && "$(stat -c '%a' "$prior_build_evidence")" == "600" && "$(stat -c '%u' "$prior_build_evidence")" == "0" ]] || die "prior release build evidence is unavailable or unsafe"
    prior_build_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$prior_build_evidence")" || die "prior build evidence hash is invalid"
    [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$prior_build_evidence" | sha256sum | awk '{print $1}')" == "$prior_build_hash" ]] || die "prior build evidence was modified"
    prior_api_digest="$(jq -er '.images.api.digest | strings | select(test("^sha256:[0-9a-f]{64}$"))' "$prior_build_evidence")"
    prior_web_digest="$(jq -er '.images.web.digest | strings | select(test("^sha256:[0-9a-f]{64}$"))' "$prior_build_evidence")"
    jq -e --arg source_sha "$prior_source_sha" --arg release_id "$prior_release_id" --arg box_id "$GUARD_BOX_ID" --arg registry "$LIVE_REGISTRY" '
      .schema_version == 1 and .evidence_type == "protected-runner-build-push" and
      .source_sha == $source_sha and .build_release_id == $release_id and .box_id == $box_id and
      .registry.login_server == $registry and .registry.admin_user_enabled == false and
      .images.api.tag_write_delete_locked == true and .images.api.manifest_write_delete_locked == true and
      .images.web.tag_write_delete_locked == true and .images.web.manifest_write_delete_locked == true and
      .images.api.high_critical_vulnerabilities == 0 and .images.web.high_critical_vulnerabilities == 0
    ' "$prior_build_evidence" >/dev/null || die "prior build evidence is outside the exact D3 release/Box/registry boundary"
    jq -e --arg current_api "$LIVE_API_DIGEST" --arg current_web "$LIVE_WEB_DIGEST" --arg prior_api "$prior_api_digest" --arg prior_web "$prior_web_digest" '
      .owner_approval.current.api_digest == $current_api and .owner_approval.current.web_digest == $current_web and
      .owner_approval.prior.api_digest == $prior_api and .owner_approval.prior.web_digest == $prior_web
    ' "$payload_file" >/dev/null || die "owner approval digests differ from the accepted immutable build evidence"
    acr_name="${LIVE_REGISTRY%%.*}"
    guard_lock_and_verify_acr_immutable_tag "$acr_name" cosmas-os "git-$source_sha" "$LIVE_API_DIGEST"
    guard_lock_and_verify_acr_immutable_tag "$acr_name" cosmas-os-web "git-$source_sha" "$LIVE_WEB_DIGEST"
    guard_lock_and_verify_acr_immutable_tag "$acr_name" cosmas-os "git-$prior_source_sha" "$prior_api_digest"
    guard_lock_and_verify_acr_immutable_tag "$acr_name" cosmas-os-web "git-$prior_source_sha" "$prior_web_digest"
    recovery_root="$release_root/executions/recovery"
    recovery_state="$recovery_root/state.private.json"
    recovery_script="$repository_root/infra/beta/release_recovery_acceptance.py"
    recovery_evidence_file="$recovery_root/$recovery_phase-attestation.json"
    install -d -o root -g root -m 0700 "$recovery_root"
    [[ -f "$recovery_script" && ! -L "$recovery_script" ]] || die "committed release-recovery primitive is unavailable"
    git -C "$repository_root" ls-files --error-unmatch infra/beta/release_recovery_acceptance.py >/dev/null 2>&1 || die "release-recovery primitive is not part of the approved commit"
    approval_hash="$(jq -cS '.owner_approval' "$payload_file" | sha256sum | awk '{print $1}')"
    reviewer_hash="$(jq -jr '.owner_approval.reviewer_reference' "$payload_file" | sha256sum | awk '{print $1}')"
    if [[ -e "$recovery_evidence_file" || -L "$recovery_evidence_file" ]]; then
      [[ -f "$recovery_evidence_file" && ! -L "$recovery_evidence_file" && "$(stat -c '%a' "$recovery_evidence_file")" == "600" && "$(stat -c '%u' "$recovery_evidence_file")" == "0" ]] || die "stored release-recovery evidence is unsafe"
      existing_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$recovery_evidence_file")" || die "stored release-recovery evidence hash is invalid"
      [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$recovery_evidence_file" | sha256sum | awk '{print $1}')" == "$existing_hash" ]] || die "stored release-recovery evidence was modified"
      jq -e --arg phase "$recovery_phase" --arg source_sha "$source_sha" --arg release_id "$release_id" --arg approval_hash "$approval_hash" '
        .evidence_type == "protected-runner-release-recovery" and .recovery_phase == $phase and
        .source_sha == $source_sha and .release_id == $release_id and .owner_approval_sha256 == $approval_hash
      ' "$recovery_evidence_file" >/dev/null || die "stored release-recovery evidence belongs to a different approval or release"
      emit_sanitized_artifact "$recovery_evidence_file"
      exit 0
    fi
    if [[ "$recovery_phase" == "rollback" && ! -e "$recovery_state" && ! -L "$recovery_state" ]]; then
      pre_no_drift_hash="$(recovery_no_drift_review pre "$recovery_root")"
    else
      pre_review="$recovery_root/pre-no-drift-review.json"
      [[ -f "$pre_review" && ! -L "$pre_review" ]] || die "release recovery lacks its exact pre-change no-drift review"
      pre_no_drift_hash="$(sha256sum "$pre_review" | awk '{print $1}')"
    fi
    export COSMAS_RECOVERY_OPERATION="$recovery_phase"
    export COSMAS_RECOVERY_SUBSCRIPTION_ID="${subscription_id,,}"
    export COSMAS_RECOVERY_RESOURCE_GROUP="$GUARD_WORKLOAD_RESOURCE_GROUP"
    export COSMAS_RECOVERY_BETA_ID="$GUARD_BETA_ID"
    export COSMAS_RECOVERY_REGISTRY="$LIVE_REGISTRY"
    COSMAS_RECOVERY_RUNTIME_IDENTITY_ID="$(jq -er '.runtime_identity_resource_id.value | strings' "$probe_outputs")" || die "runtime identity output is invalid"
    export COSMAS_RECOVERY_WEB_IDENTITY_ID="/subscriptions/$subscription_id/resourceGroups/$GUARD_WORKLOAD_RESOURCE_GROUP/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-cosmas-beta-web-$GUARD_BETA_ID"
    COSMAS_RECOVERY_API_READY_URL="$(jq -er '.api_origin.value | strings | select(test("^https://[^/?#]+$"))' "$probe_outputs")/ready" || die "API readiness URL is invalid"
    COSMAS_RECOVERY_WEB_HEALTH_URL="$(jq -er '.web_health_url.value | strings | select(test("^https://[^?#]+/healthz$"))' "$probe_outputs")" || die "web health URL is invalid"
    export COSMAS_RECOVERY_RUNTIME_IDENTITY_ID COSMAS_RECOVERY_API_READY_URL COSMAS_RECOVERY_WEB_HEALTH_URL
    export COSMAS_RECOVERY_CURRENT_SOURCE_SHA="$source_sha"
    export COSMAS_RECOVERY_CURRENT_RELEASE_ID="$release_id"
    export COSMAS_RECOVERY_CURRENT_API_DIGEST="$LIVE_API_DIGEST"
    export COSMAS_RECOVERY_CURRENT_WEB_DIGEST="$LIVE_WEB_DIGEST"
    export COSMAS_RECOVERY_PRIOR_SOURCE_SHA="$prior_source_sha"
    export COSMAS_RECOVERY_PRIOR_RELEASE_ID="$prior_release_id"
    export COSMAS_RECOVERY_PRIOR_API_DIGEST="$prior_api_digest"
    export COSMAS_RECOVERY_PRIOR_WEB_DIGEST="$prior_web_digest"
    export COSMAS_RECOVERY_APPROVAL_SHA256="$approval_hash"
    export COSMAS_RECOVERY_STATE_PATH="$recovery_state"
    export COSMAS_RECOVERY_POLL_ATTEMPTS=60
    export COSMAS_RECOVERY_POLL_INTERVAL_SECONDS=10
    operation_temp_dir="$(mktemp -d /run/cosmas-release-recovery.XXXXXX)"
    chmod 0700 "$operation_temp_dir"
    private_result_file="$operation_temp_dir/recovery-output.json"
    set +e
    python3 "$recovery_script" >"$private_result_file" 2>"$operation_temp_dir/recovery.private.log"
    recovery_status_code=$?
    set -e
    [[ "$recovery_status_code" == 0 ]] || die "release-recovery primitive failed; private diagnostics remain root-only on the runner"
    [[ "$(wc -l <"$private_result_file" | tr -d ' ')" == "1" && "$(wc -c <"$private_result_file")" -le 32768 ]] || die "release-recovery primitive did not return one bounded sanitized record"
    jq -e --arg phase "$recovery_phase" --arg approval_hash "$approval_hash" '
      type == "object" and .schema_version == 1 and .contract == "cosmas-os-d3-release-recovery-acceptance-v1" and
      .operation == $phase and .approval_sha256 == $approval_hash and .mutable_tags_used == false and
      .route_binding_verified == true and .readiness_verified == true and .public_health_verified == true and
      .configuration_unchanged_except_exact_digest == true and
      (.evidence_sha256 | strings | test("^[0-9a-f]{64}$"))
    ' "$private_result_file" >/dev/null || die "release-recovery primitive returned an invalid sanitized contract"
    recovery_output_hash="$(jq -cS 'del(.evidence_sha256)' "$private_result_file" | sha256sum | awk '{print $1}')"
    [[ "$(jq -er '.evidence_sha256' "$private_result_file")" == "$recovery_output_hash" ]] || die "release-recovery primitive evidence self-hash is invalid"
    forward_no_drift_hash=""
    terraform_no_drift=false
    if [[ "$recovery_phase" == "forward" ]]; then
      forward_no_drift_hash="$(recovery_no_drift_review forward "$recovery_root")"
      terraform_no_drift=true
    fi
    probe_payload="$(mktemp /run/cosmas-release-recovery-evidence.XXXXXX)"
    jq -cS -n \
      --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
      --arg prior_source_sha "$prior_source_sha" --arg prior_release_id "$prior_release_id" --arg recovery_phase "$recovery_phase" \
      --arg current_api_digest "$LIVE_API_DIGEST" --arg current_web_digest "$LIVE_WEB_DIGEST" \
      --arg prior_api_digest "$prior_api_digest" --arg prior_web_digest "$prior_web_digest" \
      --arg approval_sha256 "$approval_hash" --arg reviewer_reference_sha256 "$reviewer_hash" \
      --arg current_build_evidence_sha256 "$(jq -er '.evidence_payload_sha256' "$build_root/build-evidence.json")" \
      --arg prior_build_evidence_sha256 "$prior_build_hash" --arg pre_no_drift_review_sha256 "$pre_no_drift_hash" \
      --arg forward_no_drift_review_sha256 "$forward_no_drift_hash" --argjson terraform_no_drift "$terraform_no_drift" \
      --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
      --arg recovery_script_sha256 "$(sha256sum "$recovery_script" | awk '{print $1}')" \
      --slurpfile recovery_output "$private_result_file" '
        {
          schema_version: 1, evidence_type: "protected-runner-release-recovery", recovery_phase: $recovery_phase,
          recovery_status: $recovery_output[0].status, completed_at: $completed_at,
          source_sha: $source_sha, release_id: $release_id,
          prior_source_sha: $prior_source_sha, prior_release_id: $prior_release_id,
          images: {
            current: {api_digest: $current_api_digest, web_digest: $current_web_digest},
            prior: {api_digest: $prior_api_digest, web_digest: $prior_web_digest}
          },
          revision_ids: {baseline: $recovery_output[0].baseline_revision_ids, result: $recovery_output[0].result_revision_ids},
          state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
          owner_approval_sha256: $approval_sha256, reviewer_reference_sha256: $reviewer_reference_sha256,
          build_evidence_sha256: {current: $current_build_evidence_sha256, prior: $prior_build_evidence_sha256},
          pre_no_drift_review_sha256: $pre_no_drift_review_sha256,
          forward_no_drift_review_sha256: (if $forward_no_drift_review_sha256 == "" then null else $forward_no_drift_review_sha256 end),
          terraform_no_drift: $terraform_no_drift,
          route_binding_verified: true, readiness_verified: true, public_health_verified: true,
          configuration_unchanged_except_exact_digest: true, immutable_acr_tag_and_manifest_locks_verified: true,
          mutable_tags_used: false, recovery_script_sha256: $recovery_script_sha256,
          recovery_output_sha256: $recovery_output[0].evidence_sha256,
          secrets_returned: false
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    evidence_tmp="$(mktemp "$recovery_root/.$recovery_phase-attestation.XXXXXX")"
    jq -S --arg hash "$evidence_hash" '. + {evidence_payload_sha256: $hash}' "$probe_payload" >"$evidence_tmp"
    chmod 0600 "$evidence_tmp"
    ln -- "$evidence_tmp" "$recovery_evidence_file" || die "release-recovery evidence appeared concurrently"
    rm -f -- "$evidence_tmp"
    emit_sanitized_artifact "$recovery_evidence_file"
    ;;
  offboarding-acceptance)
    [[ "$stage" == "offboarding" ]] || die "offboarding-acceptance requires stage=offboarding"
    jq -e '
      type == "object" and
      ((.offboarding_phase == "baseline" and
        (keys | sort) == (["offboarding_phase", "offboarding_request"] | sort) and
        (.offboarding_request | type == "object")) or
       (.offboarding_phase == "verify" and
        (keys | sort) == (["offboarding_phase", "owner_confirmation", "prior_attestation"] | sort) and
        (.owner_confirmation | type == "object") and (.prior_attestation | type == "object")))
    ' "$payload_file" >/dev/null || die "protected offboarding payload is invalid"
    offboarding_phase="$(jq -er '.offboarding_phase | select(. == "baseline" or . == "verify")' "$payload_file")"
    prepare_live_acceptance_context
    offboarding_root="$release_root/executions/offboarding"
    offboarding_evidence_file="$offboarding_root/$offboarding_phase-attestation.json"
    install -d -o root -g root -m 0700 "$offboarding_root"
    input_hash="$(jq -cS '.' "$payload_file" | sha256sum | awk '{print $1}')"
    if [[ -e "$offboarding_evidence_file" || -L "$offboarding_evidence_file" ]]; then
      [[ -f "$offboarding_evidence_file" && ! -L "$offboarding_evidence_file" && "$(stat -c '%a' "$offboarding_evidence_file")" == "600" && "$(stat -c '%u' "$offboarding_evidence_file")" == "0" ]] || die "stored offboarding evidence is unsafe"
      existing_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$offboarding_evidence_file")" || die "stored offboarding evidence hash is invalid"
      [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$offboarding_evidence_file" | sha256sum | awk '{print $1}')" == "$existing_hash" ]] || die "stored offboarding evidence was modified"
      jq -e --arg phase "$offboarding_phase" --arg source_sha "$source_sha" --arg release_id "$release_id" --arg input_hash "$input_hash" '
        .evidence_type == "protected-runner-offboarding-acceptance" and .offboarding_phase == $phase and
        .source_sha == $source_sha and .release_id == $release_id and .protected_input_sha256 == $input_hash
      ' "$offboarding_evidence_file" >/dev/null || die "stored offboarding evidence belongs to a different protected input"
      emit_sanitized_artifact "$offboarding_evidence_file"
      exit 0
    fi
    expected_api_digest="$LIVE_API_DIGEST"
    exact_image="$LIVE_API_IMAGE"
    if [[ "$offboarding_phase" == "baseline" ]]; then
      jq -e \
        --arg box_id "$(jq -er '.box_id.value' "$probe_outputs")" \
        --arg clerk_issuer "$(jq -er '.clerk_issuer_url.value | strings' "$probe_outputs")" \
        --arg clerk_org "$(jq -er '.clerk_organization_id.value | strings' "$probe_outputs")" '
          (.offboarding_request | keys | sort) == (["approved_at", "box_id", "clerk_issuer", "clerk_organization_id", "clerk_subject", "contract", "principal_id", "reviewer_reference", "schema_version"] | sort) and
          .offboarding_request.schema_version == 1 and .offboarding_request.contract == "cosmas-os-d3-offboarding-request-v1" and
          (.offboarding_request.box_id | ascii_downcase) == ($box_id | ascii_downcase) and
          .offboarding_request.clerk_issuer == $clerk_issuer and .offboarding_request.clerk_organization_id == $clerk_org and
          (.offboarding_request.clerk_subject | strings | test("^user_[^[:space:]]+$")) and
          (.offboarding_request.principal_id | strings | test("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"))
        ' "$payload_file" >/dev/null || die "offboarding target differs from the exact live Box/Clerk boundary"
    else
      prior_wrapper_hash="$(jq -er '.prior_attestation.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$payload_file")" || die "offboarding baseline wrapper hash is invalid"
      [[ "$(jq -cS '.prior_attestation | del(.evidence_payload_sha256)' "$payload_file" | sha256sum | awk '{print $1}')" == "$prior_wrapper_hash" ]] || die "offboarding baseline wrapper was modified"
      jq -e --arg source_sha "$source_sha" --arg release_id "$release_id" --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" --arg digest "$expected_api_digest" '
        .prior_attestation.schema_version == 1 and .prior_attestation.evidence_type == "protected-runner-offboarding-acceptance" and
        .prior_attestation.offboarding_phase == "baseline" and .prior_attestation.source_sha == $source_sha and
        .prior_attestation.release_id == $release_id and .prior_attestation.state == {lineage: $lineage, serial: $serial, sha256: $state_sha256} and
        .prior_attestation.workload.api_image_digest == $digest and
        .prior_attestation.offboarding_output.contract == "cosmas-os-d3-offboarding-acceptance-v1" and
        .prior_attestation.offboarding_output.stage == "baseline" and .prior_attestation.offboarding_output.status == "ready_for_owner" and
        .owner_confirmation.challenge == .prior_attestation.offboarding_output.confirmation_challenge and
        .owner_confirmation.baseline_evidence_sha256 == .prior_attestation.offboarding_output.evidence_sha256 and
        .owner_confirmation.owner_assertion == "I CONFIRM D3 CLERK OFFBOARDING AND LIVE ACCESS DENIAL" and
        .owner_confirmation.clerk_organization_membership_removed == true and
        .owner_confirmation.clerk_sessions_revoked == true and .owner_confirmation.live_access_denied == true
      ' "$payload_file" >/dev/null || die "offboarding verification is not bound to the exact live release/baseline/human handoff"
      prior_state_hash="$(jq -cS '.prior_attestation.offboarding_output | del(.evidence_sha256)' "$payload_file" | sha256sum | awk '{print $1}')"
      [[ "$(jq -er '.prior_attestation.offboarding_output.evidence_sha256' "$payload_file")" == "$prior_state_hash" ]] || die "offboarding baseline state self-hash is invalid"
    fi
    operation_temp_dir="$(mktemp -d /run/cosmas-offboarding-acceptance.XXXXXX)"
    chmod 0700 "$operation_temp_dir"
    key_vault_uri="$(jq -er '.key_vault_uri.value | strings | select(test("^https://[^/?#]+/$"))' "$probe_outputs")"
    key_vault_host="${key_vault_uri#https://}"
    key_vault_host="${key_vault_host%%/*}"
    key_vault_name="${key_vault_host%%.*}"
    [[ "$key_vault_host" == "$key_vault_name.vault.azure.net" && "$key_vault_name" =~ ^[A-Za-z0-9-]{3,24}$ ]] || die "workload Key Vault URI is invalid"
    for secret_name in database-url redis-url human-deploy-evidence-reference runtime-acceptance-hmac-key; do
      secret_file="$operation_temp_dir/$secret_name"
      az keyvault secret show --vault-name "$key_vault_name" --name "$secret_name" --query value --output tsv --only-show-errors >"$secret_file" 2>"$operation_temp_dir/key-vault.private.log" || die "required private offboarding runtime secret is unavailable"
      [[ -s "$secret_file" && "$(wc -l <"$secret_file" | tr -d ' ')" == "1" ]] || die "private offboarding runtime secret has an invalid shape"
      chmod 0600 "$secret_file"
    done
    runtime_env_file="$operation_temp_dir/runtime.env"
    runtime_manifest_file="$operation_temp_dir/offboarding-input.json"
    if [[ "$offboarding_phase" == "baseline" ]]; then
      jq -cS '.offboarding_request' "$payload_file" >"$runtime_manifest_file"
    else
      jq -cS '{prior_state: .prior_attestation.offboarding_output, owner_confirmation}' "$payload_file" >"$runtime_manifest_file"
    fi
    chmod 0400 "$runtime_manifest_file"
    chown 10001:10001 "$runtime_manifest_file"
    python3 - "$probe_outputs" "$operation_temp_dir" "$runtime_env_file" <<'PY' || die "cannot construct the exact offboarding runtime environment"
import json
import pathlib
import sys
from urllib.parse import parse_qs, urlparse

outputs_path, private_dir, destination = map(pathlib.Path, sys.argv[1:])
outputs = json.loads(outputs_path.read_text(encoding="utf-8"))

def secret(name: str) -> str:
    value = (private_dir / name).read_text(encoding="utf-8")
    if value.endswith("\n"):
        value = value[:-1]
    if not value or any(character in value for character in "\r\n\x00"):
        raise SystemExit(1)
    return value

database_url = secret("database-url")
database = urlparse(database_url)
database_query = parse_qs(database.query, keep_blank_values=True)
if database.scheme != "postgresql+psycopg" or set(database_query) != {"sslmode", "sslrootcert"} or database_query.get("sslmode") != ["verify-full"] or database_query.get("sslrootcert") != ["system"]:
    raise SystemExit(1)
redis_url = secret("redis-url")
redis = urlparse(redis_url)
if redis.scheme != "rediss" or parse_qs(redis.query, keep_blank_values=True).get("ssl_cert_reqs") != ["required"]:
    raise SystemExit(1)
hmac_key = secret("runtime-acceptance-hmac-key")
if len(hmac_key) != 64 or any(character not in "0123456789abcdef" for character in hmac_key):
    raise SystemExit(1)
values = {
    "COSMAS_ENV": "early_adopter_beta", "DATA_MODE": "synthetic", "AUTH_MODE": "clerk_jwt",
    "CORS_ALLOWED_ORIGINS": outputs["web_origin"]["value"], "SYNTH_SEED": "false", "BLOB_BACKEND": "azure",
    "BETA_BOX_ID": outputs["box_id"]["value"], "CLERK_ORGANIZATION_ID": outputs["clerk_organization_id"]["value"],
    "CLERK_ISSUER": outputs["clerk_issuer_url"]["value"], "CLERK_JWKS_URL": outputs["clerk_jwks_url"]["value"],
    "CLERK_AUDIENCE": outputs["clerk_audience"]["value"], "CLERK_AUTHORIZED_PARTIES": outputs["web_origin"]["value"],
    "HUMAN_DEPLOY_EVIDENCE_REF": secret("human-deploy-evidence-reference"), "DATABASE_URL": database_url,
    "REDIS_URL": redis_url, "AZURE_STORAGE_ACCOUNT_URL": outputs["blob_account_url"]["value"],
    "AZURE_BLOB_CONTAINER": outputs["blob_container_name"]["value"], "SYNC_WORKER": "false",
    "COSMAS_ACCEPTANCE_HMAC_KEY": hmac_key,
}
if any(not isinstance(value, str) or not value or any(character in value for character in "\r\n\x00") for value in values.values()):
    raise SystemExit(1)
destination.write_text("".join(f"{name}={value}\n" for name, value in values.items()), encoding="utf-8")
PY
    chmod 0600 "$runtime_env_file"
    docker_config_dir="$(mktemp -d /run/cosmas-offboarding-docker.XXXXXX)"
    chmod 0700 "$docker_config_dir"
    export DOCKER_CONFIG="$docker_config_dir"
    acr_name="${LIVE_REGISTRY%%.*}"
    acr_token="$(az acr login --name "$acr_name" --expose-token --query accessToken --output tsv --only-show-errors)" || die "cannot obtain an ephemeral ACR token for offboarding acceptance"
    [[ -n "$acr_token" ]] || die "ACR returned an empty offboarding token"
    printf '%s' "$acr_token" | docker login "$LIVE_REGISTRY" --username 00000000-0000-0000-0000-000000000000 --password-stdin >/dev/null 2>&1 || die "offboarding ACR login failed"
    unset acr_token
    offboarding_log="$operation_temp_dir/offboarding.private.log"
    : >"$offboarding_log"
    chmod 0600 "$offboarding_log"
    docker pull "$exact_image" >>"$offboarding_log" 2>&1 || die "cannot pull the accepted offboarding image digest"
    docker image inspect "$exact_image" --format '{{json .RepoDigests}}' | jq -e --arg exact "$exact_image" 'index($exact) != null' >/dev/null || die "local offboarding image differs from the accepted registry digest"
    ensure_docker_platform_isolation "$offboarding_log"
    private_result_file="$operation_temp_dir/offboarding-output.json"
    offboarding_command=(baseline-beta-offboarding-acceptance /run/offboarding-input.json --confirm-synthetic-only --confirm-reviewed-target)
    if [[ "$offboarding_phase" == "verify" ]]; then
      offboarding_command=(verify-beta-offboarding-acceptance /run/offboarding-input.json --confirm-synthetic-only --confirm-browser-complete)
    fi
    if ! docker run --rm --network bridge --read-only --cap-drop ALL --security-opt no-new-privileges \
      --pids-limit 128 --memory 256m --cpus 1 --user 10001:10001 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=16m \
      --env-file "$runtime_env_file" \
      --mount "type=bind,source=$runtime_manifest_file,target=/run/offboarding-input.json,readonly" \
      "$exact_image" python -m cosmas_os.cli "${offboarding_command[@]}" >"$private_result_file" 2>"$offboarding_log"; then
      die "offboarding acceptance failed; private diagnostics remain root-only on the runner"
    fi
    docker logout "$LIVE_REGISTRY" >/dev/null 2>&1 || true
    [[ "$(wc -l <"$private_result_file" | tr -d ' ')" == "1" && "$(wc -c <"$private_result_file")" -le 16384 ]] || die "offboarding acceptance did not return one bounded sanitized record"
    jq -e --arg phase "$offboarding_phase" '
      type == "object" and .contract == "cosmas-os-d3-offboarding-acceptance-v1" and
      ((($phase == "baseline") and .stage == "baseline" and .status == "ready_for_owner") or
       (($phase == "verify") and .stage == "post_browser" and .status == "verified")) and
      (.evidence_sha256 | strings | test("^[0-9a-f]{64}$"))
    ' "$private_result_file" >/dev/null || die "offboarding acceptance returned an invalid sanitized contract"
    offboarding_output_hash="$(jq -cS 'del(.evidence_sha256)' "$private_result_file" | sha256sum | awk '{print $1}')"
    [[ "$(jq -er '.evidence_sha256' "$private_result_file")" == "$offboarding_output_hash" ]] || die "offboarding acceptance evidence self-hash is invalid"
    for private_value in \
      "$(jq -r '.offboarding_request.box_id // empty' "$payload_file")" \
      "$(jq -r '.offboarding_request.clerk_issuer // empty' "$payload_file")" \
      "$(jq -r '.offboarding_request.clerk_organization_id // empty' "$payload_file")" \
      "$(jq -r '.offboarding_request.clerk_subject // empty' "$payload_file")" \
      "$(jq -r '.offboarding_request.principal_id // empty' "$payload_file")"; do
      [[ -z "$private_value" || "$(cat "$private_result_file")" != *"$private_value"* ]] || die "offboarding output exposed a private target identifier"
    done
    probe_payload="$(mktemp /run/cosmas-offboarding-evidence.XXXXXX)"
    jq -cS -n \
      --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" --arg source_sha "$source_sha" --arg release_id "$release_id" \
      --arg offboarding_phase "$offboarding_phase" --arg protected_input_sha256 "$input_hash" \
      --arg api_image_digest "$expected_api_digest" --arg offboarding_output_sha256 "$offboarding_output_hash" \
      --arg lineage "$GUARD_STATE_LINEAGE" --argjson serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
      --slurpfile offboarding_output "$private_result_file" '
        {
          schema_version: 1, evidence_type: "protected-runner-offboarding-acceptance", offboarding_phase: $offboarding_phase,
          completed_at: $completed_at, source_sha: $source_sha, release_id: $release_id,
          state: {lineage: $lineage, serial: $serial, sha256: $state_sha256},
          workload: {api_image_digest: $api_image_digest, deployment_mode: "synthetic_lab"},
          protected_input_sha256: $protected_input_sha256,
          offboarding_output_sha256: $offboarding_output_sha256,
          offboarding_output: $offboarding_output[0],
          human_clerk_browser_steps_machine_verified: false,
          identifiers_returned: false, secrets_returned: false
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    evidence_tmp="$(mktemp "$offboarding_root/.$offboarding_phase-attestation.XXXXXX")"
    jq -S --arg hash "$evidence_hash" '. + {evidence_payload_sha256: $hash}' "$probe_payload" >"$evidence_tmp"
    chmod 0600 "$evidence_tmp"
    ln -- "$evidence_tmp" "$offboarding_evidence_file" || die "offboarding evidence appeared concurrently"
    rm -f -- "$evidence_tmp" "$offboarding_log"
    emit_sanitized_artifact "$offboarding_evidence_file"
    ;;
  bootstrap-identity)
    [[ "$stage" == "identity" ]] || die "bootstrap-identity requires stage=identity"
    validate_source
    verify_pinned_toolchain
    bind_release_to_source
    verify_release_network_evidence
    network_evidence_file="$VERIFIED_NETWORK_EVIDENCE"
    verify_release_build_evidence
    jq -e \
      --arg source_sha "$source_sha" \
      --arg release_id "$release_id" '
        type == "object" and .schema_version == 1 and
        (keys | sort) == (["bootstrap_manifest", "deployment_binding", "schema_version"] | sort) and
        (.deployment_binding | type == "object") and
        (.deployment_binding | keys | sort) == (["api_image_digest", "release_id", "source_sha", "state_lineage", "state_serial"] | sort) and
        .deployment_binding.source_sha == $source_sha and
        .deployment_binding.release_id == $release_id and
        (.deployment_binding.api_image_digest | strings | test("^sha256:[0-9a-f]{64}$")) and
        (.deployment_binding.state_lineage | strings | test("^[0-9a-fA-F-]{36}$")) and
        (.deployment_binding.state_serial | numbers | floor == . and . >= 0) and
        (.bootstrap_manifest | type == "object") and
        (.bootstrap_manifest | keys | sort) == (["box_id", "clerk_issuer", "clerk_organization_id", "clerk_subject", "clinic_display_name", "evidence_ref", "owner_display_name", "reviewed_by", "schema_version"] | sort) and
        .bootstrap_manifest.schema_version == "cosmas-os/d3-beta-bootstrap/v1" and
        (.bootstrap_manifest.box_id | strings | test("^[0-9a-fA-F-]{36}$")) and
        (.bootstrap_manifest.clerk_issuer | strings | test("^https://[^/?#]+/?$")) and
        (.bootstrap_manifest.clerk_subject | strings | test("^user_[^[:space:]]+$")) and
        (.bootstrap_manifest.clerk_organization_id | strings | test("^org_[^[:space:]]+$")) and
        ([.bootstrap_manifest.clinic_display_name, .bootstrap_manifest.owner_display_name, .bootstrap_manifest.reviewed_by, .bootstrap_manifest.evidence_ref] | all(type == "string" and length >= 1 and . == ltrimstr(" ") and . == rtrimstr(" ")))
      ' "$payload_file" >/dev/null || die "protected identity-bootstrap envelope is invalid or not bound to this source/release"
    fresh_managed_identity_login
    # shellcheck source=deployment-guard-lib.sh
    source "$repository_root/infra/beta/deployment-guard-lib.sh"
    GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
    guard_find_terraform
    guard_source_metadata "$repository_root"
    guard_load_bootstrap_outputs "$bootstrap_outputs"
    guard_verify_azure_context_and_boundary
    export TF_DATA_DIR="$release_root/identity-terraform-data"
    guard_backend_init >/dev/null
    probe_state="$(mktemp /run/cosmas-identity-state.XXXXXX)"
    guard_pull_state "$probe_state"
    guard_validate_environment_state "$probe_state"
    jq -e --slurpfile evidence "$network_evidence_file" '
      .lineage == $evidence[0].state.lineage and .serial == $evidence[0].state.serial
    ' "$probe_state" >/dev/null || die "re-probe the protected network after the workload apply before bootstrapping identity"
    [[ "$GUARD_STATE_SHA256" == "$(jq -er '.state.sha256' "$network_evidence_file")" ]] || die "re-probe the protected network after the workload state changed"
    probe_outputs="$(mktemp /run/cosmas-identity-outputs.XXXXXX)"
    "$GUARD_TERRAFORM_BIN" -chdir="$GUARD_ENVIRONMENT_DIR" output -json >"$probe_outputs"
    chmod 0600 "$probe_outputs"
    expected_api_digest="$(jq -er '.images.api.digest' "$build_root/build-evidence.json")"
    jq -e \
      --arg source_sha "$source_sha" \
      --arg release_id "$release_id" \
      --arg state_lineage "$GUARD_STATE_LINEAGE" \
      --argjson state_serial "$GUARD_STATE_SERIAL" \
      --arg api_digest "$expected_api_digest" \
      --arg box_id "$(jq -er '.box_id.value' "$probe_outputs")" \
      --arg clerk_issuer "$(jq -er '.clerk_issuer_url.value | strings' "$probe_outputs")" \
      --arg clerk_org "$(jq -er '.clerk_organization_id.value | strings' "$probe_outputs")" '
        .deployment_binding.source_sha == $source_sha and
        .deployment_binding.release_id == $release_id and
        (.deployment_binding.state_lineage | ascii_downcase) == ($state_lineage | ascii_downcase) and
        .deployment_binding.state_serial == $state_serial and
        .deployment_binding.api_image_digest == $api_digest and
        (.bootstrap_manifest.box_id | ascii_downcase) == ($box_id | ascii_downcase) and
        .bootstrap_manifest.clerk_issuer == $clerk_issuer and
        .bootstrap_manifest.clerk_organization_id == $clerk_org
      ' "$payload_file" >/dev/null || die "identity-bootstrap envelope differs from the live workload state/Box/Clerk binding"
    jq -e \
      --arg expected_image "$(jq -er '.registry.login_server' "$build_root/build-evidence.json")/cosmas-os@$expected_api_digest" \
      --arg clerk_issuer "$(jq -er '.clerk_issuer_url.value | strings' "$probe_outputs")" '
        .workloads_enabled.value == true and
        .database_preparation_job_enabled.value == true and
        .deployment_mode.value == "synthetic_lab" and .runtime_data_mode.value == "synthetic" and
        .image_reference.value == $expected_image and
        (.web_origin.value | strings | test("^https://[^/?#]+$")) and
        (.clerk_jwks_url.value | strings | startswith($clerk_issuer)) and
        (.clerk_audience.value | strings | length >= 3) and
        (.blob_account_url.value | strings | test("^https://[^/?#]+/?$")) and
        (.blob_container_name.value | strings | test("^[a-z0-9-]{3,63}$"))
      ' "$probe_outputs" >/dev/null || die "live workloads are not the exact synthetic, digest-pinned identity-bootstrap target"
    manifest_evidence_hash="$(jq -jr '.bootstrap_manifest.evidence_ref' "$payload_file" | sha256sum | awk '{print $1}')"
    [[ "$manifest_evidence_hash" == "$(jq -er '.human_deploy_evidence_reference_sha256.value' "$probe_outputs")" ]] || die "bootstrap manifest evidence reference differs from the workload state"
    protected_manifest_hash="$(jq -cS '.' "$payload_file" | sha256sum | awk '{print $1}')"
    identity_root="$release_root/executions/identity"
    identity_evidence_file="$identity_root/bootstrap-evidence.json"
    install -d -o root -g root -m 0700 "$identity_root"
    if [[ -e "$identity_evidence_file" || -L "$identity_evidence_file" ]]; then
      [[ -f "$identity_evidence_file" && ! -L "$identity_evidence_file" && "$(stat -c '%a' "$identity_evidence_file")" == "600" && "$(stat -c '%u' "$identity_evidence_file")" == "0" ]] || die "existing identity-bootstrap evidence has unsafe ownership or type"
      existing_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$identity_evidence_file")" || die "existing identity-bootstrap evidence is invalid"
      [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$identity_evidence_file" | sha256sum | awk '{print $1}')" == "$existing_hash" ]] || die "existing identity-bootstrap evidence was modified"
      jq -e --arg source_sha "$source_sha" --arg release_id "$release_id" --arg manifest_hash "$protected_manifest_hash" '
        .schema_version == 1 and .evidence_type == "protected-runner-beta-identity-bootstrap" and
        .source_sha == $source_sha and .release_id == $release_id and
        .protected_manifest_sha256 == $manifest_hash and
        .identity_bootstrap_idempotent == true and .synthetic_seed_idempotent == true
      ' "$identity_evidence_file" >/dev/null || die "existing identity-bootstrap evidence belongs to a different reviewed manifest"
      emit_sanitized_artifact "$identity_evidence_file"
      exit 0
    fi

    operation_temp_dir="$(mktemp -d /run/cosmas-identity-bootstrap.XXXXXX)"
    chmod 0700 "$operation_temp_dir"
    key_vault_host="$(jq -er '.key_vault_uri.value | strings | sub("^https://"; "") | split("/")[0]' "$probe_outputs")"
    key_vault_name="${key_vault_host%%.*}"
    [[ "$key_vault_host" == "$key_vault_name.vault.azure.net" && "$key_vault_name" =~ ^[A-Za-z0-9-]{3,24}$ ]] || die "workload Key Vault URI is invalid"
    for secret_name in database-url redis-url human-deploy-evidence-reference; do
      secret_file="$operation_temp_dir/$secret_name"
      secret_ready=false
      for _ in $(seq 1 60); do
        if az keyvault secret show --vault-name "$key_vault_name" --name "$secret_name" --query value --output tsv --only-show-errors >"$secret_file" 2>/dev/null && [[ -s "$secret_file" ]]; then
          secret_ready=true
          break
        fi
        sleep 10
      done
      [[ "$secret_ready" == "true" ]] || die "required private runtime secret was unavailable within ten minutes: $secret_name"
      chmod 0600 "$secret_file"
    done
    runtime_env_file="$operation_temp_dir/runtime.env"
    runtime_manifest_file="$operation_temp_dir/beta-bootstrap.json"
    jq -cS '.bootstrap_manifest' "$payload_file" >"$runtime_manifest_file"
    chmod 0400 "$runtime_manifest_file"
    chown 10001:10001 "$runtime_manifest_file"
    python3 - "$probe_outputs" "$operation_temp_dir" "$runtime_env_file" <<'PY'
import json
import pathlib
import sys
from urllib.parse import parse_qs, urlparse

outputs_path, private_dir, destination = map(pathlib.Path, sys.argv[1:])
outputs = json.loads(outputs_path.read_text(encoding="utf-8"))

def secret(name: str) -> str:
    value = (private_dir / name).read_text(encoding="utf-8")
    if value.endswith("\n"):
        value = value[:-1]
    if not value or "\n" in value or "\r" in value or "\x00" in value:
        raise SystemExit(1)
    return value

database_url = secret("database-url")
database = urlparse(database_url)
database_query = parse_qs(database.query, keep_blank_values=True)
if database.scheme != "postgresql+psycopg" or database_query.get("sslmode") != ["verify-full"] or database_query.get("sslrootcert") != ["system"]:
    raise SystemExit(1)
redis_url = secret("redis-url")
redis = urlparse(redis_url)
if redis.scheme != "rediss" or parse_qs(redis.query, keep_blank_values=True).get("ssl_cert_reqs") != ["required"]:
    raise SystemExit(1)

values = {
    "COSMAS_ENV": "early_adopter_beta",
    "DATA_MODE": "synthetic",
    "AUTH_MODE": "clerk_jwt",
    "CORS_ALLOWED_ORIGINS": outputs["web_origin"]["value"],
    "SYNTH_SEED": "false",
    "BLOB_BACKEND": "azure",
    "BETA_BOX_ID": outputs["box_id"]["value"],
    "CLERK_ORGANIZATION_ID": outputs["clerk_organization_id"]["value"],
    "CLERK_ISSUER": outputs["clerk_issuer_url"]["value"],
    "CLERK_JWKS_URL": outputs["clerk_jwks_url"]["value"],
    "CLERK_AUDIENCE": outputs["clerk_audience"]["value"],
    "CLERK_AUTHORIZED_PARTIES": outputs["web_origin"]["value"],
    "HUMAN_DEPLOY_EVIDENCE_REF": secret("human-deploy-evidence-reference"),
    "DATABASE_URL": database_url,
    "REDIS_URL": redis_url,
    "AZURE_STORAGE_ACCOUNT_URL": outputs["blob_account_url"]["value"],
    "AZURE_BLOB_CONTAINER": outputs["blob_container_name"]["value"],
    "SYNC_WORKER": "false",
}
if any(not isinstance(value, str) or not value or "\n" in value or "\r" in value or "\x00" in value for value in values.values()):
    raise SystemExit(1)
destination.write_text("".join(f"{name}={value}\n" for name, value in values.items()), encoding="utf-8")
PY
    chmod 0600 "$runtime_env_file"
    key_vault_evidence_hash="$(python3 - "$operation_temp_dir/human-deploy-evidence-reference" <<'PY' | sha256sum | awk '{print $1}'
import pathlib
import sys

value = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
if value.endswith("\n"):
    value = value[:-1]
if not value or "\n" in value or "\r" in value or "\x00" in value:
    raise SystemExit(1)
sys.stdout.write(value)
PY
)"
    [[ "$key_vault_evidence_hash" == "$manifest_evidence_hash" ]] || die "Key Vault human evidence reference differs from the protected bootstrap manifest"
    identity_log="$identity_root/bootstrap.private.log"
    : >"$identity_log"
    chmod 0600 "$identity_log"
    docker_config_dir="$(mktemp -d /run/cosmas-identity-docker.XXXXXX)"
    chmod 0700 "$docker_config_dir"
    export DOCKER_CONFIG="$docker_config_dir"
    acr_host="$(jq -er '.registry.login_server' "$build_root/build-evidence.json")"
    acr_name="${acr_host%%.*}"
    acr_token="$(az acr login --name "$acr_name" --expose-token --query accessToken --output tsv --only-show-errors)" || die "cannot obtain an ephemeral ACR token for identity bootstrap"
    [[ -n "$acr_token" ]] || die "ACR returned an empty identity-bootstrap token"
    printf '%s' "$acr_token" | docker login "$acr_host" --username 00000000-0000-0000-0000-000000000000 --password-stdin >/dev/null 2>&1 || die "identity-bootstrap ACR login failed"
    unset acr_token
    exact_image="$acr_host/cosmas-os@$expected_api_digest"
    docker pull "$exact_image" >>"$identity_log" 2>&1 || die "cannot pull the accepted identity-bootstrap image digest"
    docker image inspect "$exact_image" --format '{{json .RepoDigests}}' | jq -e --arg exact "$exact_image" 'index($exact) != null' >/dev/null || die "local identity-bootstrap image does not match the accepted registry digest"
    ensure_docker_platform_isolation "$identity_log"
    if ! docker run --rm --network bridge --read-only --cap-drop ALL --security-opt no-new-privileges \
      --user 10001:10001 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
      --env-file "$runtime_env_file" \
      --mount "type=bind,source=$runtime_manifest_file,target=/run/beta-bootstrap.json,readonly" \
      "$exact_image" python -m cosmas_os.cli bootstrap-beta-identity /run/beta-bootstrap.json --confirm-reviewed-human-deploy >>"$identity_log" 2>&1; then
      die "beta identity bootstrap failed; private diagnostics remain root-only on the runner"
    fi
    if ! docker run --rm --network bridge --read-only --cap-drop ALL --security-opt no-new-privileges \
      --user 10001:10001 --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m \
      --env-file "$runtime_env_file" \
      "$exact_image" python -m cosmas_os.cli seed-beta-synthetic --confirm-synthetic-only >>"$identity_log" 2>&1; then
      die "synthetic beta seed failed; private diagnostics remain root-only on the runner"
    fi
    docker logout "$acr_host" >/dev/null 2>&1 || true
    probe_payload="$(mktemp /run/cosmas-identity-evidence-payload.XXXXXX)"
    jq -cS -n \
      --arg completed_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
      --arg source_sha "$source_sha" --arg release_id "$release_id" \
      --arg state_lineage "$GUARD_STATE_LINEAGE" --argjson state_serial "$GUARD_STATE_SERIAL" --arg state_sha256 "$GUARD_STATE_SHA256" \
      --arg api_image_digest "$expected_api_digest" --arg box_id "$(jq -er '.box_id.value' "$probe_outputs")" \
      --arg protected_manifest_sha256 "$protected_manifest_hash" \
      --arg clerk_binding_sha256 "$(jq -cS '.bootstrap_manifest | {clerk_issuer,clerk_subject,clerk_organization_id}' "$payload_file" | sha256sum | awk '{print $1}')" \
      --arg human_evidence_reference_sha256 "$manifest_evidence_hash" '
        {
          schema_version: 1,
          evidence_type: "protected-runner-beta-identity-bootstrap",
          completed_at: $completed_at,
          source_sha: $source_sha,
          release_id: $release_id,
          state: {lineage: $state_lineage, serial: $state_serial, sha256: $state_sha256},
          workload: {api_image_digest: $api_image_digest, box_id: $box_id, deployment_mode: "synthetic_lab"},
          protected_manifest_sha256: $protected_manifest_sha256,
          clerk_binding_sha256: $clerk_binding_sha256,
          human_evidence_reference_sha256: $human_evidence_reference_sha256,
          identity_bootstrap_idempotent: true,
          synthetic_seed_idempotent: true,
          secrets_returned: false
        }
      ' >"$probe_payload"
    evidence_hash="$(sha256sum "$probe_payload" | awk '{print $1}')"
    identity_evidence_tmp="$(mktemp "$identity_root/.bootstrap-evidence.XXXXXX")"
    jq -S --arg evidence_payload_sha256 "$evidence_hash" '. + {evidence_payload_sha256: $evidence_payload_sha256}' "$probe_payload" >"$identity_evidence_tmp"
    chmod 0600 "$identity_evidence_tmp"
    jq -e --arg hash "$evidence_hash" '.schema_version == 1 and .evidence_payload_sha256 == $hash' "$identity_evidence_tmp" >/dev/null || die "generated identity-bootstrap evidence is invalid"
    ln -- "$identity_evidence_tmp" "$identity_evidence_file" || die "identity-bootstrap evidence appeared concurrently"
    rm -f -- "$identity_evidence_tmp" "$identity_log"
    identity_evidence_tmp=""
    emit_sanitized_artifact "$identity_evidence_file"
    ;;
  retrieve)
    validate_source
    [[ -f "$release_root/source-sha" && ! -L "$release_root/source-sha" && "$(cat "$release_root/source-sha")" == "$source_sha" ]] || die "release ID is not bound to the approved source commit"
    jq -e '
      type == "object" and
      (.artifact_kind == "review" or .artifact_kind == "result" or .artifact_kind == "network" or
       .artifact_kind == "build" or .artifact_kind == "database" or .artifact_kind == "runtime" or
       .artifact_kind == "domain" or .artifact_kind == "alert" or .artifact_kind == "pitr" or .artifact_kind == "recovery" or
       .artifact_kind == "offboarding" or .artifact_kind == "identity") and
      if .artifact_kind == "runtime" then
        (keys | sort) == (["acceptance_phase", "artifact_kind"] | sort) and
        (.acceptance_phase == "runtime" or .acceptance_phase == "workflow-baseline" or
         .acceptance_phase == "workflow-verify" or .acceptance_phase == "purge-setup" or
         .acceptance_phase == "purge-verify")
      elif .artifact_kind == "alert" then
        (keys | sort) == (["alert_phase", "artifact_kind"] | sort) and
        (.alert_phase == "send" or .alert_phase == "confirm")
      elif .artifact_kind == "pitr" then
        (keys | sort) == (["artifact_kind", "pitr_phase"] | sort) and
        (.pitr_phase == "freeze" or .pitr_phase == "manifest" or .pitr_phase == "start" or
         .pitr_phase == "complete" or .pitr_phase == "cleanup" or .pitr_phase == "resume")
      elif .artifact_kind == "recovery" then
        (keys | sort) == (["artifact_kind", "recovery_phase"] | sort) and
        (.recovery_phase == "rollback" or .recovery_phase == "forward")
      elif .artifact_kind == "offboarding" then
        (keys | sort) == (["artifact_kind", "offboarding_phase"] | sort) and
        (.offboarding_phase == "baseline" or .offboarding_phase == "verify")
      else keys == ["artifact_kind"] end
    ' "$payload_file" >/dev/null || die "artifact retrieval payload is invalid"
    artifact_kind="$(jq -er '.artifact_kind' "$payload_file")"
    case "$artifact_kind" in
      review)
        [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || die "review retrieval requires the exact environment stage"
        artifact_file="$stage_root/review.json"
        [[ -f "$artifact_file" && -f "$stage_root/plan.tfplan" ]] || die "reviewed plan artifact is unavailable"
        jq -e --arg source_sha "$source_sha" --arg stage "$stage" '
          .schema_version == 1 and .source_sha == $source_sha and
          (.phase == "first" or .phase == "subsequent" or (.phase == "foundation_reconcile" and $stage == "foundation"))
        ' "$artifact_file" >/dev/null || die "stored review is not bound to the approved source/stage"
        ;;
      result)
        [[ "$stage" == "foundation" || "$stage" == "database" || "$stage" == "workloads" ]] || die "result retrieval requires the exact environment stage"
        artifact_file="$stage_root/result.json"
        [[ -f "$artifact_file" && -f "$stage_root/review.json" ]] || die "apply result artifact is unavailable"
        jq -e --slurpfile review "$stage_root/review.json" '.schema_version == 1 and .plan_sha256 == $review[0].plan_sha256' "$artifact_file" >/dev/null || die "stored apply result is not bound to the reviewed plan"
        ;;
      network)
        [[ "$stage" == "network" ]] || die "network retrieval requires stage=network"
        verify_release_network_evidence
        artifact_file="$VERIFIED_NETWORK_EVIDENCE"
        ;;
      build)
        [[ "$stage" == "images" ]] || die "build retrieval requires stage=images"
        verify_release_build_evidence
        artifact_file="$build_root/build-evidence.json"
        ;;
      database)
        [[ "$stage" == "database" ]] || die "database retrieval requires stage=database"
        pointer="$release_root/database-attestation.current"
        [[ -f "$pointer" && ! -L "$pointer" && "$(stat -c '%a' "$pointer")" == "600" && "$(stat -c '%u' "$pointer")" == "0" ]] || die "database-attestation pointer is unavailable"
        execution_name="$(cat "$pointer")"
        [[ "$execution_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$ ]] || die "database-attestation pointer is invalid"
        artifact_file="$release_root/executions/database/$execution_name/attestation.json"
        ;;
      runtime)
        [[ "$stage" == "acceptance" ]] || die "runtime retrieval requires stage=acceptance"
        acceptance_phase="$(jq -er '.acceptance_phase' "$payload_file")"
        pointer="$release_root/runtime-acceptance.$acceptance_phase.current"
        [[ -f "$pointer" && ! -L "$pointer" && "$(stat -c '%a' "$pointer")" == "600" && "$(stat -c '%u' "$pointer")" == "0" ]] || die "runtime-acceptance pointer is unavailable"
        execution_name="$(cat "$pointer")"
        [[ "$execution_name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{2,255}$ ]] || die "runtime-acceptance pointer is invalid"
        artifact_file="$release_root/executions/runtime-acceptance/$acceptance_phase/$execution_name/attestation.json"
        jq -e --arg phase "$acceptance_phase" '.acceptance_phase == $phase' "$artifact_file" >/dev/null || die "runtime-acceptance artifact phase differs from the requested phase"
        ;;
      domain)
        [[ "$stage" == "domain" ]] || die "domain-verification retrieval requires stage=domain"
        artifact_file="$release_root/executions/domain-verification/attestation.json"
        ;;
      alert)
        [[ "$stage" == "alert" ]] || die "alert retrieval requires stage=alert"
        alert_phase="$(jq -er '.alert_phase | select(. == "send" or . == "confirm")' "$payload_file")"
        artifact_file="$release_root/executions/alert-delivery/$alert_phase-attestation.json"
        jq -e --arg phase "$alert_phase" '.alert_phase == $phase' "$artifact_file" >/dev/null || die "alert-delivery artifact phase differs from the requested phase"
        ;;
      pitr)
        [[ "$stage" == "pitr" ]] || die "PITR retrieval requires stage=pitr"
        pitr_phase="$(jq -er '.pitr_phase | select(. == "freeze" or . == "manifest" or . == "start" or . == "complete" or . == "cleanup" or . == "resume")' "$payload_file")"
        if [[ "$pitr_phase" == "freeze" ]]; then
          artifact_file="$release_root/executions/pitr/freeze-attestation.json"
        else
          pointer="$release_root/executions/pitr/evidence/$pitr_phase.current"
          [[ -f "$pointer" && ! -L "$pointer" && "$(stat -c '%a' "$pointer")" == "600" && "$(stat -c '%u' "$pointer")" == "0" ]] || die "PITR evidence pointer is unavailable"
          pitr_evidence_name="$(cat "$pointer")"
          [[ "$pitr_evidence_name" =~ ^[0-9a-f]{64}\.json$ ]] || die "PITR evidence pointer is invalid"
          artifact_file="$release_root/executions/pitr/evidence/$pitr_evidence_name"
        fi
        jq -e --arg phase "$pitr_phase" '.evidence_type == "protected-runner-pitr" and .pitr_phase == $phase' "$artifact_file" >/dev/null || die "PITR artifact phase differs from the requested phase"
        ;;
      recovery)
        [[ "$stage" == "recovery" ]] || die "release-recovery retrieval requires stage=recovery"
        recovery_phase="$(jq -er '.recovery_phase | select(. == "rollback" or . == "forward")' "$payload_file")"
        artifact_file="$release_root/executions/recovery/$recovery_phase-attestation.json"
        jq -e --arg phase "$recovery_phase" '.evidence_type == "protected-runner-release-recovery" and .recovery_phase == $phase' "$artifact_file" >/dev/null || die "release-recovery artifact phase differs from the requested phase"
        ;;
      offboarding)
        [[ "$stage" == "offboarding" ]] || die "offboarding retrieval requires stage=offboarding"
        offboarding_phase="$(jq -er '.offboarding_phase | select(. == "baseline" or . == "verify")' "$payload_file")"
        artifact_file="$release_root/executions/offboarding/$offboarding_phase-attestation.json"
        jq -e --arg phase "$offboarding_phase" '.evidence_type == "protected-runner-offboarding-acceptance" and .offboarding_phase == $phase' "$artifact_file" >/dev/null || die "offboarding artifact phase differs from the requested phase"
        ;;
      identity)
        [[ "$stage" == "identity" ]] || die "identity retrieval requires stage=identity"
        artifact_file="$release_root/executions/identity/bootstrap-evidence.json"
        ;;
    esac
    [[ -f "$artifact_file" && ! -L "$artifact_file" && "$(stat -c '%a' "$artifact_file")" == "600" && "$(stat -c '%u' "$artifact_file")" == "0" ]] || die "requested sanitized artifact is unavailable or unsafe"
    if [[ "$artifact_kind" == "domain" ]]; then
      # shellcheck source=deployment-guard-lib.sh
      source "$repository_root/infra/beta/deployment-guard-lib.sh"
      guard_validate_domain_verification_artifact "$artifact_file" "$source_sha" "$release_id"
    fi
    if [[ "$artifact_kind" == "network" || "$artifact_kind" == "build" || "$artifact_kind" == "database" || "$artifact_kind" == "runtime" || "$artifact_kind" == "domain" || "$artifact_kind" == "alert" || "$artifact_kind" == "pitr" || "$artifact_kind" == "recovery" || "$artifact_kind" == "offboarding" || "$artifact_kind" == "identity" ]]; then
      artifact_hash="$(jq -er '.evidence_payload_sha256 | strings | select(test("^[0-9a-f]{64}$"))' "$artifact_file")" || die "stored evidence hash is invalid"
      [[ "$(jq -cS 'del(.evidence_payload_sha256)' "$artifact_file" | sha256sum | awk '{print $1}')" == "$artifact_hash" ]] || die "stored evidence was modified"
      jq -e --arg source_sha "$source_sha" --arg release_id "$release_id" '.schema_version == 1 and .source_sha == $source_sha and ((.release_id // .build_release_id) == $release_id or .evidence_type == "protected-runner-build-push")' "$artifact_file" >/dev/null || die "stored evidence is not bound to this source/release"
    fi
    emit_sanitized_artifact "$artifact_file"
    ;;
  plan)
    [[ "$stage" != "source" ]] || die "plan requires an environment stage"
    validate_source
    [[ -f "$release_root/source-sha" && "$(cat "$release_root/source-sha")" == "$source_sha" ]] || die "release ID is not bound to the approved source commit"
    verify_pinned_toolchain
    [[ -f "$stage_root/environment.tfvars.json" && ! -L "$stage_root/environment.tfvars.json" ]] || die "private stage tfvars are missing"
    [[ "$(stat -c '%a' "$stage_root/environment.tfvars.json")" == "600" && "$(stat -c '%u' "$stage_root/environment.tfvars.json")" == "0" ]] || die "private stage tfvars are not root-owned mode 0600"
    [[ ! -e "$stage_root/plan.tfplan" && ! -e "$stage_root/review.json" ]] || die "stage plan/review already exist; retain or remove them through an explicit reviewed recovery"
    fresh_managed_identity_login
    private_log="$stage_root/plan.private.log"
    if [[ "$stage" == "foundation" ]]; then
      # A fresh foundation uses the stricter no-state wrapper. If a prior
      # approved apply was interrupted after persisting any canonical state,
      # reconciliation uses the normal lineage-bound non-destructive wrapper.
      # A zero-byte backend lock stub is not canonical and remains the first
      # wrapper's responsibility.
      # shellcheck source=deployment-guard-lib.sh
      source "$repository_root/infra/beta/deployment-guard-lib.sh"
      GUARD_ENVIRONMENT_DIR="$repository_root/infra/beta/environment"
      guard_find_terraform
      guard_load_bootstrap_outputs "$bootstrap_outputs"
      export TF_DATA_DIR="$stage_root/foundation-state-detection-terraform-data"
      guard_backend_init >/dev/null
      foundation_plan_wrapper="$repository_root/infra/beta/first-environment-plan.sh"
      foundation_reconcile_flag=()
      if guard_state_exists; then
        state_content_length="$(az storage blob show \
          --auth-mode login \
          --account-name "$GUARD_STATE_STORAGE_ACCOUNT" \
          --container-name "$GUARD_STATE_CONTAINER" \
          --name "$GUARD_STATE_KEY" \
          --query properties.contentLength \
          --output tsv \
          --only-show-errors)" || die "cannot inspect the foundation state object"
        [[ "$state_content_length" =~ ^[0-9]+$ ]] || die "foundation state object has an invalid content length"
        if (( state_content_length > 0 )); then
          foundation_plan_wrapper="$repository_root/infra/beta/subsequent-environment-plan.sh"
          foundation_state="$(mktemp /run/cosmas-foundation-state.XXXXXX)"
          guard_pull_state "$foundation_state"
          # A fully completed foundation retry is a normal subsequent/no-op
          # drift plan. Only a state missing required boundary outputs enters
          # the deliberately bounded reconciliation path.
          if ! (guard_validate_environment_state "$foundation_state") >/dev/null 2>&1; then
            guard_validate_environment_state "$foundation_state" partial_foundation
            foundation_reconcile_flag=(--allow-partial-foundation)
          fi
        fi
      fi
      if ! bash "$foundation_plan_wrapper" \
          --bootstrap-outputs "$bootstrap_outputs" \
          --var-file "$stage_root/environment.tfvars.json" \
          --plan-out "$stage_root/plan.tfplan" \
          --review-out "$stage_root/review.json" \
          "${foundation_reconcile_flag[@]}" >"$private_log" 2>&1; then
          die "foundation plan/reconciliation failed; sensitive diagnostics remain root-only on the runner"
        fi
    else
      if ! bash "$repository_root/infra/beta/subsequent-environment-plan.sh" \
        --bootstrap-outputs "$bootstrap_outputs" \
        --var-file "$stage_root/environment.tfvars.json" \
        --plan-out "$stage_root/plan.tfplan" \
        --review-out "$stage_root/review.json" >"$private_log" 2>&1; then
        die "$stage plan failed; sensitive diagnostics remain root-only on the runner"
      fi
      verify_release_network_evidence
      jq -e --slurpfile evidence "$VERIFIED_NETWORK_EVIDENCE" '
        .prior_state.lineage == $evidence[0].state.lineage and
        .prior_state.serial == $evidence[0].state.serial and
        .prior_state.sha256 == $evidence[0].state.sha256
      ' "$stage_root/review.json" >/dev/null || {
        rm -f -- "$stage_root/plan.tfplan" "$stage_root/review.json"
        die "live runner-network evidence is stale for the state used by this plan"
      }
    fi
    rm -f -- "$private_log"
    emit_sanitized_artifact "$stage_root/review.json"
    ;;
  apply)
    [[ "$stage" != "source" ]] || die "apply requires an environment stage"
    validate_source
    [[ -f "$release_root/source-sha" && "$(cat "$release_root/source-sha")" == "$source_sha" ]] || die "release ID is not bound to the approved source commit"
    verify_pinned_toolchain
    [[ -f "$stage_root/plan.tfplan" && -f "$stage_root/review.json" ]] || die "reviewed stage plan/review are missing"
    [[ ! -e "$stage_root/result.json" ]] || die "stage result already exists; use guarded artifact retrieval"
    jq -e 'type == "object" and .schema_version == 1' "$payload_file" >/dev/null || die "approval payload must be a schema-version-1 JSON object"
    if [[ -e "$stage_root/approval.json" || -L "$stage_root/approval.json" ]]; then
      [[ -f "$stage_root/approval.json" && ! -L "$stage_root/approval.json" && "$(stat -c '%a' "$stage_root/approval.json")" == "600" && "$(stat -c '%u' "$stage_root/approval.json")" == "0" ]] || die "existing approval has unsafe ownership or type"
      [[ "$(sha256sum "$stage_root/approval.json" | awk '{print $1}')" == "$(sha256sum "$payload_file" | awk '{print $1}')" ]] || die "apply retry must provide the exact previously staged approval"
    else
      install -o root -g root -m 0600 "$payload_file" "$stage_root/approval.json"
    fi
    fresh_managed_identity_login
    private_log="$stage_root/apply.private.log"
    review_phase="$(jq -er '.phase | strings' "$stage_root/review.json")"
    [[ "$review_phase" != "foundation_reconcile" || "$stage" == "foundation" ]] || die "partial-foundation reconciliation cannot be applied as a later stage"
    [[ "$stage" == "foundation" || "$review_phase" == "subsequent" ]] || die "database/workload applies require a normal complete-state review"
    if [[ "$stage" == "foundation" && "$review_phase" == "first" ]]; then
      if ! bash "$repository_root/infra/beta/apply-first-environment-plan.sh" \
        --bootstrap-outputs "$bootstrap_outputs" \
        --var-file "$stage_root/environment.tfvars.json" \
        --plan "$stage_root/plan.tfplan" \
        --review "$stage_root/review.json" \
        --approval "$stage_root/approval.json" \
        --result-out "$stage_root/result.json" >"$private_log" 2>&1; then
        die "foundation apply failed; sensitive diagnostics remain root-only on the runner"
      fi
    elif [[ "$review_phase" == "subsequent" || "$review_phase" == "foundation_reconcile" ]]; then
      if ! bash "$repository_root/infra/beta/apply-environment-plan.sh" \
        --bootstrap-outputs "$bootstrap_outputs" \
        --var-file "$stage_root/environment.tfvars.json" \
        --plan "$stage_root/plan.tfplan" \
        --review "$stage_root/review.json" \
        --approval "$stage_root/approval.json" \
        --result-out "$stage_root/result.json" >"$private_log" 2>&1; then
        die "$stage apply failed; sensitive diagnostics remain root-only on the runner"
      fi
    else
      die "stage review phase is invalid for guarded apply"
    fi
    rm -f -- "$private_log"
    emit_sanitized_artifact "$stage_root/result.json"
    ;;
esac
