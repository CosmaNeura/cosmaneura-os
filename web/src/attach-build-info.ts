import { buildVersionLabel } from "./build-info";
import "./build-info.css";

const HOSTS = [".settings-hub", ".team-sidebar-bottom", "main.shell"] as const;

function ensureLabel(host: Element, label: string) {
  const existing = host.querySelector<HTMLElement>(":scope > .workspace-build-info");
  if (existing) {
    if (existing.textContent !== label) existing.textContent = label;
    return;
  }
  const footer = document.createElement("p");
  footer.className = "workspace-build-info";
  footer.dataset.buildInfo = "true";
  footer.textContent = label;
  host.append(footer);
}

function sync(root: ParentNode, label: string) {
  for (const selector of HOSTS) {
    root.querySelectorAll(selector).forEach(host => ensureLabel(host, label));
  }
}

/** Place the build label in Settings and workspace footers without editing those hosts. */
export function attachBuildInfo(root: ParentNode = document, label = buildVersionLabel()): () => void {
  sync(root, label);
  if (typeof MutationObserver !== "function") return () => undefined;
  const target = root instanceof Document ? root.documentElement : root instanceof Element ? root : null;
  if (!target) return () => undefined;
  const observer = new MutationObserver(() => sync(root, label));
  observer.observe(target, { childList: true, subtree: true });
  return () => observer.disconnect();
}
