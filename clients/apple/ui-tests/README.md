# CosmaBot synthetic Simulator UI tests

XCUITests for the synthetic Simulator app (`com.cosmasos.synthetic`).

They require the app to be installed on a booted Simulator and launched with
`-COSMAS_UI_TEST_FIXTURES`. That argument enables the native synthetic fixture
surface in `startup-recovery/CosmasWorkspaceViewController.swift` (visit timer
and Chief engagement rows with accessibility identifiers). Fixtures stay off
unless both the synthetic bundle id and the launch argument are present.

```sh
python3 clients/apple/ui-tests/generate-uitest-project.py
xcodebuild test \
  -project clients/apple/ui-tests/CosmasSyntheticUITests.xcodeproj \
  -scheme CosmasSyntheticUITests \
  -destination 'platform=iOS Simulator,id=<booted-udid>' \
  -resultBundlePath /tmp/cosmas-synthetic-ui.xcresult
```
