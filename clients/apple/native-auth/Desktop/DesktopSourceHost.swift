import CosmasNativeAuth
import Foundation
import Security

/// Existing sign-in helper owns the source journal and stop-only recovery.
/// Its dedicated parent pipe is not exposed through renderer IPC.
@MainActor final class DesktopSourceHost {
    private let auth: NativeWorkspaceAuth
    private let connection: NativeProviderConnection
    private let sources = DesktopSourceRegistry()
    private var recovery: NativeSourceRecovery?
    private var revision: String

    init(auth: NativeWorkspaceAuth) throws {
        guard Bundle.main.bundleIdentifier == "com.cosmasos.beta.desktop.auth",
              let settings = Bundle.main.object(forInfoDictionaryKey: "CosmasConfiguredCapture") as? [String: Any]
        else { throw ProviderNativeError.unavailable }
        self.auth = auth
        revision = auth.state().revision
        connection = NativeProviderConnection(auth: auth, wire: try WorkspaceSourceTransport(settings: settings))
    }

    func authChanged(_ state: NativeAuthState) {
        connection.authChanged(state)
        if state.phase != .ready || state.revision != revision { sources.retireForAuthenticationChange() }
        revision = state.revision
    }

    func dispatch(_ method: String, payload: Data) async throws -> Any {
        guard let value = try JSONSerialization.jsonObject(with: payload) as? [String: Any] else {
            throw ProviderNativeError.invalidRequest
        }
        switch method {
        case "sourcePrepare":
            guard Set(value.keys.filter { $0 != "firstSequenceNumber" }) == ["revision", "preparationId", "workspaceId", "sessionId",
                "leaseId", "leaseReceiptId", "leaseGeneration", "captureAuthorizedUntil"],
                  let revision = value["revision"] as? String,
                  auth.state().phase == .ready, auth.state().revision == revision,
                  let identity = auth.state().identity,
                  let generation = value["leaseGeneration"] as? NSNumber,
                  CFGetTypeID(generation) != CFBooleanGetTypeID(),
                  generation.doubleValue.rounded(.down) == generation.doubleValue,
                  generation.doubleValue > 0, generation.doubleValue < 2_147_483_648,
                  let deadline = value["captureAuthorizedUntil"] as? String else {
                throw ProviderNativeError.invalidRequest
            }
            try await recoverSources()
            guard auth.state().phase == .ready, auth.state().revision == revision, let recovery else {
                throw ProviderNativeError.unavailable
            }
            try recovery.requireReady()
            let preparation = try NativeSourcePreparation(workspaceID: Self.uuid(value["workspaceId"]),
                sessionID: Self.uuid(value["sessionId"]), leaseID: Self.uuid(value["leaseId"]),
                leaseReceiptID: Self.uuid(value["leaseReceiptId"]), leaseGeneration: generation.intValue,
                captureAuthorizedUntil: deadline, source: .desktop,
                firstSequenceNumber: nativeSourceFirstSequence(value["firstSequenceNumber"]))
            let grant = try await sources.prepare(id: Self.uuid(value["preparationId"]), preparation: preparation) {
                try NativeSourceStartOwner(connection: connection, revision: revision, preparation: preparation,
                    identity: identity, journal: recovery.journal,
                    stopRevision: { [connection] in try connection.stopRevision(for: identity) })
            }
            guard auth.state().phase == .ready, auth.state().revision == revision else { throw ProviderNativeError.unavailable }
            return ["grant": grant.desktopPayload, "processFence": try recovery.processFence]
        case "sourceExtend":
            guard Set(value.keys) == ["revision", "sourceLeaseId", "leaseReceiptId", "leaseGeneration",
                "captureAuthorizedUntil", "reservationBatchId", "firstSequenceNumber", "reservationCount"],
                  let revision = value["revision"] as? String, auth.state().phase == .ready,
                  auth.state().revision == revision, let deadline = value["captureAuthorizedUntil"] as? String else {
                throw ProviderNativeError.invalidRequest
            }
            let request = try NativeCaptureExtensionRequest(leaseReceiptID: Self.uuid(value["leaseReceiptId"]),
                leaseGeneration: Self.integer(value["leaseGeneration"]), captureAuthorizedUntil: deadline,
                reservationBatchID: Self.uuid(value["reservationBatchId"]),
                firstSequenceNumber: Self.integer(value["firstSequenceNumber"]),
                reservationCount: Self.integer(value["reservationCount"]))
            let permit = try await sources.extend(sourceLeaseID: Self.uuid(value["sourceLeaseId"]).uuidString.lowercased(), request: request)
            guard auth.state().phase == .ready, auth.state().revision == revision else { throw ProviderNativeError.unavailable }
            // Metadata travels only on the private main/helper pipe. The original
            // proof stays in this native owner and its stop journal.
            return ["runId": permit.runID, "generation": permit.generation,
                    "expiresAt": Int64(permit.expiresAt.timeIntervalSince1970 * 1000),
                    "previousCaptureAuthorizedUntil": Int64(permit.previousCaptureExpiresAt.timeIntervalSince1970 * 1000),
                    "captureAuthorizedUntil": Int64(permit.captureExpiresAt.timeIntervalSince1970 * 1000),
                    "maximumChunks": permit.maximumChunks]
        case "sourcePreparationRelease":
            guard Set(value.keys) == ["preparationId"] else { throw ProviderNativeError.invalidRequest }
            try await sources.releasePreparation(id: Self.uuid(value["preparationId"]))
            return NSNull()
        case "sourceAuthorize", "sourceRelease", "sourceStopped":
            guard Set(value.keys) == ["sourceLeaseId"] else { throw ProviderNativeError.invalidRequest }
            let start = try Self.uuid(value["sourceLeaseId"]).uuidString.lowercased()
            if method == "sourceAuthorize" { return try await sources.authorize(sourceLeaseID: start).desktopPayload }
            try await sources.release(sourceLeaseID: start, stopped: method == "sourceStopped")
            return NSNull()
        default: throw ProviderNativeError.invalidRequest
        }
    }

    private func recoverSources() async throws {
        if recovery == nil {
            let bundle = Bundle.main.bundleIdentifier ?? ""
            let journal = try NativeSourceProofJournal(platform: .desktop,
                backing: KeychainNativeSourceJournal(platform: .desktop, bundleIdentifier: bundle,
                    accessGroup: Self.signedAccessGroup(bundle)))
            recovery = NativeSourceRecovery(journal: journal, desktopDirectory: try nativeDesktopFenceDirectory())
        }
        guard let recovery else { throw ProviderNativeError.unavailable }
        try await recovery.recover(connection: connection)
    }

    /// macOS packaging does not expand Xcode's AppIdentifierPrefix in Info.plist.
    /// Read the exact private group from this helper's signed entitlements.
    private static func signedAccessGroup(_ bundle: String) throws -> String {
        var code: SecCode?
        var staticCode: SecStaticCode?
        var information: CFDictionary?
        guard SecCodeCopySelf(SecCSFlags(), &code) == errSecSuccess, let code,
              SecCodeCopyStaticCode(code, SecCSFlags(), &staticCode) == errSecSuccess, let staticCode,
              SecCodeCopySigningInformation(staticCode, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
              let values = information as? [String: Any],
              let entitlements = values[kSecCodeInfoEntitlementsDict as String] as? [String: Any],
              let groups = entitlements["keychain-access-groups"] as? [String], groups.count == 1,
              groups[0].hasSuffix("." + bundle) else { throw ProviderNativeError.unavailable }
        return groups[0]
    }

    func close() { connection.close(); sources.close() }
    private static func integer(_ value: Any?) throws -> Int {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue > 0, number.doubleValue < 2_147_483_648,
              number.doubleValue.rounded(.down) == number.doubleValue else { throw ProviderNativeError.invalidRequest }
        return number.intValue
    }
    private static func uuid(_ value: Any?) throws -> UUID {
        guard let text = value as? String, let id = UUID(uuidString: text), id.uuidString.lowercased() == text else {
            throw ProviderNativeError.invalidRequest
        }
        return id
    }
}
