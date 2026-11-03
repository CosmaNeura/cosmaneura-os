# CosmaBot synthetic Simulator UI tests

XCUITests for the Debug synthetic Simulator app (`com.cosmasos.synthetic`).

Debug synthetic builds present a local invented demo surface (visit timer + Chief
rows) without sign-in or network. That surface is wrapped in `#if DEBUG` and
scoped to the synthetic bundle id, so Release/TestFlight binaries compile it out
(see `prove_release_excludes_demo_fixture.py` and `SyntheticDemoFixtureGate`).

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
