import CryptoKit
import CoreFoundation
import Foundation

public struct NativePrivateRecordingConsent: Equatable, Sendable {
    public let modality: String, regions: [String], language: String, grantedAt: Date
    public init(_ value: [String: Any], now: Date = Date()) throws {
        guard Set(value.keys) == ["modality", "participant_regions", "method", "all_parties_consented", "granted_at", "language"],
              let all = value["all_parties_consented"] as? NSNumber, CFGetTypeID(all) == CFBooleanGetTypeID(), all.boolValue,
              value["method"] as? String == "verbal_attestation",
              let modality = value["modality"] as? String, ["in_person", "virtual", "phone"].contains(modality),
              let language = value["language"] as? String, ["en-US", "en-US+es-US"].contains(language),
              let regions = value["participant_regions"] as? [String], (0...16).contains(regions.count), Set(regions).count == regions.count,
              regions.allSatisfy({ $0.range(of: "^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$", options: .regularExpression) != nil }),
              let raw = value["granted_at"] as? String, raw.range(of: "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$", options: .regularExpression) != nil else { throw NativeAuthError.unavailable }
        let format = ISO8601DateFormatter(); format.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = format.date(from: raw), format.string(from: date) == raw, date <= now, now.timeIntervalSince(date) <= 300 else { throw NativeAuthError.unavailable }
        self.modality = modality; self.language = language; self.regions = regions; grantedAt = date
    }
}

public struct NativePrivateRecordingProof: Sendable {
    public let id: UUID, scope: String, revision: String, accountDigest: String, expiresAt: Date
}
public struct NativePrivateRecordingPermit: Sendable {
    public let owner: UUID, runID: UUID, recordingID: UUID, scope: String, revision: String, accountDigest: String
    public let maximumChunks: Int, captureExpiresAt: Date
}

/// Native account proof and local consent authorize only foreground device PCM.
/// No token, Core lease, provider reservation or clinical admission enters this gate.
@MainActor public enum NativePrivateRecordingGate {
    private struct Active { let permit: NativePrivateRecordingPermit; var stop: (@MainActor () async throws -> Void)?; var retiring = false; var started = false; var stopping = false }
    private static var auth: NativeWorkspaceAuth?
    private static var derive: (@MainActor (String) async throws -> (scope: String, accountDigest: String))?
    private static var proof: NativePrivateRecordingProof?
    private static var active: Active?
    private static var preparing = false
    private static var generation = UUID()
    private static var usedIntents = Set<UUID>()
    private static var lastFinished: UUID?
    public static func configure(auth: NativeWorkspaceAuth, derive: @escaping @MainActor (String) async throws -> (scope: String, accountDigest: String)) {
        let replaced = self.auth !== auth
        if replaced { generation = UUID(); proof = nil }
        self.auth = auth; self.derive = derive
        // Auth plugin replacement must fence an old microphone immediately,
        // even before the replacement delivers its first change notification.
        if replaced, active != nil { retire() }
    }
    public static func prepare(scope: String, revision: String) async throws -> NativePrivateRecordingProof {
        guard !preparing, active == nil, let auth, let derive, Self.hex(scope) else { throw NativeAuthError.busy }
        let before = auth.state(); guard before.phase == .ready, before.revision == revision else { throw NativeAuthError.sessionChanged }
        preparing = true; defer { preparing = false }; let ticket = generation
        let account = try auth.recordingAccountDigest(expectedRevision: revision)
        let observed = try await derive(revision)
        guard ticket == generation, auth.state().revision == revision,
              try auth.recordingAccountDigest(expectedRevision: revision) == account,
              observed.accountDigest == account, observed.scope == scope else { throw NativeAuthError.sessionChanged }
        let result = NativePrivateRecordingProof(id: UUID(), scope: scope, revision: revision, accountDigest: account, expiresAt: Date().addingTimeInterval(300))
        proof = result; return result
    }
    public static func begin(proofID: UUID, scope: String, revision: String, recordingID: UUID, intent: UUID,
                             consent: NativePrivateRecordingConsent, maximumChunks: Int, now: Date = Date()) throws -> NativePrivateRecordingPermit {
        guard active == nil, !preparing, let proof, proof.id == proofID, proof.scope == scope,
              proof.revision == revision, proof.expiresAt > now, (1...90).contains(maximumChunks),
              consent.grantedAt <= now, now.timeIntervalSince(consent.grantedAt) <= 300,
              !usedIntents.contains(intent), usedIntents.count < 10000, let auth,
              try auth.recordingAccountDigest(expectedRevision: revision) == proof.accountDigest else { throw NativeAuthError.unavailable }
        let owner = UUID(); try NativeCaptureStartGate.reservePrivate(owner: owner)
        usedIntents.insert(intent); self.proof = nil
        let permit = NativePrivateRecordingPermit(owner: owner, runID: UUID(), recordingID: recordingID, scope: scope,
            revision: revision, accountDigest: proof.accountDigest, maximumChunks: maximumChunks, captureExpiresAt: now.addingTimeInterval(Double(maximumChunks * 10)))
        active = Active(permit: permit); return permit
    }
    public static func consume<T>(_ permit: NativePrivateRecordingPermit, foreground: Bool, start: @MainActor () throws -> T) throws -> T {
        guard foreground, current(permit), active?.started == false, permit.captureExpiresAt > Date() else { throw NativeAuthError.unavailable }
        let result = try NativeCaptureStartGate.consumePrivate(owner: permit.owner, start: start)
        active?.started = true; return result
    }
    public static func retainStop(_ permit: NativePrivateRecordingPermit, stop: @escaping @MainActor () async throws -> Void) throws {
        guard active?.permit.owner == permit.owner else { throw NativeAuthError.unavailable }
        active?.stop = stop
        if !current(permit) { retire() }
    }
    public static func current(_ permit: NativePrivateRecordingPermit) -> Bool {
        guard let active, active.permit.owner == permit.owner, !active.retiring else { return false }
        return accountCurrent(permit)
    }
    /// Exact original account may recover a lost local stop response; never grants a new Start.
    public static func accountCurrent(_ permit: NativePrivateRecordingPermit) -> Bool {
        guard let auth else { return false }
        return (try? auth.recordingAccountDigest(expectedRevision: permit.revision)) == permit.accountDigest
    }
    public static func finish(_ permit: NativePrivateRecordingPermit) throws {
        if active == nil, lastFinished == permit.owner { return }
        guard active?.permit.owner == permit.owner else { throw NativeAuthError.unavailable }
        try NativeCaptureStartGate.finishPrivate(owner: permit.owner); active = nil; lastFinished = permit.owner
    }
    public static func authChanged(_ state: NativeAuthState) {
        if state.phase != .ready || proof?.revision != state.revision { proof = nil; generation = UUID() }
        if let active, !current(active.permit) { retire() }
    }
    public static func retire() {
        guard let selected = active else { return }
        active?.retiring = true; NativeCaptureStartGate.retire(owner: selected.permit.owner)
        if let stop = selected.stop, !selected.stopping {
            active?.stopping = true
            Task { @MainActor in do { try await stop(); try finish(selected.permit) } catch { if active?.permit.owner == selected.permit.owner { active?.stopping = false } /* Retain physical ownership for exact Stop retry. */ } }
        }
    }
    public static func scope(apiBase: String, recoveryScope: String) throws -> String {
        guard Self.hex(recoveryScope), !apiBase.isEmpty, apiBase.utf8.count <= 2048 else { throw NativeAuthError.unavailable }
        let data = try JSONSerialization.data(withJSONObject: ["cosmas-private-drafts-v1", apiBase.trimmingCharacters(in: CharacterSet(charactersIn: "/")), recoveryScope], options: [.withoutEscapingSlashes])
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
    private static func hex(_ value: String) -> Bool { value.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil }
}
