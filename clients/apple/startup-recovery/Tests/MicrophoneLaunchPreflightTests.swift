import XCTest

/// Documents the launch-time microphone TCC probe for capture-off CosmaBot builds.
///
/// Caller (outside this package, in the bundled PCM Capacitor plugin):
/// `clients/capture/native-configured/ios-pcm-capacitor/Sources/CosmaneuraIOSPCMCapacitor/IOSPCMCapacitorPlugin.swift`
/// `load()` at lines 41–54 constructs `IOSPCMBridgeCore` → `LiveAppleAudioSystem`,
/// which still creates `AVAudioEngine()` at
/// `clients/capture/native-configured/ios-pcm-capture/Sources/CosmaneuraIOSAVFoundationDriver/LiveAVFoundationSystem.swift:63`
/// during Capacitor plugin registration. That path does **not** call
/// `requestRecordPermission` (no prompt) but still touches `AVAudioSession` /
/// `AVAudioEngine`, which can surface as a silent `kTCCServiceMicrophone` preflight.
///
/// CosmaBot-side mitigation (clients/apple):
/// Debug `com.cosmasos.synthetic` presents `CosmasSyntheticDemoSurface` and
/// returns before `openWorkspace()` / `CosmasBridgeViewController`, so Capacitor
/// never loads `IOSPCMCapacitorPlugin` on that default configuration — no mic touch.
///
/// `-COSMAS_SKIP_SYNTHETIC_DEMO` opens the real bridge/plugin path for the
/// automatic mic-permission XCUITest. T-REL-7b lazy AVAudioEngine is **not**
/// present at this tip (`LiveAVFoundationSystem` still assigns
/// `private var engine = AVAudioEngine()`), so Release/TestFlight residual risk
/// remains: loading IOSPCM can still touch the audio engine before start.
/// Start-recording requests permission only through the plugin's shared
/// `requestStartRecordingMicPermission` entry.
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

    func testLiveAppleAudioSystemStillConstructsEngineEagerly() throws {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // Tests
            .deletingLastPathComponent() // startup-recovery
            .deletingLastPathComponent() // apple
            .deletingLastPathComponent() // clients
        let live = root
            .appendingPathComponent("clients/capture/native-configured/ios-pcm-capture/Sources/CosmaneuraIOSAVFoundationDriver/LiveAVFoundationSystem.swift")
        let text = try String(contentsOf: live, encoding: .utf8)
        XCTAssertTrue(
            text.contains("private var engine = AVAudioEngine()"),
            "Residual Release/TestFlight risk: AVAudioEngine is still constructed eagerly (T-REL-7b lazy path not at this tip)"
        )
    }
}
