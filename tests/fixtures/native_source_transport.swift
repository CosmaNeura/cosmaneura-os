import Foundation
import CosmasNativeAuth

/// Emit the actual native request without starting a session or touching Keychain.
@main struct NativeSourceTransportProbe {
    @MainActor static func main() async throws {
        let workspace = "00000000-0000-4000-8000-000000000101"
        let session = "00000000-0000-4000-8000-000000000102"
        let transport = try WorkspaceSourceTransport(settings: [
            "enabled": true, "apiOrigin": "https://api.example.invalid",
        ])
        var rows = try ["source_start", "source_extend", "native_recording_context"].map { kind in
            let body = try JSONSerialization.data(withJSONObject: [
                "workspace_id": workspace, "session_id": session,
                "operation": ["kind": kind],
            ])
            let operation = kind == "native_recording_context"
                ? try ProviderNativeRequest(recordingContextID: UUID(uuidString: "00000000-0000-4000-8000-000000000103")!,
                    revision: UUID().uuidString.lowercased(), workspaceID: UUID(uuidString: workspace)!,
                    sessionID: UUID(uuidString: session)!)
                : try ProviderNativeRequest(nativeStartID: UUID(),
                    revision: UUID().uuidString.lowercased(), key: "synthetic-source-key", body: body)
            let request = try transport.makeRequest(operation, token: "synthetic-test-token")
            return ["kind": kind, "url": request.url!.absoluteString,
                "method": request.httpMethod!, "headers": request.allHTTPHeaderFields!,
                "body_base64": request.httpBody!.base64EncodedString()] as [String: Any]
        }
        rows.append(try await contextChecks(transport: transport))
        let encoded = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
        FileHandle.standardOutput.write(encoded)
    }
}

@MainActor private final class ContextBlock: NativeAuthAccessBlock {
    func isBlocked() throws -> Bool { false }
    func setBlocked(_ blocked: Bool) throws {}
}

@MainActor private final class ContextDriver: NativeAuthDriver {
    var loaded = true
    var identity: NativeAuthIdentity? = try! NativeAuthIdentity(
        userID: "user_synthetic", sessionID: "sess_synthetic", organizationID: "org_synthetic")
    func signIn() async throws {}
    func signOut() async throws { identity = nil }
    func freshToken() async throws -> String? {
        guard let identity else { return nil }
        func encode(_ value: [String: Any]) throws -> String {
            try JSONSerialization.data(withJSONObject: value).base64EncodedString()
                .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
                .replacingOccurrences(of: "=", with: "")
        }
        let now = Int(Date().timeIntervalSince1970)
        return try encode(["alg": "RS256", "kid": "synthetic"]) + "." + encode([
            "iss": "https://invented.clerk.accounts.dev", "aud": "synthetic-workspace",
            "azp": "capacitor://localhost", "sub": identity.userID, "sid": identity.sessionID,
            "org_id": identity.organizationID, "exp": now + 60, "iat": now, "nbf": now,
        ]) + ".c3ludGhldGlj"
    }
}

@MainActor private final class ContextWire: ProviderNativeWire {
    let driver: ContextDriver
    let fault: String
    var calls = 0
    init(driver: ContextDriver, fault: String) { self.driver = driver; self.fault = fault }
    func send(_ request: ProviderNativeRequest, token: String) async throws -> ProviderNativeReply {
        calls += 1
        precondition(request.action == .recordingContext && !token.isEmpty)
        let input = try JSONSerialization.jsonObject(with: request.body) as! [String: Any]
        precondition(Set(input.keys) == ["workspace_id", "session_id", "operation"])
        var receipt: [String: Any] = ["schema_version": "1.0", "workspace_id": input["workspace_id"]!,
            "session_id": input["session_id"]!, "tenant_id": "00000000-0000-4000-8000-000000000104", "status": "created"]
        var body: [String: Any] = ["workspace_id": input["workspace_id"]!, "session_id": input["session_id"]!,
            "operation": "native_recording_context"]
        switch fault {
        case "workspace", "session": receipt[fault + "_id"] = UUID().uuidString.lowercased()
        case "outer_workspace", "outer_session": body[fault.replacingOccurrences(of: "outer_", with: "") + "_id"] = UUID().uuidString.lowercased()
        case "tenant": receipt["tenant_id"] = "authority_tenant_synthetic"
        case "version": receipt["schema_version"] = "2.0"
        case "missing_version": receipt.removeValue(forKey: "schema_version")
        case "status": receipt["status"] = "uploaded"
        case "extra": receipt["unexpected"] = true
        case "operation": body["operation"] = "encryption_key"
        case "signout": driver.identity = nil
        case "session_change": driver.identity = try NativeAuthIdentity(
            userID: "user_synthetic", sessionID: "sess_changed", organizationID: "org_synthetic")
        default: break
        }
        body["receipt"] = receipt
        return ProviderNativeReply(status: fault == "unauthorized" ? 401 : 200,
            body: try JSONSerialization.data(withJSONObject: body))
    }
}

@MainActor private func contextChecks(transport: WorkspaceSourceTransport) async throws -> [String: Any] {
    let workspace = UUID(uuidString: "00000000-0000-4000-8000-000000000101")!
    let session = UUID(uuidString: "00000000-0000-4000-8000-000000000102")!
    let faults = ["", "workspace", "session", "outer_workspace", "outer_session", "tenant", "version",
        "missing_version", "status", "extra", "operation", "signout", "session_change", "unauthorized", "cancelled"]
    for fault in faults {
        let driver = ContextDriver(), block = ContextBlock()
        let policy = try NativeTokenPolicy(issuer: "https://invented.clerk.accounts.dev", audience: "synthetic-workspace")
        let auth = NativeWorkspaceAuth(enabled: true, organizationID: "org_synthetic", tokenPolicy: policy,
            driver: { driver }, accessBlock: { block })
        let wire = ContextWire(driver: driver, fault: fault)
        let connection = NativeProviderConnection(auth: auth, wire: wire)
        let revision = auth.state().revision, id = UUID()
        if fault == "cancelled" { connection.cancel(id) }
        var confirmed = false
        do {
            let context = try await connection.recordingContext(workspaceID: workspace, sessionID: session,
                revision: revision, requestID: id)
            precondition(context.workspaceID == workspace && context.sessionID == session)
            precondition(context.tenantID.uuidString.lowercased() == "00000000-0000-4000-8000-000000000104")
            let acceptedRevision = try connection.recordingRevision(accountDigest: context.accountDigest)
            precondition(acceptedRevision == revision)
            confirmed = true
        } catch { precondition(!fault.isEmpty, "Valid native context failed: \(error)") }
        precondition(confirmed == fault.isEmpty)
        precondition(wire.calls == (fault == "cancelled" ? 0 : 1))
    }
    var genericRejected = false, confusedActionRejected = false
    do {
        _ = try ProviderNativeRequest(id: UUID().uuidString.lowercased(), revision: UUID().uuidString.lowercased(),
            action: "native-recording-context", key: "synthetic-key", body: "{}")
    } catch { genericRejected = true }
    do {
        let body = try JSONSerialization.data(withJSONObject: ["workspace_id": workspace.uuidString.lowercased(),
            "session_id": session.uuidString.lowercased(), "operation": ["kind": "native_recording_context"]])
        let request = try ProviderNativeRequest(nativeStartID: UUID(), revision: UUID().uuidString.lowercased(),
            key: "synthetic-key", body: body)
        _ = try transport.makeRequest(request, token: "synthetic-token")
    } catch { confusedActionRejected = true }
    precondition(genericRejected && confusedActionRejected)
    return ["kind": "context_checks", "scenarios": faults.count, "generic_rejected": genericRejected,
        "confused_action_rejected": confusedActionRejected]
}
