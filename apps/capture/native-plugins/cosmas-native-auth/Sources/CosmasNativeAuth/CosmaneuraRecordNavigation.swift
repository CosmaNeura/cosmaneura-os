import Foundation
import CoreFoundation

public enum CosmaneuraNavigationError: Error { case unavailable }

/// Reference-only navigation. These values contain neither auth tokens nor note text.
public struct CosmaneuraRecordNavigation {
    public let origin: String?
    public let google: GoogleConnectionNavigation
    public let microsoft: MicrosoftConnectionNavigation
    public let scheduling: SchedulingGoogleNavigation
    private static let appleEntries = Set(["capacitor://localhost", "capacitor://localhost/", "capacitor://localhost/index.html"])
    private static let originPattern = #"^https://[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?$"#
    private static let pathPattern = #"^/notes/appointment_[0-7][0-9a-hjkmnp-tv-z]{25}$"#
    private static let uuidPattern = #"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"#

    public init(webOrigin: String = "", schedulingClientID: String = "", schedulingCallbackURI: String = "", microsoftTenantID: String = "", microsoftClientID: String = "", microsoftCallbackURI: String = "", googleClientID: String = "", googleCallbackURI: String = "") throws {
        google = try GoogleConnectionNavigation(clientID:googleClientID, callbackURI:googleCallbackURI)
        microsoft = try MicrosoftConnectionNavigation(tenantID:microsoftTenantID, clientID:microsoftClientID, callbackURI:microsoftCallbackURI)
        scheduling = try SchedulingGoogleNavigation(clientID: schedulingClientID, callbackURI: schedulingCallbackURI)
        if webOrigin.isEmpty { origin = nil; return }
        guard webOrigin.utf8.count <= 255, Self.matches(webOrigin, Self.originPattern),
              let parts = URLComponents(string: webOrigin), parts.scheme == "https", parts.host != nil,
              parts.user == nil, parts.password == nil, parts.path.isEmpty, parts.query == nil, parts.fragment == nil,
              parts.port == nil,
              parts.url?.absoluteString == webOrigin else { throw CosmaneuraNavigationError.unavailable }
        origin = webOrigin
    }

    public func request(_ payload: [String: Any]) throws -> Request {
        guard Set(payload.keys) == ["schemaVersion", "requestId", "expectedRevision", "href"],
              let version = payload["schemaVersion"] as? NSNumber, CFGetTypeID(version) != CFBooleanGetTypeID(), version == 1,
              let requestID = payload["requestId"] as? String, Self.matches(requestID, Self.uuidPattern),
              let revision = payload["expectedRevision"] as? String, Self.matches(revision, Self.uuidPattern),
              let href = payload["href"] as? String,
              (origin.map { href.utf8.count <= 512 && href.hasPrefix($0) && Self.matches(String(href.dropFirst($0.count)), Self.pathPattern) } == true || scheduling.accepts(href) || microsoft.accepts(href) || google.accepts(href)),
              let url = URL(string: href), url.absoluteString == href else { throw CosmaneuraNavigationError.unavailable }
        return Request(requestID: requestID, expectedRevision: revision, url: url)
    }

    public static func currentAppleDocument(_ document: String?, frameDocument: String?, mainFrame: Bool,
                                            scheme: String, host: String, port: Int) -> Bool {
        guard let document else { return false }
        return mainFrame && appleEntries.contains(document) && frameDocument == document &&
            scheme == "capacitor" && host == "localhost" && port == 0
    }

    private static func matches(_ value: String, _ pattern: String) -> Bool {
        guard let range = value.range(of: pattern, options: .regularExpression) else { return false }
        return range == value.startIndex..<value.endIndex
    }

    public struct Request {
        public let requestID: String
        public let expectedRevision: String
        public let url: URL
    }
}
