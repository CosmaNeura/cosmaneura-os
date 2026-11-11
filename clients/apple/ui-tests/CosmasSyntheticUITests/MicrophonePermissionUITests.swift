import XCTest

/// Automatic record / microphone-permission test for the UNSIGNED Debug
/// Simulator app (`com.cosmasos.synthetic`).
///
/// Goes through the REAL native plugin path (Capacitor + IOSPCMCapacitorPlugin),
/// not the Debug demo surface that returns early in CosmasWorkspaceViewController.
/// Invented engagement only; no PHI.
///
/// Preconditions (Mac runner handles these):
///   xcrun simctl privacy <udid> reset microphone
final class MicrophonePermissionUITests: XCTestCase {
    private var app: XCUIApplication!
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication(bundleIdentifier: "com.cosmasos.synthetic")
    }

    override func tearDownWithError() throws {
        app?.terminate()
        app = nil
    }

    /// iOS 27 may present TCC as a SpringBoard alert or sheet (sometimes both
    /// hierarchies briefly expose nested "Don't Allow" buttons).
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
        // Real workspace path: demo surface must NOT appear.
        XCTAssertFalse(
            app.otherElements["cosmas.uiTest.surface"].waitForExistence(timeout: 3),
            "Skip-demo launch must not present CosmasSyntheticDemoSurface"
        )
        // Give Capacitor plugin load() time; with lazy mic, no TCC prompt here.
        RunLoop.current.run(until: Date().addingTimeInterval(4))
        screenshot("01-launch-capture-off-no-mic-prompt")
        XCTAssertNil(
            micPermissionPrompt(timeout: 1),
            "Launch with capture off must not show a microphone permission prompt"
        )
    }

    func testStartRecordingShowsMicrophonePrompt() throws {
        app.launchArguments = [
            "-COSMAS_SKIP_SYNTHETIC_DEMO",
            "-COSMAS_UI_TEST_START_CAPTURE",
        ]
        app.launch()
        XCTAssertFalse(
            app.otherElements["cosmas.uiTest.surface"].waitForExistence(timeout: 3),
            "Capture-start path must use the real native plugin bridge, not the demo surface"
        )
        // Capture evidence before the assertion so a missing prompt still leaves
        // a screenshot in the xcresult / runner artifacts.
        screenshot("02-start-recording-before-mic-assert")
        let prompt = micPermissionPrompt(timeout: 12)
        XCTAssertNotNil(
            prompt,
            "Starting recording must present the microphone permission prompt"
        )
        screenshot("02-start-recording-mic-prompt")
        // Dismiss without granting so the Simulator stays reset-friendly.
        let dontAllow = dontAllowButton(in: prompt!)
        XCTAssertTrue(
            dontAllow.waitForExistence(timeout: 5),
            "Microphone permission prompt must expose Don't Allow"
        )
        dontAllow.tap()
    }
}
