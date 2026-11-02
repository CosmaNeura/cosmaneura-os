import Foundation
import Testing
@testable import CosmasNativeAuth

private let practiceOne = "https://api.practice-one.example.invalid"
private let practiceTwo = "https://api.practice-two.example.invalid"

private func practiceRealm() throws -> NativeClerkAccountConfiguration {
    let key = "pk_test_" + Data("invented.clerk.accounts.dev$".utf8).base64EncodedString()
    return try NativeClerkAccountConfiguration(publishableKey: key,
        frontendOrigin: "https://invented.clerk.accounts.dev", bundleIdentifier: "com.cosmasos.beta.ios",
        profile: .operationalStaging, storageNamespace: String(repeating: "a", count: 64))
}
private func practiceBinding() throws -> NativePracticeAccountServiceBinding {
    try .init(accountOrigin: "https://accounts.example.invalid", realm: practiceRealm(), audience: "",
              allowedAPIOrigins: [practiceOne, practiceTwo])
}
private func account(_ suffix: String = "one") throws -> NativeAccountIdentity {
    try .init(issuer: "https://invented.clerk.accounts.dev", userID: "user_" + suffix, sessionID: "sess_" + suffix)
}
private func selection(nonce: UInt8 = 1, api: String = practiceOne, org: String = "org_one",
                       box: UUID = UUID(), user: NativeAccountIdentity? = nil) throws -> NativePracticeConnectionExpectation {
    try .init(selectionID: UUID(), nonce: UUID(uuid: (nonce,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0)), account: user ?? account(),
              organizationID: org, boxID: box, apiOrigin: api)
}
@MainActor private final class AccountSnapshot {
    var identity: NativeAccountIdentity?
    init(_ identity: NativeAccountIdentity?) { self.identity = identity }
}
@MainActor private final class PracticeService: NativePracticeAccountService {
    let binding: NativePracticeAccountServiceBinding
    var calls = 0
    var body: (@MainActor (NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt)?
    init(_ binding: NativePracticeAccountServiceBinding) { self.binding = binding }
    func resolve(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeAccountServiceReceipt {
        calls += 1
        if let body { return try await body(expectation) }
        return .init(expectation: expectation, expiresAt: Date().addingTimeInterval(300))
    }
}
@MainActor private final class PracticeDriver: NativeAuthDriver {
    var loaded = true
    var identity: NativeAuthIdentity?
    var tokenBody: (@MainActor () async throws -> String?)?
    func signIn() async throws {}
    func signOut() async throws { identity = nil }
    func freshToken() async throws -> String? { try await tokenBody?() }
}
@MainActor private final class PracticeBlock: NativeAuthAccessBlock {
    var value = false
    var writes: [Bool] = []
    func isBlocked() throws -> Bool { value }
    func setBlocked(_ blocked: Bool) throws { value = blocked; writes.append(blocked) }
}
@MainActor private final class PracticeResources: NativePracticeRequestResources {
    let apiOrigin: String
    var isIdle = true
    var fenced = false
    var closed = false
    var closeBody: (@MainActor () async throws -> Void)?
    var onFence: (@MainActor () -> Void)?
    // A stand-in for encrypted storage ownership; switch never receives a delete/copy method.
    var retainedDraft = "Synthetic exact unconfirmed draft"
    init(_ api: String) { apiOrigin = api }
    func fence() { fenced = true; onFence?() }
    func close() async throws { if let closeBody { try await closeBody() }; closed = true }
}
@MainActor private final class PracticeAdmission: NativePracticeWorkspaceAdmission {
    var calls = 0
    var body: (@MainActor (NativePracticeRuntime, String) async throws -> NativePracticeWorkspaceBinding)?
    func admit(_ runtime: NativePracticeRuntime, expectedRevision: String) async throws -> NativePracticeWorkspaceBinding {
        calls += 1
        if let body { return try await body(runtime, expectedRevision) }
        guard let profile = runtime.profile, let identity = runtime.auth.state().identity else {
            throw NativePracticeProfileError.invalidBinding
        }
        return .init(identity: identity, boxID: profile.boxID, actorID: UUID(), apiOrigin: profile.apiOrigin)
    }
}
@MainActor private func minted(_ expectation: NativePracticeConnectionExpectation) async throws -> NativePracticeProfile {
    let binding = try practiceBinding(), service = PracticeService(binding)
    return try await NativePracticeProfileResolver(binding: binding, service: service,
        currentAccount: { expectation.account }).resolve(expectation)
}
@MainActor private func runtime(_ profile: NativePracticeProfile) throws -> (NativePracticeRuntime, PracticeDriver, PracticeResources) {
    let driver = PracticeDriver(), block = PracticeBlock(), resources = PracticeResources(profile.apiOrigin)
    driver.identity = try .init(userID: profile.account.userID, sessionID: "sess_workspace", organizationID: profile.organizationID)
    let auth = NativeWorkspaceAuth(enabled: true, organizationID: profile.organizationID, tokenPolicy: try profile.tokenPolicy,
        driver: { driver }, accessBlock: { block })
    return (try .init(profile: profile, auth: auth, resources: resources), driver, resources)
}
@MainActor private func spin(_ predicate: @MainActor () -> Bool) async throws {
    for _ in 0..<1000 { if predicate() { return }; await Task.yield() }
    throw NativeAuthError.unavailable
}

@Suite @MainActor struct NativePracticeProfileTests {
    @Test func resolverRejectsWrongNonceSessionOrgBoxOrAPIReceipt() async throws {
        let binding = try practiceBinding(), expected = try selection()
        for mutation in 0..<5 {
            let service = PracticeService(binding)
            service.body = { value in
                let changed = try NativePracticeConnectionExpectation(selectionID: value.selectionID,
                    nonce: mutation == 0 ? UUID() : value.nonce,
                    account: mutation == 1 ? account("other") : value.account,
                    organizationID: mutation == 2 ? "org_other" : value.organizationID,
                    boxID: mutation == 3 ? UUID() : value.boxID,
                    apiOrigin: mutation == 4 ? practiceTwo : value.apiOrigin)
                return .init(expectation: changed, expiresAt: Date().addingTimeInterval(300))
            }
            let resolver = try NativePracticeProfileResolver(binding: binding, service: service, currentAccount: { expected.account })
            await #expect(throws: NativePracticeProfileError.invalidBinding) { try await resolver.resolve(expected) }
        }
    }

    @Test func resolverRejectsUnpinnedAPIAndDoesNotDispatch() async throws {
        let binding = try practiceBinding(), service = PracticeService(binding), expected = try selection(api: "https://other.example.invalid")
        let resolver = try NativePracticeProfileResolver(binding: binding, service: service, currentAccount: { expected.account })
        await #expect(throws: NativePracticeProfileError.invalidBinding) { try await resolver.resolve(expected) }
        #expect(service.calls == 0)
    }

    @Test func resolverRejectsAccountChangedWhileReceiptWasPending() async throws {
        let binding = try practiceBinding(), service = PracticeService(binding), expected = try selection()
        let current = AccountSnapshot(expected.account)
        var finish: CheckedContinuation<NativePracticeAccountServiceReceipt, Never>?
        service.body = { _ in await withCheckedContinuation { finish = $0 } }
        let resolver = try NativePracticeProfileResolver(binding: binding, service: service, currentAccount: { current.identity })
        let task = Task { try await resolver.resolve(expected) }
        try await spin { finish != nil }; current.identity = try account("replacement")
        finish?.resume(returning: .init(expectation: expected, expiresAt: Date().addingTimeInterval(300))); finish = nil
        await #expect(throws: NativePracticeProfileError.sessionChanged) { try await task.value }
    }

    @Test func resolverRejectsReplayEvenWithDifferentSelectionID() async throws {
        let binding = try practiceBinding(), service = PracticeService(binding), expected = try selection()
        let resolver = try NativePracticeProfileResolver(binding: binding, service: service, currentAccount: { expected.account })
        _ = try await resolver.resolve(expected)
        await #expect(throws: NativePracticeProfileError.invalidBinding) { try await resolver.resolve(expected) }
        let replay = try selection(box: expected.boxID)
        await #expect(throws: NativePracticeProfileError.invalidBinding) { try await resolver.resolve(replay) }
        #expect(service.calls == 1)
    }

    @Test func stablePracticeNamespaceIsolatesUsersBoxesAPIsAndKeepsLegacyQueries() async throws {
        let box = UUID(), first = try selection(box: box)
        let a = try await minted(first), renewed = try await minted(selection(nonce: 2, box: box))
        let otherAPI = try await minted(selection(nonce: 3, api: practiceTwo, box: box))
        let otherBox = try await minted(selection(nonce: 4))
        let otherUser = try await minted(selection(nonce: 5, box: box, user: account("two")))
        #expect(a.storageNamespace == renewed.storageNamespace)
        #expect(Set([a.storageNamespace, otherAPI.storageNamespace, otherBox.storageNamespace, otherUser.storageNamespace]).count == 4)
        let realm = try practiceRealm()
        let unscoped = try NativeClerkConfiguration(publishableKey: realm.publishableKey, frontendOrigin: realm.frontendOrigin,
            organizationID: "org_one", bundleIdentifier: realm.bundleIdentifier, profile: .operationalStaging)
        #expect(unscoped.keychainService == "com.cosmasos.beta.ios.clerk.invented.clerk.accounts.dev")
        #expect(a.configuration.keychainService == realm.keychainService)
        #expect(a.storageNamespace != realm.storageNamespace)
        let legacy = try KeychainAccessBlock(bundleIdentifier: realm.bundleIdentifier, profile: .operationalStaging)
        let selected = try KeychainAccessBlock(bundleIdentifier: realm.bundleIdentifier, profile: .operationalStaging,
            profileNamespace: a.storageNamespace)
        #expect(legacy.operationQuery() as NSDictionary != selected.operationQuery() as NSDictionary)
    }

    @Test func activationFencesOriginalResourcesBeforeFactoryAndPreservesDraft() async throws {
        let oldProfile = try await minted(selection()), nextProfile = try await minted(selection(nonce: 2, api: practiceTwo, org: "org_two"))
        let (old, _, oldResources) = try runtime(oldProfile), admission = PracticeAdmission()
        var factoryCalls = 0
        oldResources.onFence = { #expect(old.auth.isRetired) }
        let owner = NativePracticeActivationOwner(retainedDefault: old, admission: admission) { profile in
            factoryCalls += 1
            #expect(old.auth.isRetired && oldResources.fenced && oldResources.closed && oldResources.isIdle)
            return try runtime(profile).0
        }
        let before = owner.state()
        #expect(owner.current === old && !old.auth.isRetired && factoryCalls == 0)
        let result = try await owner.activate(nextProfile, expectedRevision: before.revision)
        #expect(result.phase == .ready && result.profileID == nextProfile.id && factoryCalls == 1 && admission.calls == 1)
        #expect(owner.current?.resources.apiOrigin == practiceTwo && oldResources.retainedDraft == "Synthetic exact unconfirmed draft")
        #expect(old.auth.state().phase == .unavailable)
    }

    @Test func activationWaitsForAbandonedSDKOwnershipBeforeReconfiguring() async throws {
        let profile = try await minted(selection()), nextProfile = try await minted(selection(nonce: 2, api: practiceTwo))
        let (old, driver, _) = try runtime(profile), admission = PracticeAdmission()
        var finish: CheckedContinuation<String?, Never>?, factoryCalls = 0
        driver.tokenBody = { await withCheckedContinuation { finish = $0 } }
        let revision = old.auth.state().revision, token = Task { try await old.auth.token(expectedRevision: revision) }
        try await spin { finish != nil }
        let owner = NativePracticeActivationOwner(retainedDefault: old, admission: admission) { profile in
            factoryCalls += 1; return try runtime(profile).0
        }
        await #expect(throws: NativePracticeProfileError.busy) { try await owner.activate(nextProfile, expectedRevision: owner.state().revision) }
        #expect(factoryCalls == 0 && owner.current == nil && old.auth.hasUnsettledOperations)
        finish?.resume(returning: nil); finish = nil
        _ = await token.result; try await spin { !old.auth.hasUnsettledOperations }
        _ = try await owner.activate(nextProfile, expectedRevision: owner.state().revision)
        #expect(factoryCalls == 1 && owner.current?.profile == nextProfile)
    }

    @Test func activationRejectsWrongBoxAndDoesNotFallbackToDefault() async throws {
        let profile = try await minted(selection()), admission = PracticeAdmission()
        let (old, _, _) = try runtime(profile)
        var candidate: NativePracticeRuntime?
        admission.body = { next, _ in
            .init(identity: next.auth.state().identity!, boxID: UUID(), actorID: UUID(), apiOrigin: profile.apiOrigin)
        }
        let owner = NativePracticeActivationOwner(retainedDefault: old, admission: admission) { selected in
            let next = try runtime(selected).0; candidate = next; return next
        }
        await #expect(throws: NativePracticeProfileError.invalidBinding) { try await owner.activate(profile, expectedRevision: owner.state().revision) }
        #expect(owner.current == nil && owner.state().phase == .unavailable && old.auth.isRetired && candidate?.auth.isRetired == true)
    }

    @Test func activationRejectsConcurrentSwitchAndLateChangedIdentity() async throws {
        let profile = try await minted(selection()), admission = PracticeAdmission()
        var finish: CheckedContinuation<NativePracticeWorkspaceBinding, Never>?, candidate: NativePracticeRuntime?, driver: PracticeDriver?
        admission.body = { _, _ in await withCheckedContinuation { finish = $0 } }
        let owner = NativePracticeActivationOwner(admission: admission) { selected in
            let (next, native, _) = try runtime(selected); candidate = next; driver = native; return next
        }
        let initial = owner.state().revision, task = Task { try await owner.activate(profile, expectedRevision: initial) }
        try await spin { finish != nil }
        await #expect(throws: NativePracticeProfileError.busy) { try await owner.activate(profile, expectedRevision: initial) }
        let original = candidate!.auth.state().identity!
        driver?.identity = try .init(userID: "user_other", sessionID: "sess_other", organizationID: profile.organizationID)
        finish?.resume(returning: .init(identity: original, boxID: profile.boxID, actorID: UUID(), apiOrigin: profile.apiOrigin)); finish = nil
        await #expect(throws: NativePracticeProfileError.invalidBinding) { try await task.value }
        #expect(owner.current == nil && candidate?.auth.isRetired == true)
    }

    @Test func runtimeRejectsMismatchedNativeAuthPolicyBeforeAdmission() async throws {
        let profile = try await minted(selection()), driver = PracticeDriver(), block = PracticeBlock()
        let wrong = try NativeTokenPolicy(issuer: "https://other.clerk.accounts.dev", audience: "",
            nativeSessionWithoutOrigin: true, sharedStagingSession: true)
        let auth = NativeWorkspaceAuth(enabled: true, organizationID: profile.organizationID, tokenPolicy: wrong,
            driver: { driver }, accessBlock: { block })
        #expect(throws: NativePracticeProfileError.invalidBinding) {
            try NativePracticeRuntime(profile: profile, auth: auth, resources: PracticeResources(profile.apiOrigin))
        }
    }
}
