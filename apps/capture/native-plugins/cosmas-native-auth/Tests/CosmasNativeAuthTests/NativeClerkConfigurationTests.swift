import Foundation
import Testing
@testable import CosmasNativeAuth

private func configuration() throws -> NativeClerkConfiguration {
    let key = "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString()
    return try NativeClerkConfiguration(publishableKey: key,
        frontendOrigin: "https://invented.clerk.accounts.dev", organizationID: "org_one",
        bundleIdentifier: "com.cosmasos.synthetic.w8t")
}

@Suite struct NativeClerkConfigurationTests {
    @Test func sharedStagingIdentityKeepsBetaCallbacksAndIsolatesCredentials() throws {
        let key = "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString()
        for origin in [NativeWorkspaceOrigin.appleWebView, .desktopApp] {
            let bundle = origin == .appleWebView ? "com.cosmasos.beta.ios" : "com.cosmasos.beta.desktop.auth"
            let config = try NativeClerkConfiguration(publishableKey: key,
                frontendOrigin: "https://invented.clerk.accounts.dev", organizationID: "org_beta",
                bundleIdentifier: bundle, workspaceOrigin: origin, profile: .operationalStaging)
            #expect(config.callbackURL == bundle + "://callback")
            #expect(config.keychainService == bundle + ".clerk.invented.clerk.accounts.dev")
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: key,
                    frontendOrigin: config.frontendOrigin, organizationID: "org_beta",
                    bundleIdentifier: bundle, workspaceOrigin: origin, profile: .operationalBeta)
            }
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: "pk_test_" + Data("clerk.example.invalid$".utf8).base64EncodedString(),
                    frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
                    bundleIdentifier: bundle, workspaceOrigin: origin, profile: .operationalStaging)
            }
        }
    }

    @Test func operationalIdentityRequiresProductionKeyAndSeparateBundle() throws {
        let key = "pk_live_" + Data("clerk.example.invalid$".utf8).base64EncodedString()
        let config = try NativeClerkConfiguration(publishableKey: key,
            frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        #expect(config.callbackURL == "com.cosmasos.beta.ios://callback")
        #expect(config.profile == .operationalBeta)
        for bundle in ["com.cosmasos.synthetic.w60", "com.cosmasos.beta.desktop.auth", "com.cosmasos.beta.ios.extra"] {
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: key,
                    frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
                    bundleIdentifier: bundle, profile: .operationalBeta)
            }
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(publishableKey: key,
                frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios")
        }
        let desktop = try NativeClerkConfiguration(publishableKey: key,
            frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.desktop.auth", workspaceOrigin: .desktopApp, profile: .operationalBeta)
        var request = URLRequest(url: URL(string: "https://unrelated.example.invalid/v1/client")!)
        #expect(throws: NativeAuthError.unavailable) { try desktop.prepareFrontendRequest(&request) }
    }

    @Test func exactFrontendRequestPreservesNativeCredentialsWithoutBrowserOrigin() throws {
        let config = try configuration()
        var request = URLRequest(url: URL(string: config.frontendOrigin + "/v1/client/sessions")!)
        request.setValue("synthetic-native-client-token", forHTTPHeaderField: "Authorization")
        try config.prepareFrontendRequest(&request)
        #expect(request.value(forHTTPHeaderField: "Origin") == nil)
        #expect(request.value(forHTTPHeaderField: "Authorization") == "synthetic-native-client-token")
        #expect(config.callbackURL == "com.cosmasos.synthetic.w8t://callback")
    }

    @Test(arguments: [
        "http://invented.clerk.accounts.dev/v1/client", "https://other.clerk.accounts.dev/v1/client",
        "https://invented.clerk.accounts.dev.evil.invalid/v1/client",
        "https://user@invented.clerk.accounts.dev/v1/client",
        "https://invented.clerk.accounts.dev:443/v1/client",
        "https://invented.clerk.accounts.dev/v1/client#callback",
    ])
    func nativeCredentialsCannotBeSentToAnotherFrontend(_ url: String) throws {
        var request = URLRequest(url: URL(string: url)!)
        #expect(throws: NativeAuthError.unavailable) { try configuration().prepareFrontendRequest(&request) }
        #expect(request.value(forHTTPHeaderField: "Origin") == nil)
    }

    @Test(arguments: ["https://different.invalid", "capacitor://localhost", "app://cosmas"])
    func anyBrowserOriginIsRejectedByTheNativeRequestBoundary(_ origin: String) throws {
        var request = URLRequest(url: URL(string: "https://invented.clerk.accounts.dev/v1/client")!)
        request.setValue(origin, forHTTPHeaderField: "Origin")
        #expect(throws: NativeAuthError.unavailable) { try configuration().prepareFrontendRequest(&request) }
    }

    @Test(arguments: ["pk_live_a", "pk_test_invalid", "pk_test_" + Data("other.clerk.accounts.dev$".utf8).base64EncodedString()])
    func nonTestOrMismatchedKeyCannotConfigureSDK(_ key: String) {
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(publishableKey: key,
                frontendOrigin: "https://invented.clerk.accounts.dev", organizationID: "org_one",
                bundleIdentifier: "com.cosmasos.synthetic.w8t")
        }
    }
}
