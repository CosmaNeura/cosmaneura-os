import Foundation
import Testing
@testable import CosmasNativeAuth

private let selectedRevision = "00000000-0000-4000-8000-000000000001"
private let selectedID = UUID(uuidString: "00000000-0000-4000-8000-000000000002")!
private func selectedRequest(_ registry: Int = 7) throws -> NativeSelectedPracticeRequest {
    try .init(options: ["expectedRevision": selectedRevision, "expectedPracticeId": selectedID.uuidString.lowercased(), "expectedRegistryRevision": registry])
}
private func selectedInputs(session: String = "sess_one", box: UUID = UUID(uuidString: "00000000-0000-4000-8000-000000000003")!,
                            api: String = "https://api.practice.example.invalid") throws -> (NativePracticeConnectionExpectation, NativePracticeAccountServiceBinding) {
    let issuer = "https://invented.clerk.accounts.dev"
    let realm = try NativeClerkAccountConfiguration(publishableKey: "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString(),
        frontendOrigin: issuer, bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalStaging, storageNamespace: String(repeating: "a", count: 64))
    let binding = try NativePracticeAccountServiceBinding(accountOrigin: NativePracticeAccountServiceBinding.stagingAccountOrigin, realm: realm,
        audience: "", allowedAPIOrigins: ["https://api.practice.example.invalid", "https://api.other.example.invalid"])
    return (try .init(selectionID: selectedID, nonce: UUID(), account: .init(issuer: issuer, userID: "user_one", sessionID: session),
        organizationID: "org_one", boxID: box, apiOrigin: api), binding)
}
@MainActor private final class SelectedProfileService: NativePracticeAccountService {
    let binding: NativePracticeAccountServiceBinding; let bootstrap: NativePracticeWorkspaceBootstrap
    init(_ binding: NativePracticeAccountServiceBinding, _ bootstrap: NativePracticeWorkspaceBootstrap) { self.binding = binding; self.bootstrap = bootstrap }
    func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt {
        .init(expectation: expectation, expiresAt: bootstrap.expiresAt, bootstrap: bootstrap)
    }
}
@MainActor private func selectedProfile(_ expected: NativePracticeConnectionExpectation, _ binding: NativePracticeAccountServiceBinding,
                                      source: String = String(repeating: "1", count: 40), image: String = String(repeating: "2", count: 64),
                                      proof: String = String(repeating: "3", count: 64)) async throws -> NativePracticeProfile {
    let now = Int(Date().timeIntervalSince1970), address = expected.apiOrigin.replacingOccurrences(of: "https://api.", with: "https://")
    let body: [String: Any] = ["contract_version": "cosmas-native-workspace-profile.v1", "client": "apple", "nonce": expected.nonce.uuidString.lowercased(),
        "native_origin": "capacitor://localhost", "data_mode": "synthetic",
        "nativeIdentity": ["version": 1, "profile": "operational-staging-v1", "client": "apple", "apiOrigin": expected.apiOrigin,
            "publishableKey": binding.realm.publishableKey, "frontendOrigin": binding.realm.frontendOrigin, "organizationId": expected.organizationID, "audience": ""],
        "session": ["issuer": expected.account.issuer, "subject": expected.account.userID, "session_id": expected.account.sessionID],
        "practice": ["practice_id": expected.selectionID.uuidString.lowercased(), "box_id": expected.boxID.uuidString.lowercased()],
        "workspace": ["url": address, "source_commit": source, "image_sha256": image, "workspace_proof_sha256": proof,
            "member_proof_sha256": proof, "native_qualification_sha256": proof], "issued_at": now, "expires_at": now + 30]
    let bootstrap = try NativePracticeWorkspaceBootstrap.decode(JSONSerialization.data(withJSONObject: body), expectation: expected, binding: binding)
    return try await NativePracticeProfileResolver(binding: binding, service: SelectedProfileService(binding, bootstrap), currentAccount: { expected.account }).resolve(expected)
}
@MainActor private final class SelectedDriver: NativeAuthDriver {
    var loaded = true; var identity: NativeAuthIdentity?
    func signIn() async throws {}; func signOut() async throws { identity = nil }
    func clearStoredCredentials() throws {}; func freshToken() async throws -> String? { nil }
}
@MainActor private final class SelectedBlock: NativeAuthAccessBlock {
    func isBlocked() throws -> Bool { false }; func setBlocked(_ value: Bool) throws {}
}
@MainActor private final class SelectedResources: NativePracticeRequestResources {
    let apiOrigin: String; var isIdle = true; var fenced = false
    init(_ api: String) { apiOrigin = api }; func fence() { fenced = true }; func close() async throws {}
}
@MainActor private func selectedRuntime(_ profile: NativePracticeProfile) throws -> (NativePracticeRuntime, SelectedResources) {
    let driver = SelectedDriver(); driver.identity = try .init(userID: profile.account.userID, sessionID: profile.account.sessionID, organizationID: profile.organizationID)
    let auth = NativeWorkspaceAuth(enabled: true, organizationID: profile.organizationID, tokenPolicy: try profile.tokenPolicy,
        driver: { driver }, accessBlock: { SelectedBlock() }), resources = SelectedResources(profile.apiOrigin)
    return (try .init(profile: profile, auth: auth, resources: resources), resources)
}
private func selectedReceipt(_ expected: NativePracticeConnectionExpectation, registry: Int = 7, id: UUID = selectedID) throws -> NativeRegisteredPracticeReceipt {
    try .init(account: expected.account, practiceID: id, organizationID: expected.organizationID, boxID: expected.boxID, registryRevision: registry)
}

@Suite struct NativeSelectedPracticeTests {
    @Test func rejectsMalformedOrAuthorityBearingSelectedInput() throws {
        let valid: [String: Any] = ["expectedRevision": selectedRevision, "expectedPracticeId": selectedID.uuidString.lowercased(), "expectedRegistryRevision": 7]
        _ = try NativeSelectedPracticeRequest(options: valid)
        for mutation in 0..<7 {
            var value = valid
            switch mutation {
            case 0: value["expectedRegistryRevision"] = true
            case 1: value["expectedRegistryRevision"] = 7.5
            case 2: value["expectedRegistryRevision"] = 2_147_483_648
            case 3: value["expectedRegistryRevision"] = -1
            case 4: value["expectedPracticeId"] = "not-a-practice"
            case 5: value["expectedRevision"] = "browser-revision"
            default: value["organizationId"] = "org_injected"
            }
            #expect(throws: NativePracticeProfileError.invalidBinding) { try NativeSelectedPracticeRequest(options: value) }
        }
    }
    @Test func pinsNativeAccountPracticeAndRegistryRevision() throws {
        let (expected, _) = try selectedInputs(), request = try selectedRequest()
        try request.validate(selectedReceipt(expected), account: expected.account, revision: selectedRevision)
        #expect(throws: NativePracticeProfileError.sessionChanged) { try request.validate(selectedReceipt(expected, registry: 8), account: expected.account, revision: selectedRevision) }
        #expect(throws: NativePracticeProfileError.sessionChanged) { try request.validate(selectedReceipt(expected, id: UUID()), account: expected.account, revision: selectedRevision) }
        #expect(throws: NativePracticeProfileError.sessionChanged) { try request.validate(selectedReceipt(expected), account: expected.account, revision: UUID().uuidString.lowercased()) }
        let changed = try NativeAccountIdentity(issuer: expected.account.issuer, userID: expected.account.userID, sessionID: "sess_changed")
        #expect(throws: NativePracticeProfileError.sessionChanged) { try request.validate(selectedReceipt(expected), account: changed, revision: selectedRevision) }
    }
    @Test @MainActor func freshlyVerifiedLogicalBindingAllowsNewNonceAndProofMeasurement() async throws {
        let (expected, binding) = try selectedInputs(), (freshExpected, _) = try selectedInputs()
        let original = try await selectedProfile(expected, binding), fresh = try await selectedProfile(freshExpected, binding, proof: String(repeating: "6", count: 64))
        #expect(original.bootstrap!.canonicalData != fresh.bootstrap!.canonicalData)
        try selectedRequest().validateFinal(candidate: original, fresh: fresh, receipt: selectedReceipt(expected), account: expected.account, revision: selectedRevision)
    }
    @Test @MainActor func refusesFacadeResumeUntilOriginalSourceIsRetiredIdleAndSameAccount() async throws {
        let (expected, binding) = try selectedInputs(), profile = try await selectedProfile(expected, binding)
        let (runtime, resources) = try selectedRuntime(profile)
        #expect(throws: NativePracticeProfileError.busy) { try NativeSelectedPracticeRequest.requireRetiredSource(runtime, account: expected.account) }
        resources.isIdle = false; runtime.retire(); #expect(resources.fenced)
        #expect(throws: NativePracticeProfileError.busy) { try NativeSelectedPracticeRequest.requireRetiredSource(runtime, account: expected.account) }
        resources.isIdle = true; try NativeSelectedPracticeRequest.requireRetiredSource(runtime, account: expected.account)
        let changed = try NativeAccountIdentity(issuer: expected.account.issuer, userID: expected.account.userID, sessionID: "sess_changed")
        #expect(throws: NativePracticeProfileError.sessionChanged) { try NativeSelectedPracticeRequest.requireRetiredSource(runtime, account: changed) }
    }
    @Test @MainActor func finalSynchronousGateNeverInstallsChangedSelectionSourceOrAccount() async throws {
        let (expected, binding) = try selectedInputs(), original = try await selectedProfile(expected, binding), request = try selectedRequest()
        let (runtime, _) = try selectedRuntime(original), state = runtime.auth.state(); var installs = 0
        let stable = try await selectedProfile(expected, binding)
        try request.commit(runtime: runtime, fresh: stable, receipt: selectedReceipt(expected), account: expected.account,
            revision: selectedRevision, currentAccount: expected.account, admittedState: state) { installs += 1 }
        #expect(installs == 1)
        let changedSource = try await selectedProfile(expected, binding, source: String(repeating: "9", count: 40))
        let changedImage = try await selectedProfile(expected, binding, image: String(repeating: "8", count: 64))
        let (boxExpected, _) = try selectedInputs(box: UUID()), (apiExpected, _) = try selectedInputs(api: "https://api.other.example.invalid")
        let changedBox = try await selectedProfile(boxExpected, binding), changedAPI = try await selectedProfile(apiExpected, binding)
        for changed in [changedSource, changedImage, changedBox, changedAPI] {
            #expect(throws: NativePracticeProfileError.invalidBinding) {
                try request.commit(runtime: runtime, fresh: changed, receipt: selectedReceipt(expected), account: expected.account,
                    revision: selectedRevision, currentAccount: expected.account, admittedState: state) { installs += 1 }
            }
        }
        #expect(throws: NativePracticeProfileError.sessionChanged) {
            try request.commit(runtime: runtime, fresh: stable, receipt: selectedReceipt(expected, registry: 8), account: expected.account,
                revision: selectedRevision, currentAccount: expected.account, admittedState: state) { installs += 1 }
        }
        let changedAccount = try NativeAccountIdentity(issuer: expected.account.issuer, userID: expected.account.userID, sessionID: "sess_changed")
        #expect(throws: NativePracticeProfileError.sessionChanged) {
            try request.commit(runtime: runtime, fresh: stable, receipt: selectedReceipt(expected), account: expected.account,
                revision: selectedRevision, currentAccount: changedAccount, admittedState: state) { installs += 1 }
        }
        runtime.retire()
        #expect(throws: NativePracticeProfileError.sessionChanged) {
            try request.commit(runtime: runtime, fresh: stable, receipt: selectedReceipt(expected), account: expected.account,
                revision: selectedRevision, currentAccount: expected.account, admittedState: state) { installs += 1 }
        }
        #expect(installs == 1)
    }
}
