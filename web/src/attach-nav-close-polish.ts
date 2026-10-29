import "./nav-close-polish.css";

const CLOSE_LABEL = "Close notebook";

function isCloseNotebookButton(node: Element): node is HTMLButtonElement {
  if (!(node instanceof HTMLButtonElement)) return false;
  const label = (node.getAttribute("aria-label") || node.textContent || "").replace(/\s+/g, " ").trim();
  return label === CLOSE_LABEL;
}

function polishCloseButtons(root: ParentNode) {
  root.querySelectorAll("button").forEach(button => {
    if (!isCloseNotebookButton(button)) return;
    if (button.dataset.navClosePolish !== "true") button.dataset.navClosePolish = "true";
    if (!button.getAttribute("aria-label")) button.setAttribute("aria-label", CLOSE_LABEL);
  });
}

/** Mark Close notebook controls and load nav-highlight CSS without editing EncounterWorkspace. */
export function attachNavClosePolish(root: ParentNode = document): () => void {
  polishCloseButtons(root);
  if (typeof MutationObserver !== "function") return () => undefined;
  const target = root instanceof Document ? root.documentElement : root instanceof Element ? root : null;
  if (!target) return () => undefined;
  const observer = new MutationObserver(() => polishCloseButtons(root));
  observer.observe(target, { childList: true, subtree: true, characterData: true });
  return () => observer.disconnect();
}
