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
/// CosmaBot Debug `com.cosmasos.synthetic` still presents
/// `CosmasSyntheticDemoSurface` and returns before `openWorkspace()` /
/// `CosmasBridgeViewController`, so Capacitor never loads
/// `IOSPCMCapacitorPlugin` on that configuration.
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
    }
}
