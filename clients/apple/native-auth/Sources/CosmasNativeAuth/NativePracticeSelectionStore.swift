import Foundation
import Security

/// Selection metadata only. Never a JWT, SDK/client credential, clinical record,
/// draft or admission grant. Every reopen refetches current server qualification.
public struct NativePracticeSelectionMarker: Codable, Equatable, Sendable {
    public let version: Int
    public let userID: String
    public let issuer: String
    public let practiceID: UUID
    public let organizationID: String
    public let boxID: UUID
    public let apiOrigin: String
    public init(profile: NativePracticeProfile) {
        version = 1; userID = profile.account.userID; issuer = profile.account.issuer
        practiceID = profile.id; organizationID = profile.organizationID; boxID = profile.boxID; apiOrigin = profile.apiOrigin
    }
    public static func decode(_ data: Data) throws -> NativePracticeSelectionMarker {
        guard data.count <= 4096,
              let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              Set(object.keys) == ["version", "userID", "issuer", "practiceID", "organizationID", "boxID", "apiOrigin"] else {
            throw NativePracticeProfileError.invalidBinding
        }
        let result = try JSONDecoder().decode(Self.self, from: data)
        guard result.version == 1 else { throw NativePracticeProfileError.invalidBinding }
        return result
    }
    public func validate(binding: NativePracticeAccountServiceBinding) throws {
        guard version == 1, issuer == binding.realm.frontendOrigin,
              userID.range(of: "^user_[A-Za-z0-9_]{1,250}$", options: .regularExpression) != nil,
              organizationID.range(of: "^org_[A-Za-z0-9_]{1,251}$", options: .regularExpression) != nil,
              binding.allowsAPI(apiOrigin, practiceID: practiceID) else { throw NativePracticeProfileError.invalidBinding }
    }
}
@MainActor public protocol NativePracticeSelectionStore: AnyObject {
    func read() throws -> NativePracticeSelectionMarker?
    func write(_ marker: NativePracticeSelectionMarker) throws
    func clear() throws
}
/// One new, exact, encrypted app-private metadata item. No wildcard, shared
/// identity group, SDK credential access, draft copy or migration is involved.
@MainActor public final class KeychainNativePracticeSelectionStore: NativePracticeSelectionStore {
    private let query: [CFString: Any]
    public init(bundleIdentifier: String) throws {
        guard bundleIdentifier == "com.cosmasos.beta.ios" else { throw NativePracticeProfileError.invalidBinding }
        query = [kSecClass: kSecClassGenericPassword,
                 kSecAttrService: bundleIdentifier + ".registered-practice",
                 kSecAttrAccount: "selection-v1", kSecAttrSynchronizable: false,
                 kSecUseAuthenticationUI: kSecUseAuthenticationUIFail]
    }
    public func read() throws -> NativePracticeSelectionMarker? {
        var request = query; request[kSecReturnData] = true; request[kSecMatchLimit] = kSecMatchLimitOne
        var item: CFTypeRef?
        let result = SecItemCopyMatching(request as CFDictionary, &item)
        if result == errSecItemNotFound { return nil }
        guard result == errSecSuccess, let data = item as? Data, data.count <= 4096 else { throw NativeAuthError.storageUnavailable }
        return try NativePracticeSelectionMarker.decode(data)
    }
    public func write(_ marker: NativePracticeSelectionMarker) throws {
        let data = try JSONEncoder().encode(marker)
        guard data.count <= 4096 else { throw NativePracticeProfileError.invalidBinding }
        var item = query; item[kSecValueData] = data; item[kSecAttrAccessible] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        let result = SecItemAdd(item as CFDictionary, nil)
        guard result == errSecSuccess || (result == errSecDuplicateItem &&
            SecItemUpdate(query as CFDictionary, [kSecValueData: data] as CFDictionary) == errSecSuccess) else {
            throw NativeAuthError.storageUnavailable
        }
    }
    public func clear() throws {
        let result = SecItemDelete(query as CFDictionary)
        guard result == errSecSuccess || result == errSecItemNotFound else { throw NativeAuthError.storageUnavailable }
    }
}
