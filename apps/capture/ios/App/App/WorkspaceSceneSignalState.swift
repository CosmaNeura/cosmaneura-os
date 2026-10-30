import Foundation

/// Scene hints contain no authority. One generation belongs to one live bridge.
struct WorkspaceSceneSignalState {
    let generation: String
    private(set) var isReady = false
    private(set) var isClosed = false
    private var sceneActive = false
    private var lastDispatched: Bool?

    init(generation: String) { self.generation = generation }

    mutating func setSceneActive(_ active: Bool) {
        guard !isClosed else { return }
        sceneActive = active
    }

    mutating func ready(generation: String, mainFrame: Bool, sameOrigin: Bool) {
        guard !isClosed, generation == self.generation, mainFrame, sameOrigin else { return }
        isReady = true
    }

    var pending: Bool? {
        guard isReady, !isClosed, lastDispatched != sceneActive else { return nil }
        return sceneActive
    }

    mutating func didDispatch(_ active: Bool, generation: String) {
        guard !isClosed, isReady, generation == self.generation, active == sceneActive else { return }
        lastDispatched = active
    }

    mutating func close() { isClosed = true }

    static func script(generation: String, active: Bool) -> String? {
        guard UUID(uuidString: generation) != nil,
              let data = try? JSONSerialization.data(withJSONObject: ["generation": generation, "active": active],
                                                      options: [.sortedKeys]),
              let detail = String(data: data, encoding: .utf8) else { return nil }
        // WebKit may queue evaluation. Recheck the document and immutable bridge
        // generation at delivery; a late hint must not reach a replacement page.
        return """
        (() => {
            const detail = \(detail);
            if (window !== window.top || window.location.protocol !== 'capacitor:' ||
                window.location.hostname !== 'localhost' || window.location.port !== '' ||
                window.__cosmasWorkspaceGeneration !== detail.generation) return;
            window.dispatchEvent(new CustomEvent('cosmas:native-scene-state', {detail}));
        })();
        """
    }
}
