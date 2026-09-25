import Foundation

/// Native-only source ownership through the existing authenticated OS API.
/// The bundle selects one HTTPS origin. No renderer URL, headers or token enter here.
final class WorkspaceSourceTransport: NSObject, ProviderNativeWire, URLSessionTaskDelegate,
    @unchecked Sendable {
    private let origin: URL

    init(settings: [String: Any]) throws {
        guard Set(settings.keys) == ["enabled", "apiOrigin"], settings["enabled"] as? Bool == true,
              let value = settings["apiOrigin"] as? String, value.utf8.count <= 253,
              value.range(of: "^https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", options: .regularExpression) != nil,
              !value.hasSuffix(".localhost"), value.range(of: "^https://[0-9]+(?:\\.[0-9]+){3}$", options: .regularExpression) == nil,
              let origin = URL(string: value), origin.absoluteString == value else {
            throw ProviderNativeError.unavailable
        }
        self.origin = origin
    }

    func send(_ operation: ProviderNativeRequest, token: String) async throws -> ProviderNativeReply {
        try Task.checkCancellation()
        guard operation.action == .sourceStart,
              let value = try JSONSerialization.jsonObject(with: operation.body) as? [String: Any],
              Set(value.keys) == ["workspace_id", "session_id", "operation"],
              let workspace = value["workspace_id"] as? String,
              UUID(uuidString: workspace)?.uuidString.lowercased() == workspace,
              let sessionID = value["session_id"] as? String,
              UUID(uuidString: sessionID)?.uuidString.lowercased() == sessionID,
              let capture = value["operation"] as? [String: Any],
              ["source_start", "source_extend"].contains(capture["kind"] as? String ?? ""),
              !token.isEmpty, token.utf8.count <= 8192,
              token.unicodeScalars.allSatisfy({ $0.isASCII && $0.value >= 33 && $0.value < 127 }) else {
            throw ProviderNativeError.invalidRequest
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil; configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil; configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        configuration.timeoutIntervalForRequest = 40; configuration.timeoutIntervalForResource = 45
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        var request = URLRequest(url: origin.appendingPathComponent("workspaces/" + workspace + "/capture/operations"))
        request.httpMethod = "POST"
        request.httpBody = try JSONSerialization.data(withJSONObject: ["session_id": sessionID,
            "idempotency_key": operation.key, "operation": capture])
        #if os(macOS)
        request.setValue("app://cosmas", forHTTPHeaderField: "Origin")
        #else
        request.setValue("capacitor://localhost", forHTTPHeaderField: "Origin")
        #endif
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        do {
            let (bytes, response) = try await session.bytes(for: request)
            guard let http = response as? HTTPURLResponse, http.url == request.url,
                  [200, 401, 403, 409, 422, 503].contains(http.statusCode), http.mimeType == "application/json",
                  http.value(forHTTPHeaderField: "Cache-Control")?.split(separator: ",").contains(where: {
                      $0.trimmingCharacters(in: .whitespaces).lowercased() == "no-store"
                  }) == true else { throw ProviderNativeError.response }
            var data = Data()
            for try await byte in bytes {
                try Task.checkCancellation()
                guard data.count < operation.action.responseLimit else { throw ProviderNativeError.response }
                data.append(byte)
            }
            try Task.checkCancellation()
            return ProviderNativeReply(status: http.statusCode, body: data)
        } catch { throw ProviderNativeError.unavailable }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
