import Foundation

/// Only the configured web-client consent screen can leave the native app.
public struct GoogleConnectionNavigation {
    public let enabled: Bool
    private let clientID: String
    private let callbackURI: String
    private static let callbackPath = "/connections/google/callback"
    private static let fields: Set<String> = ["access_type", "client_id", "code_challenge", "code_challenge_method", "include_granted_scopes", "prompt", "redirect_uri", "response_type", "scope", "state"]
    public init(clientID: String = "", callbackURI: String = "") throws {
        self.clientID = clientID; self.callbackURI = callbackURI
        if clientID.isEmpty && callbackURI.isEmpty { enabled = false; return }
        guard Self.matches(clientID, #"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com"#),
              callbackURI.hasSuffix(Self.callbackPath),
              Self.matches(String(callbackURI.dropLast(Self.callbackPath.count)), #"https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?"#) else { throw CosmaneuraNavigationError.unavailable }
        enabled = true
    }
    public func accepts(_ href: String) -> Bool {
        guard enabled, href.utf8.count <= 4096,
              href.hasPrefix("https://accounts.google.com/o/oauth2/v2/auth?"),
              !href.unicodeScalars.contains(where: { $0.value <= 32 || $0.value == 127 }),
              let url = URLComponents(string: href), url.scheme == "https", url.host == "accounts.google.com",
              url.port == nil, url.user == nil, url.password == nil, url.fragment == nil,
              url.path == "/o/oauth2/v2/auth", let items = url.queryItems, items.count == Self.fields.count,
              Set(items.map(\.name)) == Self.fields else { return false }
        // OAuth form encoding uses '+' for spaces; URLComponents preserves it.
        let values = Dictionary(uniqueKeysWithValues: items.map { ($0.name, ($0.value ?? "").replacingOccurrences(of: "+", with: " ")) })
        return values["client_id"] == clientID && values["redirect_uri"] == callbackURI &&
            values["response_type"] == "code" && values["scope"] == "openid email https://www.googleapis.com/auth/gmail.metadata" && values["access_type"] == "offline" &&
            values["include_granted_scopes"] == "false" && values["prompt"] == "consent select_account" && values["code_challenge_method"] == "S256" &&
            ["state", "code_challenge"].allSatisfy { Self.matches(values[$0] ?? "", #"[A-Za-z0-9_-]{43}"#) }
    }
    private static func matches(_ value: String, _ pattern: String) -> Bool {
        guard let range = value.range(of: "^(?:" + pattern + ")$", options: .regularExpression) else { return false }
        return range == value.startIndex..<value.endIndex
    }
}
