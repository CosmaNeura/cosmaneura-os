import Foundation

/// Emit the actual native request without starting a session or touching Keychain.
@main struct NativeSourceTransportProbe {
    static func main() throws {
        let workspace = "00000000-0000-4000-8000-000000000101"
        let session = "00000000-0000-4000-8000-000000000102"
        let transport = try WorkspaceSourceTransport(settings: [
            "enabled": true, "apiOrigin": "https://api.example.invalid",
        ])
        let rows = try ["source_start", "source_extend"].map { kind in
            let body = try JSONSerialization.data(withJSONObject: [
                "workspace_id": workspace, "session_id": session,
                "operation": ["kind": kind],
            ])
            let operation = try ProviderNativeRequest(nativeStartID: UUID(),
                revision: UUID().uuidString.lowercased(), key: "synthetic-source-key", body: body)
            let request = try transport.makeRequest(operation, token: "synthetic-test-token")
            return ["kind": kind, "url": request.url!.absoluteString,
                "method": request.httpMethod!, "headers": request.allHTTPHeaderFields!,
                "body_base64": request.httpBody!.base64EncodedString()] as [String: Any]
        }
        let encoded = try JSONSerialization.data(withJSONObject: rows, options: [.sortedKeys])
        FileHandle.standardOutput.write(encoded)
    }
}
