import Foundation
import Testing
import CosmaneuraIOSAVFoundationDriver
import CosmaneuraIOSPCMCore

struct PermissionDismissalTests {
  @Test func waitsForPermissionModalToRestoreForeground() async {
    let foreground = DismissalForeground(activeAfter: 3)
    let permission = AVFoundationMicrophonePermissionAdapter(provider: ModalPermission(), foreground: foreground)
    let result = await permission.requestPermission(cancellation: StartupCancellation())
    #expect(result == .granted)
    #expect(foreground.checks == 3)
  }

  @Test func stopDuringModalDismissalCannotCompleteReadiness() async {
    let cancellation = StartupCancellation()
    let foreground = DismissalForeground(activeAfter: 3, cancellation: cancellation)
    let permission = AVFoundationMicrophonePermissionAdapter(provider: ModalPermission(), foreground: foreground)
    #expect(await permission.requestPermission(cancellation: cancellation) == .unavailable)
    #expect(foreground.checks == 1)
  }

  @Test func foregroundThatNeverReturnsEndsReadinessWithoutOpeningAudio() async {
    let foreground = DismissalForeground(activeAfter: 31)
    let permission = AVFoundationMicrophonePermissionAdapter(provider: ModalPermission(), foreground: foreground)
    #expect(await permission.requestPermission(cancellation: StartupCancellation()) == .unavailable)
    #expect(foreground.checks == 30)
  }

  @Test func alreadyGrantedPermissionDoesNotWaitForAnotherModal() async {
    let foreground = DismissalForeground(activeAfter: 3)
    let permission = AVFoundationMicrophonePermissionAdapter(provider: ModalPermission(alreadyGranted: true), foreground: foreground)
    #expect(await permission.requestPermission(cancellation: StartupCancellation()) == .granted)
    #expect(foreground.checks == 0)
  }
}

private struct ModalPermission: AppleMicrophonePermissionProviding {
  var alreadyGranted = false
  func currentPermission() -> AppleMicrophonePermissionState { alreadyGranted ? .granted : .notDetermined }
  func requestPermission() async -> AppleMicrophonePermissionState { .granted }
}

private final class DismissalForeground: AppleApplicationForegroundProviding, @unchecked Sendable {
  private let lock = NSLock()
  private var count = 0
  let activeAfter: Int
  let cancellation: StartupCancellation?
  init(activeAfter: Int, cancellation: StartupCancellation? = nil) {
    self.activeAfter = activeAfter; self.cancellation = cancellation
  }
  var checks: Int { lock.withLock { count } }
  func isForegroundActive() async -> Bool {
    let current = lock.withLock { count += 1; return count }
    cancellation?.cancel()
    return current >= activeAfter
  }
}
