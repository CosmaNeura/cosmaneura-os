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
        let host = "clerk.cosmas.ai"
        let key = "pk_live_" + Data((host + "$").utf8).base64EncodedString()
        let config = try NativeClerkConfiguration(publishableKey: key,
            frontendOrigin: "https://" + host, organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        #expect(config.callbackURL == "com.cosmasos.beta.ios://callback")
        #expect(config.profile == .operationalBeta)
        #expect(config.frontendOrigin == "https://clerk.cosmas.ai")
        for bundle in ["com.cosmasos.synthetic.w60", "com.cosmasos.beta.desktop.auth", "com.cosmasos.beta.ios.extra"] {
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: key,
                    frontendOrigin: "https://" + host, organizationID: "org_beta",
                    bundleIdentifier: bundle, profile: .operationalBeta)
            }
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(publishableKey: key,
                frontendOrigin: "https://" + host, organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios")
        }
        // Production Infos reject any non-pinned live Clerk frontend.
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: "pk_live_" + Data("clerk.example.invalid$".utf8).base64EncodedString(),
                frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        }
        let desktop = try NativeClerkConfiguration(publishableKey: key,
            frontendOrigin: "https://" + host, organizationID: "org_beta",
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

    @Test func everyExistingProfileResolvesTheSameExactClerkHostsAsBefore() throws {
        // Byte-identical host policy for profiles that already shipped.
        #expect(NativeIdentityProfile.synthetic.allowedClerkHosts == [])
        #expect(NativeIdentityProfile.operationalStaging.allowedClerkHosts == [])
        #expect(NativeIdentityProfile.operationalBeta.allowedClerkHosts == [
            "clerk.cosmas.ai", "clerk.staging.cosmas.ai"])
        #expect(NativeIdentityProfile.simulatorStaging.allowedClerkHosts == ["clerk.staging.cosmas.ai"])
        #expect(NativeIdentityProfile.operationalProduction.allowedClerkHosts == ["clerk.beta.cosmas.ai"])

        let accountsDev = "invented.clerk.accounts.dev"
        let accountsKey = "pk_test_" + Data((accountsDev + "$").utf8).base64EncodedString()
        let synthetic = try NativeClerkConfiguration(publishableKey: accountsKey,
            frontendOrigin: "https://" + accountsDev, organizationID: "org_one",
            bundleIdentifier: "com.cosmasos.synthetic.w8t", profile: .synthetic)
        #expect(synthetic.frontendOrigin == "https://invented.clerk.accounts.dev")
        #expect(synthetic.profile == .synthetic)

        let staging = try NativeClerkConfiguration(publishableKey: accountsKey,
            frontendOrigin: "https://" + accountsDev, organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalStaging)
        #expect(staging.frontendOrigin == "https://invented.clerk.accounts.dev")
        #expect(staging.profile == .operationalStaging)

        let liveHost = "clerk.cosmas.ai"
        let liveKey = "pk_live_" + Data((liveHost + "$").utf8).base64EncodedString()
        let live = try NativeClerkConfiguration(publishableKey: liveKey,
            frontendOrigin: "https://" + liveHost, organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        #expect(live.frontendOrigin == "https://clerk.cosmas.ai")
        #expect(live.profile == .operationalBeta)

        let simulatorHost = "clerk.staging.cosmas.ai"
        let simulatorKey = "pk_live_" + Data((simulatorHost + "$").utf8).base64EncodedString()
        let simulator = try NativeClerkConfiguration(publishableKey: simulatorKey,
            frontendOrigin: "https://" + simulatorHost, organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.synthetic", profile: .simulatorStaging)
        #expect(simulator.frontendOrigin == "https://clerk.staging.cosmas.ai")
        #expect(simulator.profile == .simulatorStaging)
    }

    @Test func productionProfileAcceptsBetaClerkAndRejectsStagingAndLiveHosts() throws {
        let betaHost = "clerk.beta.cosmas.ai"
        let betaKey = "pk_live_" + Data((betaHost + "$").utf8).base64EncodedString()
        let config = try NativeClerkConfiguration(publishableKey: betaKey,
            frontendOrigin: "https://" + betaHost, organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalProduction)
        #expect(config.frontendOrigin == "https://clerk.beta.cosmas.ai")
        #expect(config.profile == .operationalProduction)
        #expect(config.callbackURL == "com.cosmasos.beta.ios://callback")
        #expect(NativeIdentityProfile.operationalProduction.requiresLivePublishableKey)

        for host in ["clerk.cosmas.ai", "clerk.staging.cosmas.ai", "invented.clerk.accounts.dev",
                     "clerk.example.invalid", "preview.clerk.beta.cosmas.ai"] {
            let keyPrefix = host.hasSuffix(".clerk.accounts.dev") ? "pk_test_" : "pk_live_"
            let key = keyPrefix + Data((host + "$").utf8).base64EncodedString()
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: key,
                    frontendOrigin: "https://" + host, organizationID: "org_beta",
                    bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalProduction)
            }
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: "pk_test_" + Data((betaHost + "$").utf8).base64EncodedString(),
                frontendOrigin: "https://" + betaHost, organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalProduction)
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(publishableKey: betaKey,
                frontendOrigin: "http://" + betaHost, organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalProduction)
        }
    }

    @Test func stagingAndLiveProfilesRejectProductionBetaClerkHost() throws {
        let betaHost = "clerk.beta.cosmas.ai"
        let betaKey = "pk_live_" + Data((betaHost + "$").utf8).base64EncodedString()
        for profile in [NativeIdentityProfile.operationalStaging, .operationalBeta, .simulatorStaging, .synthetic] {
            let bundle = profile == .simulatorStaging || profile == .synthetic
                ? "com.cosmasos.synthetic" : "com.cosmasos.beta.ios"
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: betaKey,
                    frontendOrigin: "https://" + betaHost, organizationID: "org_beta",
                    bundleIdentifier: bundle, profile: profile)
            }
        }
        let liveHost = "clerk.cosmas.ai"
        let liveKey = "pk_live_" + Data((liveHost + "$").utf8).base64EncodedString()
        for profile in [NativeIdentityProfile.operationalStaging, .simulatorStaging, .synthetic, .operationalProduction] {
            let bundle = profile == .simulatorStaging || profile == .synthetic
                ? "com.cosmasos.synthetic" : "com.cosmasos.beta.ios"
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: liveKey,
                    frontendOrigin: "https://" + liveHost, organizationID: "org_beta",
                    bundleIdentifier: bundle, profile: profile)
            }
        }
        let stagingHost = "clerk.staging.cosmas.ai"
        let stagingKey = "pk_live_" + Data((stagingHost + "$").utf8).base64EncodedString()
        for profile in [NativeIdentityProfile.operationalProduction, .operationalStaging, .synthetic] {
            let bundle = profile == .synthetic ? "com.cosmasos.synthetic" : "com.cosmasos.beta.ios"
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(publishableKey: stagingKey,
                    frontendOrigin: "https://" + stagingHost, organizationID: "org_beta",
                    bundleIdentifier: bundle, profile: profile)
            }
        }
        // operationalBeta admits clerk.staging.cosmas.ai so rebuilds keep the
        // identity already shipped to TestFlight / synthetic Mac users.
        let betaStaging = try NativeClerkConfiguration(publishableKey: stagingKey,
            frontendOrigin: "https://" + stagingHost, organizationID: "org_beta",
            bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        #expect(betaStaging.frontendOrigin == "https://clerk.staging.cosmas.ai")
        #expect(betaStaging.profile == .operationalBeta)
    }

    @Test func productionAndLiveClerkKeychainServicesStayIsolated() throws {
        let liveHost = "clerk.cosmas.ai"
        let live = try NativeClerkAccountConfiguration(
            publishableKey: "pk_live_" + Data((liveHost + "$").utf8).base64EncodedString(),
            frontendOrigin: "https://" + liveHost, bundleIdentifier: "com.cosmasos.beta.ios",
            profile: .operationalBeta)
        #expect(live.keychainService == "com.cosmasos.beta.ios.clerk")

        let productionHost = "clerk.beta.cosmas.ai"
        let production = try NativeClerkAccountConfiguration(
            publishableKey: "pk_live_" + Data((productionHost + "$").utf8).base64EncodedString(),
            frontendOrigin: "https://" + productionHost, bundleIdentifier: "com.cosmasos.beta.ios",
            profile: .operationalProduction)
        #expect(production.keychainService == "com.cosmasos.beta.ios.clerk.clerk.beta.cosmas.ai")
        #expect(production.keychainService != live.keychainService)
    }

    @Test(arguments: [
        "https://CLERK.BETA.COSMAS.AI",
        "https://clerk.beta.cosmas.ai.",
        "https://clerk.beta.cosmas.ai:443",
        "https://user@clerk.beta.cosmas.ai",
        "https://clerk.beta.cosmas.ai.evil.com",
        "https://xn--clerk-beta-cosmas-ai",
        "https://clerk.beta.cosmas.ai/v1",
        "https://clerk.beta.cosmas.ai?x=1",
    ])
    func productionProfileRejectsBypassFrontendShapes(_ origin: String) throws {
        let host = "clerk.beta.cosmas.ai"
        let key = "pk_live_" + Data((host + "$").utf8).base64EncodedString()
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(publishableKey: key, frontendOrigin: origin,
                organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .operationalProduction)
        }
    }

    @Test func allowListGuardsAcceptPinnedHostsAndRefuseCrossProfileAndUnlistedHosts() throws {
        // Removing a host from allowedClerkHosts, or dropping the contains(host)
        // guard in NativeClerkAccountConfiguration, fails these expectations.
        #expect(NativeIdentityProfile.operationalBeta.allowedClerkHosts == [
            "clerk.cosmas.ai", "clerk.staging.cosmas.ai"])
        #expect(NativeIdentityProfile.operationalProduction.allowedClerkHosts == ["clerk.beta.cosmas.ai"])

        let liveHost = "clerk.cosmas.ai"
        let liveKey = "pk_live_" + Data((liveHost + "$").utf8).base64EncodedString()
        let live = try NativeClerkConfiguration(
            publishableKey: liveKey, frontendOrigin: "https://" + liveHost,
            organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
            profile: .operationalBeta)
        #expect(live.frontendOrigin == "https://clerk.cosmas.ai")
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: "pk_live_" + Data("clerk.beta.cosmas.ai$".utf8).base64EncodedString(),
                frontendOrigin: "https://clerk.beta.cosmas.ai", organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        }

        let productionHost = "clerk.beta.cosmas.ai"
        let productionKey = "pk_live_" + Data((productionHost + "$").utf8).base64EncodedString()
        let production = try NativeClerkConfiguration(
            publishableKey: productionKey, frontendOrigin: "https://" + productionHost,
            organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
            profile: .operationalProduction)
        #expect(production.frontendOrigin == "https://clerk.beta.cosmas.ai")
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: liveKey, frontendOrigin: "https://" + liveHost,
                organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .operationalProduction)
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: "pk_live_" + Data("clerk.example.invalid$".utf8).base64EncodedString(),
                frontendOrigin: "https://clerk.example.invalid", organizationID: "org_beta",
                bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalProduction)
        }
    }

    @Test func operationalBetaAcceptsLiveAndStagingClerkHostsAndRefusesLookalikes() throws {
        // Staging identity already shipped to TestFlight 1107/1110/1120 and
        // synthetic Mac 1120: clerk.staging.cosmas.ai with api.staging.cosmas.ai,
        // audience cosmas-os-beta-api, and a synthetic pk_live_ key.
        #expect(NativeIdentityProfile.operationalBeta.allowedClerkHosts == [
            "clerk.cosmas.ai", "clerk.staging.cosmas.ai"])

        for host in ["clerk.cosmas.ai", "clerk.staging.cosmas.ai"] {
            let key = "pk_live_" + Data((host + "$").utf8).base64EncodedString()
            let config = try NativeClerkConfiguration(
                publishableKey: key, frontendOrigin: "https://" + host,
                organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .operationalBeta)
            #expect(config.frontendOrigin == "https://" + host)
            #expect(config.profile == .operationalBeta)
        }

        for host in [
            "clerk.beta.cosmas.ai",
            "clerk.invented.example",
            "clerk.staging-.cosmas.ai",
            "clerk.staging.cosmas.ai.evil.example",
        ] {
            let key = "pk_live_" + Data((host + "$").utf8).base64EncodedString()
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(
                    publishableKey: key, frontendOrigin: "https://" + host,
                    organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
                    profile: .operationalBeta)
            }
        }

        let stagingHost = "clerk.staging.cosmas.ai"
        let stagingKey = "pk_live_" + Data((stagingHost + "$").utf8).base64EncodedString()
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: stagingKey, frontendOrigin: "https://" + stagingHost,
                organizationID: "org_beta", bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .operationalProduction)
        }
    }
}
