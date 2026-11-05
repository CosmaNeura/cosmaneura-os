import CryptoKit
import Foundation

/// Account-first identity has no organization and is never workspace authority.
public struct NativeAccountIdentity: Equatable, Sendable {
    public let issuer: String
    public let userID: String
    public let sessionID: String

    public init(issuer: String, userID: String, sessionID: String) throws {
        guard exactPracticeOrigin(issuer),
              userID.range(of: "^user_[A-Za-z0-9_]{1,250}$", options: .regularExpression) != nil,
              sessionID.range(of: "^sess_[A-Za-z0-9_]{1,250}$", options: .regularExpression) != nil else {
            throw NativeAuthError.unavailable
        }
        self.issuer = issuer; self.userID = userID; self.sessionID = sessionID
    }
}

/// Only for a pinned account service; it does not omit Org checks on workspace JWTs.
public struct NativeAccountTokenPolicy: Sendable {
    private let policy: NativeTokenPolicy
    public init(configuration: NativeClerkAccountConfiguration, audience: String) throws {
        policy = try NativeTokenPolicy(issuer: configuration.frontendOrigin, audience: audience,
            authorizedParty: configuration.workspaceOrigin.rawValue,
            nativeSessionWithoutOrigin: configuration.profile != .synthetic,
            sharedStagingSession: configuration.profile == .operationalStaging)
    }
    public func validate(_ token: String, identity: NativeAccountIdentity, now: Date = Date()) throws {
        guard identity.issuer == policy.issuer else { throw NativeAuthError.tokenUnavailable }
        _ = try policy.validatedClaims(token, userID: identity.userID, sessionID: identity.sessionID, now: now)
    }
}

public enum NativePracticeProfileError: String, Error, Sendable {
    case invalidBinding = "native_practice_binding_invalid"
    case sessionChanged = "native_practice_session_changed"
    case busy = "native_practice_activation_busy"
    case unavailable = "native_practice_activation_unavailable"
}

/// Native-host policy only. Neither the renderer nor a callback may supply URLs,
/// Clerk keys or alternative issuers. The concrete authenticated service adapter
/// must be pinned to this exact origin and realm, with redirects prohibited.
public enum NativeRegisteredPracticeOriginPolicy: String, Sendable {
    case exact
    case syntheticPracticeUUIDStaging = "synthetic-practice-uuid-staging-v1"
    /// Real practice data: production Clerk realm and `<uuid>.workspace.cosmas.ai` only.
    case practiceUUIDProduction = "practice-uuid-production-v1"

    /// Each registered policy is bound to exactly one realm profile.
    func admits(_ profile: NativeIdentityProfile) -> Bool {
        switch self {
        case .exact, .syntheticPracticeUUIDStaging: return profile == .operationalStaging
        case .practiceUUIDProduction: return profile == .operationalBeta
        }
    }

    var dataMode: String { self == .practiceUUIDProduction ? "authorized_beta" : "synthetic" }
}

public struct NativePracticeAccountServiceBinding: Equatable, Sendable {
    /// Reviewed staging enrollment HTTPS origin; staging Infos cannot wire production.
    public static let stagingAccountOrigin = "https://enrollment-api.staging.cosmas.ai"
    /// Reviewed production enrollment HTTPS origin; production Infos cannot use another host.
    public static let productionAccountOrigin = "https://enrollment-api.cosmas.ai"

    public let accountOrigin: String
    public let realm: NativeClerkAccountConfiguration
    public let audience: String
    public let allowedAPIOrigins: Set<String>
    public let registeredPracticeOrigins: NativeRegisteredPracticeOriginPolicy

    public init(accountOrigin: String, realm: NativeClerkAccountConfiguration,
                audience: String, allowedAPIOrigins: Set<String>,
                registeredPracticeOrigins: NativeRegisteredPracticeOriginPolicy = .exact) throws {
        guard exactPracticeOrigin(accountOrigin), registeredPracticeOrigins != .exact || !allowedAPIOrigins.isEmpty,
              allowedAPIOrigins.count <= 32, allowedAPIOrigins.allSatisfy(exactPracticeOrigin),
              registeredPracticeOrigins.admits(realm.profile), realm.storageNamespace != nil else {
            throw NativePracticeProfileError.invalidBinding
        }
        // Fail closed at parse: staging↔prod enrollment API mix never lights Connect.
        switch registeredPracticeOrigins {
        case .practiceUUIDProduction:
            guard accountOrigin == Self.productionAccountOrigin else {
                throw NativePracticeProfileError.invalidBinding
            }
        case .exact, .syntheticPracticeUUIDStaging:
            guard accountOrigin == Self.stagingAccountOrigin else {
                throw NativePracticeProfileError.invalidBinding
            }
        }
        _ = try NativeAccountTokenPolicy(configuration: realm, audience: audience)
        self.accountOrigin = accountOrigin; self.realm = realm
        self.audience = audience; self.allowedAPIOrigins = allowedAPIOrigins
        self.registeredPracticeOrigins = registeredPracticeOrigins
    }
    /// Exact reviewed addresses remain valid. The optional dynamic policy is
    /// closed to this server-registered UUID in its own environment (synthetic
    /// staging or production); reserved names and arbitrary suffixes cannot match it.
    public func allowsAPI(_ origin: String, practiceID: UUID) -> Bool {
        if allowedAPIOrigins.contains(origin) { return true }
        let practice = practiceID.uuidString.lowercased()
        switch registeredPracticeOrigins {
        case .exact: return false
        case .syntheticPracticeUUIDStaging:
            return realm.profile == .operationalStaging && origin == "https://api." + practice + ".staging.cosmas.ai"
        case .practiceUUIDProduction:
            return realm.profile == .operationalBeta && origin == "https://api." + practice + ".workspace.cosmas.ai"
        }
    }

    /// The data mode the account service must report for this binding.
    public var dataMode: String { registeredPracticeOrigins.dataMode }

    /// Contract step 2: GET /native/config must echo this binding's realm Origin/issuer/audience.
    /// Mismatched Infos vs enrollment host force rebuild churn if left unchecked until Open Chief.
    public func validateNativeAccountConfig(_ value: [String: Any]) throws {
        guard let account = value["native_account"] as? [String: Any],
              Set(account.keys) == ["issuer", "audience", "session_policy", "native_origin"],
              account["issuer"] as? String == realm.frontendOrigin,
              account["audience"] as? String == audience,
              account["native_origin"] as? String == realm.workspaceOrigin.rawValue,
              let policy = account["session_policy"] as? String,
              !policy.isEmpty, policy.utf8.count <= 64,
              policy.unicodeScalars.allSatisfy({ $0.isASCII && $0.value >= 33 && $0.value <= 126 }) else {
            throw NativePracticeProfileError.invalidBinding
        }
    }

    /// Contract practice open: only `https://<practice-host>/chief` → `https://api.<practice-host>`.
    /// Rejects account-web hosts, missing `/chief`, and API shapes this binding does not admit.
    public func practiceAPIOrigin(fromWorkspaceURL address: String, practiceID: UUID) throws -> String {
        guard address.utf8.count <= 2048, let parsed = URLComponents(string: address), parsed.scheme == "https",
              let host = parsed.host, host == host.lowercased(),
              parsed.user == nil, parsed.password == nil, parsed.port == nil,
              parsed.query == nil, parsed.fragment == nil, parsed.path == "/chief",
              address == "https://" + host + "/chief",
              host != "app.cosmas.ai", host != "api.cosmas.ai" else {
            throw NativePracticeProfileError.invalidBinding
        }
        let api = "https://api." + host
        guard allowsAPI(api, practiceID: practiceID) else { throw NativePracticeProfileError.invalidBinding }
        return api
    }
}

/// Minted by native setup/selection after a trusted account-service discovery.
/// This is not a public plugin payload: a renderer selects only an opaque ID.
public struct NativePracticeConnectionExpectation: Equatable, Sendable {
    public let selectionID: UUID
    public let nonce: UUID
    public let account: NativeAccountIdentity
    public let organizationID: String
    public let boxID: UUID
    public let apiOrigin: String

    public init(selectionID: UUID, nonce: UUID, account: NativeAccountIdentity,
                organizationID: String, boxID: UUID, apiOrigin: String) throws {
        guard exactPracticeOrigin(apiOrigin),
              organizationID.range(of: "^org_[A-Za-z0-9_]{1,251}$", options: .regularExpression) != nil else {
            throw NativePracticeProfileError.invalidBinding
        }
        self.selectionID = selectionID; self.nonce = nonce; self.account = account
        self.organizationID = organizationID; self.boxID = boxID; self.apiOrigin = apiOrigin
    }
}

/// A transport result, not a caller-supplied "authenticated" flag. A concrete
/// native service adapter may return this only after authenticating the response
/// from its pinned account service and redeeming the exact one-use setup flow.
public struct NativePracticeAccountServiceReceipt: Sendable {
    public let expectation: NativePracticeConnectionExpectation
    public let expiresAt: Date
    public let bootstrap: NativePracticeWorkspaceBootstrap?
    public init(expectation: NativePracticeConnectionExpectation, expiresAt: Date, bootstrap: NativePracticeWorkspaceBootstrap? = nil) {
        self.expectation = expectation; self.expiresAt = expiresAt; self.bootstrap = bootstrap
    }
}

/// Parsed from the fresh authenticated native registry status, never an Org
/// parameter supplied to a plugin method.
public struct NativeRegisteredPracticeReceipt: Sendable {
    public let account: NativeAccountIdentity
    public let practiceID: UUID
    public let organizationID: String
    public let boxID: UUID
    public let registryRevision: Int
    public init(account: NativeAccountIdentity, practiceID: UUID, organizationID: String,
                boxID: UUID, registryRevision: Int) throws {
        guard registryRevision >= 0, organizationID.range(of: "^org_[A-Za-z0-9_]{1,251}$", options: .regularExpression) != nil else {
            throw NativePracticeProfileError.invalidBinding
        }
        self.account = account; self.practiceID = practiceID; self.organizationID = organizationID
        self.boxID = boxID; self.registryRevision = registryRevision
    }
}

public struct NativePracticeOrganizationSelection: Sendable {
    public let binding: NativePracticeAccountServiceBinding
    public let receipt: NativeRegisteredPracticeReceipt
    fileprivate init(binding: NativePracticeAccountServiceBinding, receipt: NativeRegisteredPracticeReceipt) {
        self.binding = binding; self.receipt = receipt
    }
}

@MainActor public protocol NativePracticeAccountService: AnyObject {
    var binding: NativePracticeAccountServiceBinding { get }
    func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt
    func registeredPractice(account: NativeAccountIdentity) async throws -> NativeRegisteredPracticeReceipt
}

public extension NativePracticeAccountService {
    func registeredPractice(account: NativeAccountIdentity) async throws -> NativeRegisteredPracticeReceipt {
        throw NativePracticeProfileError.unavailable
    }
}

/// No raw public initializer: profile is minted only by the pinned native service
/// resolver. Structural checks complement server authentication; they cannot
/// authenticate a server response or grant membership by themselves.
public struct NativePracticeProfile: Equatable, Sendable {
    public let id: UUID
    public let account: NativeAccountIdentity
    public let boxID: UUID
    public let apiOrigin: String
    public let configuration: NativeClerkConfiguration
    public let audience: String
    public let expiresAt: Date
    public let bootstrap: NativePracticeWorkspaceBootstrap?
    /// Profile/logout/draft scope is distinct from the issuer-scoped SDK realm slot.
    public let storageNamespace: String
    public var organizationID: String { configuration.organizationID }
    public var tokenPolicy: NativeTokenPolicy {
        get throws {
            try NativeTokenPolicy(issuer: configuration.frontendOrigin, audience: audience,
                authorizedParty: configuration.workspaceOrigin.rawValue,
                nativeSessionWithoutOrigin: configuration.profile != .synthetic,
                sharedStagingSession: configuration.profile == .operationalStaging)
        }
    }

    fileprivate init(expectation: NativePracticeConnectionExpectation, binding: NativePracticeAccountServiceBinding,
                     expiresAt: Date, bootstrap: NativePracticeWorkspaceBootstrap? = nil) throws {
        let data = try JSONSerialization.data(withJSONObject: [
            "purpose": "cosmas-native-practice-slot-v1", "issuer": binding.realm.frontendOrigin,
            "user": expectation.account.userID, "organization": expectation.organizationID,
            "box": expectation.boxID.uuidString.lowercased(), "api": expectation.apiOrigin,
            "audience": binding.audience,
        ], options: [.sortedKeys, .withoutEscapingSlashes])
        let namespace = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        configuration = try NativeClerkConfiguration(publishableKey: binding.realm.publishableKey,
            frontendOrigin: binding.realm.frontendOrigin, organizationID: expectation.organizationID,
            bundleIdentifier: binding.realm.bundleIdentifier, workspaceOrigin: binding.realm.workspaceOrigin,
            profile: binding.realm.profile, storageNamespace: binding.realm.storageNamespace)
        id = expectation.selectionID; account = expectation.account; boxID = expectation.boxID
        apiOrigin = expectation.apiOrigin; audience = binding.audience
        self.expiresAt = expiresAt; self.bootstrap = bootstrap; storageNamespace = namespace
    }
}

@MainActor public final class NativePracticeProfileResolver {
    private let binding: NativePracticeAccountServiceBinding
    private let service: any NativePracticeAccountService
    private let currentAccount: @MainActor () -> NativeAccountIdentity?
    private var pending: Set<UUID> = []
    private var consumed: Set<UUID> = []
    private var consumedNonces: Set<UUID> = []

    public init(binding: NativePracticeAccountServiceBinding, service: any NativePracticeAccountService,
                currentAccount: @escaping @MainActor () -> NativeAccountIdentity?) throws {
        guard service.binding == binding else { throw NativePracticeProfileError.invalidBinding }
        self.binding = binding; self.service = service; self.currentAccount = currentAccount
    }

    public func registeredOrganization() async throws -> NativePracticeOrganizationSelection {
        guard let account = currentAccount(), account.issuer == binding.realm.frontendOrigin,
              service.binding == binding else { throw NativePracticeProfileError.sessionChanged }
        let receipt = try await service.registeredPractice(account: account)
        try Task.checkCancellation()
        guard currentAccount() == account else { throw NativePracticeProfileError.sessionChanged }
        guard service.binding == binding, receipt.account == account else { throw NativePracticeProfileError.invalidBinding }
        return .init(binding: binding, receipt: receipt)
    }

    public func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeProfile {
        guard pending.count < 8, consumed.count < 128,
              !pending.contains(expectation.selectionID), !consumed.contains(expectation.selectionID),
              !consumedNonces.contains(expectation.nonce),
              service.binding == binding, expectation.account.issuer == binding.realm.frontendOrigin,
              binding.allowsAPI(expectation.apiOrigin, practiceID: expectation.selectionID) else {
            throw NativePracticeProfileError.invalidBinding
        }
        guard currentAccount() == expectation.account else { throw NativePracticeProfileError.sessionChanged }
        pending.insert(expectation.selectionID)
        // One-use flows remain consumed after cancellation/failure. Explicit new
        // discovery/redeem is required; the same callback cannot be replayed.
        consumed.insert(expectation.selectionID)
        consumedNonces.insert(expectation.nonce)
        defer { pending.remove(expectation.selectionID) }
        let receipt = try await service.resolve(expectation)
        try Task.checkCancellation()
        guard currentAccount() == expectation.account else { throw NativePracticeProfileError.sessionChanged }
        guard service.binding == binding, receipt.expectation == expectation,
              receipt.expiresAt > Date(), receipt.expiresAt.timeIntervalSince1970.isFinite else {
            throw NativePracticeProfileError.invalidBinding
        }
        if let bootstrap = receipt.bootstrap {
            guard bootstrap.expiresAt == receipt.expiresAt else { throw NativePracticeProfileError.invalidBinding }
            // Verify the typed receipt again against this resolver's exact flow.
            _ = try NativePracticeWorkspaceBootstrap.decode(bootstrap.canonicalData, expectation: expectation, binding: binding)
        }
        return try NativePracticeProfile(expectation: expectation, binding: binding,
            expiresAt: receipt.expiresAt, bootstrap: receipt.bootstrap)
    }
}

private func exactPracticeOrigin(_ value: String) -> Bool {
    guard value.utf8.count <= 253, let url = URLComponents(string: value), url.scheme == "https",
          let host = url.host, host == host.lowercased(), value == "https://" + host,
          url.port == nil, url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
          !host.hasSuffix(".localhost"),
          host.range(of: "^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", options: .regularExpression) != nil,
          host.range(of: "^[0-9.]+$", options: .regularExpression) == nil else { return false }
    return true
}
