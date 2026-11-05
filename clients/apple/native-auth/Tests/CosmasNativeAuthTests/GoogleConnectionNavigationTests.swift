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

private func practiceGoogleOptions(namespace: String = String(repeating: "b", count: 64)) -> [String: Any] {
    let host = "invented.clerk.accounts.dev"
    let account = NativePracticeAccountServiceBinding.stagingAccountOrigin
    return ["enabled": true, "accountOrigin": account,
        "realm": ["publishableKey": "pk_test_" + Data((host + "$").utf8).base64EncodedString(),
            "frontendOrigin": "https://" + host, "audience": "", "profile": "operational-staging-v1",
            "keychainNamespace": namespace], "apiOrigins": ["https://api.a.staging.cosmas.ai"]]
}

@Test func nativePracticeGoogleConfigurationKeepsOmissionDarkAndRequiresItsExactAccountCallback() throws {
    var value = practiceGoogleOptions()
    let omitted = try #require(try NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.ios"))
    #expect(omitted.googleConnection == nil)
    let callback = NativePracticeAccountServiceBinding.stagingAccountOrigin + "/connections/google/callback"
    let pair = ["clientID": "invented-practice.apps.googleusercontent.com", "callbackURI": callback]
    value["googleConnection"] = pair
    let pinned = try #require(try NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.ios"))
    #expect(pinned.googleConnection?.clientID == pair["clientID"])
    #expect(pinned.googleConnection?.callbackURI == pair["callbackURI"])
    let invalidPairs: [[String: Any]] = [[:], ["clientID": pair["clientID"]!],
        ["clientID": "", "callbackURI": pair["callbackURI"]!],
        ["clientID": pair["clientID"]!, "callbackURI": "https://beta.example.invalid/connections/google/callback"],
        ["clientID": pair["clientID"]!, "callbackURI": pair["callbackURI"]! + "?next=other"],
        ["clientID": pair["clientID"]!, "callbackURI": pair["callbackURI"]!, "scope": "gmail.send"]]
    for invalid in invalidPairs {
        value["googleConnection"] = invalid
        #expect((try? NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.ios")) == nil)
    }
}

@MainActor private final class GooglePolicyProfileService: NativePracticeAccountService {
    let binding: NativePracticeAccountServiceBinding
    init(_ binding: NativePracticeAccountServiceBinding) { self.binding = binding }
    func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt {
        .init(expectation: expectation, expiresAt: Date().addingTimeInterval(30))
    }
}

@Test @MainActor func nativeRegisteredGoogleNavigationRequiresThePinnedRealmAndKeepsSeparateReadOnlyConsent() async throws {
    var value = practiceGoogleOptions()
    let omitted = try #require(try NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.ios"))
    let account = try NativeAccountIdentity(issuer: omitted.binding.realm.frontendOrigin, userID: "user_invented", sessionID: "sess_invented")
    let expectation = try NativePracticeConnectionExpectation(selectionID: UUID(), nonce: UUID(), account: account,
        organizationID: "org_invented", boxID: UUID(), apiOrigin: "https://api.a.staging.cosmas.ai")
    let service = GooglePolicyProfileService(omitted.binding)
    let resolver = try NativePracticeProfileResolver(binding: omitted.binding, service: service, currentAccount: { account })
    let profile = try await resolver.resolve(expectation)
    #expect(try !omitted.registeredNavigation(for: profile).google.enabled)
    let callback = NativePracticeAccountServiceBinding.stagingAccountOrigin + "/connections/google/callback"
    value["googleConnection"] = ["clientID": "invented-practice.apps.googleusercontent.com", "callbackURI": callback]
    let pinned = try #require(try NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.ios"))
    let policy = try pinned.registeredNavigation(for: profile)
    #expect(policy.origin == nil && !policy.scheduling.enabled && !policy.microsoft.enabled && policy.google.enabled)
    let client = "invented-practice.apps.googleusercontent.com"
    #expect(policy.google.accepts(fullMailConsentLink("openid email https://www.googleapis.com/auth/gmail.metadata", clientID: client, callbackURI: callback)))
    #expect(policy.google.accepts(fullMailConsentLink(clientID: client, callbackURI: callback)))
    #expect(!policy.google.accepts(fullMailConsentLink(fullMailConsentScope + " https://www.googleapis.com/auth/gmail.send", clientID: client, callbackURI: callback)))
    #expect(!policy.google.accepts(fullMailConsentLink(clientID: "invented.apps.googleusercontent.com", callbackURI: callback)))
    #expect(!policy.google.accepts(fullMailConsentLink(clientID: client, callbackURI: "https://beta.example.invalid/connections/google/callback")))
    var changed = practiceGoogleOptions(namespace: String(repeating: "c", count: 64)); changed["googleConnection"] = value["googleConnection"]
    let otherRealm = try #require(try NativePracticeBundleConfiguration.parse(changed, bundleIdentifier: "com.cosmasos.beta.ios"))
    #expect(throws: NativePracticeProfileError.invalidBinding) { try otherRealm.registeredNavigation(for: profile) }
}
