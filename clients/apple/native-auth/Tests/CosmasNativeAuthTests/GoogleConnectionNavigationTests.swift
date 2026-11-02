import Foundation
import Testing
@testable import CosmasNativeAuth

@Test func googleCalendarNavigationKeepsExactClientCallbackAndReadOnlyScope() throws {
    let callback = "https://api.example.invalid/connections/google/callback"
    let policy = try GoogleConnectionNavigation(clientID: "invented.apps.googleusercontent.com", callbackURI: callback)
    let base = "openid email https://www.googleapis.com/auth/gmail.metadata"
    func link(_ scope: String, callbackURI: String? = nil) -> String {
        var url = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
        let fields = ["client_id": "invented.apps.googleusercontent.com", "redirect_uri": callbackURI ?? callback,
                      "response_type": "code", "scope": scope, "access_type": "offline",
                      "prompt": "consent select_account", "include_granted_scopes": "false",
                      "code_challenge_method": "S256", "state": String(repeating: "s", count: 43),
                      "code_challenge": String(repeating: "c", count: 43)]
        url.queryItems = fields.map { URLQueryItem(name: $0.key, value: $0.value) }
        return url.url!.absoluteString
    }
    #expect(policy.accepts(link(base)))
    #expect(policy.accepts(link(base + " https://www.googleapis.com/auth/calendar.events.readonly")))
    #expect(!policy.accepts(link(base + " https://www.googleapis.com/auth/calendar.events")))
    #expect(!policy.accepts(link(base + " https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/gmail.send")))
    #expect(!policy.accepts(link(base, callbackURI: "https://other.example.invalid/connections/google/callback")))
}

private let fullMailConsentScope = "openid email https://www.googleapis.com/auth/gmail.metadata https://www.googleapis.com/auth/calendar.events.readonly https://www.googleapis.com/auth/gmail.readonly"

private func fullMailConsentLink(_ scope: String = fullMailConsentScope,
                                 clientID: String = "invented.apps.googleusercontent.com",
                                 callbackURI: String = "https://api.example.invalid/connections/google/callback") -> String {
    var url = URLComponents(string: "https://accounts.google.com/o/oauth2/v2/auth")!
    let fields = ["client_id": clientID, "redirect_uri": callbackURI, "response_type": "code", "scope": scope,
                  "access_type": "offline", "prompt": "consent select_account", "include_granted_scopes": "false",
                  "code_challenge_method": "S256", "state": String(repeating: "s", count: 43),
                  "code_challenge": String(repeating: "c", count: 43)]
    url.queryItems = fields.map { URLQueryItem(name: $0.key, value: $0.value) }
    return url.url!.absoluteString
}

@Test func googleFullMailNavigationKeepsSeparateExactReadOnlyConsent() throws {
    let policy = try GoogleConnectionNavigation(clientID: "invented.apps.googleusercontent.com",
        callbackURI: "https://api.example.invalid/connections/google/callback")
    // This is the existing backend's separate start_full_mail tuple, not an
    // automatic upgrade of its normal metadata/calendar sign-in request.
    #expect(policy.accepts(fullMailConsentLink()))
}

@Test func googleFullMailNavigationRejectsWritesAndConsentFieldEscalation() throws {
    let policy = try GoogleConnectionNavigation(clientID: "invented.apps.googleusercontent.com",
        callbackURI: "https://api.example.invalid/connections/google/callback")
    for scope in [fullMailConsentScope.replacingOccurrences(of: "gmail.readonly", with: "gmail.modify"),
                  fullMailConsentScope + " https://www.googleapis.com/auth/gmail.send",
                  fullMailConsentScope.replacingOccurrences(of: "calendar.events.readonly", with: "calendar.events"),
                  fullMailConsentScope + " https://www.googleapis.com/auth/gmail.readonly",
                  fullMailConsentScope.replacingOccurrences(of: "openid email", with: "email openid")] {
        #expect(!policy.accepts(fullMailConsentLink(scope)))
    }
    #expect(!policy.accepts(fullMailConsentLink(clientID: "other.apps.googleusercontent.com")))
    #expect(!policy.accepts(fullMailConsentLink(callbackURI: "https://other.example.invalid/connections/google/callback")))
    #expect(!policy.accepts(fullMailConsentLink() + "&scope=duplicate"))
    #expect(!policy.accepts(fullMailConsentLink() + "&login_hint=synthetic%40example.invalid"))
}
