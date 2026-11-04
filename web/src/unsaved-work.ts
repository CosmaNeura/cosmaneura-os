import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";

// Presence only: no text, request bodies, identity or credentials leave the editor.
const pending = new Set<symbol>();
const observers = new Set<() => void>();
const notify = () => { for (const observer of observers) observer(); };
const warn = (event: BeforeUnloadEvent) => {
  if (!pending.size) return;
  event.preventDefault();
  event.returnValue = "unsaved";
};

export const hasUnsavedWork = () => pending.size > 0;
/** Account navigation observes only the existing editor/request presence fence. */
export function useUnsavedWorkPresent(): boolean {
  return useSyncExternalStore(observer => { observers.add(observer); return () => { observers.delete(observer); }; },
    hasUnsavedWork, () => false);
}

/** Protect navigation; release only this editor's marker after confirmed persistence. */
export function useUnsavedWork(unsafe: boolean): () => void {
  const active = useRef<symbol | null>(null);
  const release = useCallback(() => {
    const editor = active.current;
    if (editor === null) return;
    active.current = null;
    pending.delete(editor);
    notify();
    if (!pending.size) window.removeEventListener("beforeunload", warn);
  }, []);
  useEffect(() => {
    if (!unsafe) return;
    const editor = Symbol();
    active.current = editor;
    pending.add(editor);
    notify();
    if (pending.size === 1) window.addEventListener("beforeunload", warn);
    return () => {
      pending.delete(editor);
      notify();
      if (active.current === editor) active.current = null;
      if (!pending.size) window.removeEventListener("beforeunload", warn);
    };
  }, [unsafe]);
  return release;
}
