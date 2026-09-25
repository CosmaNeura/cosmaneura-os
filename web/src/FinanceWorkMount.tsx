import { useContext, useMemo } from "react";
import { EditorRecoveryContext, editorDraft } from "./editor-recovery";
import { editorAddress } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import { FinanceWorkPanel } from "./FinanceWorkPanel";
import type { FinanceRecoveryAccess } from "./finance-recovery";
import type { WorkspaceIdentity } from "./workspace-api";

export const FINANCE_WORK_BUILD = import.meta.env.VITE_FINANCE_WORK_ENABLED === "true";

export function FinanceWorkspaceMount({ identity, workspaceId, locked }: {
  identity: WorkspaceIdentity; workspaceId: string; locked?: boolean;
}) {
  const context = useContext(EditorRecoveryContext);
  const recovery = useMemo<FinanceRecoveryAccess | null>(() => {
    if (!context || context.workspaceId !== workspaceId) return null;
    const address = editorAddress(workspaceId, "finance-work");
    return {
      async load() {
        const draft = await context.journal.load(address);
        if (draft && (draft.kind !== "editor" || draft.editor !== "finance-work" || draft.workspaceId !== workspaceId || draft.pending !== null)) throw new DraftStoreError("integrity");
        return draft?.data ?? null;
      },
      persist: value => context.journal.persist(address, value ? editorDraft(workspaceId,"finance-work",value) : null),
      async authorize() { await context.authorize(); },
      denied: error => context.denied(error),
    };
  }, [context, workspaceId, identity]);
  return <FinanceWorkPanel identity={identity} workspaceId={workspaceId} recovery={recovery} locked={locked} />;
}
