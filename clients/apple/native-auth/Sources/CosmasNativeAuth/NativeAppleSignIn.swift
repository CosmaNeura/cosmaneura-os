import Foundation
#if canImport(AuthenticationServices)
import AuthenticationServices
#endif

/// Decode the public environment directly; absence, wrong types and errors stay dark.
public enum NativeAppleSignIn {
    /// Reuse the existing profile/host/identity validator for the public read.
    public static func configuration(values: [String: Any], browserKey: String?, bundleIdentifier: String?) throws -> NativeClerkConfiguration {
        guard let key = values["publishableKey"] as? String, browserKey == key,
              let origin = values["frontendOrigin"] as? String,
              let org = values["organizationId"] as? String,
              let profile = NativeIdentityProfile(rawValue: values["profile"] as? String ?? ""),
              let bundleIdentifier else { throw NativeAuthError.unavailable }
        return try NativeClerkConfiguration(publishableKey: key, frontendOrigin: origin,
            organizationID: org, bundleIdentifier: bundleIdentifier, profile: profile)
    }

    public static func enabled(environment: Data, response: URLResponse, requestedURL: URL) -> Bool {
        response.url == requestedURL && (response as? HTTPURLResponse)?.statusCode == 200
            && enabled(environment: environment)
    }

    public static func failureStatus(_ error: Error) -> String {
        #if canImport(AuthenticationServices)
        let native = error as NSError
        if native.domain == ASAuthorizationError.errorDomain && native.code == ASAuthorizationError.canceled.rawValue {
            return "canceled"
        }
        #endif
        return "error"
    }
    public static func enabled(environment: Data) -> Bool {
        struct Environment: Decodable {
            struct Settings: Decodable {
                struct Social: Decodable { let enabled: Bool? }
                let social: [String: Social]?
            }
            let user_settings: Settings?
        }
        return (try? JSONDecoder().decode(Environment.self, from: environment))?
            .user_settings?.social?["oauth_apple"]?.enabled == true
    }
}

/// Owns one native gesture through Apple authorization and browser completion.
public struct NativeAppleButtonState {
    public private(set) var id: String?
    public private(set) var busy = false
    private var requestID: String?
    public init() {}

    public mutating func mount(_ id: String) -> Bool {
        guard !id.isEmpty, requestID == nil || self.id == id, !busy || self.id == id else { return false }
        self.id = id
        return true
    }
    public mutating func tap() -> String? {
        guard let id, !busy else { return nil }
        busy = true
        return id
    }
    public mutating func beginCredential(_ id: String) -> Bool {
        guard busy, self.id == id, requestID == nil else { return false }
        requestID = id
        return true
    }
    public mutating func endCredential(_ id: String) {
        guard requestID == id else { return }
        requestID = nil
        if self.id != id { busy = false }
    }
    public mutating func finish(_ id: String) {
        guard self.id == id, requestID == nil else { return }
        busy = false
    }
    public mutating func unmount() {
        id = nil
        if requestID == nil { busy = false }
    }
}

#if canImport(ClerkKit) && os(iOS)
import ClerkKit

extension NativeAppleSignIn {
    /// Only obtains a credential. The existing WebView Clerk client owns sign-in;
    /// no second SDK client, native sign-up attempt or Keychain credential is created.
    @MainActor public static func identityToken() async throws -> String {
        try await Auth.requestAppleIdentityToken()
    }
}
#endif
