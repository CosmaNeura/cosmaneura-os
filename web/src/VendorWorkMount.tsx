import { useContext, useMemo, useRef } from "react";
import { EditorRecoveryContext, editorDraft } from "./editor-recovery";
import { AccountRecoveryContext } from "./account-recovery";
import { accountEditorAddress, editorAddress } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import { VendorWorkPanel } from "./VendorWorkPanel";
import { VendorSharedWorkCard } from "./VendorSharedWorkCard";
import type { VendorRecoveryAccess } from "./vendor-recovery";
import type { SharedVendorWork, Person } from "./vendor-schema";
import type { WorkspaceIdentity } from "./workspace-api";

/** Connect delivery editors to the existing account-scoped encrypted journal. */
export function VendorWorkspaceMount({ identity, workspaceId, locked, onChanged }: {
  identity: WorkspaceIdentity; workspaceId: string; locked?: boolean; onChanged?: () => void;
}) {
  const context = useContext(EditorRecoveryContext);
  const recovery = useMemo<VendorRecoveryAccess | null>(() => {
    if (!context || context.workspaceId !== workspaceId) return null;
    const address = editorAddress(workspaceId, "vendor-work");
    return {
      async load() {
        const draft = await context.journal.load(address);
        if (draft && (draft.kind !== "editor" || draft.editor !== "vendor-work" || draft.workspaceId !== workspaceId || draft.pending !== null)) throw new DraftStoreError("integrity");
        return draft?.data ?? null;
      },
      persist: value => context.journal.persist(address, value ? editorDraft(workspaceId, "vendor-work", value) : null),
      async authorize() { await context.authorize(); },
      denied: error => context.denied(error),
    };
  }, [context, workspaceId, identity]);
  return <VendorWorkPanel identity={identity} workspaceId={workspaceId} recovery={recovery} locked={locked} onChanged={onChanged} />;
}

export function VendorPracticeMount({ identity, item, people, locked, onChanged, onDenied }: {
  identity: WorkspaceIdentity; item: SharedVendorWork; people: Person[]; locked?: boolean;
  onChanged?: () => void; onDenied: (error: unknown) => void;
}) {
  const context = useContext(AccountRecoveryContext);
  const denied = useRef(onDenied); denied.current = onDenied;
  const recovery = useMemo<VendorRecoveryAccess | null>(() => {
    if (!context) return null;
    const editor = `vendor-work:${item.ticket_id}` as const;
    const address = accountEditorAddress(editor);
    return {
      async load() {
        const draft = await context.journal.load(address);
        if (draft && (draft.kind !== "account-editor" || draft.editor !== editor || draft.pending !== null)) throw new DraftStoreError("integrity");
        return draft?.data ?? null;
      },
      persist: value => context.journal.persist(address, value ? {kind:"account-editor",editor,data:value,pending:null} : null),
      authorize: () => context.authorize(),
      denied: error => denied.current(error),
    };
  }, [context, item.ticket_id, identity]);
  return <VendorSharedWorkCard identity={identity} item={item} people={people} recovery={recovery} locked={locked} onChanged={onChanged} />;
}
