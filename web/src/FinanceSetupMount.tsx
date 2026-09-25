import type {SetupPresentation} from './connection-setup-flow';
import { useContext, useMemo, useRef } from "react";
import { AccountRecoveryContext } from "./account-recovery";
import { accountEditorAddress } from "./draft-journal";
import { DraftStoreError } from "./draft-store";
import { FinanceSetupPanel } from "./FinanceSetupPanel";
import type { FinanceSetupRecoveryAccess } from "./finance-setup-recovery";
import type { WorkspaceIdentity } from "./workspace-api";

export const FINANCE_SETUP_BUILD = import.meta.env.VITE_FINANCE_SETUP_ENABLED === "true";

export function FinanceSetupMount({ identity, onDenied, presentation='expanded', onBusyChange }: {
  identity: WorkspaceIdentity; onDenied: (error: unknown) => void; presentation?:SetupPresentation; onBusyChange?:(blocked:boolean)=>void;
}) {
  const context = useContext(AccountRecoveryContext);
  const denied = useRef(onDenied); denied.current = onDenied;
  const recovery = useMemo<FinanceSetupRecoveryAccess | null>(() => {
    if (!context) return null;
    const editor = "finance-setup", address = accountEditorAddress(editor);
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
  return <FinanceSetupPanel identity={identity} recovery={recovery} presentation={presentation} onBusyChange={onBusyChange} />;
}
