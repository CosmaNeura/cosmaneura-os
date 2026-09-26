import { useContext, useEffect, useRef, useState } from "react";
import { mountCreatorReview } from "../../clients/scribe-review/creator-review-panel";
import { parsePendingReviewDecision, type PendingReviewDecision } from "../../clients/scribe-review/creator-review-journal";
import type { CreatorReviewView } from "../../clients/scribe-review/creator-review-api";
import { creatorReviewApi } from "./creator-review-api";
import { EditorRecoveryContext, editorDraft } from "./editor-recovery";
import { editorAddress } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import type { AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { useUnsavedWork } from "./unsaved-work";

/** Reuse Scribe's clinician review UI with the workspace's encrypted recovery store. */
export function CreatorReviewPanel({ workspaceId, sessionId, identity, locked, onLock, onSource, onContinue }: {
  workspaceId: string; sessionId: string; identity: AuthenticatedWorkspaceIdentity; locked: boolean;
  onLock: (locked: boolean) => void; onSource: (view: CreatorReviewView | null) => void;
  onContinue: () => Promise<void>;
}) {
  const root = useRef<HTMLDivElement>(null);
  const access = useContext(EditorRecoveryContext);
  const callbacks = useRef({onLock, onSource, onContinue, locked});
  callbacks.current = {onLock, onSource, onContinue, locked};
  const [retained, setRetained] = useState(false);
  useUnsavedWork(retained);
  useEffect(() => {
    if (!root.current || !access || access.workspaceId !== workspaceId) return;
    const controller = new AbortController();
    let current = true, pending: PendingReviewDecision | null = null, working = 0;
    const kind = `creator-review:${sessionId}` as const;
    const address = editorAddress(workspaceId, kind);
    const report = () => {
      if (current) { setRetained(pending !== null || working > 0); callbacks.current.onLock(pending !== null || working > 0); }
    };
    const requireCurrent = () => { if (!current || controller.signal.aborted) throw new DraftStoreError("unavailable"); };
    const authorize = async () => {
      requireCurrent();
      const workspace = await access.authorize();
      requireCurrent();
      if (workspace.id !== workspaceId) throw new DraftStoreError("integrity");
    };
    const load = async (): Promise<PendingReviewDecision | null> => {
      await authorize();
      const record = await access.journal.load(address);
      requireCurrent();
      if (record === null) return null;
      if (record.kind !== "editor" || record.workspaceId !== workspaceId || record.editor !== kind) throw new DraftStoreError("integrity");
      const result = parsePendingReviewDecision(record.data);
      if (record.pending !== result.key) throw new DraftStoreError("integrity");
      return result;
    };
    const journal = {
      load: async () => { pending = await load(); report(); return pending; },
      save: async (value: PendingReviewDecision) => {
        const selected = parsePendingReviewDecision(value);
        const previous = await load();
        if (previous && JSON.stringify(previous) !== JSON.stringify(selected)) throw new DraftStoreError("integrity");
        await access.journal.persist(address, editorDraft(workspaceId, kind, selected, selected.key));
        requireCurrent(); pending = selected; report();
      },
      clear: async (key: string) => {
        const previous = await load();
        if (previous && previous.key !== key) throw new DraftStoreError("integrity");
        await access.journal.persist(address, null);
        requireCurrent(); pending = null; report();
      },
    };
    const api = creatorReviewApi(workspaceId, sessionId, identity, controller.signal);
    const dispose = mountCreatorReview(root.current, {
      read: async () => {
        working++; report(); callbacks.current.onSource(null);
        try { const view = await api.read(); requireCurrent(); callbacks.current.onSource(view); return view; }
        finally { working--; report(); }
      },
      decide: async (decision, key) => {
        requireCurrent();
        if (callbacks.current.locked) throw new DraftStoreError("unavailable");
        working++; report(); callbacks.current.onSource(null);
        try { return await api.decide(decision, key); }
        finally { working--; report(); }
      },
    }, {journal, continueToNote: async () => {
      requireCurrent();
      if (callbacks.current.locked) throw new DraftStoreError("unavailable");
      await callbacks.current.onContinue();
    }});
    return () => {
      current = false; controller.abort(); dispose(); callbacks.current.onLock(false);
    };
  }, [access, workspaceId, sessionId, identity]);
  return <fieldset disabled={locked} className="capture-creator-review" aria-label="Recorded transcript review">
    {!access && <p role="status">Opening secure transcript review…</p>}
    <div ref={root} />
  </fieldset>;
}
