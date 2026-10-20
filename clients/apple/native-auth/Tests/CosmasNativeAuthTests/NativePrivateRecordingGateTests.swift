import Foundation
import XCTest
@testable import CosmasNativeAuth

@MainActor final class NativePrivateRecordingGateTests: XCTestCase {
    func testNamespaceMatchesPortableOriginBoundDerivation() throws {
        XCTAssertEqual(try NativePrivateRecordingGate.scope(apiBase: "https://api.example.invalid/", recoveryScope: String(repeating: "a", count: 64)), "902cbb366b70f1c28742fa300ef257e48f73aa8216ce08bfb3379e22607a5c7c")
        // JSON.stringify's exact UTF-8 array for the shipped native/renderer origin.
        XCTAssertEqual(try NativePrivateRecordingGate.scope(apiBase: "https://api.staging.cosmas.ai", recoveryScope: String(repeating: "a", count: 64)), "ba04ba2ba2c52b8a3e346c8879df71f8298b3677ef3742e71f7ab3a6ac4bad57")
    }
    func testPrivateProofConsentOneUseAndSharedExclusion() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        let proof = try await h.prepare()
        let intent = UUID(), permit = try h.begin(proof, intent: intent)
        XCTAssertThrowsError(try h.begin(proof, intent: UUID()))
        XCTAssertThrowsError(try NativeCaptureStartGate.startTicket())
        XCTAssertThrowsError(try NativeCaptureStartGate.install(owner: UUID()) { try NativeCapturePermit(runID: UUID().uuidString.lowercased(), startExpiresAt: Date().addingTimeInterval(5), captureExpiresAt: Date().addingTimeInterval(10)) })
        var starts = 0
        _ = try NativePrivateRecordingGate.consume(permit, foreground: true) { starts += 1; h.idle = false }
        NativeCaptureStartGate.clear(owner: permit.owner)
        XCTAssertThrowsError(try NativeCaptureStartGate.reservePrivate(owner: UUID()))
        XCTAssertEqual(starts, 1)
        XCTAssertThrowsError(try NativePrivateRecordingGate.consume(permit, foreground: true) { starts += 1 })
        XCTAssertThrowsError(try NativePrivateRecordingGate.finish(permit))
        h.idle = true; try NativePrivateRecordingGate.finish(permit)
        XCTAssertTrue(NativePrivateRecordingGate.accountCurrent(permit)); XCTAssertFalse(NativePrivateRecordingGate.current(permit))
        try NativePrivateRecordingGate.finish(permit) // Exact closure replay.
        let fresh = try await h.prepare(); XCTAssertThrowsError(try h.begin(fresh, intent: intent))
        let next = try h.begin(fresh); try NativePrivateRecordingGate.finish(next)
        XCTAssertEqual(h.driver.tokens, 0)
    }
    func testExpiryScopeAndLimitsFailBeforePhysicalReservation() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        let p = try await h.prepare()
        XCTAssertThrowsError(try h.begin(p, scope: String(repeating: "f", count: 64)))
        XCTAssertThrowsError(try h.begin(p, maximum: 91))
        XCTAssertThrowsError(try h.begin(p, maximum: 0))
        XCTAssertThrowsError(try h.begin(p, now: p.expiresAt.addingTimeInterval(1)))
        XCTAssertThrowsError(try h.begin(p, proofID: UUID()))
        let valid = try h.begin(p); XCTAssertThrowsError(try NativePrivateRecordingGate.consume(valid, foreground: false) {})
        try NativePrivateRecordingGate.finish(valid)
    }
    func testAuthLossDuringPermissionCannotStartAndStopsRetainedOwnerWithoutRenderer() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        let first = try h.begin(await h.prepare())
        h.driver.identity = try NativeAuthIdentity(userID: "user_other", sessionID: "sess_other", organizationID: "org_one")
        let changed = h.auth.state(); NativePrivateRecordingGate.authChanged(changed)
        XCTAssertThrowsError(try NativePrivateRecordingGate.consume(first, foreground: true) {})
        try NativePrivateRecordingGate.finish(first)
        let next = try h.begin(await h.prepare())
        _ = try NativePrivateRecordingGate.consume(next, foreground: true) { h.idle = false }
        var stops = 0
        try NativePrivateRecordingGate.retainStop(next) { stops += 1; h.idle = true }
        h.driver.identity = nil; NativePrivateRecordingGate.authChanged(h.auth.state())
        for _ in 0..<100 where stops == 0 { await Task.yield() }
        XCTAssertEqual(stops, 1); XCTAssertFalse(NativePrivateRecordingGate.current(next))
        try await NativeCaptureStartGate.recoverWhileIdle {}
    }
    func testUnconfirmedAuthLossStopKeepsPhysicalGateUntilExplicitExactRetry() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        let selected = try h.begin(await h.prepare()); _ = try NativePrivateRecordingGate.consume(selected, foreground: true) { h.idle = false }
        var attempted = false
        try NativePrivateRecordingGate.retainStop(selected) { attempted = true; throw NativeAuthError.unavailable }
        h.driver.identity = nil; NativePrivateRecordingGate.authChanged(h.auth.state())
        for _ in 0..<100 where !attempted { await Task.yield() }
        XCTAssertTrue(attempted); XCTAssertThrowsError(try NativePrivateRecordingGate.finish(selected))
        XCTAssertThrowsError(try NativeCaptureStartGate.reservePrivate(owner: UUID()))
        h.idle = true; try NativePrivateRecordingGate.finish(selected)
    }
    func testReplacingAuthRetiresPhysicalOwnerWithoutWaitingForChangeCallback() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        let selected = try h.begin(await h.prepare())
        _ = try NativePrivateRecordingGate.consume(selected, foreground: true) { h.idle = false }
        var stops = 0
        try NativePrivateRecordingGate.retainStop(selected) { stops += 1; h.idle = true }
        let replacement = try PrivateGateHarness()
        defer { replacement.cleanup() }
        for _ in 0..<100 where stops == 0 { await Task.yield() }
        XCTAssertEqual(stops, 1)
        XCTAssertFalse(NativePrivateRecordingGate.current(selected))
        try await NativeCaptureStartGate.recoverWhileIdle {}
    }
    func testAccountChangedDuringNativeAccountReadCannotInstallProof() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        NativePrivateRecordingGate.configure(auth: h.auth) { revision in
            let digest = try h.auth.recordingAccountDigest(expectedRevision: revision)
            h.driver.identity = nil; return (h.scope, digest)
        }
        do { _ = try await h.prepare(); XCTFail("Stale read must not prepare") } catch {}
        try await NativeCaptureStartGate.recoverWhileIdle {}
    }
    func testUnavailableAccountReadCannotInstallProofAndFreshReadCanRecover() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        NativePrivateRecordingGate.configure(auth: h.auth) { _ in throw NativeAuthError.unavailable }
        do { _ = try await h.prepare(); XCTFail("Missing account route must not prepare") } catch {}
        XCTAssertThrowsError(try NativePrivateRecordingGate.begin(proofID: UUID(), scope: h.scope,
            revision: h.auth.state().revision, recordingID: UUID(), intent: UUID(),
            consent: NativePrivateRecordingConsent(privateConsent()), maximumChunks: 90))
        NativePrivateRecordingGate.configure(auth: h.auth) { revision in
            (h.scope, try h.auth.recordingAccountDigest(expectedRevision: revision))
        }
        let permit = try h.begin(await h.prepare())
        var starts = 0
        _ = try NativePrivateRecordingGate.consume(permit, foreground: true) { starts += 1 }
        try NativePrivateRecordingGate.finish(permit)
        XCTAssertEqual(starts, 1)
    }
    func testSavedAudioReusesVerifiedScopeWithoutPCMAndFencesActualOwnerChanges() async throws {
        let h = try PrivateGateHarness(); defer { h.cleanup() }
        _ = try await h.prepare()
        NativePrivateRecordingGate.configure(auth: h.auth) { _ in throw NativeAuthError.unavailable }
        let read = try await NativePrivateRecordingGate.authorizeSaved(scope: h.scope, revision: h.auth.state().revision)
        XCTAssertTrue(NativePrivateRecordingGate.savedCurrent(read))
        NativePrivateRecordingGate.authChanged(h.auth.state())
        NativePrivateRecordingGate.authChanged(h.auth.state())
        XCTAssertTrue(NativePrivateRecordingGate.savedCurrent(read)) // Repeated ready notification is not an account replacement.
        do { _ = try await NativePrivateRecordingGate.authorizeSaved(scope: String(repeating: "f", count: 64), revision: h.auth.state().revision); XCTFail("Unverified scope must not read") } catch {}
        h.driver.identity = nil; NativePrivateRecordingGate.authChanged(h.auth.state())
        XCTAssertFalse(NativePrivateRecordingGate.savedCurrent(read))
        XCTAssertEqual(h.driver.tokens, 0)
    }
    func testConsentClosedSchemaBooleanFreshnessLanguageAndRegions() throws {
        let valid = privateConsent()
        _ = try NativePrivateRecordingConsent(valid)
        let unspecified = try NativePrivateRecordingConsent(valid.merging(["participant_regions": [String]()]) { _, new in new })
        XCTAssertEqual(unspecified.regions, [])
        for changed: [String: Any] in [["all_parties_consented": false], ["all_parties_consented": 1], ["language": "fr-FR"], ["method": "implicit"], ["participant_regions": ["New York"]], ["participant_regions": ["US-NY", "US-NY"]], ["participant_regions": (1...17).map { "US-\($0)" }], ["granted_at": "2026-01-01T00:00:00.000Z"], ["extra": true]] {
            XCTAssertThrowsError(try NativePrivateRecordingConsent(valid.merging(changed) { _, new in new }))
        }
    }
}

@MainActor private final class PrivateGateDriver: NativeAuthDriver {
    var loaded = true, tokens = 0
    var identity: NativeAuthIdentity? = try! NativeAuthIdentity(userID: "user_one", sessionID: "sess_one", organizationID: "org_one")
    func signIn() async throws {}
    func signOut() async throws { identity = nil }
    func freshToken() async throws -> String? { tokens += 1; return nil }
}
@MainActor private final class PrivateGateBlock: NativeAuthAccessBlock {
    func isBlocked() throws -> Bool { false }
    func setBlocked(_ blocked: Bool) throws {}
}
@MainActor private final class PrivateGateHarness {
    let driver = PrivateGateDriver(), block = PrivateGateBlock(), auth: NativeWorkspaceAuth
    let scope = String(repeating: "a", count: 64)
    var idle = true
    init() throws {
        let driver = self.driver, block = self.block
        auth = NativeWorkspaceAuth(enabled: true, organizationID: "org_one", tokenPolicy: try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "cosmas-workspace-local"), driver: { driver }, accessBlock: { block })
        NativeCaptureStartGate.registerIdleProbe { [weak self] in self?.idle == true }
        NativePrivateRecordingGate.configure(auth: auth) { [weak self] revision in
            guard let self else { throw NativeAuthError.unavailable }
            return (scope, try auth.recordingAccountDigest(expectedRevision: revision))
        }
    }
    func prepare() async throws -> NativePrivateRecordingProof { try await NativePrivateRecordingGate.prepare(scope: scope, revision: auth.state().revision) }
    func begin(_ proof: NativePrivateRecordingProof, intent: UUID = UUID(), scope: String? = nil, maximum: Int = 90, now: Date = Date(), proofID: UUID? = nil) throws -> NativePrivateRecordingPermit {
        try NativePrivateRecordingGate.begin(proofID: proofID ?? proof.id, scope: scope ?? self.scope, revision: proof.revision, recordingID: UUID(), intent: intent, consent: NativePrivateRecordingConsent(privateConsent()), maximumChunks: maximum, now: now)
    }
    func cleanup() { idle = true; NativePrivateRecordingGate.retire() }
}
private func privateConsent() -> [String: Any] {
    let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return ["modality": "in_person", "participant_regions": ["US-NY"], "method": "verbal_attestation", "all_parties_consented": true, "language": "en-US", "granted_at": formatter.string(from: Date().addingTimeInterval(-1))]
}
