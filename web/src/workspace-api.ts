import type {SessionPrepAnalysis} from "./session-prep-analysis-contract";
import type {MembershipAnalysis} from "./membership-analysis-contract";
import {workspaceFetch} from './workspace-protocol';
import { permittedWorkspaceApi } from "./workspace-origin";
import {hostedWorkspaceConfiguration} from "./hosted-workspace";
import { assertCurrentDesktopSession, workspaceAuthHeaders } from "./workspace-auth-headers";
import type { CaptureGapReview } from "./capture-gap-review";
import type { NotebookSource } from "./notebook-source";
import type {BlockedCapability, BotResources, ModelWorkPolicy, PresetBinding, SetupReview} from "./team-setup-request";
import type {EntryModelRequest} from "./model-work-request";
import type {InboxAnalysis} from "./inbox-analysis-contract";
import type {ResearchAnalysis} from "./research-analysis-contract";
import {TEAM_REQUEST_BYTES, TEAM_RESPONSE_BYTES, normalizeTeamConfiguration, teamCanonical, validTeamSave, teamClosed, teamUuid, teamText} from "./team-setup-request";
import {validProviderTeam} from "./team-setup-validators";
import {modelWorkApi} from "./model-work-api";
import { readVendorPracticeCatalog } from "./vendor-api";
import { validatePracticeWorkPage } from "./practice-work-catalog";
import type { SharedVendorWork } from "./vendor-schema";

export const WORKSPACE_BUILD = import.meta.env.VITE_WORKSPACE_ENABLED === "true" &&
  (import.meta.env.VITE_COSMAS_ENV === "synth_os" || !!hostedWorkspaceConfiguration());
// Preserve an explicit login request even if another required flag is missing:
// the runtime must show a configuration error, never fall back to a demo user.
export const WORKSPACE_AUTHENTICATED_BUILD = import.meta.env.VITE_WORKSPACE_AUTHENTICATED_ENABLED === "true";

export type AuthenticatedWorkspaceIdentity = {
  mode: "clerk_jwt"; getToken: (options: { skipCache: true }) => Promise<string | null>;
  nativeSession?: {revision:string;isCurrent:()=>boolean};
} | { mode: "desktop_native"; revision: string; isCurrent: () => boolean };
export type WorkspaceIdentity = { boxId: string; actorId: string } | AuthenticatedWorkspaceIdentity;
export type WorkspaceEncounter = { appointment_id: string; label: string; workspace_id: string | null };
export type WorkReference = { id: string; state: string; lane: string };
export type BotRole = "scribe" | "visit_prep" | "follow_up" | "chief" | "custom" | "research";
export type BotSkill = "saved_context" | "work_status" | "encounter_prep" | "calendar_availability" | "inbox_review" | "membership_review";
// A template describes a skill set; an address selects one private installed bot.
export type BotAddress = string;
export type CaptureBotSelection = { address: BotAddress; team_revision: number };
export type CaptureTaskBot = { selection: CaptureBotSelection; name: string; enabled: boolean; includeNotebook: boolean };
export const botAddress = (bot: { role: BotRole; instance_id?: string | null }): BotAddress => bot.instance_id ?? bot.role;
export type BotSettings = {
  role: BotRole; name: string; enabled: boolean; response_style: "brief" | "detailed";
  include_notebook: boolean; include_evidence: boolean;
  instance_id?: string | null; job_focus?: string; working_preferences?: string; retired?: boolean;
  skills?: BotSkill[];
  blocked_capabilities?: BlockedCapability[];
  resources?: BotResources;
};
export const supportsSkill = (bot: BotSettings, skill: BotSkill): boolean => bot.role === "custom"
  ? (bot.skills ?? []).includes(skill)
  : ({saved_context: ["scribe", "visit_prep", "follow_up", "chief", "research"], work_status: ["scribe", "visit_prep", "follow_up", "chief", "research"],
      encounter_prep: ["scribe", "visit_prep"], calendar_availability: ["follow_up"], inbox_review: [] as string[], membership_review: [] as string[]})[skill].includes(bot.role);
export type TeamConfiguration = { practice_context: string; bots: BotSettings[]; presets?: PresetBinding[]; model_work?: ModelWorkPolicy };
export type BotTemplate = {
  role: BotRole; agent_id: string | null; name: string; initials: string; description: string; prompt: string;
  instance_id?: string | null;
  capabilities: { key: string; label: string; state: "local" | "enabled" | "awaiting_connection"; connector: string; contract: string | null }[];
};
export type ProviderTeam = { revision: number; template_version: string; configuration: TeamConfiguration; members: BotTemplate[]; recovery_scope?: string; custom_skills?: (BotTemplate["capabilities"][number] & {key: BotSkill})[]; scheduling?: { enabled: boolean }; templates?: BotTemplate[]; llm: { enabled: boolean; model: string }; capture?: { enabled: boolean; notes_enabled?: boolean; corrections_enabled?: boolean; prep_enabled?: boolean; prep_work_enabled?: boolean } };
export type TeamSaveInput = { expected_revision: number; idempotency_key: string; configuration: TeamConfiguration; setup_review?: SetupReview };
export type ConversationInput = { expected_revision: number; team_revision: number; idempotency_key: string; role: BotAddress; content: string; research_analysis?:ResearchAnalysis; inbox_analysis?:InboxAnalysis;membership_analysis?:MembershipAnalysis;session_prep_analysis?:SessionPrepAnalysis };
export type AssistantReply = { agent_name: string; agent_id?: string; role: BotRole; backend: string; content: string; context_revision: number;
  citations: { entry_id: string; revision: number; label: string; kind: string }[] };
export type WorkspaceEntry = {
  id: string; revision: number;
  kind: "synthetic_source" | "scratchpad" | "conversation" | "evidence" | "work_link" | "handoff_result" | "google_message" | "google_calendar" | "efax_inbound_source" | "fax_inbound_source";
  content: string; source_label: string | null; origin: string;
  ticket: WorkReference | null; created_at: string;
  google_source_state?: "current" | "unavailable";
  calendar_source_state?: "current" | "unavailable";
  practice_fax_source_state?: "current" | "unavailable";
  fax_source_state?: "current" | "unavailable";
  reply?: AssistantReply | null;
  model_request?: EntryModelRequest;
};
export type TaskSourceVersion = {entry_id:string;revision:number;label:string;kind:string;sha256:string};
export type HandoffTaskBrief = {version:1|2;goal:string;missing_facts:string[];expected_output:string;
  completion_criteria:string[];independent:true;source_versions:TaskSourceVersion[];
  allowed_actions:["prepare_private_draft"];depends_on:{entry_id:string;revision:number}};
export type DraftHandoff = {
  id: string; origin_entry_id: string; recipient_role: Exclude<BotRole, "chief">; recipient_name: string;
  recipient_agent_id?: string; recipient_key?: BotAddress;
  task_brief?:HandoffTaskBrief;task_brief_unavailable?:boolean;
  completion_evidence?:{kind:"saved_private_draft";entry_id:string;revision:number;sha256:string;source_versions:TaskSourceVersion[]};
  result_sha256?:string|null;
  review_status?:"current"|"stale"|"not_reviewed";
  review?:{id:string;attempt_id:string;result_entry_id:string;result_sha256:string;decision:"accepted"|"changes_requested";
    feedback:string;created_at:string;revision_handoff_id?:string|null}|null;
  revision_request?:{parent_handoff_id:string;review_id:string;attempt_id:string;result_entry_id:string;result_sha256:string;feedback:string};
  brief: string; context_revision: number; status: "queued" | "running" | "completed" | "failed" | "interrupted";
  attempt_id: string; attempt_count: number; result_entry_id: string | null; error_code: string | null;
  attempts: { id: string; number: number; status: string; error_code: string | null }[];
};
export type HandoffRetryInput = { expected_revision: number; previous_attempt_id: string; idempotency_key: string };
export type PrivateNote = {
  id: string; version: number; workspace_revision: number; content: string; content_hash: string;
  source_reply_id: string | null; source_revision: number; source_fingerprint: string; sources_changed: boolean;
  created_at: string; review: { id: string; reviewer_id: string; created_at: string; capture_gap_review_sha256?: string } | null;
  core_source?: CoreNoteReference & { note_type: string } | null;
};
export type CoreNoteReference = { session_id: string; scribe_source_id: string; source_sha256: string;
  schema_ref: string; transcript_ref: string; note_ref: string; note_sha256: string; capture_gap_review?: CaptureGapReview; notebook_source?: NotebookSource; reviewed_source?: import("./capture-notes-api").ReviewedSource };
export type CoreNoteLinkInput = { expected_revision: number; idempotency_key: string; base_note_id: string | null; source: CoreNoteReference };
export type NoteSaveInput = { expected_revision: number; idempotency_key: string; base_note_id: string | null;
  source_reply_id: string | null; content: string; sources_reconciled: boolean };
export type NoteReviewInput = { expected_revision: number; idempotency_key: string; content_hash: string; source_fingerprint: string;
  gap_acknowledgment?: { recovery_sha256: string; acknowledged: true } };
export type NoteOperation = { type: "note"; body: NoteSaveInput } | { type: "review"; noteId: string; body: NoteReviewInput } |
  { type: "coreNoteLink"; body: CoreNoteLinkInput };
export type FollowUp = {
  ticket_id: string; revision_id: string; payload_hash: string; state: string; create_key: string;
  body: string; due_date: string; expected_outcome: string; owner_id: string; responsible_id?: string;
  note_version: number; source_changed: boolean; operation_status: string | null;
  core_check_required?: boolean;
  receipts: { id: string; kind: "local_delivery" | "human_completion"; content: string; actor_id: string; created_at: string }[];
};
export type FollowUpProposeInput = { expected_revision: number; idempotency_key: string; note_id: string;
  body: string; due_date: string; expected_outcome: string; share: boolean };
export type FollowUpDecisionInput = { revision_id: string; payload_hash: string; choice: "approve" | "reject" };
export type FollowUpCompleteInput = { expected_version?: number; revision_id: string; payload_hash: string; idempotency_key: string; evidence: string };
export type WorkPerson = { id: string; name: string; available: boolean };
export type WorkHandoffKind = "offer" | "accept" | "decline" | "recall" | "reclaim";
export type PracticeWorkItem = {
  work_kind?: "follow_up" | "visit_preparation"; ready_for_review?: boolean;
  ticket_id: string; version: number; revision_id: string; payload_hash: string; state: string;
  body: string; due_date: string; expected_outcome: string; viewer_id: string;
  originator: WorkPerson; responsible: WorkPerson;
  pending_offer: { id: string; from: WorkPerson; to: WorkPerson } | null;
  handoffs: { id: string; kind: WorkHandoffKind; actor: WorkPerson; from: WorkPerson; to: WorkPerson; offer_id: string | null; created_at: string }[];
  receipts: { id: string; kind: "local_delivery" | "human_completion" | "internal_publication" | "ready_for_review" | "provider_verification"; content: string; actor: WorkPerson; created_at: string }[];
};
export type PracticeWorkEntry = PracticeWorkItem | SharedVendorWork;
export type PracticeWorkPage = { items: PracticeWorkEntry[]; people: WorkPerson[]; next_cursor: string | null };
export type WorkHandoffInput = { expected_version: number; revision_id: string; payload_hash: string;
  idempotency_key: string; kind: WorkHandoffKind; recipient_id?: string; offer_id?: string };
export type FollowUpOperation = { type: "followUpPropose"; body: FollowUpProposeInput } |
  { type: "followUpDecision"; ticketId: string; body: FollowUpDecisionInput } |
  { type: "followUpComplete"; ticketId: string; body: FollowUpCompleteInput };
export type Workspace = {
  id: string; appointment_id: string | null; label: string; revision: number;
  private_draft?: {title:string;state:'unlinked'|'linked';link_receipt_id:string|null;linked_at:string|null};
  entries: WorkspaceEntry[]; work_candidates: WorkReference[];
  handoffs?: DraftHandoff[];
  note?: { latest: PrivateNote | null; history: PrivateNote[] };
  follow_ups?: FollowUp[];
  model_contract_version?: 1;
  model_observed_at?: string;
};
export type PrivateDraftCreateInput={title:string;idempotency_key:string};
export type PrivateDraftLinkInput={expected_revision:number;idempotency_key:string;appointment_id:string;appointment_link_confirmed:true};
export type PrivateDraftCatalog={contract_version:1;drafts:{workspace_id:string;title:string;revision:number;created_at:string;link_state:'unlinked'|'linked';appointment_id:string|null}[];has_more:boolean};
export type PrivateDraftResolution={contract_version:1;outcome:'saved'|'not_found';workspace:Workspace|null};
export type PrivateDraftLinkResolution=PrivateDraftResolution&{link_receipt_id:string|null};
export const validPrivateDraftCreate=(value:PrivateDraftCreateInput)=>teamClosed(value,'title,idempotency_key')&&
  teamText(value.title,160,1)&&value.title===value.title.trim()&&/^[A-Za-z0-9:_-]{8,100}$/.test(value.idempotency_key);
export const validPrivateDraftLink=(value:PrivateDraftLinkInput)=>teamClosed(value,'expected_revision,idempotency_key,appointment_id,appointment_link_confirmed')&&
  Number.isSafeInteger(value.expected_revision)&&value.expected_revision>=1&&teamUuid(value.appointment_id)&&
  /^[A-Za-z0-9:_-]{8,100}$/.test(value.idempotency_key)&&value.appointment_link_confirmed===true;
export function validPrivateWorkspace(value:unknown,workspaceId?:string):value is Workspace {
  if(!value||typeof value!=='object'||Array.isArray(value))return false;
  const w=value as Workspace,d=w.private_draft;
  return teamUuid(w.id)&&(!workspaceId||workspaceId===w.id)&&Number.isSafeInteger(w.revision)&&w.revision>=1&&
    teamText(w.label,200,1)&&Array.isArray(w.entries)&&w.entries.length<=500&&Array.isArray(w.work_candidates)&&
    !!d&&teamClosed(d,'title,state,link_receipt_id,linked_at')&&teamText(d.title,160,1)&&
    (d.state==='unlinked'?w.appointment_id===null&&d.link_receipt_id===null&&d.linked_at===null:
      d.state==='linked'&&teamUuid(w.appointment_id)&&teamUuid(d.link_receipt_id)&&typeof d.linked_at==='string'&&Number.isFinite(Date.parse(d.linked_at)));
}

async function privateDraftRequest<T>(identity:AuthenticatedWorkspaceIdentity,path:string,body:unknown|undefined,validate:(value:unknown)=>value is T):Promise<T> {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const abort=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));
  const wait=<V,>(value:Promise<V>)=>Promise.race([value,abort]);
  try {
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
    const encoded=body===undefined?undefined:JSON.stringify(body);
    if(encoded&&new TextEncoder().encode(encoded).length>4096)throw new WorkspaceApiError(422);
    const headers=await wait(workspaceAuthHeaders(identity,base));headers.set('X-Cosmas-Private-Draft','1');
    assertCurrentDesktopSession(identity);
    const response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?'GET':'POST',headers,
      body:encoded,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));
    assertCurrentDesktopSession(identity);
    if(response.headers.get('content-type')?.split(';',1)[0].trim()!=='application/json'||
      !response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'))throw new WorkspaceApiError(503);
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);
    const chunks:Uint8Array[]=[];let size=0;
    while(true){const part=await wait(reader.read());if(part.done)break;size+=part.value.length;
      if(size>(response.ok?(body===undefined?65536:12000000):2048))throw new WorkspaceApiError(503);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.length;}
    const value:unknown=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
    assertCurrentDesktopSession(identity);
    if(!response.ok){const codes=['workspace_already_exists','workspace_already_linked','workspace_appointment_required','idempotency_conflict','workspace_revision_conflict','private_draft_limit','encounter_unavailable'];
      throw new WorkspaceApiError(response.status,teamClosed(value,'detail')&&typeof value.detail==='string'&&codes.includes(value.detail)?value.detail:undefined);}
    if(!validate(value))throw new WorkspaceApiError(503);return value;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);try{void reader?.cancel().catch(()=>{});}catch{/* Cancellation does not change a saved outcome. */}controller.abort();}
}

function privateResolution(value:unknown):value is PrivateDraftResolution {
  return teamClosed(value,'contract_version,outcome,workspace')&&value.contract_version===1&&
    (value.outcome==='not_found'?value.workspace===null:value.outcome==='saved'&&validPrivateWorkspace(value.workspace));
}
function privateLinkResolution(value:unknown):value is PrivateDraftLinkResolution {
  return teamClosed(value,'contract_version,outcome,workspace,link_receipt_id')&&value.contract_version===1&&
    (value.outcome==='not_found'?value.workspace===null&&value.link_receipt_id===null:
      value.outcome==='saved'&&validPrivateWorkspace(value.workspace)&&value.workspace.private_draft?.state==='linked'&&
      value.link_receipt_id===value.workspace.private_draft.link_receipt_id);
}
export type AppendInput = {
  expected_revision: number; idempotency_key: string;
  kind: "scratchpad" | "conversation" | "evidence"; content: string; source_label?: string;
};

export class WorkspaceApiError extends Error {
  constructor(public status: number, public code?: string) {
    super(code === "workspace_recovery_unavailable" ? "The workspace service could not confirm private draft recovery. Existing drafts are retained. Recheck recovery before continuing." :
      code === "handoff_source_context_too_large" ? "The selected sources are too large for a complete team handoff. Your recording and saved notes are retained. Select fewer saved sources before asking Chief to delegate." :
      code === "handoff_source_contract_unavailable" ? "Team handoffs need the source-reading tools enabled for this request. Your recording and saved notes are retained. Check Chief’s tools before preparing a new assignment." :
      code === "session_prep_analysis_too_large" ? "This brief and the selected saved notes are too large to review together. Ask without Session Prep, or narrow this bot's saved sources." :
      ["session_prep_analysis_unavailable","session_prep_not_ready","session_prep_context_changed","session_prep_request_conflict","session_prep_unavailable","invalid_session_prep_analysis"].includes(code??'') ? "Session Prep could not be confirmed. Keep this request for recovery, then open the current brief before starting a new question." :
      code === "inbox_selection_required" ? "Open Incoming messages, review the patient and message, then choose Draft a reply." :
      ["inbox_human_review_required","inbox_analysis_unavailable","inbox_bot_required"].includes(code??'') ? "Inbox drafting needs a current reviewed message, administrative human triage, and an enabled Inbox coworker. Review this item in Incoming messages." :
      code === "inbox_analysis_too_large" ? "This message is too large for Inbox drafting. Keep it with human review." :
      code === "research_analysis_too_large" ? "The selected saved packet is too large for analysis. Select fewer excerpts and save a smaller packet before reviewing a new AI request." :
      code === "source_changed" ? "A selected saved source could not be verified. Keep the exact request for recovery, then review the current saved packet before a new analysis." :
      code === "team_work_limit" ? "New model work is paused or the team's rolling attempt allowance is used. Saved requests remain available for checking." :
      code === "model_attempt_in_progress" ? "A request is already in progress. Check its saved result before starting another." :
      code === "bot_resource_restricted" ? "This bot's settings restrict this preparation or scheduling source. Review its source choices." :
      code === "team_resource_changed" ? "A selected source changed or is unavailable. Refresh the inventory and review the team draft; saved restrictions remain in place." :
      code === "team_setup_prerequisites_changed" ? "Team prerequisites changed. Your settings are retained; refresh the setup and run the invented rehearsal again before saving." :
      code === "team_setup_review_required" || code === "team_setup_configuration_changed" || code === "team_catalog_changed" ? "Review this exact team configuration and run the invented rehearsal again before saving. Your draft is retained." :
      code === "capture_notebook_changed" ? "The saved scratch notes changed. Check the latest notebook revision and prepare a draft from it before review." :
      code === "core_note_changed" || code === "capture_note_conflict" ? "The saved Core note or recording changed. Check its saved draft, use the current version for review, and review it again before follow-up." :
      code === "core_note_edit_required" ? "Edit this note in the recorded visit draft, then use the saved Core version for review." :
      status === 409 ? "The saved workspace changed. Load the latest version before saving again." :
      status === 400 || status === 422 ? "The entry was not accepted. Review the text and try again." :
      status === 426 ? "Update Cosmas before opening this workspace. Saved work and this device's drafts are retained." :
      status === 401 || status === 403 || status === 404 ? "This workspace is unavailable. Access or the local feature may have changed." :
      "The save could not be confirmed. Retry the same save before making changes.");
  }
}

export function validRecoveryScope(value: unknown): value is string {
  return typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
}
export function requireRecoveryScope(team: ProviderTeam | null): string {
  if (!validRecoveryScope(team?.recovery_scope)) throw new WorkspaceApiError(503, "workspace_recovery_unavailable");
  return team.recovery_scope;
}

async function request<T>(path: string, identity?: WorkspaceIdentity, body?: unknown, signal?: AbortSignal): Promise<T> {
  if (signal?.aborted) throw new WorkspaceApiError(503);
  const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  if (!permittedWorkspaceApi(base, import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED === "true", window.location.href)) {
    throw new Error("The synthetic workspace requires its approved local API.");
  }
  let headers = new Headers({ "Content-Type": "application/json" });
  if (identity && "mode" in identity) {
    try { headers = await workspaceAuthHeaders(identity, base); }
    catch { throw new WorkspaceApiError(401); }
  } else if (identity) {
    headers.set("X-Box-Id", identity.boxId);
    headers.set("X-Actor-Principal-Id", identity.actorId);
  }
  if (signal?.aborted) throw new WorkspaceApiError(503);
  const response = await workspaceFetch(identity,base + path, {
    method: body === undefined ? "GET" : "POST", cache: "no-store", credentials: "omit", redirect: "error",
    referrerPolicy: "no-referrer",
    headers,
    ...(signal ? { signal } : {}),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (identity && "mode" in identity) assertCurrentDesktopSession(identity);
  if (!response.ok) {
    let code: string | undefined;
    try {
      const error = await response.json();
      if (["core_note_changed", "capture_note_conflict", "core_note_edit_required"].includes(error.detail)) code = error.detail;
    } catch { /* Error content is never shown to the user. */ }
    throw new WorkspaceApiError(response.status, code);
  }
  const value = await response.json() as T;
  if (signal?.aborted) throw new WorkspaceApiError(503);
  if (identity && "mode" in identity) assertCurrentDesktopSession(identity);
  return value;
}

type TeamPath = "/provider-team" | "/provider-team/setup" | "/provider-team/rehearsal" | "/provider-team/resources" | "/provider-team/usage";
const TEAM_ERRORS = new Set(["team_contract_required","team_contract_unsupported","team_setup_unavailable","team_setup_review_required",
  "team_setup_configuration_changed","team_setup_prerequisites_changed","team_catalog_changed","team_preset_missing","team_preset_binding_immutable",
  "team_revision_conflict","idempotency_conflict","team_history_limit","team_member_missing","team_member_retired","team_template_immutable",
  "invalid_team_setup_request","invalid_team_configuration","team_resource_changed","bot_resource_restricted","team_work_limit"]);
/** The three team routes share one bounded credential/dispatch/body deadline. */
export async function requestTeamPayload<T = unknown>(identity: WorkspaceIdentity, path: TeamPath, body?: unknown, signal?: AbortSignal, validate?: (value: unknown) => T | Promise<T>): Promise<T> {
  const small=path==="/provider-team/resources"||path==="/provider-team/usage";
  if(small&&body!==undefined)throw new WorkspaceApiError(422);
  const controller=new AbortController(),abort=()=>controller.abort(),deadline=Date.now()+30000;
  const checkDeadline=()=>{if(Date.now()>=deadline)controller.abort();controller.signal.throwIfAborted();};
  const timer=setTimeout(abort,30000);
  signal?.addEventListener("abort",abort,{once:true});if(signal?.aborted)abort();
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const cancel=()=>{void reader?.cancel().catch(()=>{});};
  controller.signal.addEventListener("abort",cancel,{once:true});
  let onAbort:(()=>void)|undefined;
  const interrupted=new Promise<never>((_,reject)=>{
    onAbort=()=>reject(new WorkspaceApiError(503));controller.signal.addEventListener("abort",onAbort,{once:true});
  });
  const wait=<T,>(promise:Promise<T>)=>Promise.race([promise,interrupted]);
  try {
    checkDeadline();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,"")||"http://127.0.0.1:8000";
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==="true",window.location.href))throw new WorkspaceApiError(503);
    const encoded=body===undefined?undefined:JSON.stringify(body);
    if(encoded!==undefined&&new TextEncoder().encode(encoded).length>TEAM_REQUEST_BYTES)throw new WorkspaceApiError(422,"invalid_team_setup_request");
    let headers:Headers;
    if("mode" in identity) {
      headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));
      assertCurrentDesktopSession(identity);
    } else headers=new Headers({"Content-Type":"application/json","X-Box-Id":identity.boxId,"X-Actor-Principal-Id":identity.actorId});
    checkDeadline();headers.set("X-Cosmas-Team-Contract","4");
    const response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?"GET":"POST",body:encoded,headers,signal:controller.signal,
      cache:"no-store",credentials:"omit",redirect:"error",referrerPolicy:"no-referrer"}));
    if("mode" in identity)assertCurrentDesktopSession(identity);
    const expected=response.status===200;
    if(response.headers.get("content-type")?.split(";",1)[0].trim().toLowerCase()!=="application/json"||
      !response.headers.get("cache-control")?.split(",").some(v=>v.trim().toLowerCase()==="no-store")) {
      void response.body?.cancel().catch(()=>{});throw new WorkspaceApiError(expected?503:response.status);
    }
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(expected?503:response.status);
    const chunks:Uint8Array[]=[];let size=0;
    while(true) {
      checkDeadline();const next=await wait(reader.read());checkDeadline();
      if(next.done)break;size+=next.value.length;if(size>(expected?(small?16384:TEAM_RESPONSE_BYTES):4096))throw new WorkspaceApiError(expected?503:response.status);
      chunks.push(next.value);
    }
    const bytes=new Uint8Array(size);let offset=0;for(const part of chunks){bytes.set(part,offset);offset+=part.length;}
    let value:unknown;
    try {value=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));}
    catch {throw new WorkspaceApiError(expected?503:response.status);}
    if("mode" in identity)assertCurrentDesktopSession(identity);
    if(!expected) {
      const code=value&&typeof value==="object"&&!Array.isArray(value)&&Object.keys(value).join(",")==="detail"&&"detail" in value&&
        typeof value.detail==="string"&&TEAM_ERRORS.has(value.detail)?value.detail:undefined;
      throw new WorkspaceApiError(response.status,code);
    }
    const checked = validate ? await wait(Promise.resolve(validate(value))) : value as T;
    checkDeadline();
    if("mode" in identity)assertCurrentDesktopSession(identity);
    return checked;
  } catch(cause) {if(cause instanceof WorkspaceApiError)throw cause;throw new WorkspaceApiError(503);}
  finally {
    clearTimeout(timer);signal?.removeEventListener("abort",abort);controller.signal.removeEventListener("abort",cancel);
    if(onAbort)controller.signal.removeEventListener("abort",onAbort);
    if(reader) {const owned=reader;void owned.cancel().catch(()=>{}).finally(()=>{try{owned.releaseLock();}catch{/* An abandoned read may still be settling. */}});}
    controller.abort();
  }
}
async function requestTeam(identity: WorkspaceIdentity, body?: TeamSaveInput, signal?: AbortSignal): Promise<ProviderTeam> {
  if(body!==undefined&&!validTeamSave(body))throw new WorkspaceApiError(422,"invalid_team_configuration");
  return requestTeamPayload(identity,"/provider-team",body,signal,value => {
  if("mode" in identity)requireRecoveryScope(value as ProviderTeam);
  if(!validProviderTeam(value))throw new WorkspaceApiError(503);
  if(body&&(value.revision!==body.expected_revision+1||teamCanonical(normalizeTeamConfiguration(value.configuration))!==teamCanonical(normalizeTeamConfiguration(body.configuration))))
    throw new WorkspaceApiError(503);
  return value;
  });
}

function legacyPracticeWork(value: PracticeWorkEntry): PracticeWorkItem {
  if (value.work_kind === "vendor_delivery") throw new WorkspaceApiError(426, "vendor_contract_required");
  return value;
}

export const workspaceApi = {
  privateDrafts: (identity:AuthenticatedWorkspaceIdentity)=>privateDraftRequest<PrivateDraftCatalog>(identity,'/workspaces/private-drafts',undefined,
    (v):v is PrivateDraftCatalog=>teamClosed(v,'contract_version,drafts,has_more')&&v.contract_version===1&&typeof v.has_more==='boolean'&&Array.isArray(v.drafts)&&v.drafts.length<=50&&
      new Set(v.drafts.map(row=>row.workspace_id)).size===v.drafts.length&&v.drafts.every(row=>teamClosed(row,'workspace_id,title,revision,created_at,link_state,appointment_id')&&
        teamUuid(row.workspace_id)&&teamText(row.title,160,1)&&typeof row.revision==='number'&&Number.isSafeInteger(row.revision)&&row.revision>=1&&typeof row.created_at==='string'&&Number.isFinite(Date.parse(row.created_at))&&
        (row.link_state==='unlinked'?row.appointment_id===null:row.link_state==='linked'&&teamUuid(row.appointment_id)))),
  async createPrivateDraft(identity:AuthenticatedWorkspaceIdentity,body:PrivateDraftCreateInput) {
    if(!validPrivateDraftCreate(body))throw new WorkspaceApiError(422);
    // Both requests independently verify current authority. The caller has
    // already retained this exact create command before dispatch; a failed team
    // read cannot cancel or conceal a create which may have committed.
    const [team,workspace]=await Promise.allSettled([
      requestTeam(identity),
      privateDraftRequest<Workspace>(identity,'/workspaces/private-drafts',body,(v):v is Workspace=>validPrivateWorkspace(v)&&v.private_draft?.title===body.title),
    ]);
    if(team.status==='rejected')throw team.reason;
    if(workspace.status==='rejected')throw workspace.reason;
    try{assertCurrentDesktopSession(identity);}catch{throw new WorkspaceApiError(401);}
    if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);
    return {identity,workspace:workspace.value,team:team.value};
  },
  resolvePrivateDraft: (identity:AuthenticatedWorkspaceIdentity,body:PrivateDraftCreateInput)=>{
    if(!validPrivateDraftCreate(body))throw new WorkspaceApiError(422);
    return privateDraftRequest(identity,'/workspaces/private-drafts/resolve',body,(v):v is PrivateDraftResolution=>privateResolution(v)&&(v.workspace===null||v.workspace.private_draft?.title===body.title));
  },
  async openPrivateDraft(identity:AuthenticatedWorkspaceIdentity,workspaceId:string) {
    if(!teamUuid(workspaceId))throw new WorkspaceApiError(422);
    const team=await requestTeam(identity),workspace=await modelWorkApi.readWorkspace(identity,workspaceId);
    if(!validPrivateWorkspace(workspace,workspaceId))throw new WorkspaceApiError(503);
    return {identity,workspace,team};
  },
  linkAppointment: (identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:PrivateDraftLinkInput)=>{
    if(!teamUuid(workspaceId)||!validPrivateDraftLink(body))throw new WorkspaceApiError(422);
    return privateDraftRequest<{entry_revision:number;link_receipt_id:string;workspace:Workspace}>(identity,`/workspaces/${workspaceId}/appointment-link`,body,
      (v):v is {entry_revision:number;link_receipt_id:string;workspace:Workspace}=>teamClosed(v,'entry_revision,link_receipt_id,workspace')&&validPrivateWorkspace(v.workspace,workspaceId)&&
        v.workspace.appointment_id===body.appointment_id&&v.workspace.private_draft?.link_receipt_id===v.link_receipt_id&&v.entry_revision===v.workspace.revision);
  },
  resolveAppointmentLink: (identity:AuthenticatedWorkspaceIdentity,workspaceId:string,body:PrivateDraftLinkInput)=>{
    if(!teamUuid(workspaceId)||!validPrivateDraftLink(body))throw new WorkspaceApiError(422);
    return privateDraftRequest(identity,`/workspaces/${workspaceId}/appointment-link/resolve`,body,
      (v):v is PrivateDraftLinkResolution=>privateLinkResolution(v)&&(v.workspace===null||v.workspace.id===workspaceId&&v.workspace.appointment_id===body.appointment_id));
  },
  practiceWork: (identity: WorkspaceIdentity, cursor?: string) =>
    readVendorPracticeCatalog(identity, cursor, value => validatePracticeWorkPage(value, identity)),
  practiceWorkItem: (identity: WorkspaceIdentity, id: string, signal?:AbortSignal) =>
    request<PracticeWorkEntry>(`/practice-work/${id}`, identity, undefined, signal).then(legacyPracticeWork),
  workHandoff: (identity: WorkspaceIdentity, id: string, body: WorkHandoffInput) =>
    request<PracticeWorkEntry>(`/practice-work/${id}/handoffs`, identity, body).then(legacyPracticeWork),
  completeWork: (identity: WorkspaceIdentity, id: string, body: FollowUpCompleteInput) =>
    request<PracticeWorkEntry>(`/practice-work/${id}/complete`, identity, body).then(legacyPracticeWork),
  catalog: (identity: AuthenticatedWorkspaceIdentity) => request<WorkspaceEncounter[]>("/workspaces", identity),
  async open(access?: AuthenticatedWorkspaceIdentity, appointmentId?: string): Promise<{ identity: WorkspaceIdentity; workspace: Workspace; team: ProviderTeam }> {
    let identity: WorkspaceIdentity;
    if (access) {
      if (!appointmentId) throw new WorkspaceApiError(400);
      identity = access;
    } else {
      if (WORKSPACE_AUTHENTICATED_BUILD) throw new WorkspaceApiError(401);
      const seed = await request<{ box_id: string; owner_id: string }>("/synth/demo-queue", undefined, {});
      identity = { boxId: seed.box_id, actorId: seed.owner_id };
    }
    const encounters = await request<WorkspaceEncounter[]>("/workspaces", identity);
    const encounter = access ? encounters.find(item => item.appointment_id === appointmentId) : encounters[0];
    if (!encounter) throw new WorkspaceApiError(404);
    // Establish the private draft owner before opening or creating its notebook.
    const team = await requestTeam(identity);
    const workspace = encounter.workspace_id ? await modelWorkApi.readWorkspace(identity,encounter.workspace_id) :
      await request<Workspace>("/workspaces", identity, {
        appointment_id: encounter.appointment_id, idempotency_key: `create:${encounter.appointment_id}`,
      });
    return { identity, workspace, team };
  },
  async openExisting(identity: AuthenticatedWorkspaceIdentity, selection: {workspace_id:string;appointment_id:string}) {
    const team = await requestTeam(identity);
    const workspace = await modelWorkApi.readWorkspace(identity, selection.workspace_id);
    if (workspace.id !== selection.workspace_id || workspace.appointment_id !== selection.appointment_id) throw new WorkspaceApiError(403);
    return {identity,workspace,team};
  },
  team: (identity: WorkspaceIdentity, signal?: AbortSignal) => requestTeam(identity, undefined, signal),
  saveTeam: (identity: WorkspaceIdentity, body: TeamSaveInput, signal?: AbortSignal) => requestTeam(identity, body, signal),
  ask: (identity: WorkspaceIdentity, id: string, body: ConversationInput) =>
    modelWorkApi.submit(identity,id,{type:"ask",body}),
  retryHandoff: (identity: WorkspaceIdentity, id: string, handoffId: string, body: HandoffRetryInput) =>
    modelWorkApi.submit(identity,id,{type:"retry",handoffId,body}),
  saveNote: (identity: WorkspaceIdentity, id: string, body: NoteSaveInput) =>
    request<{ entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/notes`, identity, body),
  linkCoreNote: (identity: WorkspaceIdentity, id: string, body: CoreNoteLinkInput) =>
    request<{ entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/capture/note-links`, identity, body),
  reviewNote: (identity: WorkspaceIdentity, id: string, noteId: string, body: NoteReviewInput) =>
    request<{ entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/notes/${noteId}/review`, identity, body),
  proposeFollowUp: (identity: WorkspaceIdentity, id: string, body: FollowUpProposeInput) =>
    request<{ entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/follow-ups`, identity, body),
  decideFollowUp: (identity: WorkspaceIdentity, id: string, ticketId: string, body: FollowUpDecisionInput) =>
    request<{ entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/follow-ups/${ticketId}/decide`, identity, body),
  completeFollowUp: (identity: WorkspaceIdentity, id: string, ticketId: string, body: FollowUpCompleteInput) =>
    request<{ entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/follow-ups/${ticketId}/complete`, identity, body),
  read: (identity: WorkspaceIdentity, id: string, signal?:AbortSignal) => modelWorkApi.readWorkspace(identity,id,signal),
  append: (identity: WorkspaceIdentity, id: string, body: AppendInput) =>
    request<{ entry_id: string; entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/entries`, identity, body),
  link: (identity: WorkspaceIdentity, id: string, body: {
    expected_revision: number; idempotency_key: string; ticket_id: string;
  }) => request<{ entry_id: string; entry_revision: number; workspace: Workspace }>(`/workspaces/${id}/work-links`, identity, body),
};
