import { useContext, useMemo } from "react";
import { EditorRecoveryContext, editorDraft } from "./editor-recovery";
import { editorAddress } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import { PortalWorkPanel } from "./PortalWorkPanel";
import type { PortalWorkRecoveryAccess } from "./portal-work-recovery";
import type { WorkspaceIdentity } from "./workspace-api";

export const PORTAL_WORK_BUILD = import.meta.env.VITE_PORTAL_WORK_ENABLED === "true";

export function PortalWorkspaceMount({ identity, workspaceId, locked }: {
  identity: WorkspaceIdentity; workspaceId: string; locked?: boolean;
}) {
  const context = useContext(EditorRecoveryContext);
  const recovery = useMemo<PortalWorkRecoveryAccess | null>(() => {
    if (!context || context.workspaceId !== workspaceId) return null;
    const address = editorAddress(workspaceId, "portal-work");
    return {
      async load() {
        const draft = await context.journal.load(address);
        if (draft && (draft.kind !== "editor" || draft.editor !== "portal-work" || draft.workspaceId !== workspaceId || draft.pending !== null)) throw new DraftStoreError("integrity");
        return draft?.data ?? null;
      },
      persist: value => context.journal.persist(address, value ? editorDraft(workspaceId,"portal-work",value) : null),
      async authorize() { await context.authorize(); },
      denied: error => context.denied(error),
    };
  }, [context, workspaceId, identity]);
  return <PortalWorkPanel identity={identity} workspaceId={workspaceId} recovery={recovery} locked={locked} />;
}
