# CosmaBot synthetic Simulator UI tests

XCUITests for the Debug synthetic Simulator app (`com.cosmasos.synthetic`).

Debug synthetic builds present a local invented demo surface (visit timer + Chief
rows) without sign-in or network. That surface is wrapped in `#if DEBUG` and
scoped to the synthetic bundle id, so Release/TestFlight binaries compile it out
(see `prove_release_excludes_demo_fixture.py` and `SyntheticDemoFixtureGate`).

`MicrophonePermissionUITests` skips that demo (`-COSMAS_SKIP_SYNTHETIC_DEMO`) and
drives the real Capacitor / `IOSPCMCapacitorPlugin` path. Reset mic privacy first:
`xcrun simctl privacy <udid> reset microphone com.cosmasos.synthetic`.

## One Mac command (any PR head, throwaway temp)

From a checkout that contains the runner (this PR), against PR 349 or a full SHA.
Needs full Xcode (`DEVELOPER_DIR` if xcode-select is CLT-only) and Node.js 24.
Abbreviated SHAs only work when already present in this tooling checkout's object
database; otherwise pass a full 40-character SHA or a PR number.

```sh
export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer   # when needed
./scripts/run-iphone-sim-record-test.sh 349
./scripts/run-iphone-sim-record-test.sh 179e739f0278a05706531ffb1288cb1df7acf507b
```

That clones into a fresh temp directory (never `~/Desktop/cosmaneura-os`),
composes the unsigned `com.cosmasos.synthetic` Simulator app with a synthetic
web bundle, creates a throwaway Simulator (or reuses an exact `COSMAS_SIM_NAME`
match without re-selecting a runtime), resets microphone privacy for
`com.cosmasos.synthetic`, builds with host-arch `ONLY_ACTIVE_ARCH` flags, and runs
`MicrophonePermissionUITests`. Every START_CAPTURE / SKIP_DEMO hook stays
`#if DEBUG` + launch-argument gated so those symbols are omitted from Release
compilation; Linux CI does not compile or run the XCUITests or the Mac runner
body.

## Synthetic web bundle (one command)

```sh
node scripts/prepare-synthetic-iphone-web-bundle.mjs \
  --output /absolute/path/to/fresh-synthetic-apple-renderer
```

Inputs are `pk_test_` + `*.synthetic.example` only. Pass
`<output>/renderer/dist` through `scripts/configure-synthetic-iphone-simulator.py`.

## Generate / run from a repo checkout

```sh
python3 clients/apple/ui-tests/generate-uitest-project.py
python3 clients/apple/ui-tests/prove_release_excludes_demo_fixture.py
xcodebuild test \
  -project clients/apple/ui-tests/CosmasSyntheticUITests.xcodeproj \
  -scheme CosmasSyntheticUITests \
  -destination 'platform=iOS Simulator,name=CosmasOS Synthetic iPhone 12' \
  -resultBundlePath /tmp/cosmas-synthetic-ui.xcresult
```

The app under test must already be installed on the booted Simulator.

## Prebuilt products (no repo)

`package-sim-uitest-products.sh` runs `xcodebuild build-for-testing` and zips the
`.xctestrun` plus `Debug-iphonesimulator` products (`App.app` and
`CosmasSyntheticUITests-Runner.app`) with `ditto -c -k --norsrc --keepParent`.

From the unzipped folder:

```sh
SIM="CosmasOS Synthetic iPhone 12"
OS="26.5"
UDID=$(xcrun simctl list devices available | awk -F '[()]' -v n="$SIM" '$0 ~ n {print $2; exit}')
xcrun simctl bootstatus "$UDID" -b
xcrun simctl install "$UDID" "./Debug-iphonesimulator/App.app"
xcodebuild test-without-building \
  -xctestrun ./*.xctestrun \
  -destination "platform=iOS Simulator,name=$SIM,OS=$OS"
```
