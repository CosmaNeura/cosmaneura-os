import Foundation
import Security
import CosmasNativeAuth

/// Metadata comes from the authorized mount and saved flow. It does not grant capture.
struct NativeSourcePreparation: Equatable, Sendable {
    enum Source: String, Sendable { case desktop = "desktop_companion", ios = "ios_microphone" }
    let workspaceID: UUID
    let sessionID: UUID
    let leaseID: UUID
    let leaseReceiptID: UUID
    let leaseGeneration: Int
    let captureAuthorizedUntil: String
    let source: Source
    let firstSequenceNumber: Int

    init(workspaceID: UUID, sessionID: UUID, leaseID: UUID,
         leaseReceiptID: UUID, leaseGeneration: Int, captureAuthorizedUntil: String,
         source: Source, firstSequenceNumber: Int = 0) throws {
        guard leaseGeneration > 0, (0..<2048).contains(firstSequenceNumber), let deadline = sourceDate(captureAuthorizedUntil),
              deadline > Date() else { throw ProviderNativeError.invalidRequest }
        self.workspaceID = workspaceID; self.sessionID = sessionID
        self.leaseID = leaseID; self.leaseReceiptID = leaseReceiptID
        self.leaseGeneration = leaseGeneration; self.captureAuthorizedUntil = captureAuthorizedUntil
        self.source = source
        self.firstSequenceNumber = firstSequenceNumber
    }
}

struct NativeSourceGrant: Sendable {
    let captureSessionID: String
    let actorID: String
    let consentRecordID: String
    let sourceLeaseID: String
    let source: NativeSourcePreparation.Source

    var desktopPayload: [String: Any] {
        ["captureSessionId": captureSessionID, "actorId": actorID,
         "consentRecordId": consentRecordID, "consentStatus": "granted",
         "sessionStatus": "authorized", "source": source.rawValue,
         "sourceLeaseId": sourceLeaseID]
    }
}

struct NativeSourceDecision: Sendable {
    let grant: NativeSourceGrant
    let capabilityID: String
    let secret: String
    let issuedAt: String
    let expiresAt: String
    let captureAuthorizedUntil: String

    // Main-process-only pipe output. Never use as a Capacitor return value.
    var desktopPayload: [String: Any] {
        var value = grant.desktopPayload
        value["schemaVersion"] = 1; value["decision"] = "authorized"
        value["issuedAt"] = issuedAt; value["expiresAt"] = expiresAt
        value["captureCapability"] = ["capabilityId": capabilityID, "secret": secret,
                                       "expiresAt": expiresAt]
        return value
    }
}

@MainActor private enum NativeSourceConsumption {
    static var consumed: Set<String> = []
}

/// Native-only owner. Persist original stop custody before dispatch. Restart
/// recovery is a separate stop-only path; it cannot replay start authority.
@MainActor final class NativeSourceStartOwner {
    private let connection: NativeProviderConnection
    private let revision: String
    private let preparation: NativeSourcePreparation
    private let stopRevision: (@MainActor () throws -> String)?
    private let attemptID = UUID().uuidString.lowercased()
    private let prepareKey = UUID().uuidString.lowercased()
    private let authorizeKey = UUID().uuidString.lowercased()
    private let cancelKey = UUID().uuidString.lowercased()
    private let stopKey = UUID().uuidString.lowercased()
    private let journal: NativeSourceProofJournal
    private let record: NativeSourceProofRecord
    private var proof: String
    private var grant: NativeSourceGrant?
    private var busy = false
    private var closed = false
    private var issued = false
    private var consumedMicrophoneRunID: String?
    private var retiring = false
    private var pendingExtension: (request: NativeCaptureExtensionRequest, key: String)?
    private var acceptedExtension: (request: NativeCaptureExtensionRequest, id: String,
                                    permit: NativeCaptureExtensionPermit)?
#if os(macOS)
    private var desktopAuthorizationRequested = false
#endif

    init(connection: NativeProviderConnection, revision: String,
         preparation: NativeSourcePreparation, identity: NativeAuthIdentity,
         journal: NativeSourceProofJournal,
         stopRevision: (@MainActor () throws -> String)? = nil) throws {
        guard UUID(uuidString: revision)?.uuidString.lowercased() == revision else {
            throw ProviderNativeError.invalidRequest
        }
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw ProviderNativeError.unavailable
        }
        proof = bytes.map { String(format: "%02x", $0) }.joined()
        _ = bytes.withUnsafeMutableBytes { $0.initializeMemory(as: UInt8.self, repeating: 0) }
        self.connection = connection; self.revision = revision; self.preparation = preparation
        self.stopRevision = stopRevision; self.journal = journal
        record = NativeSourceProofRecord(attemptID: UUID(uuidString: attemptID)!,
            stopKey: UUID(uuidString: stopKey)!, proof: proof, identity: identity, preparation: preparation)
        // A failed write prevents construction/any prepare dispatch. Ambiguous
        // storage failure poisons the process journal until exclusive recovery.
        try journal.insertBeforeDispatch(record)
    }

    func prepare() async throws -> NativeSourceGrant {
        try enter(); defer { busy = false }
        let receipt = try await send(action: "prepare", key: prepareKey)
        let checked = try checkReceipt(receipt)
        guard receipt["state"] as? String == "prepared",
              let expires = receipt["preparation_expires_at"] as? String,
              let date = sourceDate(expires), date > Date() else {
            throw ProviderNativeError.response
        }
        grant = checked
        return checked
    }

    func authorize() async throws -> NativeSourceDecision {
        try enter(); defer { busy = false }
        guard let grant else { throw ProviderNativeError.unavailable }
#if os(macOS)
        desktopAuthorizationRequested = true
#endif
        let result = try await send(action: "authorize", key: authorizeKey)
        guard Set(result.keys) == ["receipt", "secret"],
              let receipt = result["receipt"] as? [String: Any],
              let secret = result["secret"] as? String, secret == proof else {
            throw ProviderNativeError.response
        }
        let checked = try checkReceipt(receipt)
        let now = Date()
        guard checked.sourceLeaseID == grant.sourceLeaseID,
              checked.actorID == grant.actorID, checked.consentRecordID == grant.consentRecordID,
              receipt["state"] as? String == "issued",
              let issuedAt = receipt["issued_at"] as? String, let issue = sourceDate(issuedAt),
              let expiresAt = receipt["expires_at"] as? String, let expiry = sourceDate(expiresAt),
              issue <= now, expiry > now, expiry > issue, expiry.timeIntervalSince(issue) <= 15.001,
              let deadline = sourceDate(preparation.captureAuthorizedUntil), expiry <= deadline,
              let capabilityID = receipt["capability_id"] as? String,
              UUID(uuidString: capabilityID)?.uuidString.lowercased() == capabilityID else {
            throw ProviderNativeError.response
        }
        issued = true
        return NativeSourceDecision(grant: checked, capabilityID: capabilityID, secret: secret,
                                    issuedAt: issuedAt, expiresAt: expiresAt,
                                    captureAuthorizedUntil: preparation.captureAuthorizedUntil)
    }

    /// Called in the native microphone start path, immediately before acquiring
    /// audio. Returns metadata only. No permission can be manufactured in JavaScript.
    func consumeForMicrophone() async throws -> NativeCapturePermit {
        guard preparation.source == .ios, consumedMicrophoneRunID == nil,
              preparation.firstSequenceNumber < 360 else { throw ProviderNativeError.unavailable }
        let decision = try await authorize()
        guard let expiry = sourceDate(decision.expiresAt), expiry > Date(),
              NativeSourceConsumption.consumed.insert(decision.capabilityID).inserted else {
            throw ProviderNativeError.unavailable
        }
        guard let captureExpiry = sourceDate(decision.captureAuthorizedUntil) else {
            throw ProviderNativeError.response
        }
        let permit = try NativeCapturePermit(runID: decision.grant.sourceLeaseID,
                                       startExpiresAt: expiry, captureExpiresAt: captureExpiry,
                                       generation: preparation.leaseGeneration,
                                       hardMaximumChunks: 360 - preparation.firstSequenceNumber)
        consumedMicrophoneRunID = permit.runID
        return permit
    }

    var recordingPreparation: NativeSourcePreparation { preparation }

    /// Renewal retains the original consumed source and its stop proof. The
    /// short capture deadline is independently enforced by the PCM watchdog.
    func requireActiveMicrophone(runID: String) throws {
        try journal.requireUsable()
        guard !closed, !retiring, issued, !proof.isEmpty, preparation.source == .ios,
              consumedMicrophoneRunID == runID, grant?.sourceLeaseID == runID else {
            throw ProviderNativeError.unavailable
        }
        guard try connection.stopRevision(userID: record.userID, organizationID: record.organizationID) == revision
        else { throw ProviderNativeError.unavailable }
    }

    /// Reuse this owner's proof and original stop custody. An uncertain response
    /// permits only an exact retry; a new request cannot skip an unknown grant.
    func extend(_ request: NativeCaptureExtensionRequest) async throws -> NativeCaptureExtensionPermit {
        try enter(); defer { busy = false }
        guard issued, let grant else { throw ProviderNativeError.unavailable }
        if let acceptedExtension, acceptedExtension.request == request {
            guard acceptedExtension.permit.expiresAt > Date() else { throw ProviderNativeError.unavailable }
            return acceptedExtension.permit
        }
        let priorGeneration = acceptedExtension?.permit.generation ?? preparation.leaseGeneration
        let priorDeadline = acceptedExtension?.permit.captureExpiresAt ?? sourceDate(preparation.captureAuthorizedUntil)
        guard let priorDeadline, priorDeadline > Date(), request.leaseGeneration == priorGeneration + 1,
              let deadline = sourceDate(request.captureAuthorizedUntil), deadline > priorDeadline,
              request.firstSequenceNumber > preparation.firstSequenceNumber,
              request.firstSequenceNumber + request.reservationCount >
                (acceptedExtension.map { $0.permit.maximumChunks + preparation.firstSequenceNumber } ?? 0)
        else { throw ProviderNativeError.invalidRequest }
        if let pendingExtension {
            guard pendingExtension.request == request else { throw ProviderNativeError.unavailable }
        } else { pendingExtension = (request, UUID().uuidString.lowercased()) }
        guard let pendingExtension else { throw ProviderNativeError.unavailable }
        let payload: [String: Any] = [
            "schema_version": "1.0", "owner": ownerPayload(),
            "previous_extension_id": acceptedExtension?.id as Any? ?? NSNull(),
            "lease_receipt_id": request.leaseReceiptID.uuidString.lowercased(),
            "lease_generation": request.leaseGeneration,
            "capture_authorized_until": request.captureAuthorizedUntil,
            "reservation_batch_id": request.reservationBatchID.uuidString.lowercased(),
            "first_sequence_number": request.firstSequenceNumber, "reservation_count": request.reservationCount]
        let body: [String: Any] = ["workspace_id": preparation.workspaceID.uuidString.lowercased(),
            "session_id": preparation.sessionID.uuidString.lowercased(),
            "operation": ["kind": "source_extend", "payload": payload]]
        let outbound = try ProviderNativeRequest(nativeStartID: UUID(), revision: revision,
            key: pendingExtension.key, body: JSONSerialization.data(withJSONObject: body))
        let first: ProviderNativeReply?
        do { first = try await connection.send(outbound) }
        catch ProviderNativeError.unavailable { first = nil }
        let response: ProviderNativeReply
        if first == nil || first?.status == 503 {
            // One exact retry while the original physical window is live. The
            // receiver returns its original capability and expiry after a lost reply.
            guard !closed, !retiring, priorDeadline > Date() else { throw ProviderNativeError.unavailable }
            response = try await connection.send(outbound)
        } else { response = first! }
        guard !closed, !retiring, response.status == 200,
              let envelope = try JSONSerialization.jsonObject(with: response.body) as? [String: Any],
              Set(envelope.keys) == ["workspace_id", "session_id", "operation", "receipt"],
              envelope["workspace_id"] as? String == preparation.workspaceID.uuidString.lowercased(),
              envelope["session_id"] as? String == preparation.sessionID.uuidString.lowercased(),
              envelope["operation"] as? String == "source_extend",
              let decision = envelope["receipt"] as? [String: Any], Set(decision.keys) == ["receipt", "secret"],
              decision["secret"] as? String == proof, let receipt = decision["receipt"] as? [String: Any],
              Set(receipt.keys) == ["schema_version", "extension_id", "source_start_id", "session_id",
                "attempt_id", "creator_actor_id", "consent_record_id", "source", "lease_id", "lease_receipt_id",
                "lease_generation", "previous_extension_id", "previous_capture_authorized_until", "capture_authorized_until",
                "reservation_batch_id", "first_sequence_number", "maximum_sequence_number", "issued_at", "expires_at", "capability_id"],
              receipt["schema_version"] as? String == "1.0",
              receipt["session_id"] as? String == preparation.sessionID.uuidString.lowercased(),
              receipt["source_start_id"] as? String == grant.sourceLeaseID,
              receipt["attempt_id"] as? String == attemptID, receipt["source"] as? String == preparation.source.rawValue,
              receipt["creator_actor_id"] as? String == grant.actorID,
              receipt["consent_record_id"] as? String == grant.consentRecordID,
              receipt["lease_id"] as? String == preparation.leaseID.uuidString.lowercased(),
              receipt["lease_receipt_id"] as? String == request.leaseReceiptID.uuidString.lowercased(),
              sourceInteger(receipt["lease_generation"]) == request.leaseGeneration,
              receipt["reservation_batch_id"] as? String == request.reservationBatchID.uuidString.lowercased(),
              sourceInteger(receipt["first_sequence_number"]) == request.firstSequenceNumber,
              sourceInteger(receipt["maximum_sequence_number"]) == request.firstSequenceNumber + request.reservationCount - 1,
              (acceptedExtension == nil ? receipt["previous_extension_id"] is NSNull :
                receipt["previous_extension_id"] as? String == acceptedExtension?.id),
              let prior = receipt["previous_capture_authorized_until"] as? String, sourceDate(prior) == priorDeadline,
              let until = receipt["capture_authorized_until"] as? String, sourceDate(until) == deadline,
              let issued = receipt["issued_at"] as? String, let issueTime = sourceDate(issued), issueTime <= Date(),
              let expires = receipt["expires_at"] as? String, let expiry = sourceDate(expires),
              expiry > issueTime, expiry.timeIntervalSince(issueTime) <= 15.001,
              let identifier = sourceUUID(receipt["extension_id"]), sourceUUID(receipt["capability_id"]) != nil else {
            throw ProviderNativeError.response
        }
        let permit = try NativeCaptureExtensionPermit(runID: grant.sourceLeaseID, generation: request.leaseGeneration,
            expiresAt: expiry, previousCaptureExpiresAt: priorDeadline, captureExpiresAt: deadline,
            maximumChunks: request.firstSequenceNumber + request.reservationCount - preparation.firstSequenceNumber)
        acceptedExtension = (request, identifier, permit)
        self.pendingExtension = nil
        return permit
    }

    func cancelPreparation() async throws {
        try enter(); defer { busy = false }
        guard !issued else { throw ProviderNativeError.unavailable }
        let receipt = try await send(action: "cancel", key: cancelKey)
        _ = try checkReceipt(receipt)
        guard receipt["state"] as? String == "cancelled" else { throw ProviderNativeError.response }
        try journal.removeAfterConfirmedStop(record)
        close()
    }

#if os(macOS)
    /// No authorization was dispatched, so physical start was impossible.
    /// Use the original stop proof even if preparation expired or its reply was lost.
    func cancelUnstartedDesktopPreparation() async throws {
        guard !desktopAuthorizationRequested else { throw ProviderNativeError.unavailable }
        try await confirmStopped()
    }
#endif

    /// Caller must fence pending start and confirm physical native closure first.
    /// Keep the same proof/key after a lost response; never refresh start authority.
    func confirmStopped() async throws {
        retiring = true
        try enter(allowRetiring: true); defer { busy = false }
        let checked = try await record.stop(connection: connection)
        if let grant {
            guard let checked, checked.sourceLeaseID == grant.sourceLeaseID,
                  checked.actorID == grant.actorID, checked.consentRecordID == grant.consentRecordID else {
                throw ProviderNativeError.response
            }
        }
        try journal.removeAfterConfirmedStop(record)
        close()
    }

    /// Authentication loss irrevocably disables preparation/authorization for
    /// this owner. Its original proof remains usable only for confirmed stop.
    func retireForAuthenticationChange() { retiring = true }

    func close() { closed = true; proof = ""; grant = nil; pendingExtension = nil; acceptedExtension = nil }

    private func enter(allowRetiring: Bool = false) throws {
        try journal.requireUsable()
        guard !closed, !busy, (!retiring || allowRetiring), !proof.isEmpty else { throw ProviderNativeError.unavailable }
        busy = true
    }

    private func ownerPayload() -> [String: Any] {
        var payload: [String: Any] = [
            "schema_version": "1.0", "attempt_id": attemptID, "owner_proof": proof,
            "source": preparation.source.rawValue,
            "lease_id": preparation.leaseID.uuidString.lowercased(),
            "lease_receipt_id": preparation.leaseReceiptID.uuidString.lowercased(),
            "lease_generation": preparation.leaseGeneration,
            "capture_authorized_until": preparation.captureAuthorizedUntil,
        ]
        if preparation.firstSequenceNumber > 0 { payload["first_sequence_number"] = preparation.firstSequenceNumber }
        return payload
    }

    private func send(action: String, key: String) async throws -> [String: Any] {
        let body: [String: Any] = [
            "workspace_id": preparation.workspaceID.uuidString.lowercased(),
            "session_id": preparation.sessionID.uuidString.lowercased(),
            "operation": ["kind": "source_start", "action": action, "payload": ownerPayload()],
        ]
        // Only the trusted host can supply a fresh, same-account revision, and
        // only cessation uses it. No start decision is rebound or refreshed.
        let requestRevision = action == "stop" ? try stopRevision?() ?? revision : revision
        let request = try ProviderNativeRequest(nativeStartID: UUID(), revision: requestRevision, key: key,
                                               body: JSONSerialization.data(withJSONObject: body))
        let reply = try await connection.send(request)
        guard !closed, (!retiring || action == "stop"), reply.status == 200,
              let value = try JSONSerialization.jsonObject(with: reply.body) as? [String: Any],
              Set(value.keys) == ["workspace_id", "session_id", "operation", "receipt"],
              value["operation"] as? String == "source_start",
              value["workspace_id"] as? String == preparation.workspaceID.uuidString.lowercased(),
              value["session_id"] as? String == preparation.sessionID.uuidString.lowercased(),
              let receipt = value["receipt"] as? [String: Any] else {
            throw ProviderNativeError.response
        }
        return receipt
    }

    private func checkReceipt(_ receipt: [String: Any]) throws -> NativeSourceGrant {
        var keys: Set<String> = ["schema_version", "session_id", "attempt_id", "source_start_id",
            "creator_actor_id", "consent_record_id", "source", "lease_id", "lease_receipt_id",
            "lease_generation", "state", "preparation_expires_at", "capture_authorized_until",
            "issued_at", "expires_at", "capability_id"]
        if preparation.firstSequenceNumber > 0 { keys.insert("first_sequence_number") }
        guard Set(receipt.keys) == keys,
              try nativeSourceFirstSequence(receipt["first_sequence_number"]) == preparation.firstSequenceNumber,
              receipt["schema_version"] as? String == "1.0",
              receipt["session_id"] as? String == preparation.sessionID.uuidString.lowercased(),
              receipt["attempt_id"] as? String == attemptID,
              receipt["source"] as? String == preparation.source.rawValue,
              receipt["lease_id"] as? String == preparation.leaseID.uuidString.lowercased(),
              receipt["lease_receipt_id"] as? String == preparation.leaseReceiptID.uuidString.lowercased(),
              let generation = receipt["lease_generation"] as? NSNumber,
              CFGetTypeID(generation) != CFBooleanGetTypeID(),
              generation.doubleValue == Double(preparation.leaseGeneration),
              let deadline = receipt["capture_authorized_until"] as? String,
              sourceDate(deadline) == sourceDate(preparation.captureAuthorizedUntil),
              let actor = receipt["creator_actor_id"] as? String,
              actor.range(of: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", options: .regularExpression) != nil,
              let consent = receipt["consent_record_id"] as? String,
              UUID(uuidString: consent)?.uuidString.lowercased() == consent,
              let start = receipt["source_start_id"] as? String,
              UUID(uuidString: start)?.uuidString.lowercased() == start else {
            throw ProviderNativeError.response
        }
        return NativeSourceGrant(captureSessionID: preparation.sessionID.uuidString.lowercased(),
                                 actorID: actor, consentRecordID: consent,
                                 sourceLeaseID: start, source: preparation.source)
    }
}

/// Zero is represented by omission, preserving the accepted first-interval wire.
func nativeSourceFirstSequence(_ value: Any?) throws -> Int {
    guard let value else { return 0 }
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
          number.doubleValue == Double(number.intValue), (1..<2048).contains(number.intValue) else {
        throw ProviderNativeError.invalidRequest
    }
    return number.intValue
}

private func sourceDate(_ value: String) -> Date? {
    let format = ISO8601DateFormatter()
    format.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let parsed = format.date(from: value) { return parsed }
    format.formatOptions = [.withInternetDateTime]
    return format.date(from: value)
}

private func sourceInteger(_ value: Any?) -> Int? {
    guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
          number.doubleValue.isFinite, number.doubleValue > 0,
          number.doubleValue < 9_007_199_254_740_991,
          number.doubleValue.rounded(.towardZero) == number.doubleValue else { return nil }
    return number.intValue
}

private func sourceUUID(_ value: Any?) -> String? {
    guard let value = value as? String, UUID(uuidString: value)?.uuidString.lowercased() == value else { return nil }
    return value
}
