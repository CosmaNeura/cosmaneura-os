import Foundation
import Security
import Testing
@testable import CosmasNativeAuth

@Suite @MainActor struct KeychainInteractionPolicyTests {
    @Test func backgroundQueryRefusesUIAndRestoresPriorQueryOnlyExplicitly() async throws {
        let block = try KeychainAccessBlock(bundleIdentifier: "com.cosmasos.beta.desktop.auth",
            profile: .operationalBeta, allowsAuthenticationUI: false)
        let background = block.operationQuery()
        #expect(background[kSecUseAuthenticationUI] as? String == kSecUseAuthenticationUIFail as String)
        #expect(block.availability == .unknown)
        await block.withAuthenticationUI {
            let interactive = block.operationQuery()
            #expect(interactive[kSecUseAuthenticationUI] == nil)
            #expect(background[kSecAttrService] as? String == interactive[kSecAttrService] as? String)
            #expect(background[kSecAttrAccount] as? String == interactive[kSecAttrAccount] as? String)
            let unrelated = Task.detached { @MainActor in
                block.operationQuery()[kSecUseAuthenticationUI] as? String == kSecUseAuthenticationUIFail as String
            }
            #expect(await unrelated.value == true)
        }
        #expect(block.operationQuery()[kSecUseAuthenticationUI] as? String == kSecUseAuthenticationUIFail as String)
    }

    @Test func existingAppleDefaultRetainsItsQueryPolicy() throws {
        let block = try KeychainAccessBlock(bundleIdentifier: "com.cosmasos.beta.ios", profile: .operationalBeta)
        #expect(block.allowsAuthenticationUI)
        #expect(block.operationQuery()[kSecUseAuthenticationUI] == nil)
    }

    @Test func diagnosticClassifiesOnlyClosedSecurityStatuses() {
        #expect(KeychainAccessBlock.availability(for: errSecSuccess) == .available)
        #expect(KeychainAccessBlock.availability(for: errSecItemNotFound) == .available)
        #expect(KeychainAccessBlock.availability(for: errSecInteractionNotAllowed) == .interactionRequired)
        #expect(KeychainAccessBlock.availability(for: errSecAuthFailed) == .unavailable)
        #expect(KeychainAccessBlock.availability(for: errSecUserCanceled) == .unavailable)
    }

    @Test func deniedBootstrapNeedsExplicitReconstructionAndSignIn() async throws {
        let block = PolicyBlock(), driver = PolicyDriver()
        var creations = 0
        let policy = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "cosmas-workspace-local")
        func make() -> NativeWorkspaceAuth {
            NativeWorkspaceAuth(enabled: true, organizationID: "org_invented", tokenPolicy: policy,
                driver: { creations += 1; return driver }, accessBlock: { block })
        }
        let denied = make()
        #expect(denied.state().phase == .unavailable)
        #expect(denied.allowsStorageRecovery)
        #expect(creations == 0)
        block.permit = true
        #expect(denied.state().phase == .unavailable)
        let recovered = make()
        #expect(recovered.state().phase == .signedOut)
        #expect(!recovered.allowsStorageRecovery)
        #expect(driver.signIns == 0)
        #expect(creations == 1)
        let ready = try await recovered.signIn()
        #expect(ready.phase == .ready)
        #expect(driver.signIns == 1)
        #expect(block.writes == [true, false])
    }

    @Test func storageRecoveryWaitsForPendingSDKTokenToSettle() async throws {
        let block = PolicyBlock(), driver = PolicyDriver()
        block.permit = true
        driver.identity = try NativeAuthIdentity(userID: "user_invented", sessionID: "sess_invented", organizationID: "org_invented")
        let policy = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "cosmas-workspace-local")
        let auth = NativeWorkspaceAuth(enabled: true, organizationID: "org_invented", tokenPolicy: policy,
            driver: { driver }, accessBlock: { block })
        let revision = auth.state().revision
        var continuation: CheckedContinuation<String?, Never>?
        driver.tokenBody = { await withCheckedContinuation { continuation = $0 } }
        let request = Task { try? await auth.token(expectedRevision: revision) }
        for _ in 0..<1000 where continuation == nil { await Task.yield() }
        let pending = try #require(continuation)
        block.permit = false
        #expect(auth.state().phase == .unavailable)
        #expect(!auth.allowsStorageRecovery)
        pending.resume(returning: nil)
        _ = await request.value
        #expect(auth.allowsStorageRecovery)
    }

    @Test(arguments: [true, false])
    func storageRecoveryWaitsForAbandonedSDKMutation(signingIn: Bool) async throws {
        let block = PolicyBlock(), driver = PolicyDriver()
        block.permit = true
        let policy = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "cosmas-workspace-local")
        let auth = NativeWorkspaceAuth(enabled: true, organizationID: "org_invented", tokenPolicy: policy,
            driver: { driver }, accessBlock: { block })
        var continuation: CheckedContinuation<Void, Never>?
        driver.mutationBody = { await withCheckedContinuation { continuation = $0 } }
        let request = Task {
            if signingIn { return try? await auth.signIn() }
            return try? await auth.signOut()
        }
        for _ in 0..<1000 where continuation == nil { await Task.yield() }
        let pending = try #require(continuation)
        request.cancel()
        _ = await request.value
        block.permit = false
        #expect(auth.state().phase == .unavailable)
        #expect(!auth.allowsStorageRecovery)
        pending.resume()
        for _ in 0..<1000 where !auth.allowsStorageRecovery { await Task.yield() }
        #expect(auth.allowsStorageRecovery)
        #expect(block.value)
    }
}

@MainActor private final class PolicyBlock: NativeAuthAccessBlock {
    var permit = false
    var value = false
    var writes: [Bool] = []
    func isBlocked() throws -> Bool {
        guard permit else { throw NativeAuthError.storageUnavailable }
        return value
    }
    func setBlocked(_ blocked: Bool) throws { value = blocked; writes.append(blocked) }
}

@MainActor private final class PolicyDriver: NativeAuthDriver {
    var loaded = true
    var identity: NativeAuthIdentity?
    var signIns = 0
    var tokenBody: (@MainActor () async -> String?)?
    var mutationBody: (@MainActor () async -> Void)?
    func signIn() async throws {
        signIns += 1
        await mutationBody?()
        identity = try NativeAuthIdentity(userID: "user_invented", sessionID: "sess_invented", organizationID: "org_invented")
    }
    func signOut() async throws { await mutationBody?(); identity = nil }
    func freshToken() async throws -> String? { await tokenBody?() }
}
