import Foundation
import Security

/// Wipes ClerkKit credential records for one configured Keychain service.
/// Never touches the separate workspace-auth access-block item.
public enum ClerkKeychainCredentials {
    public static func clear(service: String) throws {
        guard !service.isEmpty, service.utf8.count <= 512 else {
            throw NativeAuthError.storageUnavailable
        }
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
        ]
        let status = SecItemDelete(query as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw NativeAuthError.storageUnavailable
        }
    }
}
