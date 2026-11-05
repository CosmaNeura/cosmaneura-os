import Foundation

public enum NativePracticeAccountRequest: Sendable {
    case enrollment(NativePracticeEnrollmentOperation)
    case workspaceProfile
    public var path: String {
        switch self { case .enrollment(let operation): return operation.path
        case .workspaceProfile: return "/enrollment/v1/native/workspace-profile" }
    }
    public var method: String {
        switch self { case .enrollment(let operation): return operation.method
        case .workspaceProfile: return "POST" }
    }
    public var requiresAccount: Bool {
        if case .enrollment(.config) = self { return false }; return true
    }
}
public protocol NativePracticeAccountWire: Sendable {
    func send(_ operation: NativePracticeAccountRequest, token: String?, body: Data?, idempotencyKey: String?) async throws -> NativePracticeEnrollmentReply
}

/// Real pinned native HTTPS transport, with no renderer URL/header selector,
/// cookies, shared credentials, redirects, response cache or automatic replay.
public actor NativePracticeAccountHTTP: NativePracticeAccountWire {
    private let binding: NativePracticeAccountServiceBinding
    public init(binding: NativePracticeAccountServiceBinding) { self.binding = binding }
    public func send(_ operation: NativePracticeAccountRequest, token: String?, body: Data?, idempotencyKey: String?) async throws -> NativePracticeEnrollmentReply {
        guard body?.count ?? 0 <= 32_768,
              !operation.requiresAccount || token?.isEmpty == false,
              token == nil || (token!.utf8.count <= 8192 && token!.unicodeScalars.allSatisfy { $0.isASCII && $0.value >= 33 && $0.value <= 126 }),
              idempotencyKey == nil || (idempotencyKey!.utf8.count <= 255 && idempotencyKey!.unicodeScalars.allSatisfy { $0.isASCII && $0.value >= 33 && $0.value <= 126 }),
              let url = URL(string: binding.accountOrigin + operation.path) else { throw NativePracticeProfileError.invalidBinding }
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 15)
        request.httpMethod = operation.method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("enrollment.v1", forHTTPHeaderField: "X-Cosmas-Enrollment-Contract")
        request.setValue(binding.realm.workspaceOrigin.rawValue, forHTTPHeaderField: "Origin")
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let idempotencyKey { request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key") }
        if let body {
            request.httpBody = body
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(String(body.count), forHTTPHeaderField: "Content-Length")
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil; configuration.urlCache = nil
        configuration.timeoutIntervalForRequest = 15; configuration.timeoutIntervalForResource = 15
        let session = URLSession(configuration: configuration, delegate: RefusePracticeRedirect(), delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        try Task.checkCancellation()
        let (bytes, response) = try await session.bytes(for: request)
        guard let response = response as? HTTPURLResponse, response.url == url,
              (200...599).contains(response.statusCode), response.mimeType?.lowercased() == "application/json",
              response.value(forHTTPHeaderField: "Cache-Control")?.lowercased().split(separator: ",").map({ $0.trimmingCharacters(in: .whitespaces) }).contains("no-store") == true,
              response.value(forHTTPHeaderField: "X-Content-Type-Options")?.lowercased() == "nosniff",
              response.expectedContentLength <= 524_288 else { throw NativePracticeProfileError.invalidBinding }
        var data = Data()
        for try await byte in bytes {
            try Task.checkCancellation()
            guard data.count < 524_288 else { throw NativePracticeProfileError.invalidBinding }
            data.append(byte)
        }
        return try .init(status: response.statusCode, body: data)
    }
}
private final class RefusePracticeRedirect: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

/// Pure, build-owned public input. Loading it does not configure Clerk, query
/// Keychain, sign in, select an Org or change the existing beta runtime.
public struct NativePracticeGoogleConnection: Equatable, Sendable {
    public let clientID: String
    public let callbackURI: String
    public init(clientID: String, callbackURI: String) throws {
        guard !clientID.isEmpty, !callbackURI.isEmpty else { throw NativePracticeProfileError.invalidBinding }
        _ = try GoogleConnectionNavigation(clientID: clientID, callbackURI: callbackURI)
        self.clientID = clientID; self.callbackURI = callbackURI
    }
}

public struct NativePracticeBundleConfiguration: Sendable {
    public let binding: NativePracticeAccountServiceBinding
    public let googleConnection: NativePracticeGoogleConnection?
    public init(binding: NativePracticeAccountServiceBinding, googleConnection: NativePracticeGoogleConnection? = nil) throws {
        guard googleConnection == nil || googleConnection?.callbackURI == binding.accountOrigin + "/connections/google/callback" else {
            throw NativePracticeProfileError.invalidBinding
        }
        self.binding = binding; self.googleConnection = googleConnection
    }
    /// A native-admitted profile may use only this same exact account realm's
    /// separately pinned Google broker. Clinical/other-provider callbacks stay dark.
    public func registeredNavigation(for profile: NativePracticeProfile) throws -> CosmaneuraRecordNavigation {
        let realm = binding.realm
        let expected = try NativeClerkConfiguration(publishableKey: realm.publishableKey, frontendOrigin: realm.frontendOrigin,
            organizationID: profile.organizationID, bundleIdentifier: realm.bundleIdentifier, workspaceOrigin: realm.workspaceOrigin,
            profile: realm.profile, storageNamespace: realm.storageNamespace)
        guard profile.configuration == expected, profile.account.issuer == realm.frontendOrigin,
              profile.audience == binding.audience, binding.allowsAPI(profile.apiOrigin, practiceID: profile.id) else {
            throw NativePracticeProfileError.invalidBinding
        }
        return try CosmaneuraRecordNavigation(webOrigin: "", googleClientID: googleConnection?.clientID ?? "",
            googleCallbackURI: googleConnection?.callbackURI ?? "")
    }
    public static func load(bundle: Bundle = .main) throws -> NativePracticeBundleConfiguration? {
        guard let raw = bundle.object(forInfoDictionaryKey: "CosmasNativePracticeConnection") else { return nil }
        guard let value = raw as? [String: Any], let identifier = bundle.bundleIdentifier else {
            throw NativePracticeProfileError.invalidBinding
        }
        return try parse(value, bundleIdentifier: identifier)
    }
    static func parse(_ value: [String: Any], bundleIdentifier: String) throws -> NativePracticeBundleConfiguration? {
        guard Set(value.keys).isSuperset(of: ["enabled", "accountOrigin", "realm", "apiOrigins"]),
              Set(value.keys).isSubset(of: ["enabled", "accountOrigin", "realm", "apiOrigins", "registeredPracticeOrigins", "googleConnection"]),
              let enabled = value["enabled"] as? Bool else { throw NativePracticeProfileError.invalidBinding }
        guard enabled else { return nil }
        guard let accountOrigin = value["accountOrigin"] as? String, let origins = value["apiOrigins"] as? [String],
              Set(origins).count == origins.count, let realm = value["realm"] as? [String: Any],
              Set(realm.keys) == ["publishableKey", "frontendOrigin", "audience", "profile", "keychainNamespace"],
              let key = realm["publishableKey"] as? String, let frontend = realm["frontendOrigin"] as? String,
              let audience = realm["audience"] as? String,
              let profileName = realm["profile"] as? String,
              let profile = NativeIdentityProfile(rawValue: profileName),
              profile == .operationalStaging || profile == .operationalBeta,
              let namespace = realm["keychainNamespace"] as? String else { throw NativePracticeProfileError.invalidBinding }
        // Contract Origin must match this bundle (iPhone WebView vs Mac desktop auth helper).
        let workspaceOrigin: NativeWorkspaceOrigin
        if NativeWorkspaceOrigin.desktopApp.accepts(bundleIdentifier: bundleIdentifier, profile: profile) {
            workspaceOrigin = .desktopApp
        } else if NativeWorkspaceOrigin.appleWebView.accepts(bundleIdentifier: bundleIdentifier, profile: profile) {
            workspaceOrigin = .appleWebView
        } else { throw NativePracticeProfileError.invalidBinding }
        let configuration = try NativeClerkAccountConfiguration(publishableKey: key, frontendOrigin: frontend,
            bundleIdentifier: bundleIdentifier, workspaceOrigin: workspaceOrigin, profile: profile, storageNamespace: namespace)
        let policy: NativeRegisteredPracticeOriginPolicy
        if let raw = value["registeredPracticeOrigins"] {
            guard let name = raw as? String, let parsed = NativeRegisteredPracticeOriginPolicy(rawValue: name) else {
                throw NativePracticeProfileError.invalidBinding
            }
            policy = parsed
        } else { policy = .exact }
        let google: NativePracticeGoogleConnection?
        if let raw = value["googleConnection"] {
            guard let pair = raw as? [String: Any], Set(pair.keys) == ["clientID", "callbackURI"],
                  let client = pair["clientID"] as? String, let callback = pair["callbackURI"] as? String else {
                throw NativePracticeProfileError.invalidBinding
            }
            google = try .init(clientID: client, callbackURI: callback)
        } else { google = nil }
        return try .init(binding: .init(accountOrigin: accountOrigin, realm: configuration,
            audience: audience, allowedAPIOrigins: Set(origins), registeredPracticeOrigins: policy), googleConnection: google)
    }
}
