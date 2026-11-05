import Foundation
import CoreFoundation

/// Intent binding only. All account/Org/Box/API/profile authority is fetched by
/// the host from the authenticated pinned service, never supplied by a renderer.
public struct NativeSelectedPracticeRequest: Sendable {
    public let expectedRevision: String
    public let practiceID: UUID
    public let registryRevision: Int
    public init(options: [String: Any]) throws {
        guard Set(options.keys) == ["expectedRevision", "expectedPracticeId", "expectedRegistryRevision"],
              let revision = options["expectedRevision"] as? String,
              UUID(uuidString: revision)?.uuidString.lowercased() == revision,
              let id = options["expectedPracticeId"] as? String, let practice = UUID(uuidString: id),
              practice.uuidString.lowercased() == id,
              let number = options["expectedRegistryRevision"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue >= 0, number.doubleValue < 2_147_483_648,
              number.doubleValue.rounded(.down) == number.doubleValue else { throw NativePracticeProfileError.invalidBinding }
        expectedRevision = revision; practiceID = practice; registryRevision = number.intValue
    }
    public func validate(_ receipt: NativeRegisteredPracticeReceipt, account: NativeAccountIdentity, revision: String) throws {
        guard revision == expectedRevision, receipt.account == account, receipt.practiceID == practiceID,
              receipt.registryRevision == registryRevision else { throw NativePracticeProfileError.sessionChanged }
    }
    @MainActor public static func requireRetiredSource(_ runtime: NativePracticeRuntime, account: NativeAccountIdentity) throws {
        guard runtime.profile?.account == account else { throw NativePracticeProfileError.sessionChanged }
        guard runtime.auth.isRetired, !runtime.auth.hasUnsettledOperations, runtime.resources.isIdle else {
            throw NativePracticeProfileError.busy
        }
    }
    public func validateFinal(candidate: NativePracticeProfile, fresh: NativePracticeProfile,
                              receipt: NativeRegisteredPracticeReceipt, account: NativeAccountIdentity,
                              revision: String, now: Date = Date()) throws {
        try validate(receipt, account: account, revision: revision)
        guard candidate.id == practiceID, fresh.id == practiceID, candidate.account == account, fresh.account == account,
              candidate.organizationID == receipt.organizationID, fresh.organizationID == receipt.organizationID,
              candidate.boxID == receipt.boxID, fresh.boxID == receipt.boxID, candidate.apiOrigin == fresh.apiOrigin,
              candidate.configuration == fresh.configuration, candidate.audience == fresh.audience,
              candidate.storageNamespace == fresh.storageNamespace,
              candidate.expiresAt > now, fresh.expiresAt > now,
              let original = candidate.bootstrap, let checked = fresh.bootstrap,
              original.expiresAt > now, checked.expiresAt > now,
              original.sourceCommit == checked.sourceCommit, original.imageSHA256 == checked.imageSHA256 else {
            throw NativePracticeProfileError.invalidBinding
        }
        // Each bootstrap was freshly nonce/identity/Org/Box/API/proof validated.
        // Qualification hashes cover retained measurements (including their
        // verification session); a refreshed valid measurement need not hash
        // identically. Nor are nonce/issued/expiry fields stable release identity.
    }
    /// Synchronous terminal gate: callers cannot suspend between validation and
    /// marker/runtime installation. Native account/resource values only.
    @MainActor public func commit<T>(runtime: NativePracticeRuntime, fresh: NativePracticeProfile,
                                    receipt: NativeRegisteredPracticeReceipt, account: NativeAccountIdentity,
                                    revision: String, currentAccount: NativeAccountIdentity?, admittedState: NativeAuthState,
                                    install: () throws -> T) throws -> T {
        guard let profile = runtime.profile else { throw NativePracticeProfileError.invalidBinding }
        try validateFinal(candidate: profile, fresh: fresh, receipt: receipt, account: account, revision: revision)
        guard currentAccount == account, runtime.auth.state() == admittedState, admittedState.phase == .ready,
              !runtime.auth.isRetired, runtime.resources.apiOrigin == profile.apiOrigin else { throw NativePracticeProfileError.sessionChanged }
        return try install()
    }
}

public struct NativePracticeAccountView: Sendable {
    public enum Phase: String, Sendable { case signedOut, signingIn, accountReady, unavailable }
    public struct Identity: Sendable {
        public let userID: String
        public let sessionID: String
        public let email: String
        public let displayName: String
        public init(account: NativeAccountIdentity, email: String, displayName: String) throws {
            guard email.utf8.count <= 320, displayName.utf8.count <= 120,
                  email.range(of: "^\\S+@\\S+\\.\\S+$", options: .regularExpression) != nil,
                  !email.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
                  !displayName.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else {
                throw NativePracticeProfileError.invalidBinding
            }
            userID = account.userID; sessionID = account.sessionID
            self.email = email; self.displayName = displayName
        }
    }
    public let phase: Phase
    public let revision: String
    public let identity: Identity?
    public init(phase: Phase, revision: String, identity: Identity?) throws {
        guard UUID(uuidString: revision)?.uuidString.lowercased() == revision,
              (phase == .accountReady) == (identity != nil) else { throw NativePracticeProfileError.invalidBinding }
        self.phase = phase; self.revision = revision; self.identity = identity
    }
    public var payload: [String: Any] {
        ["phase": phase.rawValue, "revision": revision, "identity": identity.map {
            ["userId": $0.userID, "sessionId": $0.sessionID, "email": $0.email, "displayName": $0.displayName]
        } as Any? ?? NSNull()]
    }
}

/// A scoped JWT only for the existing server workspace-confirmation step. It
/// is not a WorkspaceIdentity or an active native runtime/profile receipt.
public struct NativePracticeOrganizationToken: Sendable {
    public let token: String
    public let revision: String
    public init(token: String, revision: String) throws {
        guard !token.isEmpty, token.utf8.count <= 8192,
              UUID(uuidString: revision)?.uuidString.lowercased() == revision else {
            throw NativePracticeProfileError.invalidBinding
        }
        self.token = token; self.revision = revision
    }
    public var payload: [String: Any] { ["token": token, "revision": revision] }
}

/// Fixed native routes only; form validators and business rules remain on the
/// enrollment server. Arbitrary URLs/methods/headers are never plugin inputs.
public enum NativePracticeEnrollmentOperation: String, Sendable {
    case config, status, practices, selectPractice, profile, practice, join, document, accept, receipt, quote
    case checkout, recover, confirmWorkspace, invitation, portal
    public var path: String {
        let prefix = "/enrollment/v1/native"
        switch self {
        // Contract: prefer /native/* siblings; they enforce Origin and never fall back to browser azp.
        case .config: return prefix + "/config"
        case .status: return prefix + "/status"
        case .practices: return prefix + "/practices"
        case .selectPractice: return prefix + "/select-practice"
        case .profile: return prefix + "/profile"
        case .practice: return prefix + "/practice"
        case .join: return prefix + "/join"
        case .document: return prefix + "/baa/current"
        case .accept: return prefix + "/baa/accept"
        case .receipt: return prefix + "/baa/receipt"
        case .quote: return prefix + "/quote"
        case .checkout: return prefix + "/checkout"
        case .recover: return prefix + "/recover"
        case .confirmWorkspace: return prefix + "/workspace/confirm"
        case .invitation: return prefix + "/invitations"
        case .portal: return prefix + "/portal"
        }
    }
    public var method: String {
        switch self {
        case .config, .status, .practices, .document, .receipt, .quote: return "GET"
        case .profile, .practice: return "PUT"
        default: return "POST"
        }
    }
}

public struct NativePracticeEnrollmentRequest: Sendable {
    public let expectedRevision: String
    public let operation: NativePracticeEnrollmentOperation
    public let body: Data?
    public let idempotencyKey: String?
    public init(expectedRevision: String, operation: NativePracticeEnrollmentOperation, body: Data?, idempotencyKey: String?) throws {
        guard UUID(uuidString: expectedRevision)?.uuidString.lowercased() == expectedRevision,
              body?.count ?? 0 <= 32_768,
              operation.method == "GET" ? body == nil && idempotencyKey == nil : body != nil,
              idempotencyKey == nil || (idempotencyKey!.utf8.count <= 255 && !idempotencyKey!.isEmpty &&
                  idempotencyKey!.unicodeScalars.allSatisfy { $0.isASCII && $0.value >= 33 && $0.value <= 126 }) else {
            throw NativePracticeProfileError.invalidBinding
        }
        if let body {
            guard (try JSONSerialization.jsonObject(with: body)) is [String: Any] else { throw NativePracticeProfileError.invalidBinding }
        }
        self.expectedRevision = expectedRevision; self.operation = operation
        self.body = body; self.idempotencyKey = idempotencyKey
    }
}

public struct NativePracticeEnrollmentReply: Sendable {
    public let status: Int
    public let body: Data
    public init(status: Int, body: Data) throws {
        guard (200...599).contains(status), body.count <= 524_288 else { throw NativePracticeProfileError.invalidBinding }
        _ = try JSONSerialization.jsonObject(with: body, options: [.fragmentsAllowed])
        self.status = status; self.body = body
    }
    public var payload: [String: Any] {
        ["status": status, "body": (try? JSONSerialization.jsonObject(with: body, options: [.fragmentsAllowed])) as Any? ?? NSNull()]
    }
}
public enum NativePracticeEnrollmentDestination: String, Sendable { case checkout, portal }

/// Created only after fresh native auth and server admission. Short-lived
/// bootstrap is required for injection/reconnect, never used as the ongoing
/// authorization clock for active API calls.
public struct NativePracticeActiveWorkspaceSnapshot: Sendable {
    public let revision: String
    public let bootstrap: NativePracticeWorkspaceBootstrap
    private let auth: NativeWorkspaceAuth
    private let expectedState: NativeAuthState
    @MainActor public init(runtime: NativePracticeRuntime) throws {
        let state = runtime.auth.state()
        guard state.phase == .ready, let identity = state.identity, let profile = runtime.profile,
              let bootstrap = profile.bootstrap, bootstrap.expiresAt > Date(),
              identity.userID == profile.account.userID, identity.sessionID == profile.account.sessionID,
              identity.organizationID == profile.organizationID, runtime.resources.apiOrigin == profile.apiOrigin else {
            throw NativePracticeProfileError.invalidBinding
        }
        revision = state.revision; self.bootstrap = bootstrap
        auth = runtime.auth; expectedState = state
    }
    /// Native scene calls again after its awaited source/capture closure and
    /// before constructing or injecting a replacement document. A decoded web
    /// profile has no equivalent guard or ability to construct this snapshot.
    @MainActor public func validateCurrentBinding(now: Date = Date()) throws {
        guard bootstrap.expiresAt > now, auth.state() == expectedState,
              expectedState.phase == .ready, expectedState.revision == revision else {
            throw NativePracticeProfileError.sessionChanged
        }
    }
    public var payload: [String: Any] {
        ["contract_version": "cosmabot.native-active-workspace.v1", "revision": revision, "profile": bootstrap.rendererProfile]
    }
}
