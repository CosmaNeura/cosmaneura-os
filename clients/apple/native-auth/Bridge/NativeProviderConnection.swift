import Foundation
import CryptoKit
import CosmasNativeAuth

enum ProviderNativeError: String, Error, Sendable {
    case unavailable = "provider_native_unavailable"
    case invalidRequest = "provider_native_request_invalid"
    case cancelled = "provider_native_cancelled"
    case response = "provider_native_response_invalid"
}

enum ProviderNativeAction: String, Sendable {
    case catalog, mount, recorder
    case sourceStart = "source-start"
    case recordingContext = "native-recording-context"
    case nativeRecording = "native-recording-operation"
    case recordingAccount = "native-recording-account"
    case admission = "capture-admissions", operation = "capture-operations", note = "capture-notes"

    var bodyLimit: Int {
        switch self {
        case .catalog, .recordingAccount: 2
        case .mount: 256
        case .recorder: 1024
        case .sourceStart: 4096
        case .recordingContext: 1024
        case .nativeRecording: 4096
        case .admission: 2048
        case .operation: 4_194_304
        case .note: 262_144 + 8192
        }
    }
    var responseLimit: Int {
        switch self {
        case .catalog: 65_536
        case .mount, .recorder, .sourceStart, .recordingContext: 8192
        case .nativeRecording: 131_072
        case .recordingAccount: 1024
        case .admission, .operation, .note: 8 * 1024 * 1024
        }
    }

    var responseStatuses: [Int] {
        self == .recordingAccount ? [200, 401, 403, 404, 405, 422, 426, 503, 504]
            : [200, 401, 403, 409, 422, 503]
    }
}

struct ProviderNativeRequest: Sendable {
    let id: UUID
    let revision: String
    let action: ProviderNativeAction
    let key: String
    let body: Data

    init(id: String, revision: String, action: String, key: String, body: String) throws {
        guard let identifier = UUID(uuidString: id), identifier.uuidString.lowercased() == id,
              UUID(uuidString: revision)?.uuidString.lowercased() == revision,
              let operation = ProviderNativeAction(rawValue: action),
              operation != .sourceStart, operation != .recordingContext, operation != .nativeRecording,
              operation != .recordingAccount,
              key.range(of: "^[A-Za-z0-9._:-]{8,255}$", options: .regularExpression) != nil,
              body.utf8.count <= operation.bodyLimit, let data = body.data(using: .utf8),
              (try? JSONSerialization.jsonObject(with: data)) is [String: Any]
        else { throw ProviderNativeError.invalidRequest }
        self.id = identifier; self.revision = revision; self.action = operation
        self.key = key; self.body = data
    }

    init(recordingAccountID: UUID, revision: String) throws {
        guard UUID(uuidString: revision)?.uuidString.lowercased() == revision else {
            throw ProviderNativeError.invalidRequest
        }
        id = recordingAccountID; self.revision = revision; action = .recordingAccount
        key = recordingAccountID.uuidString.lowercased(); body = Data("{}".utf8)
    }

    // Not reachable from the generic Capacitor/renderer string-action initializer.
    init(nativeStartID: UUID, revision: String, key: String, body: Data) throws {
        guard UUID(uuidString: revision)?.uuidString.lowercased() == revision,
              key.range(of: "^[A-Za-z0-9._:-]{8,255}$", options: .regularExpression) != nil,
              body.count <= ProviderNativeAction.sourceStart.bodyLimit,
              (try? JSONSerialization.jsonObject(with: body)) is [String: Any]
        else { throw ProviderNativeError.invalidRequest }
        self.id = nativeStartID; self.revision = revision; self.action = .sourceStart
        self.key = key; self.body = body
    }

    // Only the native recording service can construct this bounded operation.
    init(nativeRecordingID: UUID, revision: String, key: String, body: Data) throws {
        guard UUID(uuidString: revision)?.uuidString.lowercased() == revision,
              UUID(uuidString: key)?.uuidString.lowercased() == key,
              body.count <= ProviderNativeAction.nativeRecording.bodyLimit,
              (try? JSONSerialization.jsonObject(with: body)) is [String: Any] else {
            throw ProviderNativeError.invalidRequest
        }
        self.id = nativeRecordingID; self.revision = revision; self.action = .nativeRecording
        self.key = key; self.body = body
    }

    // Native caller supplies only workspace/session; the OS API resolves Core.
    init(recordingContextID: UUID, revision: String, workspaceID: UUID, sessionID: UUID) throws {
        guard UUID(uuidString: revision)?.uuidString.lowercased() == revision else {
            throw ProviderNativeError.invalidRequest
        }
        self.id = recordingContextID; self.revision = revision; self.action = .recordingContext
        self.key = recordingContextID.uuidString.lowercased()
        self.body = try JSONSerialization.data(withJSONObject: [
            "workspace_id": workspaceID.uuidString.lowercased(),
            "session_id": sessionID.uuidString.lowercased(),
            "operation": ["kind": "native_recording_context"],
        ])
    }
}

/// Minted only from the authenticated OS identity route. The UUID is a storage
/// namespace; it is never source permission or a replacement for workspace access.
struct NativeProviderRecordingAccount: Equatable, Sendable {
    let boxID: UUID
    let actorID: UUID
    let accountDigest: String
    let recoveryScope: UUID

    fileprivate init(boxID: UUID, actorID: UUID, accountDigest: String, recovery: String) {
        self.boxID = boxID; self.actorID = actorID; self.accountDigest = accountDigest
        var bytes = Array(SHA256.hash(data: Data(
            ("cosmas-native-recording-recovery-v1\u{0}" + accountDigest + "\u{0}" + recovery).utf8)).prefix(16))
        // RFC 9562 UUIDv8: a stable application-defined digest, not a random ID.
        bytes[6] = (bytes[6] & 0x0f) | 0x80; bytes[8] = (bytes[8] & 0x3f) | 0x80
        recoveryScope = UUID(uuid: (bytes[0], bytes[1], bytes[2], bytes[3], bytes[4], bytes[5],
            bytes[6], bytes[7], bytes[8], bytes[9], bytes[10], bytes[11], bytes[12], bytes[13], bytes[14], bytes[15]))
    }
}

struct NativeProviderRecordingContext: Equatable, Sendable {
    let workspaceID: UUID
    let tenantID: UUID
    let sessionID: UUID
    let accountDigest: String
    let checkedAt: Date

    fileprivate init(workspaceID: UUID, tenantID: UUID, sessionID: UUID,
                     accountDigest: String, checkedAt: Date) {
        self.workspaceID = workspaceID; self.tenantID = tenantID; self.sessionID = sessionID
        self.accountDigest = accountDigest; self.checkedAt = checkedAt
    }
}

struct ProviderNativeReply: Sendable {
    let status: Int
    let body: Data
}

protocol ProviderNativeWire: Sendable {
    func send(_ request: ProviderNativeRequest, token: String) async throws -> ProviderNativeReply
}

/// Binds the *existing* native session owner to the fixed provider receiver.
/// No SDK, token store, auth policy or permissive alternate identity is created.
@MainActor final class NativeProviderConnection {
    private let auth: NativeWorkspaceAuth
    private let wire: any ProviderNativeWire
    private var pending: [UUID: (revision: String, task: Task<ProviderNativeReply, Error>)] = [:]
    private var earlyCancellations: Set<UUID> = []
    private var closed = false

    init(auth: NativeWorkspaceAuth, wire: any ProviderNativeWire) {
        self.auth = auth; self.wire = wire
    }

    func authChanged(_ state: NativeAuthState) {
        for (_, operation) in pending where state.phase != .ready || operation.revision != state.revision {
            operation.task.cancel()
        }
    }

    func cancel(_ id: UUID) {
        if let operation = pending[id] { operation.task.cancel(); return }
        // Capacitor promise calls can be cancelled before their MainActor task
        // enters send(). Keep that cancellation, never dispatch it afterward.
        guard earlyCancellations.count < 1024 else { close(); return }
        earlyCancellations.insert(id)
    }

    func close() {
        closed = true
        for (_, operation) in pending { operation.task.cancel() }
    }

    /// Native-only cessation recovery after the same account signs in again.
    /// The immutable connection retains its original issuer/transport policy.
    func stopRevision(for identity: NativeAuthIdentity) throws -> String {
        try stopRevision(userID: identity.userID, organizationID: identity.organizationID)
    }

    func stopRevision(userID: String, organizationID: String?) throws -> String {
        let state = auth.state()
        guard !closed, state.phase == .ready, let current = state.identity,
              current.userID == userID, current.organizationID == organizationID else {
            throw ProviderNativeError.unavailable
        }
        return state.revision
    }

    func recordingRevision(accountDigest: String) throws -> String {
        let state = auth.state()
        try current(state.revision)
        guard try auth.recordingAccountDigest(expectedRevision: state.revision) == accountDigest else {
            throw ProviderNativeError.unavailable
        }
        return state.revision
    }

    func recordingAccount(revision: String, requestID: UUID = UUID())
        async throws -> NativeProviderRecordingAccount {
        try await NativeAuthAwait<NativeProviderRecordingAccount>().run(timeout: .seconds(15),
            onAbandon: { self.cancel(requestID) }) {
            try self.current(revision)
            let account = try self.auth.recordingAccountDigest(expectedRevision: revision)
            let reply = try await self.send(ProviderNativeRequest(recordingAccountID: requestID, revision: revision))
            try self.current(revision)
            guard reply.status == 200,
                  try self.auth.recordingAccountDigest(expectedRevision: revision) == account,
                  let value = try JSONSerialization.jsonObject(with: reply.body) as? [String: Any],
                  Set(value.keys) == ["contract_version", "box_id", "actor_id", "recovery_scope"],
                  let version = value["contract_version"] as? NSNumber,
                  CFGetTypeID(version) != CFBooleanGetTypeID(), version.doubleValue == 1,
                  let box = value["box_id"] as? String, let boxID = UUID(uuidString: box),
                  boxID.uuidString.lowercased() == box,
                  let actor = value["actor_id"] as? String, let actorID = UUID(uuidString: actor),
                  actorID.uuidString.lowercased() == actor,
                  let recovery = value["recovery_scope"] as? String,
                  recovery.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
                throw ProviderNativeError.response
            }
            return NativeProviderRecordingAccount(boxID: boxID, actorID: actorID,
                accountDigest: account, recovery: recovery)
        }
    }

    /// Core nonce/freshness checks are performed by the authenticated OS API.
    /// No tenant, account digest, token or service URL is supplied by JavaScript.
    func recordingContext(workspaceID: UUID, sessionID: UUID, revision: String,
                          requestID: UUID = UUID()) async throws -> NativeProviderRecordingContext {
        try current(revision)
        let account = try auth.recordingAccountDigest(expectedRevision: revision)
        let request = try ProviderNativeRequest(recordingContextID: requestID, revision: revision,
            workspaceID: workspaceID, sessionID: sessionID)
        let reply = try await send(request)
        try current(revision)
        guard reply.status == 200,
              try auth.recordingAccountDigest(expectedRevision: revision) == account,
              let value = try JSONSerialization.jsonObject(with: reply.body) as? [String: Any],
              Set(value.keys) == ["workspace_id", "session_id", "operation", "receipt"],
              value["workspace_id"] as? String == workspaceID.uuidString.lowercased(),
              value["session_id"] as? String == sessionID.uuidString.lowercased(),
              value["operation"] as? String == "native_recording_context",
              let receipt = value["receipt"] as? [String: Any],
              Set(receipt.keys) == ["schema_version", "workspace_id", "tenant_id", "session_id", "status"],
              receipt["schema_version"] as? String == "1.0",
              receipt["workspace_id"] as? String == workspaceID.uuidString.lowercased(),
              receipt["session_id"] as? String == sessionID.uuidString.lowercased(),
              let tenant = receipt["tenant_id"] as? String, let tenantID = UUID(uuidString: tenant),
              tenantID.uuidString.lowercased() == tenant,
              let status = receipt["status"] as? String, ["created", "capturing"].contains(status) else {
            throw ProviderNativeError.response
        }
        return NativeProviderRecordingContext(workspaceID: workspaceID, tenantID: tenantID,
            sessionID: sessionID, accountDigest: account, checkedAt: Date())
    }

    func send(_ request: ProviderNativeRequest) async throws -> ProviderNativeReply {
        guard !closed, pending[request.id] == nil, pending.count < 8 else {
            throw ProviderNativeError.unavailable
        }
        guard earlyCancellations.remove(request.id) == nil else { throw ProviderNativeError.cancelled }
        try current(request.revision)
        let operation = Task { @MainActor [auth, wire] in
            try Task.checkCancellation()
            let token = try await auth.token(expectedRevision: request.revision)
            try self.current(request.revision)
            try Task.checkCancellation()
            let reply = try await wire.send(request, token: token)
            try Task.checkCancellation()
            try self.current(request.revision)
            guard request.action.responseStatuses.contains(reply.status),
                  reply.body.count <= request.action.responseLimit else {
                throw ProviderNativeError.response
            }
            if reply.status != 200 {
                // Do not forward arbitrary proxy/SDK/error content to JavaScript.
                return Self.sanitizedFailure(reply, action: request.action)
            }
            guard (try? JSONSerialization.jsonObject(with: reply.body)) is [String: Any] else {
                throw ProviderNativeError.response
            }
            return reply
        }
        pending[request.id] = (request.revision, operation)
        defer { pending.removeValue(forKey: request.id) }
        return try await withTaskCancellationHandler {
            let reply = try await operation.value
            try Task.checkCancellation()
            try current(request.revision)
            return reply
        } onCancel: {
            operation.cancel()
        }
    }

    static func sanitizedFailure(_ reply: ProviderNativeReply, action: ProviderNativeAction) -> ProviderNativeReply {
        if action == .admission, reply.status == 409, reply.body.count <= 1024,
           let value = try? JSONSerialization.jsonObject(with: reply.body) as? [String: Any],
           Set(value.keys) == ["detail"], value["detail"] as? String == "core_provider_consent_required" {
            return ProviderNativeReply(status: 409,
                body: Data("{\"detail\":\"provider_consent_required\"}".utf8))
        }
        return ProviderNativeReply(status: reply.status,
            body: Data("{\"detail\":\"provider_request_unconfirmed\"}".utf8))
    }

    private func current(_ revision: String) throws {
        let state = auth.state()
        guard !closed, state.phase == .ready, state.revision == revision else {
            throw ProviderNativeError.unavailable
        }
    }
}
