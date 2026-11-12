import Foundation
import Testing

@testable import CosmaneuraIOSAVFoundationDriver
@testable import CosmaneuraIOSPCMCore

#if os(iOS)
  @preconcurrency import AVFoundation
#endif

/// T-REL-7b: with capture off, plugin load must not create AVAudioEngine or
/// query record permission. Engine creation is deferred until capture start.
struct LazyMicEngineTests {
  @Test func captureOffLoadCreatesNoEngineAndQueriesNoPermission() {
    let factory = CountingEngineFactory()
    let permission = CountingPermissionProvider()
    // Seam-level unit check only: constructs LazyAppleAudioEngine and the
    // permission adapter without starting capture. This does not invoke
    // IOSPCMCapacitorPlugin.load() or LiveAppleAudioSystem; the #if os(iOS)
    // live-adapter tests below cover that constructor path.
    let engines = LazyAppleAudioEngine(factory: factory.make)
    _ = AVFoundationMicrophonePermissionAdapter(provider: permission)

    #expect(!engines.isResolved)
    #expect(factory.creations == 0)
    #expect(permission.queries == 0)
    #expect(permission.requests == 0)

    // Stop/teardown with capture never started must not create an engine.
    engines.clear()
    #expect(!engines.isResolved)
    #expect(factory.creations == 0)
    #expect(permission.queries == 0)
  }

  @Test func startCaptureCreatesEngineAndExistingDriverFlowWorks() async throws {
    let factory = CountingEngineFactory()
    let engines = LazyAppleAudioEngine(factory: factory.make)
    let system = LazyEngineAudioSystem(engines: engines)
    let events = CapturedLazyEvents()
    let driver = AVFoundationPCMDriver(system: system, foreground: LazyForeground())

    #expect(factory.creations == 0)
    #expect(!engines.isResolved)

    try await driver.start(
      sessionID: 1, callbacks: events.callbacks, cancellation: StartupCancellation()
    )
    #expect(factory.creations == 1)
    #expect(engines.isResolved)
    #expect(system.tapInstalled)
    #expect(system.engineStarted)

    try await driver.freezeInput(sessionID: 1)
    try await driver.release(sessionID: 1)
    #expect(!system.tapInstalled)
    #expect(!engines.isResolved)
    #expect(factory.creations == 1)
    #expect(events.count == 0)
  }

  @Test func liveAdapterSourceDefersEngineUntilStart() throws {
    // Secondary source-string guard only. Prefer the #if os(iOS) live
    // adapter tests for behavioural proof that init does not create an engine.
    let configuredRoot = URL(fileURLWithPath: #filePath)
      .deletingLastPathComponent()
      .deletingLastPathComponent()
      .deletingLastPathComponent()
      .deletingLastPathComponent()
    let sourceURL =
      configuredRoot
      .appendingPathComponent("ios-pcm-capture")
      .appendingPathComponent("Sources")
      .appendingPathComponent("CosmaneuraIOSAVFoundationDriver")
      .appendingPathComponent("LiveAVFoundationSystem.swift")
    let source = try String(contentsOf: sourceURL, encoding: .utf8)
    #expect(!source.contains("private var engine = AVAudioEngine()"))
    #expect(source.contains("LazyAppleAudioEngine<AVAudioEngine>"))
    #expect(source.contains("engineFactory"))
    #expect(source.contains("engines.clear()"))
  }

  #if os(iOS)
    @Test func liveAdapterIdleLifecycleCreatesNoEngine() throws {
      let factory = CountingAVAudioEngineFactory()
      let system = LiveAppleAudioSystem(
        notificationCenter: NotificationCenter(),
        engineFactory: factory.make
      )
      #expect(factory.creations == 0)
      #expect(!system.hasResolvedEngine)

      system.setEventHandler { _ in }
      #expect(factory.creations == 0)
      #expect(!system.hasResolvedEngine)

      system.clearEventHandler()
      #expect(factory.creations == 0)
      #expect(!system.hasResolvedEngine)

      try system.freezeInput()
      #expect(factory.creations == 0)
      #expect(!system.hasResolvedEngine)

      try system.deactivate()
      #expect(factory.creations == 0)
      #expect(!system.hasResolvedEngine)
    }
  #endif
}

private final class CountingEngineFactory: @unchecked Sendable {
  private let lock = NSLock()
  private var count = 0
  var creations: Int { lock.withLock { count } }

  func make() -> EngineMarker {
    lock.withLock { count += 1 }
    return EngineMarker()
  }
}

private final class EngineMarker: NSObject {}

#if os(iOS)
  private final class CountingAVAudioEngineFactory: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    var creations: Int { lock.withLock { count } }

    func make() -> AVAudioEngine {
      lock.withLock { count += 1 }
      return AVAudioEngine()
    }
  }
#endif

private final class CountingPermissionProvider: AppleMicrophonePermissionProviding,
  @unchecked Sendable
{
  private let lock = NSLock()
  private var queryCount = 0
  private var requestCount = 0
  var queries: Int { lock.withLock { queryCount } }
  var requests: Int { lock.withLock { requestCount } }

  func currentPermission() -> AppleMicrophonePermissionState {
    lock.withLock { queryCount += 1 }
    return .notDetermined
  }

  func requestPermission() async -> AppleMicrophonePermissionState {
    lock.withLock { requestCount += 1 }
    return .granted
  }
}

private struct LazyForeground: AppleApplicationForegroundProviding {
  func isForegroundActive() async -> Bool { true }
}

private final class LazyEngineAudioSystem: AppleAudioSystem, @unchecked Sendable {
  let engines: LazyAppleAudioEngine<EngineMarker>
  private(set) var tapInstalled = false
  private(set) var engineStarted = false
  private var handler: (@Sendable (AppleAudioSystemEvent) -> Void)?

  init(engines: LazyAppleAudioEngine<EngineMarker>) {
    self.engines = engines
  }

  func setEventHandler(_ handler: @escaping @Sendable (AppleAudioSystemEvent) -> Void) {
    self.handler = handler
  }
  func clearEventHandler() { handler = nil }
  func configureAndActivate(profile: AppleAudioSessionProfile) throws {}
  func installInputTap(
    frameCapacity: UInt32, handler: @escaping @Sendable (OwnedAudioFrames) -> Void
  ) throws {
    _ = engines.resolve()
    tapInstalled = true
  }
  func startEngine() throws {
    _ = engines.resolve()
    engineStarted = true
  }
  func freezeInput() throws {
    tapInstalled = false
    engineStarted = false
  }
  func deactivate() throws {
    engines.clear()
  }
}

private final class CapturedLazyEvents: @unchecked Sendable {
  private let lock = NSLock()
  private var values: [PCMAudioEvent] = []
  var count: Int { lock.withLock { values.count } }
  var callbacks: PCMAudioCallbacks {
    PCMAudioCallbacks(
      frames: { frames in
        frames.zeroize()
        return PCMFrameAdmission(accepted: false)
      },
      event: { [self] value in lock.withLock { values.append(value) } }
    )
  }
}
