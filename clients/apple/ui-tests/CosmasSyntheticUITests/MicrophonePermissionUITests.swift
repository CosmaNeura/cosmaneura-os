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

    private func micPermissionAlert() -> XCUIElement {
        // System TCC alert copy varies by iOS version; match Allow / Don't Allow.
        let alerts = springboard.alerts
        if alerts.count > 0 { return alerts.element(boundBy: 0) }
        return springboard.alerts.matching(NSPredicate(format:
            "label CONTAINS[c] %@ OR label CONTAINS[c] %@",
            "Microphone", "microphone")).element
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
        XCTAssertFalse(
            micPermissionAlert().waitForExistence(timeout: 1),
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
        let alert = micPermissionAlert()
        XCTAssertTrue(
            alert.waitForExistence(timeout: 12),
            "Starting recording must present the microphone permission prompt"
        )
        screenshot("02-start-recording-mic-prompt")
        // Dismiss without granting so the Simulator stays reset-friendly.
        if alert.buttons["Don't Allow"].exists {
            alert.buttons["Don't Allow"].tap()
        } else if alert.buttons["Don’t Allow"].exists {
            alert.buttons["Don’t Allow"].tap()
        }
    }
}
