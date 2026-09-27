import Foundation
import Testing
@testable import CosmasNativeAuth

private func identity(_ suffix: String = "one") throws -> NativeAuthIdentity {
    try NativeAuthIdentity(userID: "user_" + suffix, sessionID: "sess_" + suffix, organizationID: "org_one")
}

private func policy() throws -> NativeTokenPolicy {
    try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "cosmas-workspace-local")
}

private func jwt(_ user: NativeAuthIdentity, changes: [String: Any] = [:], omit: [String] = []) throws -> String {
    let now = Int(Date().timeIntervalSince1970)
    var claims: [String: Any] = [
        "sub": user.userID, "sid": user.sessionID, "org_id": user.organizationID,
        "iss": "https://invented.clerk.accounts.dev", "aud": "cosmas-workspace-local",
        "azp": "capacitor://localhost", "exp": now + 60, "iat": now, "nbf": now,
    ]
    claims.merge(changes) { _, value in value }
    for name in omit { claims.removeValue(forKey: name) }
    func encode(_ value: [String: Any]) throws -> String {
        try JSONSerialization.data(withJSONObject: value, options: .sortedKeys).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
    // Deliberately not a cryptographic signature: only the API authenticates JWTs.
    return try encode(["alg": "RS256", "kid": "synthetic"]) + "." + encode(claims) + ".c3ludGhldGlj"
}

@MainActor private final class Block: NativeAuthAccessBlock {
    var value = false
    var failRead = false
    var failWrite = false
    var writes: [Bool] = []
    func isBlocked() throws -> Bool {
        if failRead { throw NativeAuthError.storageUnavailable }
        return value
    }
    func setBlocked(_ blocked: Bool) throws {
        if failWrite { throw NativeAuthError.storageUnavailable }
        value = blocked
        writes.append(blocked)
    }
}

@MainActor private final class Driver: NativeAuthDriver {
    var loaded = true
    var identity: NativeAuthIdentity?
    var tokenCalls = 0
    var signInCalls = 0
    var signOutCalls = 0
    var tokenBody: (@MainActor () async throws -> String?)?
    var signInBody: (@MainActor () async throws -> Void)?
    var signOutBody: (@MainActor () async throws -> Void)?
    func signIn() async throws {
        signInCalls += 1
        if let signInBody { try await signInBody() }
    }
    func signOut() async throws {
        signOutCalls += 1
        if let signOutBody { try await signOutBody() }
        else { identity = nil }
    }
    func freshToken() async throws -> String? {
        tokenCalls += 1
        if let tokenBody { return try await tokenBody() }
        return try identity.map { try jwt($0) }
    }
}

@MainActor private func controller(_ driver: Driver, _ block: Block) throws -> NativeWorkspaceAuth {
    NativeWorkspaceAuth(enabled: true, organizationID: "org_one", tokenPolicy: try policy(),
                        driver: { driver }, accessBlock: { block })
}

@MainActor private func spinUntil(_ condition: @MainActor () -> Bool) async throws {
    for _ in 0..<1000 {
        if condition() { return }
        await Task.yield()
    }
    throw NativeAuthError.unavailable
}

@Suite @MainActor struct NativeWorkspaceAuthTests {
    @Test func recordingNamespaceSurvivesSessionRenewalButRejectsOldRevision() throws {
        let driver = Driver(), block = Block()
        driver.identity = try identity()
        let auth = try controller(driver, block)
        let first = auth.state()
        let digest = try auth.recordingAccountDigest(expectedRevision: first.revision)
        #expect(digest.count == 64)
        driver.identity = try NativeAuthIdentity(userID: "user_one", sessionID: "sess_renewed", organizationID: "org_one")
        let next = auth.state()
        #expect(next.revision != first.revision)
        #expect(try auth.recordingAccountDigest(expectedRevision: next.revision) == digest)
        #expect(throws: NativeAuthError.sessionChanged) {
            try auth.recordingAccountDigest(expectedRevision: first.revision)
        }
        block.value = true
        #expect(throws: NativeAuthError.sessionChanged) {
            try auth.recordingAccountDigest(expectedRevision: next.revision)
        }
    }

    @Test func recordingNamespaceSeparatesAccountsAndNativePolicies() throws {
        func digest(user: String = "user_one", org: String = "org_one",
                    issuer: String = "https://invented.clerk.accounts.dev",
                    audience: String = "cosmas-workspace-local", origin: String = "capacitor://localhost",
                    withoutOrigin: Bool = false, shared: Bool = false) throws -> String {
            let driver = Driver(), block = Block()
            driver.identity = try NativeAuthIdentity(userID: user, sessionID: "sess_one", organizationID: org)
            let policy = try NativeTokenPolicy(issuer: issuer, audience: audience, authorizedParty: origin,
                nativeSessionWithoutOrigin: withoutOrigin, sharedStagingSession: shared)
            let auth = NativeWorkspaceAuth(enabled: true, organizationID: org, tokenPolicy: policy,
                driver: { driver }, accessBlock: { block })
            return try auth.recordingAccountDigest(expectedRevision: auth.state().revision)
        }
        let values = try [digest(), digest(user: "user_two"), digest(org: "org_two"),
            digest(issuer: "https://other.clerk.accounts.dev"), digest(audience: "other-api"),
            digest(origin: "app://cosmas"), digest(withoutOrigin: true), digest(audience: "", shared: true)]
        #expect(Set(values).count == values.count)
    }

    @Test func sharedStagingSessionsRequireAbsentAudienceAndRetainIdentityChecks() throws {
        let user = try identity()
        for origin in ["capacitor://localhost", "app://cosmas"] {
            let shared = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev",
                audience: "", authorizedParty: origin, nativeSessionWithoutOrigin: true, sharedStagingSession: true)
            try shared.validate(jwt(user, omit: ["aud", "azp"]), identity: user)
            for value: Any in ["cosmas-workspace-local", "", [], NSNull()] {
                #expect(throws: NativeAuthError.tokenUnavailable) {
                    try shared.validate(jwt(user, changes: ["aud": value], omit: ["azp"]), identity: user)
                }
            }
            for changes: [String: Any] in [["azp": NSNull()], ["azp": "https://other.invalid"],
                ["iss": "https://other.clerk.accounts.dev"], ["org_id": "org_other"],
                ["sub": "user_other"], ["sid": "sess_other"], ["exp": 1]] {
                #expect(throws: NativeAuthError.tokenUnavailable) {
                    try shared.validate(jwt(user, changes: changes,
                        omit: changes["azp"] == nil ? ["aud", "azp"] : ["aud"]), identity: user)
                }
            }
        }
        for (issuer, audience, shared) in [
            ("https://invented.clerk.accounts.dev", "", false),
            ("https://invented.clerk.accounts.dev", "other-api", true),
            ("https://production.example.invalid", "", true),
        ] {
            #expect(throws: NativeAuthError.unavailable) {
                try NativeTokenPolicy(issuer: issuer, audience: audience, sharedStagingSession: shared)
            }
        }
    }

    @Test func nativeSessionsWithoutOriginRetainIdentityAndRejectWrongPresentOrigin() throws {
        let user = try identity()
        let token = try jwt(user, omit: ["azp"])
        #expect(throws: NativeAuthError.tokenUnavailable) { try policy().validate(token, identity: user) }
        for origin in ["capacitor://localhost", "app://cosmas"] {
            let native = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev",
                audience: "cosmas-workspace-local", authorizedParty: origin, nativeSessionWithoutOrigin: true)
            try native.validate(token, identity: user)
            try native.validate(jwt(user, changes: ["azp": origin]), identity: user)
            for changes: [String: Any] in [["azp": NSNull()], ["azp": "https://other.invalid"],
                ["azp": origin == "app://cosmas" ? "capacitor://localhost" : "app://cosmas"],
                ["iss": "https://other.invalid"], ["aud": "other-api"], ["org_id": "org_other"],
                ["sub": "user_other"], ["sid": "sess_other"], ["exp": 1]] {
                #expect(throws: NativeAuthError.tokenUnavailable) {
                    try native.validate(jwt(user, changes: changes, omit: changes["azp"] == nil ? ["azp"] : []), identity: user)
                }
            }
        }
    }

    @Test func desktopAndAppleTokensCannotCrossNativeOrigins() throws {
        let user = try identity()
        let desktop = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev",
            audience: "cosmas-workspace-local", authorizedParty: "app://cosmas")
        let desktopToken = try jwt(user, changes: ["azp": "app://cosmas"])
        try desktop.validate(desktopToken, identity: user)
        #expect(throws: NativeAuthError.tokenUnavailable) { try policy().validate(desktopToken, identity: user) }
        #expect(throws: NativeAuthError.tokenUnavailable) { try desktop.validate(jwt(user), identity: user) }
        #expect(throws: NativeAuthError.unavailable) {
            try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "cosmas-workspace-local",
                                  authorizedParty: "app://other")
        }
    }
    @Test func disabledDoesNotConstructSDKOrOpenKeychain() {
        let auth = NativeWorkspaceAuth(enabled: false, organizationID: "", driver: {
            Issue.record("SDK initialized while disabled"); throw NativeAuthError.unavailable
        }, accessBlock: {
            Issue.record("Keychain opened while disabled"); throw NativeAuthError.unavailable
        })
        #expect(auth.state().phase == .disabled)
    }

    @Test func readFailurePrecedesSDKConstruction() throws {
        let block = Block(); block.failRead = true
        let auth = NativeWorkspaceAuth(enabled: true, organizationID: "org_one", tokenPolicy: try policy(), driver: {
            Issue.record("SDK initialized despite unavailable local state"); throw NativeAuthError.unavailable
        }, accessBlock: { block })
        #expect(auth.state().phase == .unavailable)
    }

    @Test func restorationKeepsStableRevisionAndRequestsFreshTokens() async throws {
        let driver = Driver(); driver.identity = try identity()
        let auth = try controller(driver, Block())
        let first = auth.state()
        #expect(first.phase == .ready && first.identity == driver.identity)
        #expect(auth.state().revision == first.revision)
        _ = try await auth.token(expectedRevision: first.revision)
        _ = try await auth.token(expectedRevision: first.revision)
        #expect(driver.tokenCalls == 2)
    }

    @Test func hostedSignInPersistsBlockUntilExactOrganizationIsActive() async throws {
        let driver = Driver(), block = Block()
        driver.signInBody = {
            #expect(block.value)
            driver.identity = try identity()
        }
        let auth = try controller(driver, block)
        let result = try await auth.signIn()
        #expect(result.phase == .ready && result.identity == driver.identity)
        #expect(block.writes == [true, false])
    }

    @Test func wrongOrganizationStaysBlocked() async throws {
        let driver = Driver(), block = Block()
        driver.signInBody = {
            driver.identity = try NativeAuthIdentity(userID: "user_one", sessionID: "sess_one", organizationID: "org_foreign")
        }
        let auth = try controller(driver, block)
        await #expect(throws: NativeAuthError.signInFailed) { try await auth.signIn() }
        #expect(auth.state().phase == .signOutPending && block.value)
        #expect(try controller(driver, block).state().phase == .signOutPending)
    }

    @Test func oldIdentityCannotReceiveLateToken() async throws {
        let driver = Driver(); let original = try identity(); driver.identity = original
        var pending: CheckedContinuation<String?, any Error>?
        driver.tokenBody = { try await withCheckedThrowingContinuation { pending = $0 } }
        let auth = try controller(driver, Block()); let current = auth.state()
        let task = Task { try await auth.token(expectedRevision: current.revision) }
        try await spinUntil { pending != nil }
        driver.identity = try identity("two")
        #expect(auth.state().revision != current.revision)
        pending?.resume(returning: try jwt(original))
        await #expect(throws: NativeAuthError.tokenUnavailable) { try await task.value }
    }

    @Test func intermediateIdentityTokenIsRejectedEvenIfSDKReturnsToOriginalUser() async throws {
        let driver = Driver(); driver.identity = try identity()
        driver.tokenBody = { try jwt(identity("two")) }
        let auth = try controller(driver, Block()); let current = auth.state()
        await #expect(throws: NativeAuthError.tokenUnavailable) {
            try await auth.token(expectedRevision: current.revision)
        }
    }

    @Test func failedLogoutRemainsBlockedAcrossRestartAndRetries() async throws {
        let driver = Driver(), block = Block(); driver.identity = try identity()
        driver.signOutBody = { throw NativeAuthError.unavailable }
        let auth = try controller(driver, block); let original = auth.state()
        await #expect(throws: NativeAuthError.signOutPending) { try await auth.signOut() }
        #expect(block.value && auth.state().identity == nil)
        let restarted = try controller(driver, block)
        #expect(restarted.state().phase == .signOutPending)
        await #expect(throws: NativeAuthError.sessionChanged) {
            try await restarted.token(expectedRevision: original.revision)
        }
        driver.signOutBody = nil
        #expect(try await restarted.signOut().phase == .signedOut)
        #expect(!block.value)
    }

    @Test func logoutFencesTokenAlreadyInFlight() async throws {
        let driver = Driver(), block = Block(); let original = try identity(); driver.identity = original
        var pending: CheckedContinuation<String?, any Error>?
        driver.tokenBody = { try await withCheckedThrowingContinuation { pending = $0 } }
        let auth = try controller(driver, block); let state = auth.state()
        let task = Task { try await auth.token(expectedRevision: state.revision) }
        try await spinUntil { pending != nil }
        _ = try await auth.signOut()
        pending?.resume(returning: try jwt(original))
        await #expect(throws: NativeAuthError.tokenUnavailable) { try await task.value }
    }

    @Test func lateHostedSignInCannotUndoLogout() async throws {
        let driver = Driver(), block = Block()
        var pending: CheckedContinuation<Void, Never>?
        driver.signInBody = {
            await withCheckedContinuation { pending = $0 }
            driver.identity = try identity()
        }
        let auth = try controller(driver, block)
        let task = Task { try await auth.signIn() }
        try await spinUntil { pending != nil }
        await #expect(throws: NativeAuthError.busy) { try await auth.signIn() }
        await #expect(throws: NativeAuthError.signOutPending) { try await auth.signOut() }
        pending?.resume()
        await #expect(throws: NativeAuthError.signInFailed) { try await task.value }
        #expect(auth.state().phase == .signOutPending && block.value)
        #expect(try controller(driver, block).state().phase == .signOutPending)
        _ = try await auth.signOut()
        #expect(driver.identity == nil && !block.value)
    }

    @Test func cancelledHostedSignInRequiresExplicitRecovery() async throws {
        let driver = Driver(), block = Block()
        var pending: CheckedContinuation<Void, Never>?
        driver.signInBody = {
            await withCheckedContinuation { pending = $0 }
            driver.identity = try identity()
        }
        let auth = try controller(driver, block)
        let task = Task { try await auth.signIn() }
        try await spinUntil { pending != nil }
        task.cancel(); pending?.resume()
        await #expect(throws: NativeAuthError.signInFailed) { try await task.value }
        #expect(try controller(driver, block).state().phase == .signOutPending)
    }

    @Test func cancellationReturnsEvenWhenHostedSDKIgnoresCancellation() async throws {
        let driver = Driver(), block = Block()
        var pending: CheckedContinuation<Void, Never>?
        driver.signInBody = {
            await withCheckedContinuation { pending = $0 }
            driver.identity = try identity()
        }
        let auth = try controller(driver, block)
        var finished = false
        let task = Task {
            do { _ = try await auth.signIn(); Issue.record("Cancelled sign-in succeeded") }
            catch { finished = true }
        }
        try await spinUntil { pending != nil }
        task.cancel()
        for _ in 0..<1000 { if finished { break }; await Task.yield() }
        #expect(finished, "The caller must recover without waiting for the hosted SDK")
        #expect(auth.state().phase == .signOutPending && block.value)
        pending?.resume(); await task.value
        #expect(block.value)
    }

    @Test func timedOutHostedSignInCannotReopenAccessOrOverlapAnotherSignIn() async throws {
        let driver = Driver(), block = Block()
        var pending: CheckedContinuation<Void, Never>?
        var sdkEnded = false
        driver.signInBody = {
            await withCheckedContinuation { pending = $0 }
            driver.identity = try identity(); sdkEnded = true
        }
        let auth = try controller(driver, block); auth.signInTimeout = .milliseconds(10)
        await #expect(throws: NativeAuthError.signInFailed) { try await auth.signIn() }
        #expect(pending != nil && !sdkEnded && block.value)
        await #expect(throws: NativeAuthError.busy) { try await auth.signIn() }
        await #expect(throws: NativeAuthError.signOutPending) { try await auth.signOut() }
        pending?.resume(); try await spinUntil { sdkEnded }; await Task.yield()
        #expect(auth.state().phase == .signOutPending)
        #expect(try controller(driver, block).state().phase == .signOutPending)
        _ = try await auth.signOut()
        #expect(driver.identity == nil && !block.value && driver.signInCalls == 1)
    }

    @Test func timedOutLogoutKeepsDurableBlockUntilExplicitConfirmedRetry() async throws {
        let driver = Driver(), block = Block(); driver.identity = try identity()
        var pending: CheckedContinuation<Void, Never>?
        var sdkEnded = false
        driver.signOutBody = {
            await withCheckedContinuation { pending = $0 }
            driver.identity = nil; sdkEnded = true
        }
        let auth = try controller(driver, block); auth.networkTimeout = .milliseconds(10)
        await #expect(throws: NativeAuthError.signOutPending) { try await auth.signOut() }
        #expect(pending != nil && !sdkEnded && block.value)
        await #expect(throws: NativeAuthError.busy) { try await auth.signOut() }
        await #expect(throws: NativeAuthError.busy) { try await auth.signIn() }
        pending?.resume(); try await spinUntil { sdkEnded }; await Task.yield()
        #expect(auth.state().phase == .signOutPending && block.value)
        driver.signOutBody = nil
        #expect(try await auth.signOut().phase == .signedOut)
        #expect(!block.value)
    }

    @Test func abandonedTokensAreBoundedAndLateValuesCannotEscape() async throws {
        let driver = Driver(), block = Block(); let user = try identity(); driver.identity = user
        var pending: [CheckedContinuation<String?, any Error>] = []
        var sdkEnded = 0
        driver.tokenBody = {
            let value = try await withCheckedThrowingContinuation { pending.append($0) }
            sdkEnded += 1; return value
        }
        let auth = try controller(driver, block); auth.networkTimeout = .milliseconds(2)
        for _ in 0..<8 {
            let state = auth.state()
            await #expect(throws: NativeAuthError.tokenUnavailable) { try await auth.token(expectedRevision: state.revision) }
        }
        #expect(pending.count == 8 && sdkEnded == 0)
        let state = auth.state()
        await #expect(throws: NativeAuthError.tokenUnavailable) { try await auth.token(expectedRevision: state.revision) }
        #expect(driver.tokenCalls == 8)
        for continuation in pending { continuation.resume(returning: try jwt(user)) }
        try await spinUntil { sdkEnded == 8 }; await Task.yield()
        driver.tokenBody = nil
        let fresh = auth.state()
        #expect(try await auth.token(expectedRevision: fresh.revision) == jwt(user))
        #expect(driver.tokenCalls == 9)
    }

    @Test func uncoalescedCombinedWorkStartupExceedsEightNativeTasks() async throws {
        let driver = Driver(), block = Block(), user = try identity()
        driver.identity = user
        var pending: [CheckedContinuation<String?, any Error>] = []
        driver.tokenBody = { try await withCheckedThrowingContinuation { pending.append($0) } }
        let auth = try controller(driver, block), revision = auth.state().revision
        // C1: authority + two reads; finance: authority + two reads;
        // portal: authority + three reads. The renderer must coalesce this burst.
        var rejected = 0
        let tasks = (0..<10).map { _ in Task { @MainActor in
            do { _ = try await auth.token(expectedRevision: revision); return true }
            catch { rejected += 1; return false }
        } }
        try await spinUntil { pending.count == 8 && rejected == 2 }
        #expect(driver.tokenCalls == 8)
        #expect(auth.state().revision == revision)
        for continuation in pending { continuation.resume(returning: try jwt(user)) }
        var accepted = 0
        for task in tasks { if await task.value { accepted += 1 } }
        #expect(accepted == 8 && rejected == 2)
    }

    @Test func sdkLoadingHasABoundedWaitAndCanRecover() async throws {
        let driver = Driver(); driver.loaded = false
        let auth = try controller(driver, Block()); auth.networkTimeout = .milliseconds(2)
        #expect(auth.state().phase == .loading)
        try await Task.sleep(for: .milliseconds(5))
        #expect(auth.state().phase == .unavailable)
        driver.loaded = true
        #expect(auth.state().phase == .signedOut)
    }

    @Test func storageWriteFailureLatchesLocalAccessClosed() async throws {
        let driver = Driver(), block = Block(); driver.identity = try identity()
        let auth = try controller(driver, block); let current = auth.state()
        block.failWrite = true
        await #expect(throws: NativeAuthError.signOutPending) { try await auth.signOut() }
        block.failWrite = false
        #expect(auth.state().phase == .unavailable)
        await #expect(throws: NativeAuthError.sessionChanged) { try await auth.token(expectedRevision: current.revision) }
        #expect(driver.tokenCalls == 0)
    }

    @Test(arguments: ["sub", "sid", "org_id", "iss", "aud", "azp", "exp", "nbf", "iat"])
    func tokenBindingRejectsInvalidClaims(_ claim: String) throws {
        let user = try identity()
        let replacement: Any = ["exp", "nbf", "iat"].contains(claim) ? true : "wrong"
        #expect(throws: NativeAuthError.tokenUnavailable) {
            try policy().validate(jwt(user, changes: [claim: replacement]), identity: user)
        }
    }

    @Test func compactOrganizationAndAudienceListAreSupportedWithoutConflictingClaims() throws {
        let user = try identity()
        try policy().validate(jwt(user, changes: ["aud": ["cosmas-workspace-local"],
                                                 "o": ["id": "org_one"]]), identity: user)
        #expect(throws: NativeAuthError.tokenUnavailable) {
            try policy().validate(jwt(user, changes: ["o": ["id": "org_foreign"]]), identity: user)
        }
    }
}
