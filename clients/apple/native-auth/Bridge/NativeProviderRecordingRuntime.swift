import CosmasNativeAuth
import Foundation

/// One process lifetime, shared by replacement WebViews. Authentication changes
/// still retire native audio while no renderer is attached. Renderer ownership
/// and native custody are mutually exclusive before either can prepare a source.
@MainActor final class NativeProviderRecordingRuntime {
  typealias Resources = (connection: NativeProviderConnection, recovery: NativeSourceRecovery)
  let auth: NativeWorkspaceAuth
  let recording = NativeProviderRecordingBridge()
  private let makeResources: @MainActor (NativeWorkspaceAuth) throws -> Resources
  private var retainedResources: Resources?
  private var rendererOwner: UUID?
  private var rendererBusy = false
  private var observerID: UUID?
  private var observer: (@MainActor (NativeAuthState) -> Void)?

  init(auth: NativeWorkspaceAuth,
       makeResources: @escaping @MainActor (NativeWorkspaceAuth) throws -> Resources) {
    self.auth = auth; self.makeResources = makeResources
    auth.onChange = { [weak self] state in
      guard let self else { return }
      self.retainedResources?.connection.authChanged(state)
      self.recording.authChanged(state)
      self.observer?(state)
    }
  }

  func attach(_ id: UUID, observer: @escaping @MainActor (NativeAuthState) -> Void) {
    observerID = id; self.observer = observer
  }

  func detach(_ id: UUID) {
    guard observerID == id else { return }
    observerID = nil; observer = nil
  }

  func resources() throws -> Resources {
    if let retainedResources { return retainedResources }
    let resources = try makeResources(auth)
    retainedResources = resources
    return resources
  }

  func claimRendererSource(_ id: UUID) throws {
    guard !rendererBusy, !recording.hasRetainedRecording,
          rendererOwner == nil || rendererOwner == id else {
      throw ProviderNativeError.unavailable
    }
    rendererOwner = id; rendererBusy = true
  }

  func finishRendererOperation(_ id: UUID, retainingSource: Bool) {
    guard rendererOwner == id else { return }
    rendererBusy = false
    if !retainingSource { rendererOwner = nil }
  }

  func releaseRendererSource(_ id: UUID) {
    if rendererOwner == id && !rendererBusy { rendererOwner = nil }
  }

  func requireNativeAvailable() throws {
    guard rendererOwner == nil else { throw ProviderNativeError.unavailable }
  }

  func confirmRendererReplacement() throws {
    try requireNativeAvailable()
    try recording.confirmRendererReplacement()
  }
}
