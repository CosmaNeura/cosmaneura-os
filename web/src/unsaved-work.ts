import { useCallback, useEffect, useRef } from "react";

// Presence only: no text, request bodies, identity or credentials leave the editor.
const pending = new Set<symbol>();
const warn = (event: BeforeUnloadEvent) => {
  if (!pending.size) return;
  event.preventDefault();
  event.returnValue = "unsaved";
};

export const hasUnsavedWork = () => pending.size > 0;

/** Protect navigation; release only this editor's marker after confirmed persistence. */
export function useUnsavedWork(unsafe: boolean): () => void {
  const active = useRef<symbol | null>(null);
  const release = useCallback(() => {
    const editor = active.current;
    if (editor === null) return;
    active.current = null;
    pending.delete(editor);
    if (!pending.size) window.removeEventListener("beforeunload", warn);
  }, []);
  useEffect(() => {
    if (!unsafe) return;
    const editor = Symbol();
    active.current = editor;
    pending.add(editor);
    if (pending.size === 1) window.addEventListener("beforeunload", warn);
    return () => {
      pending.delete(editor);
      if (active.current === editor) active.current = null;
      if (!pending.size) window.removeEventListener("beforeunload", warn);
    };
  }, [unsafe]);
  return release;
}
