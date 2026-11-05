import Foundation

/// Closed public configuration from the authenticated, pinned native account
/// service. Qualification hashes identify server-owned measurements; neither a
/// digest nor this parser authenticates a response or grants workspace access.
public struct NativePracticeWorkspaceBootstrap: Equatable, Sendable {
    public let canonicalData: Data
    public let issuedAt: Date
    public let expiresAt: Date
    public let nativeQualificationSHA256: String
    public let sourceCommit: String
    public let imageSHA256: String
    private init(data: Data, issued: Date, expires: Date, qualification: String, source: String, image: String) {
        canonicalData = data; issuedAt = issued; expiresAt = expires
        nativeQualificationSHA256 = qualification; sourceCommit = source; imageSHA256 = image
    }

    public static func decode(_ data: Data, expectation: NativePracticeConnectionExpectation,
                              binding: NativePracticeAccountServiceBinding, now: Date = Date()) throws -> NativePracticeWorkspaceBootstrap {
        guard data.count <= 16_384 else { throw NativePracticeProfileError.invalidBinding }
        try UniquePracticeJSON(data).validate()
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(root.keys) == ["contract_version", "client", "nonce", "native_origin", "data_mode", "nativeIdentity", "session", "practice", "workspace", "issued_at", "expires_at"],
              root["contract_version"] as? String == "cosmas-native-workspace-profile.v1",
              // Contract: client matches Origin; data_mode follows the binding's registered environment.
              root["client"] as? String == binding.realm.workspaceOrigin.nativeClient,
              root["data_mode"] as? String == binding.dataMode,
              root["native_origin"] as? String == binding.realm.workspaceOrigin.rawValue,
              root["nonce"] as? String == expectation.nonce.uuidString.lowercased(),
              let native = root["nativeIdentity"] as? [String: Any],
              Set(native.keys) == ["version", "profile", "client", "apiOrigin", "publishableKey", "frontendOrigin", "organizationId", "audience"],
              integer(native["version"]) == 1, native["client"] as? String == binding.realm.workspaceOrigin.nativeClient,
              native["apiOrigin"] as? String == expectation.apiOrigin,
              binding.allowsAPI(expectation.apiOrigin, practiceID: expectation.selectionID),
              native["organizationId"] as? String == expectation.organizationID,
              native["publishableKey"] as? String == binding.realm.publishableKey,
              native["frontendOrigin"] as? String == binding.realm.frontendOrigin,
              native["profile"] as? String == binding.realm.profile.rawValue,
              native["audience"] as? String == binding.audience,
              let session = root["session"] as? [String: Any], Set(session.keys) == ["issuer", "subject", "session_id"],
              session["issuer"] as? String == expectation.account.issuer,
              session["subject"] as? String == expectation.account.userID,
              session["session_id"] as? String == expectation.account.sessionID,
              let practice = root["practice"] as? [String: Any], Set(practice.keys) == ["practice_id", "box_id"],
              practice["practice_id"] as? String == expectation.selectionID.uuidString.lowercased(),
              practice["box_id"] as? String == expectation.boxID.uuidString.lowercased(),
              let workspace = root["workspace"] as? [String: Any],
              Set(workspace.keys) == ["url", "source_commit", "image_sha256", "workspace_proof_sha256", "member_proof_sha256", "native_qualification_sha256"],
              let workspaceURL = workspace["url"] as? String,
              pairedWorkspace(workspaceURL, api: expectation.apiOrigin),
              let source = workspace["source_commit"] as? String, digest(source, length: 40),
              let image = workspace["image_sha256"] as? String, digest(image),
              let proof = workspace["workspace_proof_sha256"] as? String, digest(proof),
              let member = workspace["member_proof_sha256"] as? String, digest(member),
              let qualification = workspace["native_qualification_sha256"] as? String, digest(qualification),
              let issued = integer(root["issued_at"]), let expires = integer(root["expires_at"]),
              issued <= now.timeIntervalSince1970 + 5, now.timeIntervalSince1970 - issued <= 30,
              expires > now.timeIntervalSince1970, expires > issued, expires - issued <= 30 else {
            throw NativePracticeProfileError.invalidBinding
        }
        let canonical = try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys, .withoutEscapingSlashes])
        return .init(data: canonical, issued: Date(timeIntervalSince1970: issued),
            expires: Date(timeIntervalSince1970: expires), qualification: qualification, source: source, image: image)
    }

    public var rendererProfile: [String: Any] {
        // Data was closed and canonicalized once above; return a fresh object.
        (try? JSONSerialization.jsonObject(with: canonicalData) as? [String: Any]) ?? [:]
    }
}

private func integer(_ value: Any?) -> Double? {
    guard let n = value as? NSNumber, CFGetTypeID(n) != CFBooleanGetTypeID(),
          n.doubleValue.isFinite, n.doubleValue >= 0, n.doubleValue <= 9_007_199_254_740_991,
          n.doubleValue.rounded(.down) == n.doubleValue else { return nil }
    return n.doubleValue
}
private func digest(_ value: String, length: Int = 64) -> Bool {
    value.count == length && value.unicodeScalars.allSatisfy { (48...57).contains($0.value) || (97...102).contains($0.value) }
}
private func pairedWorkspace(_ value: String, api: String) -> Bool {
    // Contract practice URL is https://<host>/chief paired with https://api.<host> only.
    guard value.utf8.count <= 2048, let web = URLComponents(string: value), web.scheme == "https",
          let host = web.host, host == host.lowercased(), web.port == nil,
          web.user == nil, web.password == nil, web.query == nil, web.fragment == nil,
          web.path == "/chief", value == "https://" + host + "/chief",
          host != "app.cosmas.ai", host != "api.cosmas.ai",
          let target = URLComponents(string: api), target.scheme == "https",
          target.port == nil, target.user == nil, target.password == nil,
          target.host == "api." + host else { return false }
    return true
}

/// Reject duplicate (including escaped-equivalent) JSON keys before Foundation
/// parses or the renderer receives the object. Foundation validates full syntax;
/// this bounded walk enforces uniqueness and nesting without a permissive decoder.
private struct UniquePracticeJSON {
    let data: Data
    init(_ data: Data) { self.data = data }
    func validate() throws {
        var scanner = Scanner(bytes: Array(data)); try scanner.value(depth: 0)
        scanner.space(); guard scanner.index == scanner.bytes.count else { throw NativePracticeProfileError.invalidBinding }
    }
    private struct Scanner {
        let bytes: [UInt8]
        var index = 0
        mutating func space() { while index < bytes.count && [9,10,13,32].contains(bytes[index]) { index += 1 } }
        mutating func string() throws -> String {
            guard index < bytes.count, bytes[index] == 34 else { throw NativePracticeProfileError.invalidBinding }
            let start = index; index += 1
            while index < bytes.count {
                let byte = bytes[index]; index += 1
                if byte == 34 {
                    return try JSONDecoder().decode(String.self, from: Data(bytes[start..<index]))
                }
                if byte == 92 { guard index < bytes.count else { break }; index += 1 }
            }
            throw NativePracticeProfileError.invalidBinding
        }
        mutating func value(depth: Int) throws {
            space(); guard depth <= 12, index < bytes.count else { throw NativePracticeProfileError.invalidBinding }
            let kind = bytes[index]
            if kind == 34 { _ = try string(); return }
            if kind == 123 {
                index += 1; space(); var keys = Set<String>()
                if index < bytes.count, bytes[index] == 125 { index += 1; return }
                while true {
                    space(); let key = try string()
                    guard keys.insert(key).inserted else { throw NativePracticeProfileError.invalidBinding }
                    space(); guard index < bytes.count, bytes[index] == 58 else { throw NativePracticeProfileError.invalidBinding }
                    index += 1; try value(depth: depth + 1); space()
                    guard index < bytes.count else { throw NativePracticeProfileError.invalidBinding }
                    if bytes[index] == 125 { index += 1; return }
                    guard bytes[index] == 44 else { throw NativePracticeProfileError.invalidBinding }; index += 1
                }
            }
            if kind == 91 {
                index += 1; space()
                if index < bytes.count, bytes[index] == 93 { index += 1; return }
                while true {
                    try value(depth: depth + 1); space(); guard index < bytes.count else { throw NativePracticeProfileError.invalidBinding }
                    if bytes[index] == 93 { index += 1; return }
                    guard bytes[index] == 44 else { throw NativePracticeProfileError.invalidBinding }; index += 1
                }
            }
            let start = index
            while index < bytes.count && ![9,10,13,32,44,93,125].contains(bytes[index]) { index += 1 }
            guard index > start else { throw NativePracticeProfileError.invalidBinding }
        }
    }
}
