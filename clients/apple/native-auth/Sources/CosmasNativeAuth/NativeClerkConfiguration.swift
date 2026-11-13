import Foundation

public enum NativeIdentityProfile: String, Sendable {
    case synthetic = "synthetic"
    case operationalBeta = "operational-beta-v1"
    case operationalStaging = "operational-staging-v1"
    /// Synthetic simulator builds only. Device sign-in stays on operationalBeta.
    case simulatorStaging = "simulator-staging-v1"
    /// Production-review / App Store candidate on clerk.beta.cosmas.ai.
    /// Live Infos remain operationalBeta on clerk.cosmas.ai.
    case operationalProduction = "operational-production-v1"

    /// Exact Clerk frontend hosts allowed for this profile. Empty means the
    /// profile uses the development `.clerk.accounts.dev` rule instead.
    /// No wildcards, suffixes, or ambient config — one explicit set per profile.
    public var allowedClerkHosts: Set<String> {
        switch self {
        case .operationalBeta:
            return ["clerk.cosmas.ai", "clerk.staging.cosmas.ai"]
        case .operationalProduction:
            return ["clerk.beta.cosmas.ai"]
        case .simulatorStaging:
            return ["clerk.staging.cosmas.ai"]
        case .synthetic, .operationalStaging:
            return []
        }
    }

    /// Live publishable keys for dedicated production Clerk instances.
    public var requiresLivePublishableKey: Bool {
        switch self {
        case .operationalBeta, .operationalProduction:
            return true
        case .synthetic, .operationalStaging, .simulatorStaging:
            return false
        }
    }
}

public enum NativeWorkspaceOrigin: String, Sendable {
    case appleWebView = "capacitor://localhost"
    case desktopApp = "app://cosmas"

    /// Contract client label for POST /enrollment/v1/native/workspace-profile.
    public var nativeClient: String { self == .desktopApp ? "desktop" : "apple" }

    public func accepts(bundleIdentifier: String, profile: NativeIdentityProfile = .synthetic) -> Bool {
        if profile == .simulatorStaging {
            guard self == .appleWebView else { return false }
            return bundleIdentifier.range(
                of: "^com\\.cosmasos\\.synthetic(?:\\.w[1-9][0-9]*[a-z]?)?$",
                options: .regularExpression) != nil
        }
        if profile != .synthetic {
            return bundleIdentifier == (self == .appleWebView
                ? "com.cosmasos.beta.ios" : "com.cosmasos.beta.desktop.auth")
        }
        let pattern = self == .appleWebView
            ? "^com\\.cosmasos\\.synthetic(?:\\.w[1-9][0-9]*[a-z]?)?$"
            : "^com\\.cosmasos\\.synthetic\\.desktop\\.auth(?:\\.w[1-9][0-9]*[a-z]?)?$"
        return bundleIdentifier.range(of: pattern, options: .regularExpression) != nil
    }
}

public struct NativeClerkAccountConfiguration: Sendable, Equatable {
    public let publishableKey: String
    public let frontendOrigin: String
    public let bundleIdentifier: String
    public let workspaceOrigin: NativeWorkspaceOrigin
    public let profile: NativeIdentityProfile
    public let storageNamespace: String?

    public var callbackURL: String { bundleIdentifier + "://callback" }
    // Exact legacy service names remain unchanged. Additional practice slots
    // are isolated; public SDK reconfiguration still requires fresh sign-in.
    public var keychainService: String {
        let base = bundleIdentifier + ".clerk"
        // Staging and production-review qualify by exact Clerk host so sibling
        // instances never share credentials. Live operationalBeta keeps the
        // unqualified legacy service name byte-identical.
        let qualifiesOrigin = profile == .operationalStaging || profile == .operationalProduction
        let realm = qualifiesOrigin ? base + "." + String(frontendOrigin.dropFirst(8)) : base
        return storageNamespace.map { realm + "." + $0 } ?? realm
    }

    public init(publishableKey: String, frontendOrigin: String, bundleIdentifier: String, workspaceOrigin: NativeWorkspaceOrigin = .appleWebView,
                profile: NativeIdentityProfile = .synthetic, storageNamespace: String? = nil) throws {
        let prefix: String
        if profile == .simulatorStaging {
            if publishableKey.hasPrefix("pk_live_") {
                prefix = "pk_live_"
            } else if publishableKey.hasPrefix("pk_test_") {
                prefix = "pk_test_"
            } else {
                throw NativeAuthError.unavailable
            }
        } else {
            prefix = profile.requiresLivePublishableKey ? "pk_live_" : "pk_test_"
        }
        guard publishableKey.hasPrefix(prefix), publishableKey.utf8.count <= 1024,
              workspaceOrigin.accepts(bundleIdentifier: bundleIdentifier, profile: profile),
              let url = URLComponents(string: frontendOrigin), url.scheme == "https",
              let host = url.host, host == host.lowercased(), url.port == nil,
              host.utf8.count <= 245,
              host.range(of: "^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", options: .regularExpression) != nil,
              frontendOrigin == "https://" + host, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { throw NativeAuthError.unavailable }
        let allowedHosts = profile.allowedClerkHosts
        if !allowedHosts.isEmpty {
            // Explicit per-profile allow-list (https origin already required above).
            guard allowedHosts.contains(host) else { throw NativeAuthError.unavailable }
        } else {
            guard host.hasSuffix(".clerk.accounts.dev") else { throw NativeAuthError.unavailable }
        }
        var encoded = String(publishableKey.dropFirst(prefix.count))
        guard encoded.range(of: "^[A-Za-z0-9+/_-]+={0,2}$", options: .regularExpression) != nil else {
            throw NativeAuthError.unavailable
        }
        encoded = encoded.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        encoded += String(repeating: "=", count: (4 - encoded.count % 4) % 4)
        guard let data = Data(base64Encoded: encoded),
              String(data: data, encoding: .utf8) == host + "$" else { throw NativeAuthError.unavailable }
        guard storageNamespace == nil || storageNamespace?.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            throw NativeAuthError.unavailable
        }
        self.storageNamespace = storageNamespace
        self.publishableKey = publishableKey
        self.frontendOrigin = frontendOrigin
        self.bundleIdentifier = bundleIdentifier
        self.workspaceOrigin = workspaceOrigin
        self.profile = profile
    }

    public func prepareFrontendRequest(_ request: inout URLRequest) throws {
        guard let components = request.url.flatMap({ URLComponents(url: $0, resolvingAgainstBaseURL: false) }),
              let host = components.host, components.scheme == "https", components.port == nil,
              "https://" + host == frontendOrigin, components.user == nil, components.password == nil,
              components.fragment == nil,
              request.value(forHTTPHeaderField: "Origin") == nil else {
            throw NativeAuthError.unavailable
        }
        // Clerk's native SDK authenticates its client using Authorization.
        // A browser Origin alongside that credential is rejected by the native
        // API (origin_authorization_headers_conflict). Preserve native headers;
        // workspace-origin and JWT checks remain at the OS transport boundary.
    }
}

/// Fixed workspace organization plus the same exact native Clerk realm policy.
/// Account-before-practice authentication uses NativeClerkAccountConfiguration
/// directly and cannot manufacture a workspace identity with a placeholder Org.
public struct NativeClerkConfiguration: Sendable, Equatable {
    public static let nativeOrigin = "capacitor://localhost"
    public let account: NativeClerkAccountConfiguration
    public let organizationID: String
    public var publishableKey: String { account.publishableKey }
    public var frontendOrigin: String { account.frontendOrigin }
    public var bundleIdentifier: String { account.bundleIdentifier }
    public var workspaceOrigin: NativeWorkspaceOrigin { account.workspaceOrigin }
    public var profile: NativeIdentityProfile { account.profile }
    public var callbackURL: String { account.callbackURL }
    public var keychainService: String { account.keychainService }
    public var storageNamespace: String? { account.storageNamespace }

    public init(publishableKey: String, frontendOrigin: String, organizationID: String,
                bundleIdentifier: String, workspaceOrigin: NativeWorkspaceOrigin = .appleWebView,
                profile: NativeIdentityProfile = .synthetic, storageNamespace: String? = nil) throws {
        guard organizationID.range(of: "^org_[A-Za-z0-9_]{1,251}$", options: .regularExpression) != nil else {
            throw NativeAuthError.unavailable
        }
        account = try NativeClerkAccountConfiguration(publishableKey: publishableKey,
            frontendOrigin: frontendOrigin, bundleIdentifier: bundleIdentifier,
            workspaceOrigin: workspaceOrigin, profile: profile, storageNamespace: storageNamespace)
        self.organizationID = organizationID
    }

    public func prepareFrontendRequest(_ request: inout URLRequest) throws {
        try account.prepareFrontendRequest(&request)
    }
}
