import XCTest

/// Documents the launch-time microphone TCC probe for capture-off CosmaBot builds.
///
/// Caller (outside this package, in the bundled PCM Capacitor plugin):
/// `clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift`
/// `load()` at lines 41–54 constructs `IOSPCMBridgeCore` → `LiveAppleAudioSystem`,
/// which creates `AVAudioEngine()` at
/// `clients/capture/native-configured/ios-pcm-capture/Sources/CosmaneuraIOSAVFoundationDriver/LiveAVFoundationSystem.swift:63`
/// during Capacitor plugin registration. That path does **not** call
/// `requestRecordPermission` (no prompt) but still touches `AVAudioSession` /
/// `AVAudioEngine`, which surfaces as a silent `kTCCServiceMicrophone` preflight.
///
/// CosmaBot-side mitigation in this PR (clients/apple only):
/// Debug `com.cosmasos.synthetic` presents `CosmasSyntheticDemoSurface` and
/// returns before `openWorkspace()` / `CosmasBridgeViewController`, so Capacitor
/// never loads `IOSPCMCapacitorPlugin` on that configuration — no mic touch.
///
/// Residual: Release/TestFlight capture-off builds that open the WebView still
/// register the plugin. Deferring live AVFoundation until an explicit start
/// requires editing `IOSPCMCapacitorPlugin.load()` (clients/capture), which is
/// outside this PR's clients/apple-only scope.
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
