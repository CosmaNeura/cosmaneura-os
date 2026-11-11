#!/usr/bin/env bash
# End-to-end UNSIGNED Debug iPhone Simulator record/mic-permission test.
#
# Runs in a throwaway temp folder against any PR head (PR number or full SHA).
# Does NOT touch an existing checkout such as ~/Desktop/cosmaneura-os.
# Synthetic inputs only: no real keys, no signing, no TestFlight, no deploy.
#
# Mac exact command (from a checkout that contains this script, typically this PR):
#
#   ./scripts/run-iphone-sim-record-test.sh 349
#   ./scripts/run-iphone-sim-record-test.sh 179e739f0278a05706531ffb1288cb1df7acf507b
#
# Abbreviated SHAs are resolved only when already present in the tooling
# checkout's object database; otherwise pass a full SHA or PR number.
#
# Prerequisites on the Mac:
#   - Full Xcode (not Command Line Tools alone). If `xcodebuild -version` fails
#     because xcode-select points at CLT, set:
#       export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
#   - Node.js 24 on PATH (Homebrew node@24, nvm, or COSMAS_NODE_BIN=/path/to/node).
#
# Optional:
#   COSMAS_SIM_NAME="Exact Device Name"  # exact-name reuse; no runtime reselect
#   COSMAS_ARTIFACTS=/tmp/cosmas-mic-artifacts
#   COSMAS_NODE_BIN=/opt/homebrew/opt/node@24/bin/node
#   DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
set -euo pipefail

# Select newest available iOS runtime (>= 17.0) that is not device-restricted
# (e.g. Duo-only iOS-27-2-iPhone19-4), then newest iPhone device type it lists.
# Prints: <runtime_id><TAB><device_type_id><TAB><device_name>
select_ios_runtime_and_iphone() {
  local runtimes_json_file="${1:-}"
  local devices_json_file="${2:-}"
  local runtimes_json devices_json
  if [[ -n "${runtimes_json_file}" ]]; then
    runtimes_json="$(cat "${runtimes_json_file}")"
  else
    runtimes_json="$(xcrun simctl list runtimes -j)"
  fi
  if [[ -n "${devices_json_file}" ]]; then
    devices_json="$(cat "${devices_json_file}")"
  else
    devices_json="$(xcrun simctl list devicetypes -j)"
  fi
  RUNTIMES_JSON="${runtimes_json}" DEVICES_JSON="${devices_json}" python3 - <<'PY'
import json, os, re, sys

runtimes = json.loads(os.environ["RUNTIMES_JSON"]).get("runtimes", [])
devicetypes = json.loads(os.environ["DEVICES_JSON"]).get("devicetypes", [])
by_id = {
    d.get("identifier"): d
    for d in devicetypes
    if isinstance(d, dict) and d.get("identifier")
}

def available(rt: dict) -> bool:
    return rt.get("isAvailable") is True or rt.get("available") is True

def version_tuple(raw: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for piece in str(raw or "").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]

def is_ios_runtime(rt: dict) -> bool:
    platform = str(rt.get("platform") or "").lower()
    name = str(rt.get("name") or "").lower()
    ident = str(rt.get("identifier") or "").lower()
    if platform in ("ios", "iphoneos"):
        return True
    return "ios" in name or ".ios-" in ident

def supported_ids(rt: dict) -> list[str]:
    out: list[str] = []
    for entry in rt.get("supportedDeviceTypes") or []:
        if isinstance(entry, dict) and entry.get("identifier"):
            out.append(entry["identifier"])
        elif isinstance(entry, str):
            out.append(entry)
    return out

def is_restricted_runtime(rt: dict) -> bool:
    """Device-specific / Duo-only runtimes lack a usable standard iPhone product."""
    for entry in rt.get("supportedDeviceTypes") or []:
        if isinstance(entry, dict):
            text = f"{entry.get('name') or ''} {entry.get('identifier') or ''}".lower()
        else:
            text = str(entry).lower()
        if "iphone" in text and "duo" not in text:
            return False
    return True

def iphone_score(ident: str, name: str) -> tuple:
    text = f"{name} {ident}"
    nums = [int(n) for n in re.findall(r"\d+", text)]
    score = 0
    for n in nums:
        score = score * 100 + n
    # Prefer Pro Max / Pro over base when scores tie loosely.
    boost = 0
    lower = text.lower()
    if "pro-max" in lower or "pro max" in lower:
        boost = 2
    elif re.search(r"\bpro\b", lower):
        boost = 1
    return (score, boost, name)

candidates = []
for rt in runtimes:
    if not isinstance(rt, dict) or not available(rt) or not is_ios_runtime(rt):
        continue
    ver = version_tuple(str(rt.get("version") or ""))
    if ver < (17, 0, 0):
        continue
    if is_restricted_runtime(rt):
        continue
    ident = rt.get("identifier")
    if not ident:
        continue
    candidates.append((ver, ident, rt))

if not candidates:
    raise SystemExit("no available iOS >= 17.0 runtime with a standard iPhone device type")
candidates.sort(key=lambda item: item[0], reverse=True)
runtime_ver, runtime_id, runtime = candidates[0]

iphones = []
for device_id in supported_ids(runtime):
    meta = by_id.get(device_id) or {}
    name = str(meta.get("name") or device_id)
    if "iphone" not in name.lower() and "iphone" not in device_id.lower():
        continue
    if "duo" in name.lower() or device_id.endswith("iPhone-Duo"):
        continue
    iphones.append((iphone_score(device_id, name), device_id, name))

if not iphones:
    raise SystemExit(f"runtime {runtime_id} lists no usable iPhone device type")
iphones.sort(reverse=True)
_, device_id, device_name = iphones[0]
print(f"{runtime_id}\t{device_id}\t{device_name}")
PY
}

# Linux CI helpers (no macOS / Xcode required).
if [[ "${1:-}" == "--select-runtime-and-iphone" ]]; then
  select_ios_runtime_and_iphone "${2:?runtimes.json}" "${3:?devicetypes.json}"
  exit 0
fi

if [[ "${1:-}" == "--select-runtime-for-device" ]]; then
  # Back-compat for fixture: pick newest non-restricted runtime that supports DEVICE.
  device_type_id="${2:?device type id}"
  json_file="${3:?runtimes.json}"
  python3 - "$device_type_id" "$json_file" <<'PY'
import json, sys

device = sys.argv[1]
runtimes = json.load(open(sys.argv[2])).get("runtimes", [])

def available(rt):
    return rt.get("isAvailable") is True or rt.get("available") is True

def version_tuple(raw):
    parts = []
    for piece in str(raw or "").split("."):
        try:
            parts.append(int(piece))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

def supported_ids(rt):
    out = []
    for entry in rt.get("supportedDeviceTypes") or []:
        if isinstance(entry, dict) and entry.get("identifier"):
            out.append(entry["identifier"])
        elif isinstance(entry, str):
            out.append(entry)
    return out

def is_restricted(rt):
    for entry in rt.get("supportedDeviceTypes") or []:
        if isinstance(entry, dict):
            text = f"{entry.get('name') or ''} {entry.get('identifier') or ''}".lower()
        else:
            text = str(entry).lower()
        if "iphone" in text and "duo" not in text:
            return False
    return True

cands = []
for rt in runtimes:
    if not isinstance(rt, dict) or not available(rt):
        continue
    if version_tuple(rt.get("version")) < (17, 0, 0):
        continue
    if is_restricted(rt):
        continue
    if device not in supported_ids(rt):
        continue
    ident = rt.get("identifier")
    if ident:
        cands.append((version_tuple(rt.get("version")), ident))
if not cands:
    print(
        f"No available iOS Simulator runtime supports device type {device}",
        file=sys.stderr,
    )
    raise SystemExit(1)
cands.sort(reverse=True)
print(cands[0][1])
PY
  exit $?
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This runner requires macOS with Xcode and an iOS Simulator." >&2
  exit 2
fi

REF_ARG="${1:-}"
if [[ -z "$REF_ARG" ]]; then
  echo "Usage: $0 <pr-number-or-full-sha>" >&2
  echo "Abbreviated SHAs are accepted only when already resolvable in this checkout." >&2
  exit 2
fi

TOOLING_ROOT="$(CDPATH='' cd "$(dirname "$0")/.." && pwd)"
TOOLING_SHA="$(git -C "$TOOLING_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
REPO_URL="${COSMAS_REPO_URL:-https://github.com/CosmaNeura/cosmaneura-os.git}"
SIM_NAME_OVERRIDE="${COSMAS_SIM_NAME:-}"
ARTIFACTS="${COSMAS_ARTIFACTS:-}"
CREATED_SIM_UDID=""
REUSED_SIM_UDID=""
SIM_UDID=""
WORK=""
TEST_STATUS=0
OVERLAID_FILES=()

# shellcheck disable=SC2317 # invoked via EXIT trap
cleanup() {
  local status=$?
  if [[ -n "${CREATED_SIM_UDID}" ]]; then
    echo "==> Deleting throwaway simulator ${CREATED_SIM_UDID}"
    xcrun simctl shutdown "${CREATED_SIM_UDID}" >/dev/null 2>&1 || true
    xcrun simctl delete "${CREATED_SIM_UDID}" >/dev/null 2>&1 || true
  elif [[ -n "${REUSED_SIM_UDID}" ]]; then
    echo "==> Resetting reused simulator privacy/uninstall for com.cosmasos.synthetic"
    xcrun simctl privacy "${REUSED_SIM_UDID}" reset microphone com.cosmasos.synthetic >/dev/null 2>&1 || true
    xcrun simctl uninstall "${REUSED_SIM_UDID}" com.cosmasos.synthetic >/dev/null 2>&1 || true
  fi
  # Sweep stale throwaway devices from interrupted prior runs.
  if command -v python3 >/dev/null 2>&1; then
    local sweep_json
    sweep_json="$(mktemp)"
    if xcrun simctl list devices -j >"${sweep_json}" 2>/dev/null; then
      python3 - "${sweep_json}" <<'PY' || true
import json, subprocess, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    raise SystemExit(0)
for _runtime, devices in (data.get("devices") or {}).items():
    for device in devices or []:
        name = str(device.get("name") or "")
        udid = device.get("udid")
        if udid and name.startswith("cosmas-mic-uitest-"):
            subprocess.run(["xcrun", "simctl", "shutdown", udid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(["xcrun", "simctl", "delete", udid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
PY
    fi
    rm -f "${sweep_json}"
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
NODE_DIR="$(CDPATH='' cd "$(dirname "${NODE_BIN}")" && pwd)"
export PATH="${NODE_DIR}:${PATH}"
echo "==> Node $(node -v) from ${NODE_BIN}"

HOST_ARCH="$(uname -m)"
case "${HOST_ARCH}" in
  arm64) ARCH_SETTINGS=(ONLY_ACTIVE_ARCH=YES ARCHS=arm64 EXCLUDED_ARCHS=x86_64) ;;
  x86_64) ARCH_SETTINGS=(ONLY_ACTIVE_ARCH=YES ARCHS=x86_64 EXCLUDED_ARCHS=arm64) ;;
  *) ARCH_SETTINGS=(ONLY_ACTIVE_ARCH=YES) ;;
esac
echo "==> xcodebuild arch settings: ${ARCH_SETTINGS[*]} (host ${HOST_ARCH})"

if [[ -z "$ARTIFACTS" ]]; then
  ARTIFACTS="/tmp/cosmas-iphone-sim-artifacts-$(date +%Y%m%d-%H%M%S)"
fi
mkdir -p "$ARTIFACTS"

# --- Preflight device/runtime selection (before clone/install) ----------------
REUSE_EXISTING_SIM=0
if [[ -n "${SIM_NAME_OVERRIDE}" ]]; then
  local_devices_json="$(mktemp)"
  xcrun simctl list devices -j >"${local_devices_json}"
  SIM_MATCH="$(python3 - "${local_devices_json}" "${SIM_NAME_OVERRIDE}" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
wanted = sys.argv[2]
for _runtime, devices in (data.get("devices") or {}).items():
    for device in devices or []:
        if device.get("name") == wanted and device.get("isAvailable", True):
            print(device.get("udid", ""))
            raise SystemExit(0)
raise SystemExit(1)
PY
)" || SIM_MATCH=""
  rm -f "${local_devices_json}"
  if [[ -n "${SIM_MATCH}" ]]; then
    REUSE_EXISTING_SIM=1
    SIM_UDID="${SIM_MATCH}"
    SIM_NAME="${SIM_NAME_OVERRIDE}"
    REUSED_SIM_UDID="${SIM_UDID}"
    echo "==> Reusing COSMAS_SIM_NAME exact match '${SIM_NAME}' (${SIM_UDID}); skipping runtime selection"
  fi
fi

if [[ "${REUSE_EXISTING_SIM}" -eq 0 ]]; then
  echo "==> Preflight: select newest iOS >= 17 runtime, then newest iPhone it supports"
  SELECTED="$(select_ios_runtime_and_iphone)" || {
    echo "No usable iOS >= 17.0 Simulator runtime / iPhone device type pair found." >&2
    echo "Install a generic iOS runtime in Xcode → Settings → Platforms." >&2
    exit 1
  }
  RUNTIME_ID="$(printf '%s\n' "${SELECTED}" | cut -f1)"
  DEVICE_TYPE_ID="$(printf '%s\n' "${SELECTED}" | cut -f2)"
  DEVICE_TYPE_NAME="$(printf '%s\n' "${SELECTED}" | cut -f3-)"
  echo "    runtime:     ${RUNTIME_ID}"
  echo "    device type: ${DEVICE_TYPE_NAME} (${DEVICE_TYPE_ID})"
  printf '%s\n' "${SELECTED}" > "$ARTIFACTS/selected-runtime-device.txt"
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-iphone-sim-XXXXXX")"
case "$WORK" in
  *Desktop/cosmaneura-os*)
    echo "Refusing a work path that looks like the Desktop checkout." >&2
    exit 2
    ;;
esac

SRC="$WORK/src"
OUT="$WORK/out"
mkdir -p "$OUT"

echo "==> Throwaway workdir: $WORK"
echo "==> Tooling checkout: $TOOLING_ROOT @ ${TOOLING_SHA}"

git clone --filter=blob:none "$REPO_URL" "$SRC"
cd "$SRC"

resolve_target_ref() {
  local ref="$1"
  if [[ "$ref" =~ ^[0-9]+$ ]]; then
    echo "==> Fetching pull/${ref}/head"
    git fetch --depth=1 origin "pull/${ref}/head"
    git checkout --detach FETCH_HEAD
    return 0
  fi
  if [[ "$ref" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "==> Fetching full SHA ${ref}"
    git fetch --depth=1 origin "$ref"
    git checkout --detach FETCH_HEAD
    return 0
  fi
  # Abbreviated SHA: only when the tooling checkout already has the object.
  if [[ "$ref" =~ ^[0-9a-fA-F]{7,39}$ ]]; then
    local full
    if full="$(git -C "$TOOLING_ROOT" rev-parse --verify "${ref}^{commit}" 2>/dev/null)"; then
      echo "==> Resolved abbreviated SHA ${ref} -> ${full} from tooling checkout"
      git fetch --depth=1 origin "$full"
      git checkout --detach FETCH_HEAD
      return 0
    fi
    echo "Abbreviated SHA '${ref}' is not resolvable from this tooling checkout." >&2
    echo "Pass a full 40-character SHA or a PR number." >&2
    exit 2
  fi
  echo "Unsupported ref '${ref}'. Pass a PR number or full commit SHA." >&2
  exit 2
}

resolve_target_ref "$REF_ARG"
HEAD_SHA="$(git rev-parse HEAD)"
echo "==> Target SHA $HEAD_SHA"

# Overlay tooling only when hooks are absent, or as a conflict-failing patch.
overlay_if_absent() {
  local rel="$1"
  if [[ -e "$SRC/$rel" ]]; then
    echo "    keep target $rel"
    return 0
  fi
  echo "    overlay absent $rel"
  mkdir -p "$(dirname "$SRC/$rel")"
  cp -R "$TOOLING_ROOT/$rel" "$SRC/$rel"
  OVERLAID_FILES+=("$rel")
}

overlay_patch_or_absent() {
  local rel="$1"
  if [[ ! -e "$SRC/$rel" ]]; then
    overlay_if_absent "$rel"
    return 0
  fi
  if cmp -s "$TOOLING_ROOT/$rel" "$SRC/$rel" 2>/dev/null; then
    echo "    identical $rel"
    return 0
  fi
  # Apply a unified diff with relative paths; fail on conflict (never silent replace).
  local diff_file
  diff_file="$(mktemp)"
  if diff -u "$SRC/$rel" "$TOOLING_ROOT/$rel" \
      | sed "1s|.*|--- a/${rel}|;2s|.*|+++ b/${rel}|" >"$diff_file"; then
    rm -f "$diff_file"
    return 0
  fi
  if ! (cd "$SRC" && patch --batch --forward --dry-run -p1 <"$diff_file" >/dev/null 2>&1); then
    echo "Overlay patch would conflict for $rel; refusing silent replace of target SHA sources." >&2
    rm -f "$diff_file"
    exit 1
  fi
  (cd "$SRC" && patch --batch --forward -p1 <"$diff_file" >/dev/null)
  OVERLAID_FILES+=("$rel (patched)")
  echo "    patched $rel"
  rm -f "$diff_file"
}

echo "==> Conditional overlays from tooling ${TOOLING_SHA}"
overlay_if_absent scripts/compose-portable-iphone.py
overlay_if_absent scripts/prepare-synthetic-iphone-web-bundle.mjs
overlay_if_absent scripts/configure-synthetic-iphone-simulator.py
overlay_if_absent clients/shared/operational-native-identity.mjs
overlay_patch_or_absent clients/apple/startup-recovery/CosmasWorkspaceViewController.swift
overlay_patch_or_absent clients/apple/startup-recovery/CosmasBridgeViewController.swift
overlay_patch_or_absent clients/apple/startup-recovery/SyntheticDemoFixtureGate.swift
overlay_if_absent clients/apple/ui-tests
overlay_patch_or_absent clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift
if [[ ! -f clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift ]]; then
  overlay_if_absent clients/apple/native-auth/Sources/CosmasNativeAuth/ClerkKeychainCredentials.swift
fi
if [[ ! -f clients/apple/native-auth/Tests/CosmasNativeAuthTests/ClerkKeychainCredentialsTests.swift ]]; then
  overlay_if_absent clients/apple/native-auth/Tests/CosmasNativeAuthTests/ClerkKeychainCredentialsTests.swift
fi

{
  echo "tooling_sha=${TOOLING_SHA}"
  echo "target_sha=${HEAD_SHA}"
  echo "overlaid_files<<"
  if [[ ${#OVERLAID_FILES[@]} -eq 0 ]]; then
    echo "(none)"
  else
    printf '%s\n' "${OVERLAID_FILES[@]}"
  fi
  echo ">>"
} | tee "$ARTIFACTS/overlay-receipt.txt"
if [[ ${#OVERLAID_FILES[@]} -gt 0 ]]; then
  echo "NOTE: native/tooling files were overlaid or patched; do not claim an unmodified target SHA." | tee -a "$ARTIFACTS/overlay-receipt.txt"
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

if [[ "${REUSE_EXISTING_SIM}" -eq 0 ]]; then
  if [[ -n "${SIM_NAME_OVERRIDE}" ]]; then
    SIM_NAME="${SIM_NAME_OVERRIDE}"
  else
    SIM_NAME="cosmas-mic-uitest-$$"
  fi
  SIM_UDID="$(xcrun simctl create "${SIM_NAME}" "${DEVICE_TYPE_ID}" "${RUNTIME_ID}")"
  CREATED_SIM_UDID="${SIM_UDID}"
  echo "==> Created simulator ${SIM_NAME} (${SIM_UDID})"
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

echo "==> Reset microphone privacy for com.cosmasos.synthetic, then install"
xcrun simctl privacy "$SIM_UDID" reset microphone com.cosmasos.synthetic
xcrun simctl uninstall "$SIM_UDID" com.cosmasos.synthetic 2>/dev/null || true
xcrun simctl install "$SIM_UDID" "$APP_PATH"

echo "==> Generate and run MicrophonePermissionUITests"
python3 clients/apple/ui-tests/generate-uitest-project.py
python3 clients/apple/ui-tests/prove_release_excludes_demo_fixture.py

RESULT_BUNDLE="$ARTIFACTS/mic-permission.xcresult"
rm -rf "$RESULT_BUNDLE"
set +e
xcodebuild test \
  -project clients/apple/ui-tests/CosmasSyntheticUITests.xcodeproj \
  -scheme CosmasSyntheticUITests \
  -destination "platform=iOS Simulator,id=${SIM_UDID}" \
  -only-testing:CosmasSyntheticUITests/MicrophonePermissionUITests \
  -resultBundlePath "$RESULT_BUNDLE" \
  CODE_SIGNING_ALLOWED=NO \
  "${ARCH_SETTINGS[@]}" \
  | tee "$ARTIFACTS/xcodebuild-uitest.log"
TEST_STATUS=${PIPESTATUS[0]}
set -e

extract_screenshots() {
  mkdir -p "$ARTIFACTS/screenshots"
  if command -v xcparse >/dev/null 2>&1; then
    xcparse screenshots "$RESULT_BUNDLE" "$ARTIFACTS/screenshots" || true
  fi
  if [[ -d "$RESULT_BUNDLE" ]]; then
    xcrun xcresulttool export attachments \
      --path "$RESULT_BUNDLE" \
      --output-path "$ARTIFACTS/screenshots" >/dev/null 2>&1 || true
    find "$RESULT_BUNDLE" -type f \( -name '*.png' -o -name '*.jpg' \) -print0 \
      | while IFS= read -r -d '' shot; do
          cp "$shot" "$ARTIFACTS/screenshots/" 2>/dev/null || true
        done || true
  fi
}

extract_screenshots
{
  echo "target_sha=${HEAD_SHA}"
  echo "tooling_sha=${TOOLING_SHA}"
  echo "test_status=${TEST_STATUS}"
  echo "simulator=${SIM_NAME} (${SIM_UDID})"
  if [[ ${#OVERLAID_FILES[@]} -gt 0 ]]; then
    echo "native_overlay=yes"
  else
    echo "native_overlay=no"
  fi
} | tee "$ARTIFACTS/result.txt"
printf '%s\n' "$HEAD_SHA" > "$ARTIFACTS/tested-sha.txt"

echo "==> Done. Artifacts: $ARTIFACTS"
echo "    SHA: $HEAD_SHA"
echo "    App: $APP_PATH"
echo "    Sim: ${SIM_NAME} (${SIM_UDID})"
echo "    Test status: ${TEST_STATUS}"
exit "${TEST_STATUS}"
