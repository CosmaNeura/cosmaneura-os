import Foundation
import Security

/// One app-scoped Boolean. It never reads or writes Clerk's credential records.
@MainActor public final class KeychainAccessBlock: NativeAuthAccessBlock {
    public enum Availability: Sendable, Equatable { case unknown, available, interactionRequired, unavailable }
    private let query: [CFString: Any]
    public private(set) var availability: Availability = .unknown
    /// Desktop background checks must never summon or wait for an approval UI.
    /// The desktop host grants task-scoped interaction only while its owned window is visible.
    public let allowsAuthenticationUI: Bool
    @TaskLocal private static var interactiveBlock: KeychainAccessBlock?

    public init(bundleIdentifier: String, profile: NativeIdentityProfile = .synthetic,
                allowsAuthenticationUI: Bool = true) throws {
        guard NativeWorkspaceOrigin.appleWebView.accepts(bundleIdentifier: bundleIdentifier, profile: profile) ||
              NativeWorkspaceOrigin.desktopApp.accepts(bundleIdentifier: bundleIdentifier, profile: profile) else {
            throw NativeAuthError.storageUnavailable
        }
        query = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: bundleIdentifier + ".workspace-auth",
            kSecAttrAccount: "local-access-block-v1",
        ]
        self.allowsAuthenticationUI = allowsAuthenticationUI
    }

    func operationQuery() -> [CFString: Any] {
        var request = query
        if !allowsAuthenticationUI && Self.interactiveBlock !== self {
            // Keep the refusal in the Security query itself. Creating a separate
            // LAContext can fail before its no-interaction policy is established.
            request[kSecUseAuthenticationUI] = kSecUseAuthenticationUIFail
        }
        return request
    }

    public func withAuthenticationUI<Value>(
        _ operation: @MainActor () async throws -> Value
    ) async rethrows -> Value {
        try await Self.$interactiveBlock.withValue(self, operation: operation)
    }

    static func availability(for status: OSStatus) -> Availability {
        if status == errSecSuccess || status == errSecItemNotFound { return .available }
        return status == errSecInteractionNotAllowed ? .interactionRequired : .unavailable
    }

    public func isBlocked() throws -> Bool {
        var request = operationQuery()
        request[kSecReturnData] = true
        request[kSecMatchLimit] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &result)
        availability = Self.availability(for: status)
        if status == errSecItemNotFound { return false }
        guard status == errSecSuccess, let value = result as? Data,
              value == Data([0]) || value == Data([1]) else {
            if status == errSecSuccess { availability = .unavailable }
            throw NativeAuthError.storageUnavailable
        }
        return value == Data([1])
    }

    public func setBlocked(_ blocked: Bool) throws {
        let data = Data([blocked ? 1 : 0])
        let operation = operationQuery()
        var item = operation
        item[kSecValueData] = data
        item[kSecAttrAccessible] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let inserted = SecItemAdd(item as CFDictionary, nil)
        if inserted == errSecSuccess { availability = .available; return }
        let status = inserted == errSecDuplicateItem
            ? SecItemUpdate(operation as CFDictionary, [kSecValueData: data] as CFDictionary) : inserted
        availability = status == errSecItemNotFound ? .unavailable : Self.availability(for: status)
        guard status == errSecSuccess else {
            throw NativeAuthError.storageUnavailable
        }
    }
}
