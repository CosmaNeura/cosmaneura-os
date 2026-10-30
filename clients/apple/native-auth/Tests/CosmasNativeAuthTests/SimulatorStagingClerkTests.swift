import Foundation
import Testing
@testable import CosmasNativeAuth

private let stagingHost = "clerk.staging.cosmas.ai"
private let stagingKey = "pk_live_Y2xlcmsuc3RhZ2luZy5jb3NtYXMuYWkk"
private let stagingOrganization = "org_invented_beta"

@Suite struct SimulatorStagingClerkTests {
    @Test func simulatorVariantReturnsToItsOwnScheme() throws {
        let config = try NativeClerkConfiguration(
            publishableKey: stagingKey, frontendOrigin: "https://" + stagingHost,
            organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.synthetic",
            profile: .simulatorStaging)
        #expect(config.callbackURL == "com.cosmasos.synthetic://callback")
        #expect(config.profile == .simulatorStaging)
        let variant = try NativeClerkConfiguration(
            publishableKey: stagingKey, frontendOrigin: "https://" + stagingHost,
            organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.synthetic.w8m",
            profile: .simulatorStaging)
        #expect(variant.callbackURL == "com.cosmasos.synthetic.w8m://callback")
    }

    @Test func deviceBundleKeepsTheDeviceCallbackOnTheSameStagingHost() throws {
        let device = try NativeClerkConfiguration(
            publishableKey: stagingKey, frontendOrigin: "https://" + stagingHost,
            organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.beta.ios",
            profile: .operationalBeta)
        #expect(device.callbackURL == "com.cosmasos.beta.ios://callback")
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: stagingKey, frontendOrigin: "https://" + stagingHost,
                organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.synthetic",
                profile: .operationalBeta)
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkConfiguration(
                publishableKey: stagingKey, frontendOrigin: "https://" + stagingHost,
                organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .simulatorStaging)
        }
    }

    @Test func productionAndOtherHostsCannotUseTheSimulatorProfile() throws {
        for host in ["clerk.cosmaneura.com", "app.cosmaneura.com", "clerk.example.invalid"] {
            let key = "pk_live_" + Data((host + "$").utf8).base64EncodedString()
            #expect(throws: NativeAuthError.unavailable) {
                try NativeClerkConfiguration(
                    publishableKey: key, frontendOrigin: "https://" + host,
                    organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.synthetic",
                    profile: .simulatorStaging)
            }
        }
        let testKey = "pk_test_" + Data((stagingHost + "$").utf8).base64EncodedString()
        let config = try NativeClerkConfiguration(
            publishableKey: testKey, frontendOrigin: "https://" + stagingHost,
            organizationID: stagingOrganization, bundleIdentifier: "com.cosmasos.synthetic",
            profile: .simulatorStaging)
        #expect(config.callbackURL == "com.cosmasos.synthetic://callback")
    }
}

@Suite @MainActor struct SimulatorStagingKeychainTests {
    @Test func keychainFollowsTheSimulatorProfileAndStillRefusesOperationalSyntheticBundles() throws {
        let allowed = try KeychainAccessBlock(
            bundleIdentifier: "com.cosmasos.synthetic", profile: .simulatorStaging)
        #expect(allowed.allowsAuthenticationUI)
        #expect(throws: NativeAuthError.storageUnavailable) {
            try KeychainAccessBlock(bundleIdentifier: "com.cosmasos.beta.ios", profile: .simulatorStaging)
        }
        #expect(throws: NativeAuthError.storageUnavailable) {
            try KeychainAccessBlock(bundleIdentifier: "com.cosmasos.synthetic", profile: .operationalBeta)
        }
    }
}
