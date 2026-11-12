import XCTest

/// Automatic record / microphone-permission test for the UNSIGNED Debug
/// Simulator app (`com.cosmasos.synthetic`).
///
/// Goes through the REAL native plugin path (Capacitor + IOSPCMCapacitorPlugin),
/// not the Debug demo surface that returns early in CosmasWorkspaceViewController.
/// Invented engagement only; no PHI.
///
/// Preconditions (Mac runner handles these):
///   xcrun simctl privacy <udid> reset microphone com.cosmasos.synthetic
final class MicrophonePermissionUITests: XCTestCase {
    private var app: XCUIApplication!
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    override func setUpWithError() throws {
        continueAfterFailure = false
        try requireEnglishSimulator()
        app = XCUIApplication(bundleIdentifier: "com.cosmasos.synthetic")
        if #available(iOS 17.0, *) {
            app.resetAuthorizationStatus(for: .microphone)
        }
    }

    override func tearDownWithError() throws {
        app?.terminate()
        app = nil
    }

    private func requireEnglishSimulator() throws {
        let preferred = Locale.preferredLanguages.first ?? ""
        let english = preferred.hasPrefix("en")
            || Locale.current.language.languageCode?.identifier == "en"
        if !english {
            XCTFail(
                "Simulator language must be English for Don't Allow / Microphone copy; got preferred=\(preferred) locale=\(Locale.current.identifier)"
            )
        }
    }

    /// iOS 27 may present TCC as a SpringBoard alert or sheet (sometimes both
    /// hierarchies briefly expose nested "Don't Allow" buttons). Prefer sheet,
    /// then alert; callers must still assert the prompt appeared.
    private func micPermissionPrompt(timeout: TimeInterval) -> XCUIElement? {
        let predicate = NSPredicate(
            format: "label CONTAINS[c] %@ OR label CONTAINS[c] %@",
            "Microphone",
            "microphone"
        )
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let sheet = springboard.sheets.matching(predicate).firstMatch
            if sheet.exists { return sheet }
            let alert = springboard.alerts.matching(predicate).firstMatch
            if alert.exists { return alert }
            RunLoop.current.run(until: Date().addingTimeInterval(0.2))
        }
        return nil
    }

    private func dontAllowButton(in prompt: XCUIElement) -> XCUIElement {
        // Straight and curly apostrophe variants; .firstMatch avoids the
        // Alert-vs-Sheet "Multiple matching elements found" tap failure.
        prompt.buttons.matching(
            NSPredicate(
                format: "label == %@ OR label == %@",
                "Don't Allow",
                "Don’t Allow"
            )
        ).firstMatch
    }

    private func screenshot(_ name: String) {
        let shot = XCUIScreen.main.screenshot()
        let attachment = XCTAttachment(screenshot: shot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testLaunchWithCaptureOffShowsNoMicrophonePrompt() throws {
        app.launchArguments = ["-COSMAS_SKIP_SYNTHETIC_DEMO"]
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 10))
        XCTAssertFalse(
            app.otherElements["cosmas.uiTest.surface"].waitForExistence(timeout: 3),
            "Skip-demo launch must not present CosmasSyntheticDemoSurface"
        )
        XCTAssertTrue(
            app.otherElements["cosmas.uiTest.iospcm.loaded"].waitForExistence(timeout: 8),
            "Skip-demo launch must expose the loaded IOSPCM plugin marker"
        )
        // Give Capacitor plugin load() time; no START_CAPTURE means no prompt.
        RunLoop.current.run(until: Date().addingTimeInterval(4))
        screenshot("01-launch-capture-off-no-mic-prompt")
        XCTAssertNil(
            micPermissionPrompt(timeout: 1),
            "Launch with capture off must not show a microphone permission prompt"
        )
        XCTAssertTrue(
            app.otherElements["cosmas.uiTest.micPermission.undetermined"].exists
                || app.otherElements["cosmas.uiTest.micPermission.unknown"].exists,
            "Mic permission must still be undetermined when capture has not started"
        )
    }

    func testStartRecordingShowsMicrophonePrompt() throws {
        app.launchArguments = [
            "-COSMAS_SKIP_SYNTHETIC_DEMO",
            "-COSMAS_UI_TEST_START_CAPTURE",
        ]
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 10))
        XCTAssertFalse(
            app.otherElements["cosmas.uiTest.surface"].waitForExistence(timeout: 3),
            "Capture-start path must use the real native plugin bridge, not the demo surface"
        )
        screenshot("02-start-recording-before-mic-assert")
        let prompt = micPermissionPrompt(timeout: 12)
        XCTAssertNotNil(
            prompt,
            "Starting recording must present the microphone permission prompt"
        )
        screenshot("02-start-recording-mic-prompt")
        let dontAllow = dontAllowButton(in: prompt!)
        XCTAssertTrue(
            dontAllow.waitForExistence(timeout: 5),
            "Microphone permission prompt must expose Don't Allow"
        )
        dontAllow.tap()
        XCTAssertNil(
            micPermissionPrompt(timeout: 3),
            "Don't Allow must dismiss the microphone permission prompt"
        )
        XCTAssertTrue(app.state == .runningForeground, "App must still be running after Don't Allow")
        XCTAssertTrue(
            app.otherElements["cosmas.uiTest.micPermission.denied"].waitForExistence(timeout: 8),
            "Denied mic permission marker must become visible after Don't Allow"
        )
    }
}
