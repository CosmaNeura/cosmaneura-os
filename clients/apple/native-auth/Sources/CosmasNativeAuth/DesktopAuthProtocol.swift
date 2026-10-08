import Foundation

/// Dedicated parent/child pipes only. There is no TCP or renderer entry point.
public struct DesktopAuthRequest: Sendable {
    public enum Method: String, Sendable {
        case getState, signIn, signOut, getToken
        case sourceIdle, sourcePrepare, sourceAuthorize, sourceExtend, sourceRelease, sourceStopped, sourcePreparationRelease
        public var isSource: Bool { rawValue.hasPrefix("source") }
    }
    public let id: String
    public let method: Method
    public let revision: String?
    public let payload: Data?

    public init(frame: Data) throws {
        guard !frame.isEmpty, frame.count <= 1024,
              let object = try? JSONSerialization.jsonObject(with: frame) as? [String: Any],
              let id = object["id"] as? String, Self.isRevision(id),
              let rawMethod = object["method"] as? String, let method = Method(rawValue: rawMethod) else {
            throw NativeAuthError.unavailable
        }
        let revision = object["revision"] as? String
        let fields: Set<String> = method.isSource ? ["id", "method", "payload"] :
            method == .getToken ? ["id", "method", "revision"] : ["id", "method"]
        guard Set(object.keys) == fields,
              method != .getToken || revision.map(Self.isRevision) == true else {
            throw NativeAuthError.unavailable
        }
        self.id = id
        self.method = method
        self.revision = revision
        if method.isSource {
            guard let value = object["payload"] as? [String: Any] else { throw NativeAuthError.unavailable }
            self.payload = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
        } else { self.payload = nil }
    }

    public static func isRevision(_ value: String) -> Bool {
        UUID(uuidString: value)?.uuidString.lowercased() == value
    }
}

/// Incremental frame bound applies before JSON decoding or buffering more data.
public struct DesktopAuthFrames: Sendable {
    private var pending = Data()
    public init() {}

    public mutating func append(_ byte: UInt8) throws -> DesktopAuthRequest? {
        if byte == 10 {
            let frame = pending
            pending.removeAll(keepingCapacity: true)
            return try DesktopAuthRequest(frame: frame)
        }
        guard pending.count < 1024 else { throw NativeAuthError.unavailable }
        pending.append(byte)
        return nil
    }

    public var hasPartialFrame: Bool { !pending.isEmpty }
}

public enum NativeAuthPayload {
    public static func state(_ state: NativeAuthState) -> [String: Any] {
        let identity: Any = state.identity.map {
            ["userId": $0.userID, "sessionId": $0.sessionID, "organizationId": $0.organizationID]
        } ?? NSNull()
        return ["phase": state.phase.rawValue, "revision": state.revision, "identity": identity]
    }
}
