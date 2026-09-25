import { useEffect } from "react";

// Presence only: no text, request bodies, identity or credentials leave the editor.
const pending = new Set<symbol>();
const warn = (event: BeforeUnloadEvent) => {
  if (!pending.size) return;
  event.preventDefault();
  event.returnValue = "unsaved";
};

export const hasUnsavedWork = () => pending.size > 0;

/** Protect intentional navigation; this is not persistence after an OS/app crash. */
export function useUnsavedWork(unsafe: boolean): void {
  useEffect(() => {
    if (!unsafe) return;
    const editor = Symbol();
    pending.add(editor);
    if (pending.size === 1) window.addEventListener("beforeunload", warn);
    return () => {
      pending.delete(editor);
      if (!pending.size) window.removeEventListener("beforeunload", warn);
    };
  }, [unsafe]);
}
