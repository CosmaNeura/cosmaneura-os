import Foundation
import Testing
@testable import CosmasNativeAuth

@Test func microsoftWorkSchoolAuthorityPreservesExactNativeConsent() throws {
    let tenant = "11111111-1111-4111-8111-111111111111"
    let client = "22222222-2222-4222-8222-222222222222"
    let callback = "https://api.example.invalid/connections/microsoft/callback"
    let scopes = "offline_access User.Read Mail.Read Calendars.Read"
    func link(_ authority: String, scope: String? = nil, callbackURI: String? = nil) -> String {
        var url = URLComponents(string: "https://login.microsoftonline.com/\(authority)/oauth2/v2.0/authorize")!
        let fields = ["client_id": client, "redirect_uri": callbackURI ?? callback,
                      "response_type": "code", "response_mode": "query", "scope": scope ?? scopes,
                      "prompt": "select_account", "code_challenge_method": "S256",
                      "state": String(repeating: "s", count: 43),
                      "code_challenge": String(repeating: "c", count: 43)]
        url.queryItems = fields.map { URLQueryItem(name: $0.key, value: $0.value) }
        return url.url!.absoluteString
    }
    #expect(!(try MicrosoftConnectionNavigation()).enabled)
    let fixed = try MicrosoftConnectionNavigation(tenantID: tenant, clientID: client, callbackURI: callback)
    let work = try MicrosoftConnectionNavigation(tenantID: "organizations", clientID: client, callbackURI: callback)
    #expect(fixed.accepts(link(tenant)))
    #expect(work.accepts(link("organizations")))
    #expect(!fixed.accepts(link("organizations")))
    #expect(!work.accepts(link(tenant)))
    for authority in ["common", "consumers", "Organizations", " organizations", "organizations/",
                      "https://login.microsoftonline.com/organizations"] {
        #expect(throws: (any Error).self) {
            try MicrosoftConnectionNavigation(tenantID: authority, clientID: client, callbackURI: callback)
        }
    }
    for bad in [link("common"), link("consumers"), link("organizations", scope: scopes + " Mail.Send"),
                link("organizations", callbackURI: "https://other.example.invalid/connections/microsoft/callback"),
                link("organizations") + "&state=duplicate", link("organizations") + "#fragment",
                link("organizations").replacingOccurrences(of: "login.microsoftonline.com", with: "login.microsoftonline.com.evil.invalid")] {
        #expect(!work.accepts(bad))
    }
}
