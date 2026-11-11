#!/usr/bin/env bash
# End-to-end UNSIGNED Debug iPhone Simulator record/mic-permission test.
#
# Runs in a throwaway temp folder against any PR head (PR number or SHA).
# Does NOT touch an existing checkout such as ~/Desktop/cosmaneura-os.
# Synthetic inputs only: no real keys, no signing, no TestFlight, no deploy.
#
# Mac exact command (from a checkout that contains this script, typically this PR):
#
#   ./scripts/run-iphone-sim-record-test.sh 349
#   ./scripts/run-iphone-sim-record-test.sh 179e739f
#
# Prerequisites on the Mac:
#   - Full Xcode (not Command Line Tools alone). If `xcodebuild -version` fails
#     because xcode-select points at CLT, set:
#       export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
#   - Node.js 24 on PATH (Homebrew node@24, nvm, or COSMAS_NODE_BIN=/path/to/node).
#
# Optional:
#   COSMAS_SIM_NAME="iPhone 16"   # reuse/create this device name; otherwise a
#                                # throwaway sim is created from the newest
#                                # iPhone type + iOS runtime and deleted on exit
#   COSMAS_ARTIFACTS=/tmp/cosmas-mic-artifacts
#   COSMAS_NODE_BIN=/opt/homebrew/opt/node@24/bin/node
#   DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
set -euo pipefail

# From `simctl list runtimes -j` (+ device type id): pick the newest available
# generic iOS runtime that lists the device in supportedDeviceTypes. Skips
# device-specific runtimes such as iOS-27-2-iPhone19-4 (suffix after version
# and/or a restricted supportedDeviceTypes list).
select_ios_runtime_for_device() {
  local device_type_id="$1"
  local json_file="${2:-}"
  local json
  if [[ -n "${json_file}" ]]; then
    json="$(cat "${json_file}")"
  else
    json="$(xcrun simctl list runtimes -j)"
  fi
  printf '%s' "${json}" | python3 -c '
import json, re, sys

device = sys.argv[1]
data = json.load(sys.stdin)
runtimes = data.get("runtimes", data if isinstance(data, list) else [])
generic_ios = re.compile(
    r"^com\.apple\.CoreSimulator\.SimRuntime\.iOS-\d+(?:-\d+)*$"
)

def available(rt: dict) -> bool:
    if rt.get("isAvailable") is True:
        return True
    if rt.get("available") is True:
        return True
    return False

def version_score(rt: dict) -> tuple:
    raw = str(rt.get("version") or "")
    parts = []
    for piece in raw.split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

def supports_device(rt: dict, device_id: str) -> bool:
    supported = rt.get("supportedDeviceTypes") or []
    if not isinstance(supported, list) or not supported:
        return False
    for entry in supported:
        if isinstance(entry, dict) and entry.get("identifier") == device_id:
            return True
        if isinstance(entry, str) and entry == device_id:
            return True
    return False

candidates = []
for rt in runtimes:
    if not isinstance(rt, dict):
        continue
    ident = rt.get("identifier") or ""
    name = str(rt.get("name") or "")
    platform = str(rt.get("platform") or "")
    if not available(rt):
        continue
    if platform and platform.lower() not in ("ios", "iphoneos"):
        # Some listings omit platform; fall back to name / identifier.
        if "ios" not in name.lower() and ".ios-" not in ident.lower():
            continue
    elif not platform and "ios" not in name.lower() and ".ios-" not in ident.lower():
        continue
    # Device-specific runtime: suffix after the numeric iOS version (e.g. -iPhone19-4).
    if not generic_ios.match(ident):
        continue
    if not supports_device(rt, device):
        continue
    candidates.append((version_score(rt), ident))

if not candidates:
    raise SystemExit(1)
candidates.sort(reverse=True)
print(candidates[0][1])
' "${device_type_id}"
}

# Linux CI unit-test entry (no macOS / Xcode required).
if [[ "${1:-}" == "--select-runtime-for-device" ]]; then
  device_type_id="${2:?usage: $0 --select-runtime-for-device DEVICE_TYPE_ID RUNTIMES_JSON}"
  json_file="${3:?usage: $0 --select-runtime-for-device DEVICE_TYPE_ID RUNTIMES_JSON}"
  if ! select_ios_runtime_for_device "${device_type_id}" "${json_file}"; then
    echo "No available iOS Simulator runtime supports device type ${device_type_id}." >&2
    echo "Skipped device-specific or incompatible runtimes (e.g. *-iPhone19-4)." >&2
    exit 1
  fi
  exit 0
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This runner requires macOS with Xcode and an iOS Simulator." >&2
  exit 2
fi

REF_ARG="${1:-}"
if [[ -z "$REF_ARG" ]]; then
  echo "Usage: $0 <pr-number-or-sha>" >&2
  exit 2
fi

TOOLING_ROOT="$(CDPATH= cd "$(dirname "$0")/.." && pwd)"
REPO_URL="${COSMAS_REPO_URL:-https://github.com/CosmaNeura/cosmaneura-os.git}"
SIM_NAME_OVERRIDE="${COSMAS_SIM_NAME:-}"
ARTIFACTS="${COSMAS_ARTIFACTS:-}"
CREATED_SIM_UDID=""
WORK=""

cleanup() {
  local status=$?
  if [[ -n "${CREATED_SIM_UDID}" ]]; then
    echo "==> Deleting throwaway simulator ${CREATED_SIM_UDID}"
    xcrun simctl shutdown "${CREATED_SIM_UDID}" >/dev/null 2>&1 || true
    xcrun simctl delete "${CREATED_SIM_UDID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${WORK}" && -d "${WORK}" ]]; then
    rm -rf "${WORK}"
  fi
  exit "${status}"
}
trap cleanup EXIT

# --- Xcode / DEVELOPER_DIR ----------------------------------------------------
if [[ -n "${DEVELOPER_DIR:-}" ]]; then
  export DEVELOPER_DIR
  echo "==> Using DEVELOPER_DIR=${DEVELOPER_DIR}"
fi

if ! command -v xcodebuild >/dev/null 2>&1; then
  echo "xcodebuild not found on PATH." >&2
  echo "Install full Xcode, then either:" >&2
  echo "  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer" >&2
  echo "or for this shell only:" >&2
  echo "  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer" >&2
  exit 2
fi

if ! xcodebuild -version >/dev/null 2>&1; then
  echo "xcodebuild is present but not usable (often because xcode-select points" >&2
  echo "at Command Line Tools only). Set a full Xcode developer dir, for example:" >&2
  echo "  export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer" >&2
  echo "Then re-run: $0 ${REF_ARG}" >&2
  exit 2
fi

# --- Node 24 before corepack --------------------------------------------------
node_major() {
  local bin="$1"
  "$bin" -p "process.versions.node.split('.')[0]" 2>/dev/null || true
}

resolve_node24() {
  local candidate major
  local -a candidates=()
  if [[ -n "${COSMAS_NODE_BIN:-}" ]]; then
    candidates+=("${COSMAS_NODE_BIN}")
  fi
  if command -v node >/dev/null 2>&1; then
    candidates+=("$(command -v node)")
  fi
  candidates+=(
    /opt/homebrew/opt/node@24/bin/node
    /usr/local/opt/node@24/bin/node
  )
  # Newest nvm Node 24 if present.
  local nvm_node
  for nvm_node in \
    "${HOME}/.nvm/versions/node"/v24.*/bin/node \
    "${HOME}/.local/share/nvm/versions/node"/v24.*/bin/node; do
    [[ -x "${nvm_node}" ]] && candidates+=("${nvm_node}")
  done

  for candidate in "${candidates[@]}"; do
    [[ -z "${candidate}" || ! -x "${candidate}" ]] && continue
    major="$(node_major "${candidate}")"
    if [[ "${major}" == "24" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

if ! NODE_BIN="$(resolve_node24)"; then
  echo "Node.js 24 is required before corepack enable (got none on PATH)." >&2
  echo "Install Node 24, or set COSMAS_NODE_BIN to a Node 24 binary, e.g.:" >&2
  echo "  export COSMAS_NODE_BIN=/opt/homebrew/opt/node@24/bin/node" >&2
  if command -v node >/dev/null 2>&1; then
    echo "Found node at $(command -v node) (version $(node -v 2>/dev/null || echo unknown))." >&2
  fi
  exit 2
fi
NODE_DIR="$(CDPATH= cd "$(dirname "${NODE_BIN}")" && pwd)"
export PATH="${NODE_DIR}:${PATH}"
echo "==> Node $(node -v) from ${NODE_BIN}"

# Host-arch-aware unsigned Simulator settings (Apple Silicon must not try x86_64).
HOST_ARCH="$(uname -m)"
case "${HOST_ARCH}" in
  arm64)
    ARCH_SETTINGS=(ONLY_ACTIVE_ARCH=YES ARCHS=arm64 EXCLUDED_ARCHS=x86_64)
    ;;
  x86_64)
    ARCH_SETTINGS=(ONLY_ACTIVE_ARCH=YES ARCHS=x86_64 EXCLUDED_ARCHS=arm64)
    ;;
  *)
    ARCH_SETTINGS=(ONLY_ACTIVE_ARCH=YES)
    ;;
esac
echo "==> xcodebuild arch settings: ${ARCH_SETTINGS[*]} (host ${HOST_ARCH})"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-iphone-sim-XXXXXX")"

case "$WORK" in
  *Desktop/cosmaneura-os*|*Desktop/cosmaneura-os)
    echo "Refusing a work path that looks like the Desktop checkout." >&2
    exit 2
    ;;
esac

SRC="$WORK/src"
OUT="$WORK/out"
mkdir -p "$OUT"
# Keep artifacts outside the throwaway clone so trap cleanup does not erase them.
if [[ -z "$ARTIFACTS" ]]; then
  ARTIFACTS="/tmp/cosmas-iphone-sim-artifacts-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$ARTIFACTS"

echo "==> Throwaway workdir: $WORK"
echo "==> Tooling overlay from: $TOOLING_ROOT"

git clone --filter=blob:none "$REPO_URL" "$SRC"
cd "$SRC"

if [[ "$REF_ARG" =~ ^[0-9]+$ ]]; then
  echo "==> Fetching pull/$REF_ARG/head"
  git fetch --depth=1 origin "pull/${REF_ARG}/head"
  git checkout --detach FETCH_HEAD
else
  echo "==> Fetching $REF_ARG"
  git fetch --depth=1 origin "$REF_ARG"
  git checkout --detach FETCH_HEAD
fi

HEAD_SHA="$(git rev-parse HEAD)"
echo "==> Building SHA $HEAD_SHA"

# Overlay tooling + apple Simulator hooks from the invoking checkout so older
# PR heads (e.g. 349 @ 179e739f) still get the composer/web-bundle/XCUITest fixes.
overlay() {
  local rel="$1"
  mkdir -p "$(dirname "$SRC/$rel")"
  rm -rf "$SRC/$rel"
  cp -R "$TOOLING_ROOT/$rel" "$SRC/$rel"
}

overlay scripts/compose-portable-iphone.py
overlay scripts/prepare-synthetic-iphone-web-bundle.mjs
overlay scripts/configure-synthetic-iphone-simulator.py
overlay clients/shared/operational-native-identity.mjs
overlay clients/apple/startup-recovery/CosmasWorkspaceViewController.swift
overlay clients/apple/startup-recovery/CosmasBridgeViewController.swift
overlay clients/apple/startup-recovery/SyntheticDemoFixtureGate.swift
overlay clients/apple/ui-tests
overlay clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift
# ClerkKeychainCredentials already lives on main; ensure the owned source exists.
if [[ ! -f clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift ]]; then
  overlay clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift
fi
if [[ ! -f clients/apple/native-auth/Tests/CosmasNativeAuthTests/ClerkKeychainCredentialsTests.swift ]]; then
  overlay clients/apple/native-auth/Tests/CosmasNativeAuthTests/ClerkKeychainCredentialsTests.swift
fi

echo "==> Install frozen web/capture client deps (synthetic build only)"
corepack enable
./scripts/install-client-deps.sh

echo "==> Compose portable iPhone project inputs"
python3 scripts/compose-portable-iphone.py --repository "$SRC" --output "$OUT/composed"

echo "==> Synthetic web bundle (pk_test_ + *.synthetic.example)"
node scripts/prepare-synthetic-iphone-web-bundle.mjs --output "$OUT/web-bundle"

echo "==> Configure UNSIGNED com.cosmasos.synthetic Simulator project"
python3 scripts/configure-synthetic-iphone-simulator.py \
  --composed "$OUT/composed" \
  --web-dist "$OUT/web-bundle/renderer/dist"

PROJECT="$OUT/composed/apps/capture/ios/App/App.xcodeproj"
DERIVED="$OUT/DerivedData"

# --- Throwaway (or named) Simulator ------------------------------------------
newest_iphone_devicetype() {
  # Prefer the highest numeric product among iPhone device types.
  xcrun simctl list devicetypes \
    | awk -F '[()]' '/iPhone/ { gsub(/^ +| +$/, "", $1); id=$2; print $0 "\t" id }' \
    | awk -F '\t' '
        {
          name=$1; id=$2;
          n=name; gsub(/[^0-9]/, " ", n);
          split(n, a, " ");
          score=0;
          for (i in a) if (a[i] != "") score = score * 100 + a[i] + 0;
          print score "\t" id "\t" name
        }' \
    | sort -nr \
    | head -n 1 \
    | cut -f2-3
}

echo "==> Creating / selecting Simulator"
DEVICE_INFO="$(newest_iphone_devicetype)"
DEVICE_TYPE_ID="$(echo "${DEVICE_INFO}" | cut -f1)"
DEVICE_TYPE_NAME="$(echo "${DEVICE_INFO}" | cut -f2-)"
if [[ -z "${DEVICE_TYPE_ID}" ]]; then
  echo "Could not resolve an iPhone device type from simctl." >&2
  echo "Install an iOS Simulator runtime in Xcode → Settings → Platforms." >&2
  exit 1
fi
if ! RUNTIME_ID="$(select_ios_runtime_for_device "${DEVICE_TYPE_ID}")"; then
  echo "No available iOS Simulator runtime supports device type ${DEVICE_TYPE_ID} (${DEVICE_TYPE_NAME})." >&2
  echo "Skipped device-specific or incompatible runtimes (e.g. iOS-*-iPhone19-4 / Duo-only)." >&2
  echo "Install a generic iOS runtime that supports this device in Xcode → Settings → Platforms." >&2
  exit 1
fi
echo "    device type: ${DEVICE_TYPE_NAME} (${DEVICE_TYPE_ID})"
echo "    runtime:     ${RUNTIME_ID}"

if [[ -n "${SIM_NAME_OVERRIDE}" ]]; then
  SIM_UDID="$(xcrun simctl list devices available | awk -F '[()]' -v n="${SIM_NAME_OVERRIDE}" '
    $0 ~ n && $0 !~ /unavailable/ { print $2; exit }
  ')"
  if [[ -z "${SIM_UDID}" ]]; then
    echo "==> COSMAS_SIM_NAME='${SIM_NAME_OVERRIDE}' not found; creating it"
    SIM_UDID="$(xcrun simctl create "${SIM_NAME_OVERRIDE}" "${DEVICE_TYPE_ID}" "${RUNTIME_ID}")"
    CREATED_SIM_UDID="${SIM_UDID}"
  else
    echo "==> Reusing available simulator '${SIM_NAME_OVERRIDE}' (${SIM_UDID})"
  fi
  SIM_NAME="${SIM_NAME_OVERRIDE}"
else
  SIM_NAME="cosmas-mic-uitest-$$"
  SIM_UDID="$(xcrun simctl create "${SIM_NAME}" "${DEVICE_TYPE_ID}" "${RUNTIME_ID}")"
  CREATED_SIM_UDID="${SIM_UDID}"
  echo "==> Created throwaway simulator ${SIM_NAME} (${SIM_UDID})"
fi

echo "==> xcodebuild Debug iphonesimulator CODE_SIGNING_ALLOWED=NO"
xcodebuild \
  -project "$PROJECT" \
  -scheme App \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,id=${SIM_UDID}" \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  "${ARCH_SETTINGS[@]}" \
  build | tee "$ARTIFACTS/xcodebuild-app.log"

APP_PATH="$(find "$DERIVED/Build/Products" -name 'App.app' -type d | head -n 1)"
if [[ -z "$APP_PATH" ]]; then
  echo "App.app not found under $DERIVED" >&2
  exit 1
fi

echo "==> Boot simulator ${SIM_NAME} (${SIM_UDID})"
xcrun simctl bootstatus "$SIM_UDID" -b || xcrun simctl boot "$SIM_UDID"
xcrun simctl bootstatus "$SIM_UDID" -b

echo "==> Reset microphone privacy, then install"
xcrun simctl privacy "$SIM_UDID" reset microphone
xcrun simctl uninstall "$SIM_UDID" com.cosmasos.synthetic 2>/dev/null || true
xcrun simctl install "$SIM_UDID" "$APP_PATH"

echo "==> Generate and run MicrophonePermissionUITests"
python3 clients/apple/ui-tests/generate-uitest-project.py
python3 clients/apple/ui-tests/prove_release_excludes_demo_fixture.py

RESULT_BUNDLE="$ARTIFACTS/mic-permission.xcresult"
rm -rf "$RESULT_BUNDLE"
xcodebuild test \
  -project clients/apple/ui-tests/CosmasSyntheticUITests.xcodeproj \
  -scheme CosmasSyntheticUITests \
  -destination "platform=iOS Simulator,id=${SIM_UDID}" \
  -only-testing:CosmasSyntheticUITests/MicrophonePermissionUITests \
  -resultBundlePath "$RESULT_BUNDLE" \
  CODE_SIGNING_ALLOWED=NO \
  "${ARCH_SETTINGS[@]}" \
  | tee "$ARTIFACTS/xcodebuild-uitest.log"

# Extract screenshots from the result bundle when present.
if command -v xcparse >/dev/null 2>&1; then
  xcparse screenshots "$RESULT_BUNDLE" "$ARTIFACTS/screenshots" || true
else
  mkdir -p "$ARTIFACTS/screenshots"
  find "$RESULT_BUNDLE" -type f \( -name '*.png' -o -name '*.jpg' \) -print0 \
    | while IFS= read -r -d '' shot; do
        cp "$shot" "$ARTIFACTS/screenshots/"
      done || true
fi

printf '%s\n' "$HEAD_SHA" > "$ARTIFACTS/tested-sha.txt"
echo "==> Done. Artifacts: $ARTIFACTS"
echo "    SHA: $HEAD_SHA"
echo "    App: $APP_PATH"
echo "    Sim: ${SIM_NAME} (${SIM_UDID})"
