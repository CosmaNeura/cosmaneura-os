import XCTest

/// Documents capture-off CosmaBot launch behaviour for the microphone path.
///
/// T-REL-7b (clients/capture): `LiveAppleAudioSystem` defers `AVAudioEngine`
/// construction until capture start (install/start). Plugin load /
/// `LiveAppleAudioSystem.init` must not create an engine, so a capture-off
/// launch should not trigger an engine-backed microphone TCC preflight from
/// that path. Behavioural proof lives in `ios-lazy-mic-tests` (`#if os(iOS)`
/// live-adapter idle lifecycle) plus owed Mac/simulator runs on the PR.
///
/// Caller (outside this package, in the bundled PCM Capacitor plugin):
/// `clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift`
/// `load()` constructs `IOSPCMBridgeCore` → `LiveAppleAudioSystem`.
/// That path does **not** call `requestRecordPermission` (no prompt) at load.
///
/// CosmaBot Debug `com.cosmasos.synthetic` still presents
/// `CosmasSyntheticDemoSurface` and returns before `openWorkspace()` /
/// `CosmasBridgeViewController`, so Capacitor never loads
/// `IOSPCMCapacitorPlugin` on that default configuration — no mic touch.
///
/// `-COSMAS_SKIP_SYNTHETIC_DEMO` opens the real bridge/plugin path for the
/// automatic mic-permission XCUITest. Start-recording requests permission only
/// through the plugin's shared `requestStartRecordingMicPermission` entry.
/// Every START_CAPTURE / SKIP_DEMO / uiTest hook stays behind `#if DEBUG`.
final class MicrophoneLaunchPreflightTests: XCTestCase {
    func testDebugSyntheticDemoReturnsBeforeWorkspaceBridge() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let source = try String(contentsOf: root.appendingPathComponent("CosmasWorkspaceViewController.swift"), encoding: .utf8)
        XCTAssertTrue(source.contains("CosmasSyntheticDemoSurface.isEnabled"))
        // Early return must precede opening the Capacitor workspace bridge.
        let demoIdx = source.range(of: "CosmasSyntheticDemoSurface.isEnabled")!.lowerBound
        let openIdx = source.range(of: "openWorkspace()")!.lowerBound
        XCTAssertLessThan(demoIdx, openIdx)
        let bridgeSource = try String(contentsOf: root.appendingPathComponent("CosmasBridgeViewController.swift"), encoding: .utf8)
        XCTAssertTrue(
            bridgeSource.contains("IOSPCMCapacitorPlugin"),
            "Bridge still owns IOSPCM; Debug synthetic must not construct it"
        )
        // Mic prompt must go through the loaded plugin, not a ViewController-local call.
        XCTAssertFalse(
            bridgeSource.contains("AVAudioApplication.requestRecordPermission"),
            "Bridge must not call AVAudioApplication.requestRecordPermission directly"
        )
        XCTAssertTrue(
            bridgeSource.contains("uiTestStartRecordingThroughLoadedPlugin"),
            "START_CAPTURE must invoke IOSPCMCapacitorPlugin.uiTestStartRecordingThroughLoadedPlugin"
        )
        XCTAssertTrue(
            source.contains("CosmasSyntheticDemoSurface.skipLaunchArgument"),
            "Synthetic UI-test boot must skip practice-host failure before openWorkspace"
        )
    }

    func testUiTestHooksAreDebugOnlyInSources() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let bridge = try String(contentsOf: root.appendingPathComponent("CosmasBridgeViewController.swift"), encoding: .utf8)
        let workspace = try String(contentsOf: root.appendingPathComponent("CosmasWorkspaceViewController.swift"), encoding: .utf8)
        XCTAssertTrue(
            bridge.contains("#if DEBUG\n        // Synthetic Simulator XCUITest only"),
            "Bridge uiTest hooks must be #if DEBUG"
        )
        XCTAssertTrue(
            workspace.contains("#if DEBUG\n        // Synthetic Simulator XCUITest: skip practice-host boot"),
            "Workspace skip-demo path must be #if DEBUG"
        )
        let clients = root
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let plugin = try String(
            contentsOf: clients
                .appendingPathComponent("capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift"),
            encoding: .utf8
        )
        XCTAssertTrue(
            plugin.contains("#if DEBUG\n    /// Synthetic Simulator XCUITest only"),
            "Plugin uiTestStartRecordingThroughLoadedPlugin must be #if DEBUG"
        )
        XCTAssertTrue(
            plugin.contains("uiTestStartRecordingThroughLoadedPlugin"),
            "Plugin must expose the DEBUG XCUITest start-recording hook"
        )
    }
}
