import {parsePendingReviewDecision} from "../../clients/scribe-review/creator-review-journal";
import {validScribeSourceRequest} from './scribe-source-api';
import {validateResearchDraft} from './research-contract';
import { DraftStoreError, type DraftRecord, type DraftStore, type DraftValue } from "./draft-store";
import type { PendingSave } from "./EncounterWorkspace";
import type { ProviderTeam, TeamConfiguration, TeamSaveInput, Workspace } from "./workspace-api";
import { validTeamConfiguration, validTeamSave } from "./team-setup-request";
import { validPracticeOperation, type PracticeWorkOperation } from "./practice-work-request";
import {modelRequestHash, validModelOperation,validPreviousModelRequest,type PreviousModelRequest} from "./model-work-request";
import { validateVendorRecovery } from "./vendor-recovery";
import { validatePortalRecovery } from "./portal-setup-recovery";
import { validateFinanceRecovery } from "./finance-recovery";
import { validatePortalWorkRecovery } from "./portal-work-recovery";
import { validateFinanceSetupRecovery } from "./finance-setup-recovery";
import { validateMembershipRecovery } from "./membership-recovery";
import { validateMembership } from "./membership-contract";
import { validateVendorSetupRecovery } from "./vendor-setup-recovery";
import { validateInbox } from "./inbox-contract";
import { validateInboxRecovery } from "./inbox-recovery";
import { validInboxHandoffActor, validateInboxHandoffRecovery } from "./inbox-handoff-recovery";
import { validGoogleMessageScope, validateGoogleMessageRecovery } from "./google-message-recovery";
import { validGoogleCalendarScope, validateGoogleCalendarRecovery } from "./google-calendar-recovery";

export type TeamDraft = { kind: "team"; baseRevision: number; configuration: TeamConfiguration; pending: TeamSaveInput | null };
export type NotebookDraft = { kind: "workspace"; workspaceId: string; baseRevision: number;
  note: string; thought: string; evidence: string; source: string; pending: Exclude<PendingSave, { type: "team"; body: TeamSaveInput }> | null;previous_model_request?:PreviousModelRequest };
export type EditorKind = "private-note" | "core-note" | "transcript" | "scribe-source" | `creator-review:${string}` | "follow-up-proposal" | "appointments" | "prep-work" | "vendor-work" | "finance-work" | "portal-work" | "membership-work" | `follow-up-result:${string}` | `research:${string}`;
export type EditorDraft = { kind: "editor"; workspaceId: string; editor: EditorKind; data: unknown; pending: string | null };
export type AccountOperationDraft = {kind: "account-operation"; lane: "practice-work"; pending: PracticeWorkOperation};
export type AccountEditorKind = "work-routine" | "portal_setup" | "finance-setup" | "vendor-setup" | "inbox-work" | "inbox-handoffs" | "google-messages" | "google-calendar" | `practice-result:${string}` | `vendor-work:${string}`;
export type AccountEditorDraft = {kind:"account-editor";editor:AccountEditorKind;data:unknown;pending:string|null};
export const accountEditorAddress = (editor: AccountEditorKind) => `account-editor:${editor}`;
export type RecoveredDraft = TeamDraft | NotebookDraft | EditorDraft | AccountOperationDraft | AccountEditorDraft;
export type RecoveryOffer = { address: string; draft: TeamDraft | NotebookDraft };
export const editorAddress = (workspaceId: string, editor: EditorKind) => `editor:${workspaceId}:${editor}`;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const validEditor = (kind: unknown) => typeof kind === "string" &&
  (["private-note", "core-note", "transcript", "scribe-source", "follow-up-proposal", "appointments", "prep-work", "vendor-work", "finance-work", "portal-work", "membership-work"].includes(kind) ||
    kind.startsWith("creator-review:") && UUID.test(kind.slice("creator-review:".length)) ||
    kind.startsWith("follow-up-result:") && UUID.test(kind.slice("follow-up-result:".length)) || kind.startsWith("research:") && UUID.test(kind.slice("research:".length)));
const operations = ["entry", "ask", "retry", "note", "coreNoteLink", "review", "followUpPropose", "followUpDecision", "followUpComplete", "link"];

export function notebookDraft(workspace: Workspace, note: string, thought: string, evidence: string, source: string,
  pending: PendingSave | null,previous:PreviousModelRequest|null=null): NotebookDraft | null {
  const operation = pending?.type === "team" ? null : pending;
  const latest = workspace.entries.filter(e => e.kind === "scratchpad").at(-1)?.content ?? "";
  if (!operation && !previous && note === latest && !thought && !evidence && !source) return null;
  const history=operation&&(operation.type==='ask'||operation.type==='retry')&&operation.previous_model_request?null:previous;
  return { kind: "workspace", workspaceId: workspace.id, baseRevision: workspace.revision,
    note, thought, evidence, source, pending: operation,...(history?{previous_model_request:history}:{}) };
}
export function teamDraft(team: ProviderTeam, configuration: TeamConfiguration, pending: PendingSave | null): TeamDraft | null {
  const operation = pending?.type === "team" ? pending.body : null;
  if (!operation && same(team.configuration, configuration)) return null;
  return { kind: "team", baseRevision: operation?.expected_revision ?? team.revision, configuration, pending: operation };
}
function request(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const body = value as Record<string, unknown>;
  return Number.isSafeInteger(body.expected_revision) && (body.expected_revision as number) >= 0 &&
    typeof body.idempotency_key === "string" && /^[A-Za-z0-9._:-]{8,255}$/.test(body.idempotency_key);
}
function pendingRequest(value: unknown): boolean {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const operation = value as Record<string,unknown>;
  if (typeof operation.type !== "string" || !operations.includes(operation.type)) return false;
  if(operation.type==='ask'||operation.type==='retry')return validModelOperation(operation);
  if (operation.type !== "followUpDecision" && operation.type !== "followUpComplete") return request(operation.body);
  // Follow-up authority binds an immutable ticket revision, not a notebook
  // revision. Preserve its actual wire body; never invent approval or retry fields.
  if (Object.keys(operation).sort().join(",") !== "body,ticketId,type" ||
      typeof operation.ticketId !== "string" || !UUID.test(operation.ticketId) ||
      !operation.body || typeof operation.body !== "object" || Array.isArray(operation.body)) return false;
  const body = operation.body as Record<string,unknown>;
  if (typeof body.revision_id !== "string" || !UUID.test(body.revision_id) ||
      typeof body.payload_hash !== "string" || !/^[a-f0-9]{64}$/.test(body.payload_hash)) return false;
  if (operation.type === "followUpDecision") return Object.keys(body).sort().join(",") === "choice,payload_hash,revision_id" &&
    (body.choice === "approve" || body.choice === "reject");
  return Object.keys(body).sort().join(",") === "evidence,idempotency_key,payload_hash,revision_id" &&
    typeof body.idempotency_key === "string" && /^[A-Za-z0-9:_-]{8,100}$/.test(body.idempotency_key) &&
    typeof body.evidence === "string" && !!body.evidence.trim() && body.evidence.length <= 2000;
}
function parse(value: DraftValue | null, address: string): RecoveredDraft | null {
  if (!value) return null;
  const draft = value.body as RecoveredDraft;
  if (draft && draft.kind === "account-editor") {
    if (Object.keys(draft).sort().join(",")!=="data,editor,kind,pending" ||
        typeof draft.editor!=="string" || !(draft.editor==="work-routine" || draft.editor==="portal_setup" || draft.editor==="finance-setup" || draft.editor==="vendor-setup" || draft.editor==="inbox-work" || draft.editor==="inbox-handoffs" || draft.editor==="google-messages" || draft.editor==="google-calendar" ||
          draft.editor.startsWith("practice-result:") && UUID.test(draft.editor.slice("practice-result:".length)) ||
          draft.editor.startsWith("vendor-work:") && UUID.test(draft.editor.slice("vendor-work:".length))) ||
        address!==accountEditorAddress(draft.editor) || draft.pending!==null && !UUID.test(draft.pending) ||
        !draft.data || typeof draft.data!=="object" || Array.isArray(draft.data)) throw new DraftStoreError("integrity");
    return draft;
  }
  if (draft && draft.kind === "account-operation") {
    if (address !== "account:practice-work" || Object.keys(draft).sort().join(",") !== "kind,lane,pending" ||
        draft.lane !== "practice-work" || !validPracticeOperation(draft.pending)) throw new DraftStoreError("integrity");
    return draft;
  }
  if (draft && draft.kind === "editor") {
    if (Object.keys(draft).sort().join(",") !== "data,editor,kind,pending,workspaceId" || !UUID.test(draft.workspaceId) ||
        !validEditor(draft.editor) || address !== editorAddress(draft.workspaceId, draft.editor) ||
        draft.pending !== null && !UUID.test(draft.pending) && !(draft.editor.startsWith("creator-review:") && /^[A-Za-z0-9._-]{8,255}$/.test(draft.pending)) || !draft.data || typeof draft.data !== "object") throw new DraftStoreError("integrity");
    return draft;
  }
  if (!draft || typeof draft !== "object" || !Number.isSafeInteger(draft.baseRevision) || draft.baseRevision < 0) throw new DraftStoreError("integrity");
  if (draft.kind === "team") {
    if (address !== "team" || Object.keys(draft).sort().join(",") !== "baseRevision,configuration,kind,pending" ||
        !validTeamConfiguration(draft.configuration, true) ||
        draft.pending !== null && (!validTeamSave(draft.pending) || draft.pending.expected_revision !== draft.baseRevision || !same(draft.pending.configuration, draft.configuration))) throw new DraftStoreError("integrity");
  } else if (draft.kind === "workspace") {
    if (!UUID.test(draft.workspaceId) || address !== `workspace:${draft.workspaceId}` ||
        Object.keys(draft).filter(k=>k!=='previous_model_request').sort().join(",") !== "baseRevision,evidence,kind,note,pending,source,thought,workspaceId" ||
        [draft.note, draft.thought, draft.evidence, draft.source].some(text => typeof text !== "string") ||
        draft.pending !== null && !pendingRequest(draft.pending)) throw new DraftStoreError("integrity");
    if((draft.pending?.type==='ask'||draft.pending?.type==='retry')&&draft.pending.previous_model_request&&draft.pending.previous_model_request.workspace_id!==draft.workspaceId)throw new DraftStoreError('integrity');
    if(draft.previous_model_request!==undefined&&(!validPreviousModelRequest(draft.previous_model_request)||draft.previous_model_request.workspace_id!==draft.workspaceId||
      (draft.pending?.type==='ask'||draft.pending?.type==='retry')&&draft.pending.previous_model_request))throw new DraftStoreError('integrity');
  } else throw new DraftStoreError("integrity");
  return draft;
}
async function verifyModelHistory(draft:RecoveredDraft|null):Promise<void> {
  if (draft?.kind === "account-editor" && draft.editor === "google-calendar") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {const scope=(draft.data as {scope?:unknown}).scope;if(!validGoogleCalendarScope(scope))throw new Error();await validateGoogleCalendarRecovery(draft.data,scope);}
    catch {throw new DraftStoreError("integrity");}return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "google-messages") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {
      const scope = (draft.data as {scope?:unknown}).scope;
      if (!validGoogleMessageScope(scope)) throw new DraftStoreError("integrity");
      await validateGoogleMessageRecovery(draft.data, scope);
    } catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if(draft?.kind==='editor'&&draft.editor==='scribe-source'){
    if(!validScribeSourceRequest(draft.data)||draft.pending!==draft.data.idempotency_key)throw new DraftStoreError('integrity');
    return;
  }
  if (draft?.kind === "editor" && draft.editor.startsWith("creator-review:")) {
    try {
      const operation = parsePendingReviewDecision(draft.data);
      if (draft.pending !== operation.key) throw new DraftStoreError("integrity");
    } catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if(draft?.kind==='editor'&&draft.editor.startsWith('research:')){
    try{const data=validateResearchDraft(draft.data,draft.editor.slice('research:'.length));if(draft.pending!==(data.pending?.request.idempotency_key??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "inbox-handoffs") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {
      const actor = (draft.data as {actor?:unknown}).actor;
      if (!validInboxHandoffActor(actor)) throw new DraftStoreError("integrity");
      await validateInboxHandoffRecovery(draft.data, actor);
    } catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "inbox-work") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {
      const scope = validateInbox("Scope", (draft.data as {scope?:unknown}).scope);
      await validateInboxRecovery(draft.data, scope);
    } catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "vendor-setup") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try { await validateVendorSetupRecovery(draft.data); }
    catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "editor" && draft.editor === "membership-work") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {
      const scope = validateMembership("Scope", (draft.data as {scope?:unknown}).scope);
      if (scope.workspace_id !== draft.workspaceId) throw new DraftStoreError("integrity");
      await validateMembershipRecovery(draft.data,scope);
    } catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "finance-setup") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try { await validateFinanceSetupRecovery(draft.data); }
    catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "editor" && draft.editor === "portal-work") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try { await validatePortalWorkRecovery(draft.data,{kind:"workspace",id:draft.workspaceId}); }
    catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "editor" && draft.editor === "finance-work") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try { await validateFinanceRecovery(draft.data,{kind:"workspace",id:draft.workspaceId}); }
    catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "portal_setup") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try { await validatePortalRecovery(draft.data); }
    catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if (draft?.kind === "editor" && draft.editor === "vendor-work" || draft?.kind === "account-editor" && draft.editor.startsWith("vendor-work:")) {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {
      await validateVendorRecovery(draft.data, draft.kind === "editor"
        ? {kind:"workspace",id:draft.workspaceId} : {kind:"practice_work",id:draft.editor.slice("vendor-work:".length)});
    } catch { throw new DraftStoreError("integrity"); }
    return;
  }
  if(draft?.kind!=='workspace')return;
  const prior=draft.previous_model_request??((draft.pending?.type==='ask'||draft.pending?.type==='retry')?draft.pending.previous_model_request:undefined);
  if(prior&&prior.request_sha256!==await modelRequestHash(prior.operation.body))throw new DraftStoreError('integrity');
}

/** Serial, compare-and-swap writes. Never sends a request or fetches another scope. */
export class DraftJournal {
  readonly records = new Map<string, DraftRecord>();
  private chain: Promise<unknown> = Promise.resolve();
  private active = true;
  constructor(private readonly store: DraftStore) {}
  has(address: string): boolean { return this.records.has(address); }
  async load(address: string): Promise<RecoveredDraft | null> {
    // A newly mounted editor must see writes queued by its predecessor.
    await this.chain.catch(() => {});
    if (!this.active) throw new DraftStoreError("unavailable");
    const record = await this.store.read(address);
    if (!this.active) throw new DraftStoreError("unavailable");
    const draft = parse(record.value, address);
    await verifyModelHistory(draft);
    if (!this.active) throw new DraftStoreError("unavailable");
    this.records.set(address, record);
    return draft;
  }
  persist(address: string, body: RecoveredDraft | null): Promise<void> {
    // Snapshot before enqueueing: later input mutations cannot change this save.
    const copy = structuredClone(body);
    const task = async () => {
      if (!this.active || !this.records.has(address)) throw new DraftStoreError("unavailable");
      const previous = this.records.get(address)!;
      if (same(previous.value?.body ?? null, copy)) return;
      const value: DraftValue | null = copy ? { schema: 1, updatedAt: new Date().toISOString(), body: copy } : null;
      parse(value, address);
      await verifyModelHistory(copy);
      let saved: DraftRecord;
      try { saved = await this.store.write(address, previous.revision, value); }
      catch (error) {
        // The native/database write might have committed before its reply failed.
        // Adopt only the identical body; another writer remains a visible conflict.
        const current = await this.store.read(address);
        const restored=parse(current.value,address);await verifyModelHistory(restored);
        if (!same(restored, copy)) throw error;
        saved = current;
      }
      if (!this.active) throw new DraftStoreError("unavailable");
      this.records.set(address, saved);
    };
    const result = this.chain.catch(() => {}).then(task);
    this.chain = result;
    return result;
  }
  close(): void { this.active = false; this.records.clear(); this.store.close(); }
}
