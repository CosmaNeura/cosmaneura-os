#if canImport(ClerkKit)
import ClerkKit
import Foundation

/// The local qualification composition supplies the pinned ClerkKit 1.5.5 core.
/// This file never substitutes an opaque capture grant for a Clerk JWT.
@MainActor public final class ClerkKitWorkspaceDriver: NativeAuthDriver {
    private let clerk: Clerk
    private let configuration: NativeClerkConfiguration

    public init(configuration: NativeClerkConfiguration) throws {
        guard Bundle.main.bundleIdentifier == configuration.bundleIdentifier else {
            throw NativeAuthError.unavailable
        }
        self.configuration = configuration
        clerk = Clerk.configure(publishableKey: configuration.publishableKey,
                                options: Self.options(configuration.account))
    }

    fileprivate init(configuration: NativeClerkConfiguration, clerk: Clerk) {
        self.configuration = configuration
        self.clerk = clerk
    }

    /// Called only after the prior account graph is terminally retired and all
    /// of its SDK/request/source operations have settled. The public SDK clears
    /// local credentials in both slots; returning to a profile needs sign-in.
    public static func reconfigured(configuration: NativeClerkConfiguration) async throws -> ClerkKitWorkspaceDriver {
        guard Bundle.main.bundleIdentifier == configuration.bundleIdentifier else { throw NativeAuthError.unavailable }
        let clerk = try await Clerk.reconfigure(publishableKey: configuration.publishableKey,
                                                options: options(configuration.account))
        try Task.checkCancellation()
        return ClerkKitWorkspaceDriver(configuration: configuration, clerk: clerk)
    }

    fileprivate static func matches(_ clerk: Clerk, _ configuration: NativeClerkAccountConfiguration) -> Bool {
        clerk.publishableKey == configuration.publishableKey &&
            clerk.options.keychainConfig.service == configuration.keychainService &&
            clerk.options.redirectConfig.redirectUrl == configuration.callbackURL &&
            clerk.options.redirectConfig.callbackUrlScheme == configuration.bundleIdentifier &&
            clerk.options.sharedSessionSync == nil
    }

    fileprivate static func options(_ configuration: NativeClerkAccountConfiguration) -> Clerk.Options {
        .init(logLevel: .error, telemetryEnabled: false,
              keychainConfig: .init(service: configuration.keychainService),
              redirectConfig: .init(redirectUrl: configuration.callbackURL,
                                    callbackUrlScheme: configuration.bundleIdentifier),
              watchConnectivityEnabled: false, sharedSessionSync: nil, loggerHandler: nil,
              middleware: .init(request: [NativeOriginMiddleware(configuration: configuration)]))
    }

    public var loaded: Bool { clerk.isLoaded }

    public var identity: NativeAuthIdentity? {
        guard Self.matches(clerk, configuration.account), let session = clerk.session, session.status == .active,
              session.expireAt > Date(), let user = clerk.user,
              session.lastActiveOrganizationId == configuration.organizationID else { return nil }
        return try? NativeAuthIdentity(userID: user.id, sessionID: session.id,
                                       organizationID: configuration.organizationID)
    }

    public func signIn() async throws {
        let session = try await clerk.auth.startHostedAuth(
            redirectUrl: configuration.callbackURL, prefersEphemeralWebBrowserSession: true
        )
        try Task.checkCancellation()
        guard clerk.user?.organizationMemberships?.contains(where: {
            $0.organization.id == configuration.organizationID
        }) == true else { throw NativeAuthError.signInFailed }
        try await clerk.auth.setActive(sessionId: session.id, organizationId: configuration.organizationID)
        guard identity != nil else { throw NativeAuthError.signInFailed }
    }

    public func freshToken() async throws -> String? {
        try await clerk.auth.getToken(.init(skipCache: true))
    }

    public func signOut() async throws {
        try await clerk.auth.signOut()
    }
}

/// Account-before-practice login is deliberately not a NativeAuthDriver. It has
/// no organization/workspace identity and cannot be passed to NativeWorkspaceAuth.
@MainActor public final class ClerkKitAccountDriver {
    private let clerk: Clerk
    private let configuration: NativeClerkAccountConfiguration
    private let policy: NativeAccountTokenPolicy
    private var retired = false
    private var pending = 0

    private init(clerk: Clerk, configuration: NativeClerkAccountConfiguration, policy: NativeAccountTokenPolicy) {
        self.clerk = clerk; self.configuration = configuration; self.policy = policy
    }

    /// Marked restart only, before any default-beta SDK/plugin initialization.
    /// configure restores this exact realm slot without deleting SDK credentials.
    public static func configured(configuration: NativeClerkAccountConfiguration,
                                  audience: String) throws -> ClerkKitAccountDriver {
        guard Bundle.main.bundleIdentifier == configuration.bundleIdentifier,
              configuration.storageNamespace != nil else { throw NativeAuthError.unavailable }
        let policy = try NativeAccountTokenPolicy(configuration: configuration, audience: audience)
        let clerk = Clerk.configure(publishableKey: configuration.publishableKey,
            options: ClerkKitWorkspaceDriver.options(configuration))
        guard ClerkKitWorkspaceDriver.matches(clerk, configuration) else { throw NativeAuthError.unavailable }
        return ClerkKitAccountDriver(clerk: clerk, configuration: configuration, policy: policy)
    }
    public var loaded: Bool { !retired && clerk.isLoaded }
    public var email: String { clerk.user?.primaryEmailAddress?.emailAddress ?? "" }
    public var displayName: String { [clerk.user?.firstName, clerk.user?.lastName].compactMap { $0 }.joined(separator: " ") }

    public static func reconfigured(configuration: NativeClerkAccountConfiguration,
                                    audience: String) async throws -> ClerkKitAccountDriver {
        guard Bundle.main.bundleIdentifier == configuration.bundleIdentifier,
              configuration.storageNamespace != nil else { throw NativeAuthError.unavailable }
        let policy = try NativeAccountTokenPolicy(configuration: configuration, audience: audience)
        let clerk = try await Clerk.reconfigure(publishableKey: configuration.publishableKey,
            options: ClerkKitWorkspaceDriver.options(configuration))
        try Task.checkCancellation()
        return ClerkKitAccountDriver(clerk: clerk, configuration: configuration, policy: policy)
    }

    public var identity: NativeAccountIdentity? {
        guard !retired, ClerkKitWorkspaceDriver.matches(clerk, configuration), let session = clerk.session, session.status == .active, session.expireAt > Date(),
              let user = clerk.user else { return nil }
        return try? NativeAccountIdentity(issuer: configuration.frontendOrigin, userID: user.id, sessionID: session.id)
    }

    public func signOut() async throws {
        guard !retired, pending == 0 else { throw NativeAuthError.busy }
        pending += 1; defer { pending -= 1 }
        try await clerk.auth.signOut(); try Task.checkCancellation()
        guard identity == nil else { throw NativeAuthError.signOutPending }
    }

    public func retire() { retired = true }
    public var hasUnsettledOperations: Bool { pending != 0 }

    public func signIn() async throws -> NativeAccountIdentity {
        guard !retired, pending == 0 else { throw NativeAuthError.busy }
        pending += 1; defer { pending -= 1 }
        _ = try await clerk.auth.startHostedAuth(redirectUrl: configuration.callbackURL,
                                                prefersEphemeralWebBrowserSession: true)
        try Task.checkCancellation()
        guard let identity else { throw NativeAuthError.signInFailed }
        return identity
    }

    /// The selection was minted by the pinned native registry resolver. A page
    /// supplies neither organization nor callback URL; membership is rechecked.
    public func activateOrganization(_ selection: NativePracticeOrganizationSelection) async throws {
        let expected = selection.receipt.account
        guard !retired, pending == 0, identity == expected,
              selection.binding.realm == configuration,
              clerk.user?.organizationMemberships?.contains(where: {
                  $0.organization.id == selection.receipt.organizationID
              }) == true else { throw NativePracticeProfileError.invalidBinding }
        pending += 1; defer { pending -= 1 }
        try await clerk.auth.setActive(sessionId: expected.sessionID, organizationId: selection.receipt.organizationID)
        try Task.checkCancellation()
        guard identity == expected, clerk.session?.lastActiveOrganizationId == selection.receipt.organizationID else {
            throw NativePracticeProfileError.sessionChanged
        }
    }

    /// Scoped only to the registry-selected Org for server confirmation. This
    /// never constructs a renderer WorkspaceIdentity or skips qualified profile
    /// retrieval/current server admission before actual workspace activation.
    public func workspaceConfirmationToken(_ selection: NativePracticeOrganizationSelection) async throws -> String {
        let expected = selection.receipt.account
        guard !retired, identity == expected, selection.binding.realm == configuration,
              clerk.session?.lastActiveOrganizationId == selection.receipt.organizationID else {
            throw NativePracticeProfileError.invalidBinding
        }
        pending += 1; defer { pending -= 1 }
        let token = try await clerk.auth.getToken(.init(skipCache: true))
        try Task.checkCancellation()
        guard identity == expected, clerk.session?.lastActiveOrganizationId == selection.receipt.organizationID,
              let token else { throw NativePracticeProfileError.sessionChanged }
        let identity = try NativeAuthIdentity(userID: expected.userID, sessionID: expected.sessionID,
                                             organizationID: selection.receipt.organizationID)
        let policy = try NativeTokenPolicy(issuer: configuration.frontendOrigin, audience: selection.binding.audience,
            authorizedParty: configuration.workspaceOrigin.rawValue, nativeSessionWithoutOrigin: configuration.profile != .synthetic,
            sharedStagingSession: configuration.profile == .operationalStaging)
        try policy.validate(token, identity: identity)
        return token
    }

    /// Same realm only, after registry Org activation and fresh qualified
    /// profile retrieval. No keychain copy or second configure/browser login.
    /// Other realms must use public reconfigure after complete old-graph drain.
    public func adoptWorkspace(_ profile: NativePracticeProfile) throws -> ClerkKitWorkspaceDriver {
        guard !retired, pending == 0, identity == profile.account,
              (profile.bootstrap?.expiresAt ?? .distantPast) > Date(),
              profile.configuration.account == configuration,
              ClerkKitWorkspaceDriver.matches(clerk, configuration),
              clerk.session?.lastActiveOrganizationId == profile.organizationID,
              clerk.user?.organizationMemberships?.contains(where: {
                  $0.organization.id == profile.organizationID
              }) == true else { throw NativePracticeProfileError.invalidBinding }
        // Fence the account-only facade before exposing the fixed-Org facade.
        retired = true
        return ClerkKitWorkspaceDriver(configuration: profile.configuration, clerk: clerk)
    }

    public func token(expected: NativeAccountIdentity) async throws -> String {
        guard !retired else { throw NativeAuthError.unavailable }
        pending += 1; defer { pending -= 1 }
        guard identity == expected else { throw NativeAuthError.sessionChanged }
        let token = try await clerk.auth.getToken(.init(skipCache: true))
        try Task.checkCancellation()
        guard identity == expected, let token else { throw NativeAuthError.tokenUnavailable }
        try policy.validate(token, identity: expected)
        return token
    }
}

private struct NativeOriginMiddleware: ClerkRequestMiddleware {
    let configuration: NativeClerkAccountConfiguration
    func prepare(_ request: inout URLRequest) async throws {
        try configuration.prepareFrontendRequest(&request)
    }
}
#endif
