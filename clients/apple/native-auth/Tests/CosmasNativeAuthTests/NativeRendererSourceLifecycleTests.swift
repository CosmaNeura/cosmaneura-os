import Foundation
import XCTest
@testable import CosmasNativeAuth

@MainActor final class NativeRendererSourceLifecycleTests: XCTestCase {
    func testFenceIsSynchronousAndPermanentAcrossSuccessfulClosure() async throws {
        let h = try RendererOwnerHarness()
        defer { h.cleanUp() }
        _ = try await NativeCaptureStartGate.consume(owner: h.owner) { _ in true }
        h.fence()
        XCTAssertThrowsError(try NativeCaptureStartGate.startTicket())
        XCTAssertThrowsError(try h.lifecycle.beginOperation())
        try await h.close()
        XCTAssertEqual(h.events, ["retire", "pcm", "proof", "clear"])
        XCTAssertThrowsError(try h.lifecycle.requireOpen())
        try await NativeCaptureStartGate.recoverWhileIdle {}
        let replacement = UUID()
        try NativeCaptureStartGate.install(owner: replacement) { try rendererPermit() }
        XCTAssertEqual(try NativeCaptureStartGate.startTicket(), replacement)
        NativeCaptureStartGate.clear(owner: replacement)
    }

    func testLatePreparationCannotPassFenceAfterSuspension() async throws {
        let lifecycle = NativeRendererSourceLifecycle()
        let suspension = RendererSuspension()
        var installed = false
        let operation = try lifecycle.beginOperation()
        let preparation = Task { @MainActor in
            defer { lifecycle.finishOperation(operation) }
            await suspension.wait()
            try lifecycle.requireOpen()
            installed = true
        }
        try await rendererWait { suspension.waiting }
        lifecycle.fence {}
        suspension.resume()
        do { try await preparation.value; XCTFail("Late preparation must fail") }
        catch { XCTAssertEqual(error as? NativeAuthError, .unavailable) }
        XCTAssertFalse(installed)
        XCTAssertThrowsError(try lifecycle.beginOperation())
    }

    func testPendingPrepareOrNormalCloseRetainsOwnerUntilExplicitRetry() async throws {
        let h = try RendererOwnerHarness()
        defer { h.cleanUp() }
        let pending = try h.lifecycle.beginOperation()
        h.fence()
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.events, ["retire", "pcm"])
        XCTAssertThrowsError(try NativeCaptureStartGate.install(owner: UUID()) { try rendererPermit() })
        h.lifecycle.finishOperation(UUID()) // An unrelated completion cannot release it.
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.proofCalls, 0)
        h.lifecycle.finishOperation(pending)
        XCTAssertEqual(h.proofCalls, 0) // Completion never schedules closure itself.
        try await h.close()
        XCTAssertEqual(h.proofCalls, 1)
    }

    func testPhysicalStopFailureOrFalseIdleNeverConfirmsSourceProof() async throws {
        let h = try RendererOwnerHarness()
        defer { h.cleanUp() }
        h.fence()
        h.stopFails = true
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.proofCalls, 0)
        h.stopFails = false
        h.stopReachesIdle = false
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.proofCalls, 0)
        XCTAssertThrowsError(try NativeCaptureStartGate.install(owner: UUID()) { try rendererPermit() })
        h.stopReachesIdle = true
        try await h.close()
        XCTAssertEqual(h.proofCalls, 1)
    }

    func testProofFailureKeepsExactOwnerAndRetryRequiresAnotherExplicitCall() async throws {
        let h = try RendererOwnerHarness()
        defer { h.cleanUp() }
        h.fence()
        h.proofFails = true
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.confirmedOwners, [h.owner])
        XCTAssertFalse(h.events.contains("clear"))
        XCTAssertThrowsError(try NativeCaptureStartGate.install(owner: UUID()) { try rendererPermit() })
        h.proofFails = false
        XCTAssertEqual(h.proofCalls, 1)
        try await h.close()
        XCTAssertEqual(h.confirmedOwners, [h.owner, h.owner])
        XCTAssertEqual(h.events.filter { $0 == "clear" }.count, 1)
    }

    func testConcurrentClosureDoesNotRepeatPhysicalOrProofWork() async throws {
        let h = try RendererOwnerHarness()
        defer { h.cleanUp() }
        let suspension = RendererSuspension()
        h.fence()
        let first = Task { @MainActor in
            try await h.lifecycle.close(stopCapture: {
                h.events.append("pcm")
                await suspension.wait()
                h.idle = true
            }, captureIsIdle: { h.idle }, confirmOwner: { try await h.confirmOwner() })
        }
        try await rendererWait { suspension.waiting }
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.events, ["retire", "pcm"])
        XCTAssertEqual(h.proofCalls, 0)
        suspension.resume()
        try await first.value
        XCTAssertEqual(h.proofCalls, 1)
    }

    func testInFlightAuthorizationCannotStartAndKeepsClosureBlockedUntilRetry() async throws {
        let suspension = RendererSuspension()
        let h = try RendererOwnerHarness(authorize: {
            await suspension.wait()
            return try rendererPermit()
        })
        defer { h.cleanUp() }
        var started = false
        let start = Task { @MainActor in
            try await NativeCaptureStartGate.consume(owner: h.owner) { _ in started = true }
        }
        try await rendererWait { suspension.waiting }
        h.fence()
        await rendererAssertFailure { try await h.close() }
        XCTAssertEqual(h.proofCalls, 0)
        suspension.resume()
        do { try await start.value; XCTFail("Retired authorization must not start") }
        catch { XCTAssertEqual(error as? NativeAuthError, .unavailable) }
        XCTAssertFalse(started)
        XCTAssertEqual(h.proofCalls, 0)
        try await h.close()
        XCTAssertEqual(h.proofCalls, 1)
    }

    func testRecoveryNeverClearsAnotherConfiguredOwner() async throws {
        let h = try RendererOwnerHarness()
        defer { h.cleanUp() }
        let emptyOldPlugin = NativeRendererSourceLifecycle()
        emptyOldPlugin.fence {}
        h.idle = true
        await rendererAssertFailure {
            try await emptyOldPlugin.close(stopCapture: {}, captureIsIdle: { h.idle }) {
                try await NativeCaptureStartGate.recoverWhileIdle {}
            }
        }
        XCTAssertEqual(try NativeCaptureStartGate.startTicket(), h.owner)
        XCTAssertEqual(h.proofCalls, 0)
    }

    func testClosureRequiresFenceAndRechecksIdleAfterProof() async throws {
        let lifecycle = NativeRendererSourceLifecycle()
        var work = 0
        await rendererAssertFailure {
            try await lifecycle.close(stopCapture: { work += 1 }, captureIsIdle: { true }, confirmOwner: { work += 1 })
        }
        XCTAssertEqual(work, 0)
        lifecycle.fence {}
        var idle = true
        await rendererAssertFailure {
            try await lifecycle.close(stopCapture: {}, captureIsIdle: { idle }, confirmOwner: { idle = false })
        }
        XCTAssertThrowsError(try lifecycle.requireOpen())
    }
}

@MainActor private final class RendererOwnerHarness {
    let lifecycle = NativeRendererSourceLifecycle()
    let owner = UUID()
    var idle = false
    var stopFails = false
    var stopReachesIdle = true
    var proofFails = false
    var proofCalls = 0
    var confirmedOwners: [UUID] = []
    var events: [String] = []

    init(authorize: @escaping @MainActor () async throws -> NativeCapturePermit = { try rendererPermit() }) throws {
        NativeCaptureStartGate.registerIdleProbe { [weak self] in self?.idle == true }
        try NativeCaptureStartGate.install(owner: owner, authorize: authorize)
    }

    func fence() {
        lifecycle.fence {
            events.append("retire")
            NativeCaptureStartGate.retire(owner: owner)
        }
    }

    func close() async throws {
        try await lifecycle.close(stopCapture: {
            self.events.append("pcm")
            if self.stopFails { throw RendererTestFailure.expected }
            self.idle = self.stopReachesIdle
        }, captureIsIdle: { self.idle }, confirmOwner: { try await self.confirmOwner() })
    }

    func confirmOwner() async throws {
        try NativeCaptureStartGate.confirmStopped(owner: owner)
        proofCalls += 1
        confirmedOwners.append(owner)
        events.append("proof")
        if proofFails { throw RendererTestFailure.expected }
        events.append("clear")
        NativeCaptureStartGate.clear(owner: owner)
        try await NativeCaptureStartGate.recoverWhileIdle {}
    }

    func cleanUp() {
        NativeCaptureStartGate.clear(owner: owner)
        NativeCaptureStartGate.registerIdleProbe { false }
    }
}

@MainActor private final class RendererSuspension {
    private var continuation: CheckedContinuation<Void, Never>?
    var waiting: Bool { continuation != nil }
    func wait() async { await withCheckedContinuation { continuation = $0 } }
    func resume() { let saved = continuation; continuation = nil; saved?.resume() }
}

private enum RendererTestFailure: Error { case expected, timeout }

@MainActor private func rendererPermit() throws -> NativeCapturePermit {
    try NativeCapturePermit(runID: UUID().uuidString.lowercased(),
        startExpiresAt: Date().addingTimeInterval(60), captureExpiresAt: Date().addingTimeInterval(120))
}

@MainActor private func rendererWait(_ condition: () -> Bool) async throws {
    let deadline = Date().addingTimeInterval(2)
    while !condition() {
        guard Date() < deadline else { throw RendererTestFailure.timeout }
        await Task.yield()
    }
}

@MainActor private func rendererAssertFailure(_ operation: () async throws -> Void,
                                             file: StaticString = #filePath, line: UInt = #line) async {
    do { try await operation(); XCTFail("Closure must stay blocked", file: file, line: line) }
    catch { }
}
