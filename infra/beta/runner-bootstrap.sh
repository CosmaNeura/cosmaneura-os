#!/usr/bin/env bash
set -euo pipefail

# Executed as root by Azure Run Command. Every argument is non-secret release
# metadata. Do not add repository credentials, Terraform variables, or secrets.

die() {
  printf 'D3 protected runner setup refused: %s\n' "$1" >&2
  exit 1
}

[[ $# -eq 13 ]] || die "expected bootstrap output payload plus exact OpenTofu, Trivy, and apt tool version/hash arguments"
subscription_id="$1"
deploy_identity_client_id="$2"
state_storage_account="$3"
tofu_version="$4"
tofu_linux_amd64_sha256="$5"
azure_cli_package_version="$6"
docker_package_version="$7"
docker_buildx_package_version="$8"
git_package_version="$9"
jq_package_version="${10}"
trivy_version="${11}"
trivy_linux_amd64_sha256="${12}"
bootstrap_outputs_base64="${13}"

uuid_pattern='^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
[[ "$subscription_id" =~ $uuid_pattern ]] || die "subscription ID is invalid"
[[ "$deploy_identity_client_id" =~ $uuid_pattern ]] || die "deploy identity client ID is invalid"
[[ "$state_storage_account" =~ ^[a-z0-9]{3,24}$ ]] || die "state storage account name is invalid"
[[ "$tofu_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "OpenTofu version must be exact"
[[ "$tofu_linux_amd64_sha256" =~ ^[0-9a-f]{64}$ ]] || die "OpenTofu SHA-256 must be exact lowercase hex"
[[ "$trivy_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Trivy version must be exact"
[[ "$trivy_linux_amd64_sha256" =~ ^[0-9a-f]{64}$ ]] || die "Trivy SHA-256 must be exact lowercase hex"
for package_version in "$azure_cli_package_version" "$docker_package_version" "$docker_buildx_package_version" "$git_package_version" "$jq_package_version"; do
  [[ "$package_version" =~ ^[A-Za-z0-9][A-Za-z0-9.+:~_-]*$ ]] || die "package versions must be exact apt version strings"
done
[[ "$tofu_version:$tofu_linux_amd64_sha256" == "1.12.5:dade9650e6b74fc7a8b986bd8717497d32f9e09cf82e479afef4977fa3085536" ]] || die "OpenTofu does not match the reviewed D3 pin"
[[ "$trivy_version:$trivy_linux_amd64_sha256" == "0.74.0:2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a" ]] || die "Trivy does not match the reviewed D3 pin"
[[ "$azure_cli_package_version" == "2.89.1-1~jammy" ]] || die "Azure CLI does not match the reviewed D3 Jammy pin"
[[ "$docker_package_version" == "29.1.3-0ubuntu3~22.04.2" ]] || die "Docker does not match the reviewed D3 Jammy 29.1.3 pin"
[[ "$docker_buildx_package_version" == "0.30.1-0ubuntu1~22.04.1" ]] || die "Docker Buildx does not match the reviewed D3 Jammy pin"
[[ "$git_package_version" == "1:2.34.1-1ubuntu1.17" ]] || die "git does not match the reviewed D3 Jammy pin"
[[ "$jq_package_version" == "1.6-2.1ubuntu3.2" ]] || die "jq does not match the reviewed D3 Jammy pin"
[[ "$(uname -m)" == "x86_64" ]] || die "this reviewed runner setup supports only the Standard_B2s x86_64 image"
. /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_CODENAME:-}" == "jammy" ]] || die "runner image must be Ubuntu jammy"

# The runner NSG intentionally permits Internet egress only on TCP 443. Azure's
# Jammy image can still ship HTTP archive URIs, so normalize both legacy and
# deb822 sources before the first package-index request.
if [[ -f /etc/apt/sources.list ]]; then
  sed -i \
    -e 's|http://azure.archive.ubuntu.com|https://archive.ubuntu.com|g' \
    -e 's|https://azure.archive.ubuntu.com|https://archive.ubuntu.com|g' \
    -e 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' \
    -e 's|http://security.ubuntu.com|https://security.ubuntu.com|g' \
    /etc/apt/sources.list
fi
if [[ -f /etc/apt/sources.list.d/ubuntu.sources ]]; then
  sed -i \
    -e 's|http://azure.archive.ubuntu.com|https://archive.ubuntu.com|g' \
    -e 's|https://azure.archive.ubuntu.com|https://archive.ubuntu.com|g' \
    -e 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' \
    -e 's|http://security.ubuntu.com|https://security.ubuntu.com|g' \
    /etc/apt/sources.list.d/ubuntu.sources
fi
if grep -RHE '^[[:space:]]*(deb |URIs:).*http://' /etc/apt/sources.list /etc/apt/sources.list.d 2>/dev/null; then
  die "an active apt source still requires blocked plaintext HTTP"
fi
python3 - <<'PY' || die "reviewed HTTPS Ubuntu archive is unreachable"
from urllib.request import urlopen

for url in (
    "https://archive.ubuntu.com/ubuntu/dists/jammy/InRelease",
    "https://security.ubuntu.com/ubuntu/dists/jammy-security/InRelease",
):
    with urlopen(url, timeout=15) as response:
        if response.status != 200:
            raise SystemExit(1)
PY

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates curl gnupg unzip

install -d -m 0755 /etc/apt/keyrings
key_tmp="$(mktemp /tmp/microsoft-signing-key.XXXXXX)"
trap 'rm -f -- "$key_tmp"' EXIT
curl --fail --silent --show-error --location \
  https://packages.microsoft.com/keys/microsoft.asc \
  --output "$key_tmp"
key_fingerprint="$(gpg --show-keys --with-colons "$key_tmp" | awk -F: '$1 == "fpr" {print $10; exit}')"
[[ "$key_fingerprint" == "BC528686B50D79E339D3721CEB3E94ADBE1229CF" ]] || die "Microsoft package-signing key fingerprint changed"
gpg --dearmor --yes --output /etc/apt/keyrings/microsoft.gpg "$key_tmp"
chmod 0644 /etc/apt/keyrings/microsoft.gpg
printf '%s\n' \
  'deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/azure-cli/ jammy main' \
  >/etc/apt/sources.list.d/azure-cli.list

apt-get update
for package_spec in \
  "azure-cli=$azure_cli_package_version" \
  "docker.io=$docker_package_version" \
  "docker-buildx=$docker_buildx_package_version" \
  "git=$git_package_version" \
  "jq=$jq_package_version"; do
  package_name="${package_spec%%=*}"
  package_version="${package_spec#*=}"
  apt-cache madison "$package_name" | awk '{print $3}' | grep -Fx -- "$package_version" >/dev/null || die "reviewed package is unavailable: $package_spec"
done
apt-get install -y --no-install-recommends --allow-downgrades \
  "azure-cli=$azure_cli_package_version" \
  "docker.io=$docker_package_version" \
  "docker-buildx=$docker_buildx_package_version" \
  "git=$git_package_version" \
  "jq=$jq_package_version"
apt-mark hold azure-cli docker.io docker-buildx git jq >/dev/null

tofu_archive="$(mktemp /tmp/tofu.XXXXXX.zip)"
trap 'rm -f -- "$key_tmp" "$tofu_archive"' EXIT
curl --fail --silent --show-error --location \
  "https://github.com/opentofu/opentofu/releases/download/v${tofu_version}/tofu_${tofu_version}_linux_amd64.zip" \
  --output "$tofu_archive"
printf '%s  %s\n' "$tofu_linux_amd64_sha256" "$tofu_archive" | sha256sum --check --status || die "OpenTofu archive checksum does not match the reviewed pin"
tofu_extract_dir="$(mktemp -d /tmp/tofu-extract.XXXXXX)"
export AZURE_CONFIG_DIR="/run/cosmas-azure-cli"
install -d -o root -g root -m 0700 "$AZURE_CONFIG_DIR"
trap 'rm -f -- "$key_tmp" "$tofu_archive"; rm -rf -- "$tofu_extract_dir" "$AZURE_CONFIG_DIR"' EXIT
unzip -q "$tofu_archive" -d "$tofu_extract_dir"
install -o root -g root -m 0755 "$tofu_extract_dir/tofu" /usr/local/bin/tofu

trivy_archive="$(mktemp /tmp/trivy.XXXXXX.tar.gz)"
trivy_extract_dir="$(mktemp -d /tmp/trivy-extract.XXXXXX)"
trap 'rm -f -- "$key_tmp" "$tofu_archive" "$trivy_archive"; rm -rf -- "$tofu_extract_dir" "$trivy_extract_dir" "$AZURE_CONFIG_DIR"' EXIT
curl --fail --silent --show-error --location \
  "https://github.com/aquasecurity/trivy/releases/download/v${trivy_version}/trivy_${trivy_version}_Linux-64bit.tar.gz" \
  --output "$trivy_archive"
printf '%s  %s\n' "$trivy_linux_amd64_sha256" "$trivy_archive" | sha256sum --check --status || die "Trivy archive checksum does not match the reviewed pin"
tar -xzf "$trivy_archive" -C "$trivy_extract_dir" trivy
install -o root -g root -m 0755 "$trivy_extract_dir/trivy" /usr/local/bin/trivy

systemctl enable --now docker.service
[[ -x /usr/libexec/docker/cli-plugins/docker-buildx ]] || die "reviewed Docker Buildx plugin binary is missing"
docker buildx version | grep -F 'v0.30.1' >/dev/null || die "Docker Buildx plugin does not match the reviewed release"
identity_ready=false
for _ in $(seq 1 60); do
  if az login --identity --client-id "$deploy_identity_client_id" --allow-no-subscriptions --output none >/dev/null 2>&1 &&
    az account set --subscription "$subscription_id" >/dev/null 2>&1; then
    identity_ready=true
    break
  fi
  sleep 10
done
[[ "$identity_ready" == "true" ]] || die "attached deploy identity did not become usable within ten minutes"

state_hostname="${state_storage_account}.blob.core.windows.net"
state_ip=""
for _ in $(seq 1 60); do
  state_ip="$(getent ahostsv4 "$state_hostname" 2>/dev/null | awk 'NR == 1 {print $1}')"
  [[ -z "$state_ip" ]] || break
  sleep 10
done
[[ -n "$state_ip" ]] || die "private state hostname did not resolve within ten minutes"
python3 - "$state_ip" <<'PY'
import ipaddress
import sys

if not ipaddress.ip_address(sys.argv[1]).is_private:
    raise SystemExit("state hostname did not resolve to a private IP")
PY

state_access_ready=false
for _ in $(seq 1 60); do
  if az storage container create \
    --auth-mode login \
    --account-name "$state_storage_account" \
    --name tfstate \
    --only-show-errors \
    --output none >/dev/null 2>&1 &&
    [[ "$(az storage container exists --auth-mode login --account-name "$state_storage_account" --name tfstate --query exists --output tsv --only-show-errors 2>/dev/null)" == "true" ]]; then
    state_access_ready=true
    break
  fi
  sleep 10
done
[[ "$state_access_ready" == "true" ]] || die "state Blob RBAC/private access did not become usable within ten minutes"

install -d -o root -g root -m 0700 /var/lib/cosmas-deploy-runner
printf '%s' "$bootstrap_outputs_base64" | base64 --decode >/var/lib/cosmas-deploy-runner/bootstrap-outputs.json
chmod 0600 /var/lib/cosmas-deploy-runner/bootstrap-outputs.json
jq -e '
  .subscription_id.value and
  .tenant_id.value and
  .box_id.value and
  .backend_storage_account_name.value and
  .deploy_identity_client_id.value and
  .runner_vm_name.value and
  .state_blob_private_endpoint_id.value and
  .state_private_endpoint_subnet_id.value and
  (.runner_vm_size.value == "Standard_B2s") and
  .runner_image_version.value == "22.04.202608060"
' /var/lib/cosmas-deploy-runner/bootstrap-outputs.json >/dev/null || die "transported bootstrap outputs are incomplete"
jq -n \
  --arg tofu "$(tofu version -json | jq -r '.terraform_version')" \
  --arg tofu_archive_sha256 "$tofu_linux_amd64_sha256" \
  --arg tofu_binary_sha256 "$(sha256sum /usr/local/bin/tofu | awk '{print $1}')" \
  --arg trivy "$(trivy --version | awk 'NR == 1 {print $2}')" \
  --arg trivy_archive_sha256 "$trivy_linux_amd64_sha256" \
  --arg trivy_binary_sha256 "$(sha256sum /usr/local/bin/trivy | awk '{print $1}')" \
  --arg azure_cli "$(az version --output json | jq -r '."azure-cli"')" \
  --arg azure_cli_package_version "$(dpkg-query -W -f='${Version}' azure-cli)" \
  --arg azure_cli_binary_sha256 "$(sha256sum "$(command -v az)" | awk '{print $1}')" \
  --arg docker "$(docker --version)" \
  --arg docker_server_version "$(docker version --format '{{.Server.Version}}')" \
  --arg docker_package_version "$(dpkg-query -W -f='${Version}' docker.io)" \
  --arg docker_binary_sha256 "$(sha256sum "$(command -v docker)" | awk '{print $1}')" \
  --arg dockerd_binary_sha256 "$(sha256sum /usr/bin/dockerd | awk '{print $1}')" \
  --arg docker_buildx "$(docker buildx version)" \
  --arg docker_buildx_package_version "$(dpkg-query -W -f='${Version}' docker-buildx)" \
  --arg docker_buildx_binary_sha256 "$(sha256sum /usr/libexec/docker/cli-plugins/docker-buildx | awk '{print $1}')" \
  --arg git "$(git --version)" \
  --arg git_package_version "$(dpkg-query -W -f='${Version}' git)" \
  --arg git_binary_sha256 "$(sha256sum "$(command -v git)" | awk '{print $1}')" \
  --arg jq_version "$(jq --version)" \
  --arg jq_package_version "$(dpkg-query -W -f='${Version}' jq)" \
  --arg jq_binary_sha256 "$(sha256sum "$(command -v jq)" | awk '{print $1}')" \
  --arg configured_at "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" '
    {
      configured_at: $configured_at,
      tofu: $tofu,
      tofu_archive_sha256: $tofu_archive_sha256,
      tofu_binary_sha256: $tofu_binary_sha256,
      trivy: $trivy,
      trivy_archive_sha256: $trivy_archive_sha256,
      trivy_binary_sha256: $trivy_binary_sha256,
      azure_cli: $azure_cli,
      azure_cli_package_version: $azure_cli_package_version,
      azure_cli_binary_sha256: $azure_cli_binary_sha256,
      docker: $docker,
      docker_server_version: $docker_server_version,
      docker_package_version: $docker_package_version,
      docker_binary_sha256: $docker_binary_sha256,
      dockerd_binary_sha256: $dockerd_binary_sha256,
      docker_buildx: $docker_buildx,
      docker_buildx_package_version: $docker_buildx_package_version,
      docker_buildx_binary_sha256: $docker_buildx_binary_sha256,
      git: $git,
      git_package_version: $git_package_version,
      git_binary_sha256: $git_binary_sha256,
      jq: $jq_version,
      jq_package_version: $jq_package_version,
      jq_binary_sha256: $jq_binary_sha256
    }
  ' >/var/lib/cosmas-deploy-runner/toolchain.json
chmod 0600 /var/lib/cosmas-deploy-runner/toolchain.json

printf '%s\n' "D3 protected runner is ready; private state DNS and managed-identity access passed"
