import Foundation
import Testing
@testable import CosmasNativeAuth
#if canImport(AuthenticationServices)
import AuthenticationServices
#endif

// Evaluate mutating state operations before Swift Testing expands its assertion macro.
private func expectAppleState(_ value: Bool) { #expect(value) }

@Suite struct NativeAppleSignInTests {
    @Test func gestureOwnsAuthorizationUntilBrowserCompletionAndAllowsRetry() {
        var state = NativeAppleButtonState()
        expectAppleState(state.tap() == nil)
        expectAppleState(!state.mount(""))
        expectAppleState(state.mount("first"))
        expectAppleState(!state.beginCredential("first")) // No native gesture.
        expectAppleState(state.tap() == "first")
        expectAppleState(state.busy && state.tap() == nil)
        expectAppleState(!state.beginCredential("stale"))
        expectAppleState(state.beginCredential("first"))
        expectAppleState(!state.beginCredential("first"))
        state.finish("first")
        expectAppleState(state.busy) // Cannot unlock while the Apple sheet is pending.
        state.endCredential("stale")
        expectAppleState(!state.beginCredential("first"))
        expectAppleState(state.mount("first")) // Repositioning keeps gesture ownership.
        expectAppleState(!state.mount("second"))
        state.endCredential("first")
        expectAppleState(state.busy) // Browser Clerk still owns the submitted token.
        expectAppleState(!state.mount("second"))
        state.finish("stale")
        expectAppleState(state.busy)
        state.finish("first")
        expectAppleState(!state.busy)
        expectAppleState(state.tap() == "first")
        expectAppleState(state.beginCredential("first"))
        state.endCredential("first"); state.finish("first")
        expectAppleState(!state.busy)
    }

    @Test func replacedScreenCannotOverlapAppleAuthorizationOrUnlockAnotherGesture() {
        var state = NativeAppleButtonState()
        expectAppleState(state.mount("first")); expectAppleState(state.tap() == "first")
        expectAppleState(state.beginCredential("first"))
        state.unmount()
        expectAppleState(state.id == nil && state.tap() == nil)
        expectAppleState(!state.mount("second"))
        state.endCredential("first")
        expectAppleState(state.mount("second")); expectAppleState(state.tap() == "second")
        state.finish("first")
        expectAppleState(state.busy)
        state.unmount()
        expectAppleState(!state.busy && state.id == nil)
    }
    @Test func publicReadIsBoundToTheValidatedBundleRealmAndBrowserKey() throws {
        let key = "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString()
        let values: [String: Any] = ["publishableKey": key, "frontendOrigin": "https://invented.clerk.accounts.dev",
                                    "organizationId": "org_synthetic", "profile": "synthetic"]
        let configuration = try NativeAppleSignIn.configuration(values: values, browserKey: key, bundleIdentifier: "com.cosmasos.synthetic")
        #expect(configuration.frontendOrigin == "https://invented.clerk.accounts.dev")
        for browserKey in [nil, "", "pk_test_other"] as [String?] {
            #expect(throws: NativeAuthError.unavailable) {
                try NativeAppleSignIn.configuration(values: values, browserKey: browserKey, bundleIdentifier: "com.cosmasos.synthetic")
            }
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeAppleSignIn.configuration(values: values, browserKey: key, bundleIdentifier: nil)
        }
        for field in ["publishableKey", "frontendOrigin", "organizationId", "profile"] {
            var missing = values; missing.removeValue(forKey: field)
            #expect(throws: NativeAuthError.unavailable) {
                try NativeAppleSignIn.configuration(values: missing, browserKey: key, bundleIdentifier: "com.cosmasos.synthetic")
            }
        }
        var changed = values; changed["frontendOrigin"] = "https://other.clerk.accounts.dev"
        #expect(throws: NativeAuthError.unavailable) {
            try NativeAppleSignIn.configuration(values: changed, browserKey: key, bundleIdentifier: "com.cosmasos.synthetic")
        }
    }

    @Test func onlyTheSuccessfulRequestedEnvironmentCanEnableApple() {
        let url = URL(string: "https://invented.clerk.accounts.dev/v1/environment")!
        let data = Data("{\"user_settings\":{\"social\":{\"oauth_apple\":{\"enabled\":true}}}}".utf8)
        for code in [200, 302, 401, 500] {
            let response = HTTPURLResponse(url: url, statusCode: code, httpVersion: nil, headerFields: nil)!
            #expect(NativeAppleSignIn.enabled(environment: data, response: response, requestedURL: url) == (code == 200))
        }
        let changed = HTTPURLResponse(url: URL(string: "https://other.clerk.accounts.dev/v1/environment")!, statusCode: 200,
                                      httpVersion: nil, headerFields: nil)!
        #expect(!NativeAppleSignIn.enabled(environment: data, response: changed, requestedURL: url))
        let response = URLResponse(url: url, mimeType: "application/json", expectedContentLength: data.count, textEncodingName: nil)
        #expect(!NativeAppleSignIn.enabled(environment: data, response: response, requestedURL: url))
    }
    @Test func environmentRequiresAnExplicitAppleBoolean() {
        for json in ["{}", "{\"user_settings\":{}}", "{\"user_settings\":{\"social\":{}}}",
                     "{\"user_settings\":{\"social\":{\"oauth_google\":{\"enabled\":true}}}}",
                     "{\"user_settings\":{\"social\":{\"oauth_apple\":{\"enabled\":false}}}}",
                     "{\"user_settings\":{\"social\":{\"oauth_apple\":{\"enabled\":\"true\"}}}}",
                     "{\"user_settings\":{\"social\":{\"oauth_apple\":{\"enabled\":1}}}}", "broken"] {
            #expect(!NativeAppleSignIn.enabled(environment: Data(json.utf8)))
        }
        #expect(NativeAppleSignIn.enabled(environment: Data(
            "{\"user_settings\":{\"social\":{\"oauth_apple\":{\"enabled\":true}}}}".utf8)))
    }

    @Test func onlyAppleUserCancellationIsSilent() {
        #if canImport(AuthenticationServices)
        #expect(NativeAppleSignIn.failureStatus(ASAuthorizationError(.canceled)) == "canceled")
        #expect(NativeAppleSignIn.failureStatus(ASAuthorizationError(.failed)) == "error")
        #expect(NativeAppleSignIn.failureStatus(NSError(domain: "invented.error", code: ASAuthorizationError.canceled.rawValue)) == "error")
        #endif
        #expect(NativeAppleSignIn.failureStatus(NSError(domain: "invented.error", code: 0)) == "error")
    }
}
