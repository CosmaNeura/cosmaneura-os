import {validateAthenaVisitRecovery,validAthenaVisitRecoveryScope} from './athena-visit-link-recovery';
import {validateCalendarRecovery,validCalendarOwner} from './calendar-import-recovery';
import {ehrProvider} from './ehr-read-api';
import {validateEhrReadRecovery,validEhrScope} from './ehr-read-recovery';
import {validateTebraRecovery,validTebraMedicationScope} from './tebra-medication-recovery';
import {parseConversationDraft} from './conversation-draft';
import {parseConversationPreferences} from './conversation-preferences';
import {teamAddress} from './team-setup-request';
import {validateInvitationRecovery} from './practice-invitation-contract';
import {validateTitleRecovery} from './notebook-metadata-contract';
import {parsePendingReviewDecision} from "../../clients/scribe-review/creator-review-journal";
import {validScribeSourceRequest} from './scribe-source-api';
import {validateResearchDraft} from './research-contract';
import { DraftStoreError, type DraftRecord, type DraftStore, type DraftValue } from "./draft-store";
import type { PendingSave } from "./session/model";
import {validShareSavedNoteInput} from './clinical-team-contract';
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
import {validOutlookMessageScope,validateOutlookMessageRecovery} from "./outlook-message-recovery";
import { validGoogleCalendarScope, validateGoogleCalendarRecovery } from "./google-calendar-recovery";
import {validateHandoffReviewRecovery} from './handoff-review-recovery';
import {validateFaxRecovery} from "./fax-inbound-recovery";
import {validFaxScope} from "./fax-inbound-api";
import {validateEFaxRecovery} from "./efax-inbound-recovery";
import {validateFaxSourceRecovery} from './fax-inbound-source-recovery';
import {validFaxSourceScope} from './fax-inbound-source-api';
import {validateEFaxSourceRecovery} from './efax-inbound-source-recovery';
import {validEFaxSourceScope} from './efax-inbound-source-api';
import {validateSchedulingPatientRecovery} from './scheduling-patient-recovery';
import {validateAgentResearchRecovery} from './agent-research-recovery';
import {validatePrivateDraftRecovery,validatePrivateDraftLinkRecovery} from './private-draft-recovery';

export type TeamDraft = { kind: "team"; baseRevision: number; configuration: TeamConfiguration; pending: TeamSaveInput | null };
export type ChiefNoteTaskDraft={contract:'chief-note-task.compose.v1';note_id:string;note_version:number;content_hash:string;source_fingerprint:string};
export type NotebookDraft = { kind: "workspace"; workspaceId: string; baseRevision: number;
  note: string; thought: string; evidence: string; source: string; pending: Exclude<PendingSave, { type: "team"; body: TeamSaveInput }> | null;previous_model_request?:PreviousModelRequest;chief_note_task?:ChiefNoteTaskDraft };
export type EditorKind = `conversation:${string}` | "notebook-title" | "private-draft-link" | "agent-research-review" | "private-note" | "core-note" | "transcript" | "scribe-source" | `creator-review:${string}` | `handoff-review:${string}` | `efax-source-review:${string}` | `fax-source-review:${string}` | "follow-up-proposal" | "appointments" | "scheduling-patient" | "ehr-read" | "ehr-read:tebra" | "ehr-read:tebra:fhir" | "calendar-import" | "prep-work" | "vendor-work" | "finance-work" | "portal-work" | "membership-work" | `follow-up-result:${string}` | `research:${string}`;
export type EditorDraft = { kind: "editor"; workspaceId: string; editor: EditorKind; data: unknown; pending: string | null };
export type AccountOperationDraft = {kind: "account-operation"; lane: "practice-work"; pending: PracticeWorkOperation};
export type AccountEditorKind = "athena-visit-link" | "conversation-preferences" | "practice-invite" | "private-draft" | "work-routine" | "portal_setup" | "finance-setup" | "vendor-setup" | "inbox-work" | "inbox-handoffs" | "google-messages" | "outlook-messages" | "google-calendar" | "efax-inbound" | "fax-inbound" | `practice-result:${string}` | `vendor-work:${string}`;
export type AccountEditorDraft = {kind:"account-editor";editor:AccountEditorKind;data:unknown;pending:string|null};
export const accountEditorAddress = (editor: AccountEditorKind) => `account-editor:${editor}`;
export type RecoveredDraft = TeamDraft | NotebookDraft | EditorDraft | AccountOperationDraft | AccountEditorDraft;
export type RecoveryOffer = { address: string; draft: TeamDraft | NotebookDraft };
export const editorAddress = (workspaceId: string, editor: EditorKind) => `editor:${workspaceId}:${editor}`;
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const UUID = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const validEditor = (kind: unknown) => typeof kind === "string" &&
  (kind.startsWith("conversation:") && teamAddress(kind.slice("conversation:".length)) || ["notebook-title", "private-draft-link", "agent-research-review", "private-note", "core-note", "transcript", "scribe-source", "follow-up-proposal", "appointments", "scheduling-patient", "ehr-read", "ehr-read:tebra", "ehr-read:tebra:fhir", "calendar-import", "prep-work", "vendor-work", "finance-work", "portal-work", "membership-work"].includes(kind) ||
    kind.startsWith("creator-review:") && UUID.test(kind.slice("creator-review:".length)) || kind.startsWith("handoff-review:") && UUID.test(kind.slice("handoff-review:".length)) ||
    kind.startsWith("fax-source-review:") && UUID.test(kind.slice("fax-source-review:".length)) ||
    kind.startsWith("efax-source-review:") && UUID.test(kind.slice("efax-source-review:".length)) ||
    kind.startsWith("follow-up-result:") && UUID.test(kind.slice("follow-up-result:".length)) || kind.startsWith("research:") && UUID.test(kind.slice("research:".length)));
const operations = ["entry", "ask", "retry", "note", "coreNoteLink", "review", "followUpPropose", "followUpDecision", "followUpComplete", "clinicalNoteShare", "link"];

export function notebookDraft(workspace: Workspace, note: string, thought: string, evidence: string, source: string,
  pending: PendingSave | null,previous:PreviousModelRequest|null=null,chiefNoteTask:ChiefNoteTaskDraft|null=null): NotebookDraft | null {
  const operation = pending?.type === "team" ? null : pending;
  const latest = workspace.entries.filter(e => e.kind === "scratchpad").at(-1)?.content ?? "";
  if (!operation && !previous && !chiefNoteTask && note === latest && !thought && !evidence && !source) return null;
  const history=operation&&(operation.type==='ask'||operation.type==='retry')&&operation.previous_model_request?null:previous;
  return { kind: "workspace", workspaceId: workspace.id, baseRevision: workspace.revision,
    note, thought, evidence, source, pending: operation,...(history?{previous_model_request:history}:{}),...(chiefNoteTask?{chief_note_task:chiefNoteTask}:{}) };
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
  if(operation.type==='clinicalNoteShare')return Object.keys(operation).sort().join(',')==='body,type'&&validShareSavedNoteInput(operation.body);
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
        typeof draft.editor!=="string" || !(draft.editor==="athena-visit-link" || draft.editor==="conversation-preferences" || draft.editor==="practice-invite" || draft.editor==="private-draft" || draft.editor==="work-routine" || draft.editor==="portal_setup" || draft.editor==="finance-setup" || draft.editor==="vendor-setup" || draft.editor==="inbox-work" || draft.editor==="inbox-handoffs" || draft.editor==="google-messages" || draft.editor==="outlook-messages" || draft.editor==="google-calendar" || draft.editor==="efax-inbound" || draft.editor==="fax-inbound" ||
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
    if(draft.editor.startsWith("conversation:")){if(draft.pending!==null)throw new DraftStoreError("integrity");parseConversationDraft(draft.data);}
    return draft;
  }
  if (!draft || typeof draft !== "object" || !Number.isSafeInteger(draft.baseRevision) || draft.baseRevision < 0) throw new DraftStoreError("integrity");
  if (draft.kind === "team") {
    if (address !== "team" || Object.keys(draft).sort().join(",") !== "baseRevision,configuration,kind,pending" ||
        !validTeamConfiguration(draft.configuration, true) ||
        draft.pending !== null && (!validTeamSave(draft.pending) || draft.pending.expected_revision !== draft.baseRevision || !same(draft.pending.configuration, draft.configuration))) throw new DraftStoreError("integrity");
  } else if (draft.kind === "workspace") {
    if (!UUID.test(draft.workspaceId) || address !== `workspace:${draft.workspaceId}` ||
        Object.keys(draft).filter(k=>!['previous_model_request','chief_note_task'].includes(k)).sort().join(",") !== "baseRevision,evidence,kind,note,pending,source,thought,workspaceId" ||
        [draft.note, draft.thought, draft.evidence, draft.source].some(text => typeof text !== "string") ||
        draft.pending !== null && !pendingRequest(draft.pending)) throw new DraftStoreError("integrity");
    if(draft.chief_note_task!==undefined){
      const task=draft.chief_note_task;
      if(!task||typeof task!=='object'||Array.isArray(task)||Object.keys(task).sort().join(',')!=='content_hash,contract,note_id,note_version,source_fingerprint'||
        task.contract!=='chief-note-task.compose.v1'||typeof task.note_id!=='string'||!UUID.test(task.note_id)||!Number.isSafeInteger(task.note_version)||task.note_version<1||task.note_version>50||
        typeof task.content_hash!=='string'||!/^[a-f0-9]{64}$/.test(task.content_hash)||typeof task.source_fingerprint!=='string'||!/^[a-f0-9]{64}$/.test(task.source_fingerprint))throw new DraftStoreError('integrity');
    }
    if((draft.pending?.type==='ask'||draft.pending?.type==='retry')&&draft.pending.previous_model_request&&draft.pending.previous_model_request.workspace_id!==draft.workspaceId)throw new DraftStoreError('integrity');
    if(draft.previous_model_request!==undefined&&(!validPreviousModelRequest(draft.previous_model_request)||draft.previous_model_request.workspace_id!==draft.workspaceId||
      (draft.pending?.type==='ask'||draft.pending?.type==='retry')&&draft.pending.previous_model_request))throw new DraftStoreError('integrity');
  } else throw new DraftStoreError("integrity");
  return draft;
}
async function verifyModelHistory(draft:RecoveredDraft|null):Promise<void> {
  if(draft?.kind==='account-editor'&&draft.editor==='athena-visit-link'){
    try{const scope=(draft.data as {scope?:unknown}).scope;if(draft.pending!==null||!validAthenaVisitRecoveryScope(scope))throw new Error();await validateAthenaVisitRecovery(draft.data,scope);}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='account-editor'&&draft.editor==='conversation-preferences'){
    try{if(draft.pending!==null)throw new Error();parseConversationPreferences(draft.data);}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='account-editor'&&draft.editor==='practice-invite'){
    try{const data=validateInvitationRecovery(draft.data);if(draft.pending!==(data.pending?.body.idempotency_key??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor==='notebook-title'){
    try{const data=validateTitleRecovery(draft.data,draft.workspaceId);if(draft.pending!==data.pending.idempotency_key)throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='account-editor'&&draft.editor==='private-draft'){
    try{const data=validatePrivateDraftRecovery(draft.data);if(draft.pending!==(data.pending?.idempotency_key??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor==='private-draft-link'){
    try{const data=validatePrivateDraftLinkRecovery(draft.data,draft.workspaceId);if(draft.pending!==(data.pending?.idempotency_key??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor==='agent-research-review'){
    try{const data=validateAgentResearchRecovery(draft.data,draft.workspaceId);
      if(draft.pending!==(data.pending?.revision_id??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor.startsWith('fax-source-review:')){
    try{const scope=(draft.data as {scope?:unknown}).scope;if(!validFaxSourceScope(scope)||scope.workspace_id!==draft.workspaceId||draft.pending!==null)throw new Error();
      const data=await validateFaxSourceRecovery(draft.data,scope);
      if(data.offered.operation_id!==draft.editor.slice('fax-source-review:'.length))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor.startsWith('efax-source-review:')){
    try{const scope=(draft.data as {scope?:unknown}).scope;if(!validEFaxSourceScope(scope)||scope.workspace_id!==draft.workspaceId||draft.pending!==null)throw new Error();
      const data=await validateEFaxSourceRecovery(draft.data,scope);
      if(data.offered.operation_id!==draft.editor.slice('efax-source-review:'.length))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor==='calendar-import'){
    try{const owner=(draft.data as {owner?:unknown}).owner;if(!validCalendarOwner(owner)||owner.workspace_id!==draft.workspaceId||draft.pending!==null)throw new Error();await validateCalendarRecovery(draft.data,owner);}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor==='ehr-read:tebra:fhir'){
    try{const scope=(draft.data as {scope?:unknown}).scope;if(!validTebraMedicationScope(scope)||scope.workspace_id!==draft.workspaceId||draft.pending!==null)throw new Error();await validateTebraRecovery(draft.data,scope);}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&(draft.editor==='ehr-read'||draft.editor==='ehr-read:tebra')){
    try{const scope=(draft.data as {scope?:unknown}).scope;if(!validEhrScope(scope)||ehrProvider(scope)!==(draft.editor==='ehr-read:tebra'?'tebra':'elation')||scope.workspace_id!==draft.workspaceId||draft.pending!==null)throw new Error();await validateEhrReadRecovery(draft.data,scope);}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor==='scheduling-patient'){
    try{const data=await validateSchedulingPatientRecovery(draft.data,draft.workspaceId);
      if(draft.pending!==(data.pending?.idempotency_key??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if(draft?.kind==='editor'&&draft.editor.startsWith('handoff-review:')){
    try{const data=await validateHandoffReviewRecovery(draft.data,draft.workspaceId,draft.editor.slice('handoff-review:'.length));
      if(draft.pending!==(data.pending?.body.idempotency_key??null))throw new Error();}
    catch{throw new DraftStoreError('integrity');}return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "fax-inbound") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {const scope=(draft.data as {scope?:unknown}).scope;if(!validFaxScope(scope))throw new Error();await validateFaxRecovery(draft.data,scope);}
    catch {throw new DraftStoreError("integrity");}return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "efax-inbound") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {const scope=(draft.data as {scope?:unknown}).scope;if(!scope||typeof scope!=="object"||Array.isArray(scope))throw new Error();await validateEFaxRecovery(draft.data,scope as {box_id:string;owner_id:string});}
    catch {throw new DraftStoreError("integrity");}return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "google-calendar") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {const scope=(draft.data as {scope?:unknown}).scope;if(!validGoogleCalendarScope(scope))throw new Error();await validateGoogleCalendarRecovery(draft.data,scope);}
    catch {throw new DraftStoreError("integrity");}return;
  }
  if (draft?.kind === "account-editor" && draft.editor === "outlook-messages") {
    if (draft.pending !== null) throw new DraftStoreError("integrity");
    try {
      const scope = (draft.data as {scope?:unknown}).scope;
      if (!validOutlookMessageScope(scope)) throw new DraftStoreError("integrity");
      await validateOutlookMessageRecovery(draft.data, scope);
    } catch { throw new DraftStoreError("integrity"); }
    return;
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
  private listeners = new Set<(address:string|null)=>void>();
  constructor(private readonly store: DraftStore) {}
  /** Only confirmed local changes are announced; no draft content leaves here. */
  subscribe(changed:(address:string|null)=>void):()=>void {this.listeners.add(changed);return()=>{this.listeners.delete(changed);};}
  private changed(address:string|null):void {for(const listener of [...this.listeners]){try{listener(address);}catch{/* An observer cannot fail a confirmed save. */}}}
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
  persist(address: string, body: RecoveredDraft | null, expectedRevision?: string | null): Promise<void> {
    // Snapshot before enqueueing: later input mutations cannot change this save.
    const copy = structuredClone(body);
    const task = async () => {
      if (!this.active || !this.records.has(address)) throw new DraftStoreError("unavailable");
      const previous = this.records.get(address)!;
      // Conditional cleanup must not overwrite a newer write queued while its
      // caller was checking the record. Compare inside this serialized task.
      if (expectedRevision !== undefined && previous.revision !== expectedRevision) throw new DraftStoreError("conflict");
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
      this.changed(address);
    };
    const result = this.chain.catch(() => {}).then(task);
    this.chain = result;
    return result;
  }
  close(): void { this.active = false; this.records.clear(); this.store.close(); this.changed(null); this.listeners.clear(); }
}
