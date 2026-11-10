import Foundation
import Testing
@testable import CosmasNativeAuth

private func bootstrapInputs() throws -> (NativePracticeConnectionExpectation, NativePracticeAccountServiceBinding) {
    let issuer = "https://invented.clerk.accounts.dev"
    let realm = try NativeClerkAccountConfiguration(publishableKey: "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString(),
        frontendOrigin: issuer, bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalStaging,
        storageNamespace: String(repeating: "a", count: 64))
    let binding = try NativePracticeAccountServiceBinding(accountOrigin: NativePracticeAccountServiceBinding.stagingAccountOrigin, realm: realm,
        audience: "", allowedAPIOrigins: ["https://api.practice.example.invalid"])
    let expected = try NativePracticeConnectionExpectation(selectionID: UUID(), nonce: UUID(),
        account: .init(issuer: issuer, userID: "user_one", sessionID: "sess_one"), organizationID: "org_one",
        boxID: UUID(), apiOrigin: "https://api.practice.example.invalid")
    return (expected, binding)
}
private func bootstrapBody(_ expected: NativePracticeConnectionExpectation, _ binding: NativePracticeAccountServiceBinding,
                           now: Date) -> [String: Any] {
    ["contract_version": "cosmas-native-workspace-profile.v1", "client": "apple", "nonce": expected.nonce.uuidString.lowercased(),
     "native_origin": "capacitor://localhost", "data_mode": "synthetic",
     "nativeIdentity": ["version": 1, "profile": "operational-staging-v1", "client": "apple", "apiOrigin": expected.apiOrigin,
        "publishableKey": binding.realm.publishableKey, "frontendOrigin": binding.realm.frontendOrigin,
        "organizationId": expected.organizationID, "audience": ""],
     "session": ["issuer": expected.account.issuer, "subject": expected.account.userID, "session_id": expected.account.sessionID],
     "practice": ["practice_id": expected.selectionID.uuidString.lowercased(), "box_id": expected.boxID.uuidString.lowercased()],
     // Product decode pairs https://<host>/chief with https://api.<host> only.
     "workspace": ["url": "https://practice.example.invalid/chief", "source_commit": String(repeating: "1", count: 40),
        "image_sha256": String(repeating: "2", count: 64), "workspace_proof_sha256": String(repeating: "3", count: 64),
        "member_proof_sha256": String(repeating: "4", count: 64), "native_qualification_sha256": String(repeating: "5", count: 64)],
     "issued_at": Int(now.timeIntervalSince1970), "expires_at": Int(now.timeIntervalSince1970) + 30]
}
private func encodeBootstrap(_ value: [String: Any]) throws -> Data {
    try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys, .withoutEscapingSlashes])
}

@MainActor private final class SnapshotService: NativePracticeAccountService {
    let binding: NativePracticeAccountServiceBinding
    let bootstrap: NativePracticeWorkspaceBootstrap
    init(_ binding: NativePracticeAccountServiceBinding, _ bootstrap: NativePracticeWorkspaceBootstrap) {
        self.binding = binding; self.bootstrap = bootstrap
    }
    func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt {
        .init(expectation: expectation, expiresAt: bootstrap.expiresAt, bootstrap: bootstrap)
    }
}
@MainActor private final class SnapshotDriver: NativeAuthDriver {
    var loaded = true
    var identity: NativeAuthIdentity?
    func signIn() async throws {}
    func signOut() async throws { identity = nil }
    func clearStoredCredentials() throws {}
    func freshToken() async throws -> String? { nil }
}
@MainActor private final class SnapshotBlock: NativeAuthAccessBlock {
    func isBlocked() throws -> Bool { false }
    func setBlocked(_ value: Bool) throws {}
}
@MainActor private final class SnapshotResources: NativePracticeRequestResources {
    let apiOrigin: String
    init(_ apiOrigin: String) { self.apiOrigin = apiOrigin }
    var isIdle: Bool { true }
    func fence() {}
    func close() async throws {}
}

@Suite struct NativePracticeBootstrapTests {
    @Test @MainActor func snapshotRevisionAndPostClosureGuardFollowActualNativeAuthOwner() async throws {
        let (expected, binding) = try bootstrapInputs(), now = Date()
        let bootstrap = try NativePracticeWorkspaceBootstrap.decode(encodeBootstrap(bootstrapBody(expected, binding, now: now)),
            expectation: expected, binding: binding, now: now)
        let service = SnapshotService(binding, bootstrap)
        let profile = try await NativePracticeProfileResolver(binding: binding, service: service,
            currentAccount: { expected.account }).resolve(expected)
        for mutation in 0..<2 {
            let driver = SnapshotDriver(), block = SnapshotBlock()
            driver.identity = try .init(userID: expected.account.userID, sessionID: expected.account.sessionID,
                organizationID: expected.organizationID)
            let auth = NativeWorkspaceAuth(enabled: true, organizationID: expected.organizationID,
                tokenPolicy: try profile.tokenPolicy, driver: { driver }, accessBlock: { block })
            let runtime = try NativePracticeRuntime(profile: profile, auth: auth, resources: SnapshotResources(profile.apiOrigin))
            let snapshot = try NativePracticeActiveWorkspaceSnapshot(runtime: runtime)
            #expect(snapshot.revision == auth.state().revision)
            try snapshot.validateCurrentBinding(now: now)
            #expect(throws: NativePracticeProfileError.sessionChanged) {
                try snapshot.validateCurrentBinding(now: bootstrap.expiresAt)
            }
            // Simulate the awaited old-renderer close yielding to a new SDK
            // session or terminal owner retirement, before document injection.
            if mutation == 0 {
                driver.identity = try .init(userID: expected.account.userID, sessionID: "sess_new",
                    organizationID: expected.organizationID)
            } else { auth.retire() }
            #expect(throws: NativePracticeProfileError.sessionChanged) { try snapshot.validateCurrentBinding(now: now) }
        }
    }
    @Test func closedQualifiedBootstrapBindsExactNativeSessionPracticeAndAPI() throws {
        let (expected, binding) = try bootstrapInputs(), now = Date()
        let body = bootstrapBody(expected, binding, now: now)
        let result = try NativePracticeWorkspaceBootstrap.decode(encodeBootstrap(body), expectation: expected, binding: binding, now: now)
        #expect(result.sourceCommit == String(repeating: "1", count: 40))
        #expect(result.nativeQualificationSHA256 == String(repeating: "5", count: 64))
        #expect(result.rendererProfile["nonce"] as? String == expected.nonce.uuidString.lowercased())
        #expect(result.expiresAt.timeIntervalSince(result.issuedAt) == 30)
    }

    @Test func bootstrapRejectsWrongSessionNoncePracticeAPIAndQualificationShape() throws {
        let (expected, binding) = try bootstrapInputs(), now = Date()
        for mutation in 0..<7 {
            var body = bootstrapBody(expected, binding, now: now)
            if mutation == 0 { body["nonce"] = UUID().uuidString.lowercased() }
            if mutation == 1 { var part = body["session"] as! [String: Any]; part["session_id"] = "sess_other"; body["session"] = part }
            if mutation == 2 { var part = body["practice"] as! [String: Any]; part["box_id"] = UUID().uuidString.lowercased(); body["practice"] = part }
            if mutation == 3 { var part = body["nativeIdentity"] as! [String: Any]; part["apiOrigin"] = "https://api.other.example.invalid"; body["nativeIdentity"] = part }
            if mutation == 4 { var part = body["workspace"] as! [String: Any]; part["native_qualification_sha256"] = "not-a-measurement"; body["workspace"] = part }
            if mutation == 5 { var part = body["nativeIdentity"] as! [String: Any]; part["version"] = true; body["nativeIdentity"] = part }
            if mutation == 6 { body["extra"] = "not-a-contract-field" }
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try NativePracticeWorkspaceBootstrap.decode(encodeBootstrap(body), expectation: expected, binding: binding, now: now)
            }
        }
    }

    @Test func bootstrapRejectsExpiredOverlongOrFutureProofBeforeActivation() throws {
        let (expected, binding) = try bootstrapInputs(), now = Date()
        for mutation in 0..<3 {
            var body = bootstrapBody(expected, binding, now: now)
            if mutation == 0 { body["issued_at"] = Int(now.timeIntervalSince1970) - 40; body["expires_at"] = Int(now.timeIntervalSince1970) - 10 }
            if mutation == 1 { body["expires_at"] = Int(now.timeIntervalSince1970) + 60 }
            if mutation == 2 { body["issued_at"] = Int(now.timeIntervalSince1970) + 10; body["expires_at"] = Int(now.timeIntervalSince1970) + 30 }
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try NativePracticeWorkspaceBootstrap.decode(encodeBootstrap(body), expectation: expected, binding: binding, now: now)
            }
        }
    }

    @Test func bootstrapRejectsDuplicateAndEscapedEquivalentJSONKeys() throws {
        let (expected, binding) = try bootstrapInputs(), now = Date()
        let encoded = try encodeBootstrap(bootstrapBody(expected, binding, now: now))
        for key in ["nonce", "\\u006eonce"] {
            let raw = Data(("{\"" + key + "\":\"other\"," + String(decoding: encoded.dropFirst(), as: UTF8.self)).utf8)
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try NativePracticeWorkspaceBootstrap.decode(raw, expectation: expected, binding: binding, now: now)
            }
        }
    }
}
