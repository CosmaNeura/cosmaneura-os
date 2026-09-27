import Foundation
import Security
import XCTest
@testable import CosmaBotLegacySecureQueue
@testable import CosmaneuraSecureQueue

final class LegacyQueueCompatibilityTests: XCTestCase {
    func testExistingAppFilesAndKeyRemainReadableAndRevisionCompatible() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("cosmas-queue-upgrade-test-\(UUID())", isDirectory: true)
        let service = "com.cosmasos.capture.upgrade-tests.\(UUID())"
        let account = "synthetic-only"
        defer {
            try? FileManager.default.removeItem(at: directory)
            let status = SecItemDelete([kSecClass: kSecClassGenericPassword,
                kSecAttrService: service, kSecAttrAccount: account] as CFDictionary)
            XCTAssertTrue(status == errSecSuccess || status == errSecItemNotFound)
        }
        let old = try CosmaBotLegacySecureQueue.SecureQueueStore(
            directoryURL: directory, keychainService: service, keychainAccount: account)
        let key = "cosmas-queue:v1:synthetic-workspace:synthetic-session:synthetic-object"
        let priorData = Data("invented encrypted upload metadata".utf8)
        XCTAssertEqual(try old.create(key: key, data: priorData), 1)
        let files = try FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
        let file = try XCTUnwrap(files.first { $0.pathExtension == "sq" })
        let originalCiphertext = try Data(contentsOf: file)
        func storageKey() throws -> Data {
            var item: CFTypeRef?
            XCTAssertEqual(SecItemCopyMatching([kSecClass: kSecClassGenericPassword,
                kSecAttrService: service, kSecAttrAccount: account,
                kSecReturnData: true, kSecMatchLimit: kSecMatchLimitOne] as CFDictionary, &item), errSecSuccess)
            return try XCTUnwrap(item as? Data)
        }
        let originalKey = try storageKey()
        let current = try CosmaneuraSecureQueue.SecureQueueStore(
            directoryURL: directory, keychainService: service, keychainAccount: account)
        let renderer = CosmaneuraSecureQueue.RendererSecureQueueStore(store: current)
        XCTAssertEqual(try renderer.get(key: key).data, priorData)
        XCTAssertEqual(try renderer.get(key: key).revision, 1)
        XCTAssertEqual(try Data(contentsOf: file), originalCiphertext)
        XCTAssertEqual(try storageKey(), originalKey)

        let updated = Data("invented upload receipt".utf8)
        XCTAssertEqual(try renderer.compareAndSwap(key: key, expectedRevision: 1, data: updated), 2)
        XCTAssertEqual(try old.get(key: key).data, updated)
        XCTAssertEqual(try old.get(key: key).revision, 2)
        XCTAssertEqual(try storageKey(), originalKey)

        let journal = "cosmas-native-flow:v1:synthetic"
        _ = try current.create(key: journal, data: Data([7]))
        XCTAssertThrowsError(try renderer.clear())
        XCTAssertEqual(try renderer.get(key: key).data, updated)
        XCTAssertEqual(try current.get(key: journal).data, Data([7]))
        XCTAssertEqual(try renderer.list(), [key])
    }
}
