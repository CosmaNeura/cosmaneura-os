import CosmaneuraIOSPCMBridgeCore
import CosmaneuraIOSPCMCore
import CosmaneuraIOSAVFoundationDriver
import Foundation
import XCTest

@testable import CosmaneuraIOSPCMCapacitorTransport

final class IOSPCMCapacitorTransportTests: XCTestCase {
  func testRendererLossRealBridgeRetainsFailedOwnerAndRejectsLateStart() async throws {
    let audio = RendererRecoveryAudio()
    let emitter = RecordingEmitter()
    let core = IOSPCMBridgeCore(permission: RendererRecoveryPermission(), audio: audio,
      foreground: RendererRecoveryForeground(), events: IOSPCMCapacitorEventPublisher(emitter: emitter))
    let transport = IOSPCMCapacitorTransport(bridge: core)
    let token = try transport.start(configuration: configuration())
    try await transport.ready(sessionToken: token)
    XCTAssertFalse(transport.confirmCaptureIdle())
    do {
      try await transport.fenceAndStopForRendererLoss()
      XCTFail("A failed native release cannot confirm shutdown")
    } catch { XCTAssertEqual(error as? IOSPCMCapacitorErrorCode, .stopFailed) }
    XCTAssertFalse(transport.confirmCaptureIdle())
    XCTAssertThrowsError(try transport.start(configuration: configuration()))
    try await transport.fenceAndStopForRendererLoss()
    try await transport.fenceAndStopForRendererLoss()
    XCTAssertTrue(transport.confirmCaptureIdle())
    XCTAssertTrue(IOSPCMBridgeCore.confirmProcessCaptureIdle())
    XCTAssertEqual(audio.startCalls, 1)
    XCTAssertEqual(audio.releaseCalls, 2)
    XCTAssertThrowsError(try transport.start(configuration: configuration()))
    XCTAssertTrue(emitter.events.isEmpty)
  }

  func testRendererLossLegacyBridgeFailsClosedWithoutInventingStopOrIdle() async {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)
    do {
      try await transport.fenceAndStopForRendererLoss()
      XCTFail("Legacy bridge cannot confirm renderer-loss shutdown")
    } catch { XCTAssertEqual(error as? IOSPCMCapacitorErrorCode, .stopFailed) }
    XCTAssertFalse(transport.confirmCaptureIdle())
    XCTAssertNil(bridge.configuration)
    XCTAssertNil(bridge.stopMode)
  }

  func testLegacyBridgeDoesNotInventProcessIdleProof() {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)
    XCTAssertFalse(transport.confirmCaptureIdle())
    XCTAssertNil(bridge.configuration)
  }

  func testUnsupportedBridgeDeniesAuthorityBeforeBegin() throws {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)
    let config = try IOSPCMCapacitorConfiguration(encoding: "pcm_s16le", channels: 1,
      sampleRateHz: 16_000, targetFramesPerChunk: 1_600, maximumChunks: 10,
      authority: PCMSourceAuthority(runID: UUID().uuidString.lowercased(), generation: 1,
        expiresAtMilliseconds: 1_000_000, hardMaximumChunks: 20))
    XCTAssertFalse(transport.supportsRenewableCapture)
    XCTAssertThrowsError(try transport.start(configuration: config))
    XCTAssertNil(bridge.configuration)
    bridge.supportsRenewableCapture = true
    _ = try transport.start(configuration: config)
    XCTAssertEqual(bridge.configuration?.authority, config.authority)
  }

  func testExtensionPassesExactTokenAndBoundsAndSanitizesFailure() async throws {
    let bridge = FakeBridge()
    bridge.supportsRenewableCapture = true
    let transport = IOSPCMCapacitorTransport(bridge: bridge)
    let value = PCMSourceExtension(runID: UUID().uuidString.lowercased(), generation: 2,
      expiresAtMilliseconds: 2_000_000, maximumChunks: 20)
    try await transport.extend(sessionToken: "1.fragment", value: value)
    XCTAssertEqual(bridge.extensionToken?.rawValue, "1.fragment")
    XCTAssertEqual(bridge.extensionValue, value)
    bridge.supportsRenewableCapture = false
    do {
      try await transport.extend(sessionToken: "1.fragment", value: value)
      XCTFail("unsupported extension")
    } catch { XCTAssertEqual(error as? IOSPCMCapacitorErrorCode, .captureFailed) }
  }

  func testWindowClosureHasExactTokenAndReasonWithoutAudio() throws {
    let emitter = RecordingEmitter()
    let publisher = IOSPCMCapacitorEventPublisher(emitter: emitter)
    let token = IOSPCMBridgeSessionToken(rawValue: "2.fragment")
    try publisher.publish(.windowClosed(token, .authorityExpired))
    try publisher.publish(.windowClosed(token, .frameLimit))
    XCTAssertEqual(emitter.events, [
      .windowClosed(sessionToken: "2.fragment", reason: "authority_expired"),
      .windowClosed(sessionToken: "2.fragment", reason: "frame_limit")])
  }
  func testConfigurationRequiresExactBoundedPCMContract() throws {
    XCTAssertNoThrow(try configuration())
    XCTAssertThrowsError(try configuration(encoding: "pcm_f32le"))
    XCTAssertThrowsError(try configuration(channels: 2))
    XCTAssertThrowsError(try configuration(sampleRateHz: 48_000))
    XCTAssertThrowsError(try configuration(targetFramesPerChunk: 0))
    XCTAssertThrowsError(try configuration(targetFramesPerChunk: 960_001))
    XCTAssertThrowsError(try configuration(maximumChunks: 0))
    XCTAssertThrowsError(try configuration(maximumChunks: 8_641))
  }

  func testStartReturnsOpaqueTokenAndPassesExactConfiguration() throws {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)

    XCTAssertEqual(try transport.start(configuration: configuration()), "1.fragment_1")
    XCTAssertEqual(
      bridge.configuration,
      IOSPCMBridgeConfiguration(
        encoding: "pcm_s16le",
        channels: 1,
        sampleRateHz: 16_000,
        targetFramesPerChunk: 1_600,
        maximumChunks: 100
      )
    )
  }

  func testReadyPreservesEveryFixedStartCode() async throws {
    let cases: [(IOSPCMBridgeStartErrorCode, IOSPCMCapacitorErrorCode)] = [
      (.permissionDenied, .microphonePermissionDenied),
      (.permissionRestricted, .microphonePermissionRestricted),
      (.microphoneUnavailable, .microphoneUnavailable),
      (.notForeground, .notForeground),
      (.startFailed, .startFailed),
    ]
    for (bridgeCode, expected) in cases {
      let bridge = FakeBridge()
      bridge.readyError = IOSPCMBridgeStartFailure(bridgeCode)
      let transport = IOSPCMCapacitorTransport(bridge: bridge)
      do {
        try await transport.ready(sessionToken: "1.fragment_1")
        XCTFail("expected ready failure")
      } catch let error as IOSPCMCapacitorErrorCode {
        XCTAssertEqual(error, expected)
      }
    }

    let staleBridge = FakeBridge()
    staleBridge.readyError = IOSPCMBridgeFailure(.captureFailed)
    let staleTransport = IOSPCMCapacitorTransport(bridge: staleBridge)
    do {
      try await staleTransport.ready(sessionToken: "1.fragment_1")
      XCTFail("expected stale-token failure")
    } catch let error as IOSPCMCapacitorErrorCode {
      XCTAssertEqual(error, .captureFailed)
    }
  }

  func testRejectsMalformedTokensAndOutOfRangeSequencesBeforeBridge() throws {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)
    for token in ["", "0.fragment", "01.fragment", "1.", "1.bad token", "1.a.b"] {
      XCTAssertThrowsError(
        try transport.acknowledge(sessionToken: token, sequenceNumber: 0)
      )
    }
    XCTAssertThrowsError(
      try transport.acknowledge(sessionToken: "1.fragment", sequenceNumber: -1)
    )
    XCTAssertThrowsError(
      try transport.acknowledge(sessionToken: "1.fragment", sequenceNumber: 8_640)
    )
    XCTAssertEqual(bridge.acknowledgeCalls, 0)
  }

  func testAcknowledgementAndReplayRemainDistinct() throws {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)

    for (source, expected) in [
      (IOSPCMBridgeAcknowledgementResult.accepted, IOSPCMCapacitorAcknowledgement.accepted),
      (.replayed, .replayed),
      (.stale, .stale),
    ] {
      bridge.acknowledgement = source
      XCTAssertEqual(
        try transport.acknowledge(sessionToken: "1.fragment", sequenceNumber: 2),
        expected
      )
    }
    for (source, expected) in [
      (IOSPCMBridgeReplayResult.replayed, IOSPCMCapacitorReplay.replayed),
      (.alreadyAcknowledged, .alreadyAcknowledged),
      (.stale, .stale),
      (.transportFailed, .transportFailed),
    ] {
      bridge.replay = source
      XCTAssertEqual(
        try transport.replayPendingPacket(sessionToken: "1.fragment", sequenceNumber: 2),
        expected
      )
    }
  }

  func testStopPreservesModeAndFixedFailureCode() async throws {
    let bridge = FakeBridge()
    let transport = IOSPCMCapacitorTransport(bridge: bridge)

    _ = try await transport.stop(sessionToken: "1.fragment", mode: .discard)
    XCTAssertEqual(bridge.stopMode, .discard)

    bridge.stopError = IOSPCMBridgeFailure(.stopFailed)
    do {
      _ = try await transport.stop(sessionToken: "1.fragment", mode: .drain)
      XCTFail("expected stop failure")
    } catch let error as IOSPCMCapacitorErrorCode {
      XCTAssertEqual(error, .stopFailed)
    }
  }

  func testLifecycleEventsUseExactCodes() throws {
    let emitter = RecordingEmitter()
    let publisher = IOSPCMCapacitorEventPublisher(emitter: emitter)
    let token = IOSPCMBridgeSessionToken(rawValue: "2.fragment-2")

    try publisher.publish(.interruption(token, .captureBackgrounded))
    try publisher.publish(.terminal(token, .microphonePermissionRevoked))

    XCTAssertEqual(
      emitter.events,
      [
        .interruption(
          sessionToken: "2.fragment-2",
          code: "ios_capture_backgrounded"
        ),
        .terminal(
          sessionToken: "2.fragment-2",
          code: "ios_microphone_permission_revoked"
        ),
      ]
    )
  }

  func testBase64ScratchClearsItsMutableCopy() {
    var source = [UInt8](repeating: 0x41, count: 32)
    var scratch = source.withUnsafeBytes { IOSPCMBase64Scratch(copying: $0) }

    XCTAssertEqual(scratch.encodeAndClear(), Data(source).base64EncodedString())
    XCTAssertTrue(scratch.isZeroized)
    XCTAssertEqual(source, [UInt8](repeating: 0x41, count: 32))

    _ = source.withUnsafeMutableBytes {
      $0.initializeMemory(as: UInt8.self, repeating: 0)
    }
  }
}

private func configuration(
  encoding: String = "pcm_s16le",
  channels: Int = 1,
  sampleRateHz: Int = 16_000,
  targetFramesPerChunk: Int = 1_600,
  maximumChunks: Int = 100
) throws -> IOSPCMCapacitorConfiguration {
  try IOSPCMCapacitorConfiguration(
    encoding: encoding,
    channels: channels,
    sampleRateHz: sampleRateHz,
    targetFramesPerChunk: targetFramesPerChunk,
    maximumChunks: maximumChunks
  )
}

private final class RecordingEmitter: IOSPCMCapacitorEventEmitting,
  @unchecked Sendable
{
  private let lock = NSLock()
  private var storage: [IOSPCMCapacitorEvent] = []

  var events: [IOSPCMCapacitorEvent] { lock.withLock { storage } }

  func emit(_ event: IOSPCMCapacitorEvent) throws {
    lock.withLock { storage.append(event) }
  }
}

private struct RendererRecoveryPermission: MicrophonePermissionAuthorizing {
  func requestPermission(cancellation: StartupCancellation) async -> MicrophonePermission { .granted }
}

private struct RendererRecoveryForeground: AppleApplicationForegroundProviding {
  func isForegroundActive() async -> Bool { true }
}

private final class RendererRecoveryAudio: PCMAudioDriving, @unchecked Sendable {
  private let lock = NSLock()
  private var starts = 0
  private var releases = 0
  var startCalls: Int { lock.withLock { starts } }
  var releaseCalls: Int { lock.withLock { releases } }
  func start(sessionID: UInt64, callbacks: PCMAudioCallbacks,
             cancellation: StartupCancellation) async throws { lock.withLock { starts += 1 } }
  func freezeInput(sessionID: UInt64) async throws {}
  func release(sessionID: UInt64) async throws {
    let first = lock.withLock { releases += 1; return releases == 1 }
    if first { throw IOSPCMBridgeFailure(.stopFailed) }
  }
}

private final class FakeBridge: IOSPCMBridgeServing, @unchecked Sendable {
  var supportsRenewableCapture = false
  var extensionToken: IOSPCMBridgeSessionToken?
  var extensionValue: PCMSourceExtension?
  func extend(_ token: IOSPCMBridgeSessionToken, value: PCMSourceExtension) async throws {
    extensionToken = token
    extensionValue = value
  }
  var configuration: IOSPCMBridgeConfiguration?
  var readyError: Error?
  var stopError: Error?
  var stopMode: IOSPCMBridgeStopMode?
  var acknowledgement: IOSPCMBridgeAcknowledgementResult = .stale
  var replay: IOSPCMBridgeReplayResult = .stale
  var acknowledgeCalls = 0

  func appState() async -> IOSPCMBridgeAppState { .foreground }

  func begin(
    configuration: IOSPCMBridgeConfiguration
  ) throws -> IOSPCMBridgeSessionToken {
    self.configuration = configuration
    return IOSPCMBridgeSessionToken(rawValue: "1.fragment_1")
  }

  func ready(_ token: IOSPCMBridgeSessionToken) async throws {
    if let readyError { throw readyError }
  }

  func heartbeat(_ token: IOSPCMBridgeSessionToken) async throws {}

  func stopForCapacitor(
    _ token: IOSPCMBridgeSessionToken,
    mode: IOSPCMBridgeStopMode
  ) async throws -> IOSPCMBridgePacket? {
    stopMode = mode
    if let stopError { throw stopError }
    return nil
  }

  func acknowledge(
    _ token: IOSPCMBridgeSessionToken,
    sequenceNumber: UInt64
  ) -> IOSPCMBridgeAcknowledgementResult {
    acknowledgeCalls += 1
    return acknowledgement
  }

  func replayPendingPacket(
    _ token: IOSPCMBridgeSessionToken,
    sequenceNumber: UInt64
  ) -> IOSPCMBridgeReplayResult {
    replay
  }
}
