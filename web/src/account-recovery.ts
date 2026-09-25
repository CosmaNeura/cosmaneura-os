import { createContext } from "react";
import type { DraftJournal } from "./draft-journal";

/** Private owner/API scope; available before selecting any encounter. */
export type AccountRecoveryAccess = {
  journal: DraftJournal;
  /** Fresh signed namespace used to bind actor-context reads; not an access grant. */
  recoveryScope?: string;
  authorize(): Promise<void>;
};
export const AccountRecoveryContext = createContext<AccountRecoveryAccess | null | undefined>(undefined);
