import CosmaneuraNativeRecording
import CosmasNativeAuth
import Foundation

@MainActor private final class RecordingBlock: NativeAuthAccessBlock {
    func isBlocked() throws -> Bool { false }
    func setBlocked(_ blocked: Bool) throws {}
}

@MainActor private final class RecordingDriver: NativeAuthDriver {
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

@MainActor private final class RecordingWire: ProviderNativeWire {
    let driver: RecordingDriver
    let envelopes: [String: [String: Any]]
    let fault: [String: String]
    let transport = try! WorkspaceSourceTransport(settings: [
        "enabled": true, "apiOrigin": "https://api.example.invalid",
    ])
    var requests: [[String: Any]] = []
    init(driver: RecordingDriver, input: [String: Any]) {
        self.driver = driver
        envelopes = input["envelopes"] as! [String: [String: Any]]
        fault = input["fault"] as? [String: String] ?? [:]
    }
    func send(_ request: ProviderNativeRequest, token: String) async throws -> ProviderNativeReply {
        let body = try JSONSerialization.jsonObject(with: request.body) as! [String: Any]
        let operation = body["operation"] as! [String: Any]
        let kind = operation["kind"] as! String
        let outgoing = try transport.makeRequest(request, token: token)
        // The actual builder, not a reconstructed Python approximation.
        requests.append(["kind": kind, "url": outgoing.url!.absoluteString,
            "body": try JSONSerialization.jsonObject(with: outgoing.httpBody!),
            "headers": outgoing.allHTTPHeaderFields!.filter { $0.key.lowercased() != "authorization" }])
        var response = envelopes[kind]!
        var receipt = response["receipt"] as! [String: Any]
        var status = 200
        if fault["operation"] == kind {
            switch fault["kind"]! {
            case "workspace": response["workspace_id"] = UUID().uuidString.lowercased()
            case "session": response["session_id"] = UUID().uuidString.lowercased()
            case "operation": response["operation"] = "source_start"
            case "extra": response["unexpected"] = true
            case "receipt_session": receipt["session_id"] = UUID().uuidString.lowercased()
            case "version": receipt["key_version"] = "changed"
            case "algorithm": receipt["algorithm"] = "RSA-OAEP"
            case "jwk_boolean":
                var jwk = receipt["public_jwk"] as! [String: Any]
                jwk["ext"] = 1
                receipt["public_jwk"] = jwk
            case "generation": receipt["generation"] = true
            case "lease": receipt["lease_id"] = UUID().uuidString.lowercased()
            case "deadline": receipt["capture_authorized_until"] = "2026-09-27T01:00:00Z"
            case "count":
                receipt["reservations"] = Array((receipt["reservations"] as! [[String: Any]]).dropLast())
            case "sequence", "aad", "duplicate":
                var rows = receipt["reservations"] as! [[String: Any]]
                if fault["kind"] == "sequence" { rows[0]["sequence_number"] = true }
                if fault["kind"] == "aad" { rows[0]["additional_authenticated_data"] = "e30" }
                if fault["kind"] == "duplicate" { rows[1] = rows[0] }
                receipt["reservations"] = rows
            case "signout": driver.identity = nil
            case "organization":
                driver.identity = try NativeAuthIdentity(
                    userID: "user_synthetic", sessionID: "sess_synthetic", organizationID: "org_changed")
            case "401", "403", "409", "422", "503": status = Int(fault["kind"]!)!
            default: preconditionFailure("Unknown fixture fault")
            }
        }
        response["receipt"] = receipt
        return ProviderNativeReply(status: status, body: try JSONSerialization.data(withJSONObject: response))
    }
}

@main struct NativeRecordingServiceProbe {
    @MainActor static func main() async throws {
        let input = try JSONSerialization.jsonObject(
            with: FileHandle.standardInput.readDataToEndOfFile()) as! [String: Any]
        let driver = RecordingDriver(), block = RecordingBlock()
        let policy = try NativeTokenPolicy(
            issuer: "https://invented.clerk.accounts.dev", audience: "synthetic-workspace")
        let auth = NativeWorkspaceAuth(enabled: true, organizationID: "org_synthetic",
            tokenPolicy: policy, driver: { driver }, accessBlock: { block })
        let wire = RecordingWire(driver: driver, input: input)
        let connection = NativeProviderConnection(auth: auth, wire: wire)
        let workspace = UUID(uuidString: input["workspace_id"] as! String)!
        let session = UUID(uuidString: input["session_id"] as! String)!
        let context = try await connection.recordingContext(
            workspaceID: workspace, sessionID: session, revision: auth.state().revision)
        let service = NativeProviderRecordingService(connection: connection, context: context)
        var completed: [String] = []
        var failure: String?
        do {
            let scope = try await service.recordingScope()
            precondition(scope.workspaceID == workspace && scope.sessionID == session)
            let key = try await service.publishedKey()
            completed.append("encryption_key")
            let acknowledgement = try await service.bind(key: NativeRecordingKeyReceipt(
                keyVersion: key.version, wrappedDEK: String(repeating: "A", count: 512)), intent: UUID())
            precondition(acknowledgement.sessionID == session)
            completed.append("bind_key")
            let original = try await service.requestLease(previous: nil, intent: UUID())
            precondition(original.generation == 1)
            completed.append("issue_lease")
            let next = try await service.requestLease(previous: original, intent: UUID())
            precondition(next.generation == 2 && next.leaseID == original.leaseID)
            completed.append("renew_lease")
            let batch = try await service.reserve(lease: next, first: 0, count: 2, intent: UUID())
            precondition(batch.reservations.map(\.sequence) == [0, 1])
            completed.append("reserve_chunks")
        } catch { failure = String(describing: error) }
        var rendererRejected = false, confusedRejected = false
        do {
            _ = try ProviderNativeRequest(id: UUID().uuidString.lowercased(),
                revision: auth.state().revision, action: "native-recording-operation",
                key: UUID().uuidString.lowercased(), body: "{}")
        } catch { rendererRejected = true }
        do {
            let request = try ProviderNativeRequest(nativeRecordingID: UUID(),
                revision: auth.state().revision, key: UUID().uuidString.lowercased(),
                body: JSONSerialization.data(withJSONObject: [
                    "workspace_id": workspace.uuidString.lowercased(),
                    "session_id": session.uuidString.lowercased(),
                    "operation": ["kind": "source_start"],
                ]))
            _ = try wire.transport.makeRequest(request, token: "synthetic")
        } catch { confusedRejected = true }
        let output: [String: Any] = ["completed": completed, "failure": failure as Any? ?? NSNull(),
            "requests": wire.requests, "renderer_rejected": rendererRejected,
            "confused_action_rejected": confusedRejected]
        FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys]))
    }
}
