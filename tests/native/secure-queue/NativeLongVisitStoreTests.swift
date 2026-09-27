import Foundation
import Security
import XCTest

@testable import CosmaneuraNativeRecording
@testable import CosmaneuraSecureQueue

final class NativeLongVisitStoreTests: XCTestCase {
  @MainActor
  func testThreeHourNativeQueueReopensAndSealsThroughRealEncryptedStorage() async throws {
    // Explicit synthetic consent: generated PCM only, no AVAudioEngine or
    // account. Use only a fresh temporary directory and a unique test key.
    let scope = try NativeRecordingScope(
      tenantID: UUID(), sessionID: UUID(), workspaceID: UUID(),
      accountDigest: String(repeating: "a", count: 64))
    let recovery = UUID()
    let keys = LongVisitKeys()
    let service = LongVisitService(scope: scope)
    let directory = FileManager.default.temporaryDirectory
      .appendingPathComponent("cosmas-native-queue-test-\(UUID())", isDirectory: true)
    let serviceName = "com.cosmasos.capture.tests.\(UUID())"
    let disk = try SecureQueueStore(directoryURL: directory,
      keychainService: serviceName, keychainAccount: "synthetic-only")
    let native = NativeRecordingQueueStore(store: disk)
    let prefix = scope.queuePrefix(recoveryScope: recovery)
    defer {
      try? FileManager.default.removeItem(at: directory)
      let status = SecItemDelete([kSecClass: kSecClassGenericPassword,
        kSecAttrService: serviceName, kSecAttrAccount: "synthetic-only"] as CFDictionary)
      XCTAssertTrue(status == errSecSuccess || status == errSecItemNotFound)
    }
    XCTAssertGreaterThan(try native.availableBytes(), 600_000_000)
    let wrapping = try XCTUnwrap(
      SecKeyCreateRandomKey(
        [
          kSecAttrKeyType: kSecAttrKeyTypeRSA, kSecAttrKeySizeInBits: 3072,
          kSecAttrIsPermanent: false,
        ] as CFDictionary, nil))
    let publicKey = try XCTUnwrap(SecKeyCopyPublicKey(wrapping))
    let der = try XCTUnwrap(SecKeyCopyExternalRepresentation(publicKey, nil)) as Data
    let cipher = try NativeRecordingEncryption.create(
      scope: scope,
      published: NativeRecordingPublicKey(
        version: "synthetic-long-visit", modulusBase64URL: nativeBase64URL(der.subdata(in: 9..<393))
      ), storage: keys)
    let originalKey = keys.value
    let owner = NativeRecordingFlowOwner(
      scope: scope, recoveryScope: recovery, service: service, records: native)
    let initial = try await owner.open()
    let reservations = NativeRecordingReservationOwner(
      scope: scope, recoveryScope: recovery, service: service, records: native)
    let writer = try NativeRecordingQueueWriter(
      encryption: cipher, recoveryScope: recovery, store: native,
      firstSequence: 0, priorPlaintextBytes: 0,
      maximumPlaintextBytes: NativeRecordingFlowOwner.maximumPlaintextBytes)
    var lastLease: NativeRecordingLease?
    let started = Date()
    for first in stride(from: 0, to: 1080, by: 90) {
      let lease = try service.lease(generation: first / 90 + 1)
      let batch = try await reservations.reserve(lease: lease, first: first, count: 90)
      for reservation in batch.reservations {
        try autoreleasepool {
          var pcm = Data(repeating: 4, count: 320_000)  // 10 seconds at 16kHz mono PCM16.
          _ = try writer.persist(
            pcm16: &pcm, objectID: reservation.objectID, sequence: reservation.sequence)
          XCTAssertEqual(pcm.first, 0)
          XCTAssertEqual(pcm.last, 0)
        }
      }
      lastLease = lease
    }
    XCTAssertEqual(try native.listRecordingKeys(prefix: prefix).count, 1080)
    // Fresh handles reopen only this test's existing key and encrypted files.
    let reopenedDisk = try SecureQueueStore(directoryURL: directory,
      keychainService: serviceName, keychainAccount: "synthetic-only")
    let restored = try NativeRecordingEncryption.reopen(
      scope: scope, expected: cipher.receipt, storage: keys)
    let fresh = NativeRecordingFlowOwner(
      scope: scope, recoveryScope: recovery, service: service,
      records: NativeRecordingQueueStore(store: reopenedDisk))
    let recovered = try await fresh.reconcileAfterStop(encryption: restored)
    XCTAssertEqual(recovered.committedChunks, 1080)
    XCTAssertEqual(recovered.committedPlaintextBytes, 345_647_520)
    XCTAssertEqual(recovered.completionIntent, initial.completionIntent)
    XCTAssertEqual(keys.value, originalKey)
    let renderer = RendererSecureQueueStore(store: reopenedDisk)
    let queueKeys = try native.listRecordingKeys(prefix: prefix)
    for key in [try XCTUnwrap(queueKeys.first), try XCTUnwrap(queueKeys.last)] {
      let record = try renderer.get(key: key)
      let value = try XCTUnwrap(JSONSerialization.jsonObject(with: record.data) as? [String: Any])
      XCTAssertEqual(value["state"] as? String, "encrypted")
      let filename = try SecureQueueRecordCodec.filename(
        for: SecureQueueRecordCodec.digest(for: key))
      let file = disk.directoryURL.appendingPathComponent(filename)
      let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
      #if !os(iOS) || targetEnvironment(simulator)
        // Mac and Simulator cannot prove iPhone Data Protection while locked.
        if let protection = attributes[.protectionKey] as? String {
          XCTAssertEqual(
            protection, FileProtectionType.completeUntilFirstUserAuthentication.rawValue)
        }
      #else
        XCTAssertEqual(
          attributes[.protectionKey] as? String,
          FileProtectionType.completeUntilFirstUserAuthentication.rawValue)
      #endif
    }
    XCTAssertEqual(
      try disk.directoryURL.resourceValues(forKeys: [.isExcludedFromBackupKey])
        .isExcludedFromBackup, true)
    let sealed = try await fresh.sealForUpload(encryption: restored, lease: XCTUnwrap(lastLease))
    XCTAssertEqual(sealed.phase, .sealed)
    XCTAssertEqual(sealed.completionIntent, initial.completionIntent)
    let final = NativeRecordingFlowOwner(
      scope: scope, recoveryScope: recovery, service: service,
      records: NativeRecordingQueueStore(store: reopenedDisk))
    let reopened = try await final.open()
    XCTAssertEqual(reopened, sealed)
    XCTAssertEqual(keys.value, originalKey)
    print(
      "Synthetic native queue: 1080 packets, 345647520 WAV bytes, authenticated reopen and sealed recovery; elapsed=\(Date().timeIntervalSince(started))s"
    )
  }

}

private final class LongVisitKeys: NativeRecordingKeyStorage, @unchecked Sendable {
  var value: Data?
  func read(account: String) -> Data? { value }
  func insert(account: String, value: Data) throws {
    guard self.value == nil else { throw NativeRecordingFailure.keyConflict }
    self.value = value
  }
}

private actor LongVisitService: NativeRecordingBindingService, NativeRecordingReservationService {
  let scope: NativeRecordingScope
  init(scope: NativeRecordingScope) { self.scope = scope }
  func recordingScope() -> NativeRecordingScope { scope }
  func publishedKey() throws -> NativeRecordingPublicKey { throw NativeRecordingFailure.invalidKey }
  func bind(key: NativeRecordingKeyReceipt, intent: UUID) throws
    -> NativeRecordingBindingAcknowledgement
  {
    throw NativeRecordingFailure.invalidKey
  }
  nonisolated func lease(generation: Int) throws -> NativeRecordingLease {
    let start = Date(timeIntervalSince1970: 1_790_424_000 + Double((generation - 1) * 900))
    return try NativeRecordingLease(
      receiptID: UUID(), leaseID: UUID(), sessionID: scope.sessionID,
      generation: generation, issuedAt: ISO8601DateFormatter().string(from: start),
      expiresAt: ISO8601DateFormatter().string(from: start.addingTimeInterval(900)))
  }
  func reserve(lease: NativeRecordingLease, first: Int, count: Int, intent: UUID) throws
    -> NativeRecordingReservationBatch
  {
    let reservations = try (first..<(first + count)).map { sequence in
      let object = UUID()
      return try NativeRecordingReservation(
        scope: scope, objectID: object, sequence: sequence,
        additionalData: nativeBase64URL(scope.additionalData(objectID: object, sequence: sequence)),
        createdAt: lease.issuedAt)
    }
    return NativeRecordingReservationBatch(
      batchID: UUID(), sessionID: scope.sessionID,
      authorizedUntil: lease.expiresAt, reservations: reservations)
  }
}
