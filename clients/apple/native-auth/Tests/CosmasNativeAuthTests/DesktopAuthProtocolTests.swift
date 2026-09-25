import Foundation
import Testing
@testable import CosmasNativeAuth

private let requestID = "00000000-0000-4000-8000-000000000001"

@Suite struct DesktopAuthProtocolTests {
    @Test func acceptsOnlyClosedKnownRequests() throws {
        for method in ["getState", "signIn", "signOut"] {
            let request = try DesktopAuthRequest(frame: Data("{\"id\":\"\(requestID)\",\"method\":\"\(method)\"}".utf8))
            #expect(request.method.rawValue == method)
            #expect(request.revision == nil)
        }
        let request = try DesktopAuthRequest(frame: Data("{\"id\":\"\(requestID)\",\"method\":\"getToken\",\"revision\":\"\(requestID)\"}".utf8))
        #expect(request.revision == requestID)
    }

    @Test(arguments: [
        "{}", "[]", "null", "{\"id\":\"invalid\",\"method\":\"getState\"}",
        "{\"id\":\"ID\",\"method\":\"openURL\"}",
        "{\"id\":\"ID\",\"method\":\"signIn\",\"token\":\"forged\"}",
        "{\"id\":\"ID\",\"method\":\"getToken\"}",
        "{\"id\":\"ID\",\"method\":\"getToken\",\"revision\":false}",
        "{\"id\":\"ID\",\"method\":\"getToken\",\"revision\":\"ID\",\"extra\":true}",
    ])
    func rejectsUnknownMalformedOrCredentialInput(_ value: String) {
        #expect(throws: NativeAuthError.unavailable) {
            try DesktopAuthRequest(frame: Data(value.replacingOccurrences(of: "ID", with: requestID).utf8))
        }
    }

    @Test func splitFramesStayBoundedAndDoNotDropPartialCommands() throws {
        var frames = DesktopAuthFrames()
        let line = "{\"id\":\"\(requestID)\",\"method\":\"getState\"}"
        for byte in line.utf8 { #expect(try frames.append(byte) == nil) }
        #expect(frames.hasPartialFrame)
        #expect(try frames.append(10)?.id == requestID)
        #expect(!frames.hasPartialFrame)
        for _ in 0..<1024 { #expect(try frames.append(65) == nil) }
        #expect(throws: NativeAuthError.unavailable) { try frames.append(65) }
    }

    @Test func desktopOriginIsBoundToItsOwnHelperNamespace() throws {
        let key = "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString()
        let desktop = try NativeClerkConfiguration(publishableKey: key,
            frontendOrigin: "https://invented.clerk.accounts.dev", organizationID: "org_one",
            bundleIdentifier: "com.cosmasos.synthetic.desktop.auth.w8u", workspaceOrigin: .desktopApp)
        var request = URLRequest(url: URL(string: desktop.frontendOrigin + "/v1/client")!)
        try desktop.prepareFrontendRequest(&request)
        #expect(request.value(forHTTPHeaderField: "Origin") == nil)
        #expect(desktop.callbackURL == "com.cosmasos.synthetic.desktop.auth.w8u://callback")
        #expect(!NativeWorkspaceOrigin.appleWebView.accepts(bundleIdentifier: desktop.bundleIdentifier))
        #expect(!NativeWorkspaceOrigin.desktopApp.accepts(bundleIdentifier: "com.cosmasos.synthetic.w8t"))
        #expect(!NativeWorkspaceOrigin.desktopApp.accepts(bundleIdentifier: "com.cosmasos.production.desktop.auth.w8u"))
        request.setValue("capacitor://localhost", forHTTPHeaderField: "Origin")
        #expect(throws: NativeAuthError.unavailable) { try desktop.prepareFrontendRequest(&request) }
    }
}
