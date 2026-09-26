import type {SetupPresentation} from './connection-setup-flow';
import { useContext, useMemo, useRef } from "react";
import { AccountRecoveryContext } from "./account-recovery";
import { accountEditorAddress } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import { PortalSetupPanel } from "./PortalSetupPanel";
import type { PortalRecoveryAccess } from "./portal-setup-recovery";
import type { WorkspaceIdentity } from "./workspace-api";

export const PORTAL_SETUP_BUILD = import.meta.env.VITE_PORTAL_SETUP_ENABLED === "true";

/** Portal setup has the same account-scoped encrypted recovery as other work. */
export function PortalSetupMount({ identity, onDenied, presentation='expanded', onBusyChange }: {
  identity: WorkspaceIdentity; onDenied: (error: unknown) => void; presentation?:SetupPresentation; onBusyChange?:(blocked:boolean)=>void;
}) {
  const context = useContext(AccountRecoveryContext);
  const denied = useRef(onDenied); denied.current = onDenied;
  const recovery = useMemo<PortalRecoveryAccess | null>(() => {
    if (!context) return null;
    const editor = "portal_setup", address = accountEditorAddress(editor);
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
  }, [context, identity]);
  return <PortalSetupPanel identity={identity} recovery={recovery} presentation={presentation} onBusyChange={onBusyChange} />;
}
