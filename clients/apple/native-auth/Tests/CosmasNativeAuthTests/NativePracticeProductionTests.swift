import Foundation
import Testing
@testable import CosmasNativeAuth

private let productionHost = "clerk.beta.cosmas.ai"
private func productionRealm(bundle: String = "com.cosmasos.beta.ios",
                             origin: NativeWorkspaceOrigin = .appleWebView) throws -> NativeClerkAccountConfiguration {
    try NativeClerkAccountConfiguration(publishableKey: "pk_live_" + Data((productionHost + "$").utf8).base64EncodedString(),
        frontendOrigin: "https://" + productionHost, bundleIdentifier: bundle, workspaceOrigin: origin,
        profile: .operationalBeta, storageNamespace: String(repeating: "c", count: 64))
}
private func stagingRealm() throws -> NativeClerkAccountConfiguration {
    let host = "invented.clerk.accounts.dev"
    return try NativeClerkAccountConfiguration(publishableKey: "pk_test_" + Data((host + "$").utf8).base64EncodedString(),
        frontendOrigin: "https://" + host, bundleIdentifier: "com.cosmasos.beta.ios",
        profile: .operationalStaging, storageNamespace: String(repeating: "b", count: 64))
}
private func productionBinding() throws -> NativePracticeAccountServiceBinding {
    try .init(accountOrigin: "https://enrollment-api.cosmas.ai", realm: productionRealm(), audience: "cosmabot-practice-api",
              allowedAPIOrigins: [], registeredPracticeOrigins: .practiceUUIDProduction)
}

@Suite struct NativePracticeProductionTests {
    @Test func productionPolicyAdmitsOnlyThisPracticesProductionHostAndRealData() throws {
        let binding = try productionBinding(), practice = UUID()
        let exact = "https://api." + practice.uuidString.lowercased() + ".workspace.cosmas.ai"
        #expect(binding.allowsAPI(exact, practiceID: practice))
        #expect(binding.dataMode == "authorized_beta")
        for origin in [exact.uppercased(), exact + "/", exact + ".attacker.invalid",
                       "https://api." + practice.uuidString.lowercased() + ".staging.cosmas.ai",
                       "https://api." + UUID().uuidString.lowercased() + ".workspace.cosmas.ai",
                       "https://api.workspace.cosmas.ai", "https://api.cosmas.ai"] {
            #expect(!binding.allowsAPI(origin, practiceID: practice))
        }
    }

    @Test func eachPolicyRequiresItsOwnRealm() throws {
        // A development (staging) realm can never open production practices, and the
        // production realm can never use the staging or exact synthetic policies.
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeAccountServiceBinding(accountOrigin: "https://enrollment-api.cosmas.ai", realm: stagingRealm(),
                audience: "", allowedAPIOrigins: [], registeredPracticeOrigins: .practiceUUIDProduction)
        }
        for policy in [NativeRegisteredPracticeOriginPolicy.syntheticPracticeUUIDStaging, .exact] {
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try NativePracticeAccountServiceBinding(accountOrigin: "https://enrollment-api.cosmas.ai", realm: productionRealm(),
                    audience: "cosmabot-practice-api", allowedAPIOrigins: ["https://api.a.workspace.cosmas.ai"],
                    registeredPracticeOrigins: policy)
            }
        }
        let staging = try NativePracticeAccountServiceBinding(
            accountOrigin: NativePracticeAccountServiceBinding.stagingAccountOrigin,
            realm: stagingRealm(), audience: "", allowedAPIOrigins: [], registeredPracticeOrigins: .syntheticPracticeUUIDStaging)
        #expect(staging.dataMode == "synthetic")
    }

    @Test func productionRealmRequiresLiveKeyAndTokenAudience() throws {
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkAccountConfiguration(publishableKey: "pk_test_" + Data((productionHost + "$").utf8).base64EncodedString(),
                frontendOrigin: "https://" + productionHost, bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .operationalBeta, storageNamespace: String(repeating: "c", count: 64))
        }
        #expect(throws: (any Error).self) {
            try NativePracticeAccountServiceBinding(accountOrigin: "https://enrollment-api.cosmas.ai", realm: productionRealm(),
                audience: "", allowedAPIOrigins: [], registeredPracticeOrigins: .practiceUUIDProduction)
        }
    }

    @Test func productionInfosPinEnrollmentAndClerkHosts() throws {
        for origin in ["https://enrollment-api.staging.cosmas.ai", "https://enrollment.example.invalid",
                       "https://api.accounts.staging.cosmas.ai"] {
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try NativePracticeAccountServiceBinding(accountOrigin: origin, realm: productionRealm(),
                    audience: "cosmabot-practice-api", allowedAPIOrigins: [], registeredPracticeOrigins: .practiceUUIDProduction)
            }
        }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeAccountServiceBinding(accountOrigin: NativePracticeAccountServiceBinding.productionAccountOrigin,
                realm: stagingRealm(), audience: "", allowedAPIOrigins: [],
                registeredPracticeOrigins: .syntheticPracticeUUIDStaging)
        }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeAccountServiceBinding(accountOrigin: "https://accounts.example.invalid",
                realm: stagingRealm(), audience: "", allowedAPIOrigins: ["https://api.a.staging.cosmas.ai"],
                registeredPracticeOrigins: .exact)
        }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeClerkAccountConfiguration(
                publishableKey: "pk_live_" + Data("clerk.example.invalid$".utf8).base64EncodedString(),
                frontendOrigin: "https://clerk.example.invalid", bundleIdentifier: "com.cosmasos.beta.ios",
                profile: .operationalBeta, storageNamespace: String(repeating: "c", count: 64))
        }
    }

    @Test func bundleConfigurationSelectsProductionRealm() throws {
        let value: [String: Any] = ["enabled": true, "accountOrigin": "https://enrollment-api.cosmas.ai", "apiOrigins": [String](),
            "registeredPracticeOrigins": "practice-uuid-production-v1",
            "realm": ["publishableKey": "pk_live_" + Data((productionHost + "$").utf8).base64EncodedString(),
                      "frontendOrigin": "https://" + productionHost, "audience": "cosmabot-practice-api",
                      "profile": "operational-beta-v1", "keychainNamespace": String(repeating: "c", count: 64)]]
        let parsed = try #require(try NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.ios"))
        #expect(parsed.binding.realm.profile == .operationalBeta && parsed.binding.dataMode == "authorized_beta")
        #expect(parsed.binding.accountOrigin == NativePracticeAccountServiceBinding.productionAccountOrigin)
        #expect(parsed.binding.realm.workspaceOrigin == .appleWebView)
        #expect(parsed.binding.realm.workspaceOrigin.nativeClient == "apple")
        let desktop = try #require(try NativePracticeBundleConfiguration.parse(value, bundleIdentifier: "com.cosmasos.beta.desktop.auth"))
        #expect(desktop.binding.realm.workspaceOrigin == .desktopApp)
        #expect(desktop.binding.realm.workspaceOrigin.nativeClient == "desktop")
        try desktop.binding.validateNativeAccountConfig([
            "native_account": ["issuer": "https://" + productionHost, "audience": "cosmabot-practice-api",
                               "session_policy": "default_session", "native_origin": "app://cosmas"] as [String: Any],
        ])
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try desktop.binding.validateNativeAccountConfig([
                "native_account": ["issuer": "https://" + productionHost, "audience": "cosmabot-practice-api",
                                   "session_policy": "default_session", "native_origin": "capacitor://localhost"] as [String: Any],
            ])
        }
        var mismatched = value; mismatched["registeredPracticeOrigins"] = "synthetic-practice-uuid-staging-v1"
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeBundleConfiguration.parse(mismatched, bundleIdentifier: "com.cosmasos.beta.ios")
        }
        var wrongAccount = value; wrongAccount["accountOrigin"] = NativePracticeAccountServiceBinding.stagingAccountOrigin
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeBundleConfiguration.parse(wrongAccount, bundleIdentifier: "com.cosmasos.beta.ios")
        }
        var simulator = value; simulator["realm"] = (value["realm"] as! [String: Any]).merging(["profile": "simulator-staging-v1"]) { $1 }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeBundleConfiguration.parse(simulator, bundleIdentifier: "com.cosmasos.beta.ios")
        }
        let stagingHost = "invented.clerk.accounts.dev"
        let staging: [String: Any] = ["enabled": true,
            "accountOrigin": NativePracticeAccountServiceBinding.stagingAccountOrigin, "apiOrigins": [String](),
            "registeredPracticeOrigins": "synthetic-practice-uuid-staging-v1",
            "realm": ["publishableKey": "pk_test_" + Data((stagingHost + "$").utf8).base64EncodedString(),
                      "frontendOrigin": "https://" + stagingHost, "audience": "",
                      "profile": "operational-staging-v1", "keychainNamespace": String(repeating: "b", count: 64)]]
        let stagingParsed = try #require(try NativePracticeBundleConfiguration.parse(staging, bundleIdentifier: "com.cosmasos.beta.ios"))
        #expect(stagingParsed.binding.accountOrigin == NativePracticeAccountServiceBinding.stagingAccountOrigin)
        var stagingProdMix = staging; stagingProdMix["accountOrigin"] = NativePracticeAccountServiceBinding.productionAccountOrigin
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeBundleConfiguration.parse(stagingProdMix, bundleIdentifier: "com.cosmasos.beta.ios")
        }
    }

    @Test func nativeConfigRejectsInfosRealmMismatchBeforeOpenChief() throws {
        let binding = try productionBinding()
        let matching: [String: Any] = ["native_account": [
            "issuer": "https://" + productionHost, "audience": "cosmabot-practice-api",
            "session_policy": "default_session", "native_origin": "capacitor://localhost",
        ] as [String: Any]]
        try binding.validateNativeAccountConfig(matching)
        for broken in [
            ["issuer": "https://invented.clerk.accounts.dev", "audience": "cosmabot-practice-api",
             "session_policy": "default_session", "native_origin": "capacitor://localhost"],
            ["issuer": "https://" + productionHost, "audience": "wrong-audience",
             "session_policy": "default_session", "native_origin": "capacitor://localhost"],
            ["issuer": "https://" + productionHost, "audience": "cosmabot-practice-api",
             "session_policy": "default_session", "native_origin": "app://cosmas"],
            ["issuer": "https://" + productionHost, "audience": "cosmabot-practice-api",
             "session_policy": "", "native_origin": "capacitor://localhost"],
        ] as [[String: String]] {
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try binding.validateNativeAccountConfig(["native_account": broken])
            }
        }
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try binding.validateNativeAccountConfig([:] as [String: Any])
        }
    }

    @Test func practiceOpenRejectsAccountWebNonChiefAndWrongAPIHosts() throws {
        let binding = try productionBinding(), practice = UUID()
        let ok = "https://" + practice.uuidString.lowercased() + ".workspace.cosmas.ai/chief"
        #expect(try binding.practiceAPIOrigin(fromWorkspaceURL: ok, practiceID: practice)
            == "https://api." + practice.uuidString.lowercased() + ".workspace.cosmas.ai")
        for bad in [
            "https://app.cosmas.ai/chief",
            "https://api.cosmas.ai/chief",
            "https://" + practice.uuidString.lowercased() + ".workspace.cosmas.ai",
            "https://" + practice.uuidString.lowercased() + ".workspace.cosmas.ai/chief/",
            "https://" + practice.uuidString.lowercased() + ".workspace.cosmas.ai/chief?x=1",
            "https://" + practice.uuidString.lowercased() + ".staging.cosmas.ai/chief",
            "https://" + UUID().uuidString.lowercased() + ".workspace.cosmas.ai/chief",
        ] {
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try binding.practiceAPIOrigin(fromWorkspaceURL: bad, practiceID: practice)
            }
        }
        #expect(!binding.allowsAPI("https://api.cosmas.ai", practiceID: practice))
        #expect(!binding.allowsAPI("https://api.app.cosmas.ai", practiceID: practice))
    }
}

@Suite struct NativePracticeProductionBootstrapTests {
    private func inputs() throws -> (NativePracticeConnectionExpectation, NativePracticeAccountServiceBinding, [String: Any]) {
        let binding = try productionBinding(), practice = UUID(), now = Date()
        let api = "https://api." + practice.uuidString.lowercased() + ".workspace.cosmas.ai"
        let expected = try NativePracticeConnectionExpectation(selectionID: practice, nonce: UUID(),
            account: .init(issuer: "https://" + productionHost, userID: "user_one", sessionID: "sess_one"),
            organizationID: "org_one", boxID: UUID(), apiOrigin: api)
        let body: [String: Any] = ["contract_version": "cosmas-native-workspace-profile.v1", "client": "apple",
            "nonce": expected.nonce.uuidString.lowercased(), "native_origin": "capacitor://localhost", "data_mode": "authorized_beta",
            "nativeIdentity": ["version": 1, "profile": "operational-beta-v1", "client": "apple", "apiOrigin": api,
                "publishableKey": binding.realm.publishableKey, "frontendOrigin": binding.realm.frontendOrigin,
                "organizationId": "org_one", "audience": "cosmabot-practice-api"],
            "session": ["issuer": "https://" + productionHost, "subject": "user_one", "session_id": "sess_one"],
            "practice": ["practice_id": practice.uuidString.lowercased(), "box_id": expected.boxID.uuidString.lowercased()],
            "workspace": ["url": "https://" + practice.uuidString.lowercased() + ".workspace.cosmas.ai/chief",
                "source_commit": String(repeating: "1", count: 40), "image_sha256": String(repeating: "2", count: 64),
                "workspace_proof_sha256": String(repeating: "3", count: 64), "member_proof_sha256": String(repeating: "4", count: 64),
                "native_qualification_sha256": String(repeating: "5", count: 64)],
            "issued_at": Int(now.timeIntervalSince1970), "expires_at": Int(now.timeIntervalSince1970) + 30]
        return (expected, binding, body)
    }
    private func encode(_ value: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
    }

    @Test func productionBootstrapRequiresRealDataModeFromTheAccountService() throws {
        let (expected, binding, body) = try inputs()
        _ = try NativePracticeWorkspaceBootstrap.decode(encode(body), expectation: expected, binding: binding)
        var synthetic = body; synthetic["data_mode"] = "synthetic"
        #expect(throws: (any Error).self) {
            try NativePracticeWorkspaceBootstrap.decode(encode(synthetic), expectation: expected, binding: binding)
        }
    }

    @Test func productionBootstrapRejectsAccountWebAndNonChiefWorkspaceShapes() throws {
        let (expected, binding, body) = try inputs()
        var accountWeb = body
        accountWeb["workspace"] = (body["workspace"] as! [String: Any]).merging([
            "url": "https://app.cosmas.ai/chief",
        ]) { $1 }
        #expect(throws: (any Error).self) {
            try NativePracticeWorkspaceBootstrap.decode(encode(accountWeb), expectation: expected, binding: binding)
        }
        var noChief = body
        noChief["workspace"] = (body["workspace"] as! [String: Any]).merging([
            "url": "https://" + expected.selectionID.uuidString.lowercased() + ".workspace.cosmas.ai",
        ]) { $1 }
        #expect(throws: (any Error).self) {
            try NativePracticeWorkspaceBootstrap.decode(encode(noChief), expectation: expected, binding: binding)
        }
        var unpaired = body
        let wrongAPI = "https://api.cosmas.ai"
        let wrongExpected = try NativePracticeConnectionExpectation(
            selectionID: expected.selectionID, nonce: expected.nonce, account: expected.account,
            organizationID: expected.organizationID, boxID: expected.boxID, apiOrigin: wrongAPI)
        var native = unpaired["nativeIdentity"] as! [String: Any]
        native["apiOrigin"] = wrongAPI
        unpaired["nativeIdentity"] = native
        #expect(throws: (any Error).self) {
            try NativePracticeWorkspaceBootstrap.decode(encode(unpaired), expectation: wrongExpected, binding: binding)
        }
    }

    @Test func productionBootstrapAdmitsDesktopClientMatchingAppOrigin() throws {
        let realm = try productionRealm(bundle: "com.cosmasos.beta.desktop.auth", origin: .desktopApp)
        let binding = try NativePracticeAccountServiceBinding(accountOrigin: "https://enrollment-api.cosmas.ai",
            realm: realm, audience: "cosmabot-practice-api", allowedAPIOrigins: [],
            registeredPracticeOrigins: .practiceUUIDProduction)
        let practice = UUID(), now = Date()
        let api = "https://api." + practice.uuidString.lowercased() + ".workspace.cosmas.ai"
        let expected = try NativePracticeConnectionExpectation(selectionID: practice, nonce: UUID(),
            account: .init(issuer: "https://" + productionHost, userID: "user_one", sessionID: "sess_one"),
            organizationID: "org_one", boxID: UUID(), apiOrigin: api)
        var body: [String: Any] = ["contract_version": "cosmas-native-workspace-profile.v1", "client": "desktop",
            "nonce": expected.nonce.uuidString.lowercased(), "native_origin": "app://cosmas", "data_mode": "authorized_beta",
            "nativeIdentity": ["version": 1, "profile": "operational-beta-v1", "client": "desktop", "apiOrigin": api,
                "publishableKey": binding.realm.publishableKey, "frontendOrigin": binding.realm.frontendOrigin,
                "organizationId": "org_one", "audience": "cosmabot-practice-api"],
            "session": ["issuer": "https://" + productionHost, "subject": "user_one", "session_id": "sess_one"],
            "practice": ["practice_id": practice.uuidString.lowercased(), "box_id": expected.boxID.uuidString.lowercased()],
            "workspace": ["url": "https://" + practice.uuidString.lowercased() + ".workspace.cosmas.ai/chief",
                "source_commit": String(repeating: "1", count: 40), "image_sha256": String(repeating: "2", count: 64),
                "workspace_proof_sha256": String(repeating: "3", count: 64), "member_proof_sha256": String(repeating: "4", count: 64),
                "native_qualification_sha256": String(repeating: "5", count: 64)],
            "issued_at": Int(now.timeIntervalSince1970), "expires_at": Int(now.timeIntervalSince1970) + 30]
        _ = try NativePracticeWorkspaceBootstrap.decode(encode(body), expectation: expected, binding: binding)
        body["client"] = "apple"
        #expect(throws: (any Error).self) {
            try NativePracticeWorkspaceBootstrap.decode(encode(body), expectation: expected, binding: binding)
        }
    }
}
