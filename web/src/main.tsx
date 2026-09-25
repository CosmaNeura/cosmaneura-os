import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RuntimeApp } from "./runtime";
import { notifyWorkspaceLifecycle } from "./workspace-lifecycle";
import "./styles.css";

createRoot(document.getElementById("root")!, {
  // The boundary presents safe recovery guidance; caught errors can contain
  // private workspace content and must not be copied to a diagnostic log.
  onCaughtError: () => {},
  onRecoverableError: () => {},
  onUncaughtError: () => {
    notifyWorkspaceLifecycle("failed");
    // React may still be removing its failed tree during this callback.
    queueMicrotask(() => {
      const root = document.getElementById("root");
      if (root) {
        const notice = document.createElement("p");
        notice.setAttribute("role", "alert");
        notice.textContent = "Your workspace could not continue. Close and reopen CosmasOS, then review saved work and unconfirmed requests before retrying. Unsaved edits may be missing; submitted work may still finish.";
        root.replaceChildren(notice);
      }
    });
  },
}).render(
  <StrictMode>
    <RuntimeApp />
  </StrictMode>,
);
