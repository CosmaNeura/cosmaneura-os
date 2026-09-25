type LifecycleKind = "ready" | "failed";
type LifecycleWindow = Pick<Window, "location"> & {
  __cosmasWorkspaceGeneration?: unknown;
  webkit?: { messageHandlers?: { cosmasWorkspaceLifecycle?: { postMessage: (value: unknown) => void } } };
  cosmasWorkspaceLifecycle?: { notify: (kind: LifecycleKind) => void };
};

// Only lifecycle state crosses this seam. Never include errors, identities,
// requests, or private workspace content in a native recovery notification.
export function createWorkspaceLifecycleNotifier(scope: LifecycleWindow) {
  let failed = false;
  return (kind: LifecycleKind) => {
    if (kind !== "ready" && kind !== "failed") return;
    if (failed) return;
    if (kind === "failed") failed = true;
    try {
      const page = new URL(scope.location.href);
      if (page.username || page.password || page.port || page.search || page.hash) return;
      if (page.protocol === "app:" && page.hostname === "cosmas" && page.pathname === "/index.html") {
        scope.cosmasWorkspaceLifecycle?.notify(kind);
      } else if (page.protocol === "capacitor:" && page.hostname === "localhost") {
        const generation = scope.__cosmasWorkspaceGeneration;
        if (typeof generation !== "string" ||
            !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(generation)) return;
        scope.webkit?.messageHandlers?.cosmasWorkspaceLifecycle?.postMessage({ kind, generation });
      }
    } catch {
      // The visible web recovery guidance still works without a native bridge.
    }
  };
}

export const notifyWorkspaceLifecycle = createWorkspaceLifecycleNotifier(window);
