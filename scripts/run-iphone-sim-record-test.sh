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
# Optional: COSMAS_SIM_NAME="iPhone 16" COSMAS_ARTIFACTS=/tmp/cosmas-mic-artifacts
set -euo pipefail

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
SIM_NAME="${COSMAS_SIM_NAME:-iPhone 16}"
ARTIFACTS="${COSMAS_ARTIFACTS:-}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/cosmas-iphone-sim-XXXXXX")"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

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
# Prefer tooling Node 24 if present; otherwise PATH node.
NODE_BIN="$(command -v node)"
"$NODE_BIN" scripts/prepare-synthetic-iphone-web-bundle.mjs --output "$OUT/web-bundle"

echo "==> Configure UNSIGNED com.cosmasos.synthetic Simulator project"
python3 scripts/configure-synthetic-iphone-simulator.py \
  --composed "$OUT/composed" \
  --web-dist "$OUT/web-bundle/renderer/dist"

PROJECT="$OUT/composed/apps/capture/ios/App/App.xcodeproj"
DERIVED="$OUT/DerivedData"

echo "==> xcodebuild Debug iphonesimulator CODE_SIGNING_ALLOWED=NO"
xcodebuild \
  -project "$PROJECT" \
  -scheme App \
  -configuration Debug \
  -sdk iphonesimulator \
  -destination "platform=iOS Simulator,name=${SIM_NAME}" \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  build | tee "$ARTIFACTS/xcodebuild-app.log"

APP_PATH="$(find "$DERIVED/Build/Products" -name 'App.app' -type d | head -n 1)"
if [[ -z "$APP_PATH" ]]; then
  echo "App.app not found under $DERIVED" >&2
  exit 1
fi

UDID="$(xcrun simctl list devices available | awk -F '[()]' -v n="$SIM_NAME" '
  $0 ~ n && $0 !~ /unavailable/ { print $2; exit }
')"
if [[ -z "$UDID" ]]; then
  echo "Simulator '$SIM_NAME' not found. Set COSMAS_SIM_NAME." >&2
  exit 1
fi

echo "==> Boot simulator $SIM_NAME ($UDID)"
xcrun simctl bootstatus "$UDID" -b || xcrun simctl boot "$UDID"
xcrun simctl bootstatus "$UDID" -b

echo "==> Reset microphone privacy, then install"
xcrun simctl privacy "$UDID" reset microphone
xcrun simctl uninstall "$UDID" com.cosmasos.synthetic 2>/dev/null || true
xcrun simctl install "$UDID" "$APP_PATH"

echo "==> Generate and run MicrophonePermissionUITests"
python3 clients/apple/ui-tests/generate-uitest-project.py
python3 clients/apple/ui-tests/prove_release_excludes_demo_fixture.py

RESULT_BUNDLE="$ARTIFACTS/mic-permission.xcresult"
rm -rf "$RESULT_BUNDLE"
xcodebuild test \
  -project clients/apple/ui-tests/CosmasSyntheticUITests.xcodeproj \
  -scheme CosmasSyntheticUITests \
  -destination "platform=iOS Simulator,id=${UDID}" \
  -only-testing:CosmasSyntheticUITests/MicrophonePermissionUITests \
  -resultBundlePath "$RESULT_BUNDLE" \
  CODE_SIGNING_ALLOWED=NO \
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
