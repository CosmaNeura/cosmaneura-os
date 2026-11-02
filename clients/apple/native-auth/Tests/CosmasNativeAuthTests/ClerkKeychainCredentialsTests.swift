import Foundation
import Security
import Testing
@testable import CosmasNativeAuth

@Suite struct ClerkKeychainCredentialsTests {
    @Test func clearRemovesMatchingServiceAndIgnoresMissingItems() throws {
        let service = "com.cosmasos.synthetic.clerk.keychain-wipe-test"
        let account = "invented-clerk-session"
        defer {
            SecItemDelete([
                kSecClass: kSecClassGenericPassword,
                kSecAttrService: service,
            ] as CFDictionary)
        }
        let add: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecValueData: Data([7]),
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ]
        #expect(SecItemAdd(add as CFDictionary, nil) == errSecSuccess)
        try ClerkKeychainCredentials.clear(service: service)
        var result: CFTypeRef?
        let status = SecItemCopyMatching([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ] as CFDictionary, &result)
        #expect(status == errSecItemNotFound)
        try ClerkKeychainCredentials.clear(service: service)
    }
}
