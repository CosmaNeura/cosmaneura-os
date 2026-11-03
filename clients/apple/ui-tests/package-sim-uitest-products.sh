#!/usr/bin/env bash
# Build UI tests for Simulator and zip products for test-without-building.
# Expects App.app already built at $APP_PATH (Debug-iphonesimulator, com.cosmasos.synthetic).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
REPO_APPLE="$(cd "$ROOT/.." && pwd)"
APP_PATH="${APP_PATH:?Set APP_PATH to the Debug-iphonesimulator App.app}"
DESTINATION="${DESTINATION:-platform=iOS Simulator,name=CosmasOS Synthetic iPhone 12}"
OUT_DIR="${OUT_DIR:?Set OUT_DIR to the folder that will receive the zip}"
DERIVED="${DERIVED:-/tmp/cosmas-uitest-build-for-testing}"
LABEL="${LABEL:-CosmaBot-synthetic-uitests}"

python3 "$ROOT/generate-uitest-project.py"

rm -rf "$DERIVED"
mkdir -p "$DERIVED" "$OUT_DIR"

xcodebuild build-for-testing \
  -project "$ROOT/CosmasSyntheticUITests.xcodeproj" \
  -scheme CosmasSyntheticUITests \
  -destination "$DESTINATION" \
  -derivedDataPath "$DERIVED" \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  DEVELOPMENT_TEAM=

PRODUCTS="$DERIVED/Build/Products/Debug-iphonesimulator"
XCTESTRUN=$(ls "$DERIVED/Build/Products"/*.xctestrun | head -1)
test -n "$XCTESTRUN"
test -d "$PRODUCTS/CosmasSyntheticUITests-Runner.app"
test -d "$APP_PATH"

STAGE="$DERIVED/stage/$LABEL"
rm -rf "$STAGE"
mkdir -p "$STAGE/Debug-iphonesimulator"

# Copy products without resource forks / Finder metadata.
export COPYFILE_DISABLE=1
ditto --norsrc --noextattr "$APP_PATH" "$STAGE/Debug-iphonesimulator/App.app"
ditto --norsrc --noextattr "$PRODUCTS/CosmasSyntheticUITests-Runner.app" \
  "$STAGE/Debug-iphonesimulator/CosmasSyntheticUITests-Runner.app"
ditto --norsrc --noextattr "$XCTESTRUN" "$STAGE/$(basename "$XCTESTRUN")"

# Rewrite xctestrun paths to be relative to the staged folder when possible.
python3 - <<PY
from pathlib import Path
import plistlib
stage = Path("$STAGE")
runs = list(stage.glob("*.xctestrun"))
assert len(runs) == 1, runs
data = plistlib.loads(runs[0].read_bytes())
# Xcode 16+ uses a TestConfigurations array; older used top-level targets.
def rewrite(obj):
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if isinstance(v, str) and "/Debug-iphonesimulator/" in v:
                name = v.rsplit("/Debug-iphonesimulator/", 1)[1]
                obj[k] = "__TESTROOT__/Debug-iphonesimulator/" + name
            else:
                rewrite(v)
    elif isinstance(obj, list):
        for item in obj:
            rewrite(item)
rewrite(data)
runs[0].write_bytes(plistlib.dumps(data))
print("rewrote", runs[0].name)
PY

cat > "$STAGE/RUN.txt" <<EOF
# Install the Debug synthetic app, then run prebuilt UI tests (no repo needed).
# Pin OS=26.5 so the name does not resolve to a newer blank runtime.
SIM="CosmasOS Synthetic iPhone 12"
OS="26.5"
UDID=\$(xcrun simctl list devices available | awk -F '[()]' -v n="\$SIM" '\$0 ~ n {print \$2; exit}')
test -n "\$UDID"
xcrun simctl bootstatus "\$UDID" -b
xcrun simctl install "\$UDID" "./Debug-iphonesimulator/App.app"
xcodebuild test-without-building \\
  -xctestrun "./$(basename "$XCTESTRUN")" \\
  -destination "platform=iOS Simulator,name=\$SIM,OS=\$OS"
EOF

ZIP="$OUT_DIR/${LABEL}.zip"
rm -f "$ZIP"
(
  cd "$STAGE/.."
  COPYFILE_DISABLE=1 ditto -c -k --norsrc --keepParent "$LABEL" "$ZIP"
)

# Verify no AppleDouble / __MACOSX entries.
if unzip -l "$ZIP" | grep -E '(^|/)((__MACOSX)|(\._))' ; then
  echo "FAIL: zip contains __MACOSX or ._ entries" >&2
  exit 1
fi
echo "WROTE $ZIP"
shasum -a 256 "$ZIP"
unzip -l "$ZIP" | head -40
