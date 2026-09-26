import Foundation

/// Only the configured web-client consent screen can leave the native app.
public struct MicrosoftConnectionNavigation {
    public let enabled: Bool
    private let clientID: String
    private let tenantID: String
    private let callbackURI: String
    private static let callbackPath = "/connections/microsoft/callback"
    private static let fields: Set<String> = ["client_id", "code_challenge", "code_challenge_method", "prompt", "redirect_uri", "response_mode", "response_type", "scope", "state"]
    public init(tenantID: String = "", clientID: String = "", callbackURI: String = "") throws {
        self.tenantID = tenantID; self.clientID = clientID; self.callbackURI = callbackURI
        if tenantID.isEmpty && clientID.isEmpty && callbackURI.isEmpty { enabled = false; return }
        guard Self.matches(tenantID, #"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"#), Self.matches(clientID, #"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"#),
              callbackURI.hasSuffix(Self.callbackPath),
              Self.matches(String(callbackURI.dropLast(Self.callbackPath.count)), #"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"#) else { throw CosmaneuraNavigationError.unavailable }
        enabled = true
    }
    public func accepts(_ href: String) -> Bool {
        guard enabled, href.utf8.count <= 4096,
              href.hasPrefix("https://login.microsoftonline.com/\(tenantID)/oauth2/v2.0/authorize?"),
              !href.unicodeScalars.contains(where: { $0.value <= 32 || $0.value == 127 }),
              let url = URLComponents(string: href), url.scheme == "https", url.host == "login.microsoftonline.com",
              url.port == nil, url.user == nil, url.password == nil, url.fragment == nil,
              url.path == "/\(tenantID)/oauth2/v2.0/authorize", let items = url.queryItems, items.count == Self.fields.count,
              Set(items.map(\.name)) == Self.fields else { return false }
        // OAuth form encoding uses '+' for spaces; URLComponents preserves it.
        let values = Dictionary(uniqueKeysWithValues: items.map { ($0.name, ($0.value ?? "").replacingOccurrences(of: "+", with: " ")) })
        return values["client_id"] == clientID && values["redirect_uri"] == callbackURI &&
            values["response_type"] == "code" && values["scope"] == "offline_access User.Read Mail.Read Calendars.Read" && values["response_mode"] == "query" &&
            values["prompt"] == "select_account" && values["code_challenge_method"] == "S256" &&
            ["state", "code_challenge"].allSatisfy { Self.matches(values[$0] ?? "", #"[A-Za-z0-9_-]{43}"#) }
    }
    private static func matches(_ value: String, _ pattern: String) -> Bool {
        guard let range = value.range(of: "^(?:" + pattern + ")$", options: .regularExpression) else { return false }
        return range == value.startIndex..<value.endIndex
    }
}
