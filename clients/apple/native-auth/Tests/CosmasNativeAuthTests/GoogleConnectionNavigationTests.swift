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
