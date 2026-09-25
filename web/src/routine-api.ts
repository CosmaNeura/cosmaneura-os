import {workspaceFetch} from './workspace-protocol';
import {parseIncomingBrief,type IncomingBriefSection} from './routine-inbox-contract';
import { WORKSPACE_BUILD, WORKSPACE_AUTHENTICATED_BUILD, WorkspaceApiError, type AuthenticatedWorkspaceIdentity } from "./workspace-api";
import { assertCurrentDesktopSession, workspaceAuthHeaders } from "./workspace-auth-headers";

export const ROUTINES_BUILD = WORKSPACE_BUILD && WORKSPACE_AUTHENTICATED_BUILD &&
  import.meta.env.VITE_WORKSPACE_ROUTINES_ENABLED === "true";
export type BriefSchedule = { kind: "practice_work_brief"; enabled: boolean; timezone: string; at: string;
  weekdays: number[]; quiet_start: string | null; quiet_end: string | null; max_runs_per_seven_days: number };
export type RoutineSave = { expected_revision: number; team_revision: number; idempotency_key: string; configuration: BriefSchedule };
export type RunSummary = { id: string; scheduled_at: string; completed_at: string; local_date: string };
export type RoutineStatus = "not_configured"|"paused"|"team_changed"|"bot_unavailable"|"skill_unavailable"|"restricted"|"waiting"|"missed"|"quiet_hours"|"already_run"|"run_limit"|"due";
export type Routine = { bot: string; agent_id: string; revision: number; team_revision: number;
  configuration: BriefSchedule | null; status: RoutineStatus; next_scheduled_at: string | null; runs: RunSummary[] };
export type BriefItem = { ticket_id: string; revision_id: string; payload_hash: string; version: number;
  state: "sent" | "approved" | "closed" | "withdrawn" | "superseded"; body: string; due_date: string;
  work_kind?: "follow_up" | "visit_preparation" | "vendor_delivery"; ready_for_review?: boolean;
  responsible: { id: string; name: string; available: boolean }; pending_offer: boolean; human_completion: boolean };
export type WorkBrief = RunSummary & { kind: "practice_work_brief"; items: BriefItem[]; matching_items: number;
  counts: { open: number; overdue: number; awaiting_acceptance: number; responsible_unavailable: number; verified_complete: number };
  withheld_sources: boolean; truncated: boolean; model_used: false;
  contract_version?:2; snapshot_version?:1|2; incoming?:IncomingBriefSection };
const closed = (v: unknown, keys: string): v is Record<string, any> => !!v && typeof v === "object" && !Array.isArray(v) &&
  Object.keys(v).sort().join(",") === keys.split(",").sort().join(",");
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(v);
const botId = (v: string) => ["chief", "scribe", "visit_prep", "follow_up"].includes(v) || uuid(v);
const integer = (v: unknown, max: number, min = 0): v is number => Number.isInteger(v) && Number(v) >= min && Number(v) <= max;
const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));
const date = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) &&
  Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0,10) === v;
export const isRoutineClockTime = (v: unknown): v is string => typeof v === "string" && /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === "string" && v.length > 0 && [...v].length <= max;
function invalid():never { throw new WorkspaceApiError(503); }
export function validSchedule(v: unknown): v is BriefSchedule {
  if (!closed(v,"kind,enabled,timezone,at,weekdays,quiet_start,quiet_end,max_runs_per_seven_days") ||
      v.kind !== "practice_work_brief" || typeof v.enabled !== "boolean" || !text(v.timezone,80) || !isRoutineClockTime(v.at) ||
      !Array.isArray(v.weekdays) || !v.weekdays.length || v.weekdays.length > 7 ||
      !v.weekdays.every((day: unknown) => integer(day,7,1)) || new Set(v.weekdays).size !== v.weekdays.length ||
      !integer(v.max_runs_per_seven_days,7,1)) return false;
  try { new Intl.DateTimeFormat("en", { timeZone:v.timezone }); } catch { return false; }
  if (v.quiet_start === null && v.quiet_end === null) return true;
  if (!isRoutineClockTime(v.quiet_start) || !isRoutineClockTime(v.quiet_end) || v.quiet_start === v.quiet_end) return false;
  return !(v.quiet_start < v.quiet_end ? v.quiet_start <= v.at && v.at < v.quiet_end : v.at >= v.quiet_start || v.at < v.quiet_end);
}
export function validRoutineSave(v:unknown):v is RoutineSave {
  return closed(v,"expected_revision,team_revision,idempotency_key,configuration")&&
    integer(v.expected_revision,99)&&integer(v.team_revision,Number.MAX_SAFE_INTEGER,1)&&uuid(v.idempotency_key)&&validSchedule(v.configuration);
}
function summary(v: unknown): v is RunSummary {
  return closed(v,"id,scheduled_at,completed_at,local_date") && uuid(v.id) && instant(v.scheduled_at) &&
    instant(v.completed_at) && Date.parse(v.completed_at) >= Date.parse(v.scheduled_at) && date(v.local_date);
}
export function parseRoutine(v: unknown, bot: string): Routine {
  if (!closed(v,"bot,agent_id,revision,team_revision,configuration,status,next_scheduled_at,runs") || v.bot !== bot ||
      !uuid(v.agent_id) || !integer(v.revision,100) || !integer(v.team_revision,Number.MAX_SAFE_INTEGER,1) ||
      !(v.revision === 0 ? v.configuration === null && v.status === "not_configured" : validSchedule(v.configuration)) ||
      !["not_configured","paused","team_changed","bot_unavailable","skill_unavailable", "restricted","waiting","missed","quiet_hours","already_run","run_limit","due"].includes(v.status) ||
      !(v.next_scheduled_at === null || instant(v.next_scheduled_at)) || !Array.isArray(v.runs) || v.runs.length > 20 ||
      !v.runs.every(summary) || new Set(v.runs.map((run: RunSummary) => run.id)).size !== v.runs.length) invalid();
  return v as Routine;
}
function parseLegacyBrief(v: unknown, id: string, displayLimit=10): WorkBrief {
  if (!closed(v,"id,scheduled_at,completed_at,local_date,kind,items,matching_items,counts,withheld_sources,truncated,model_used")) return invalid();
  if (!summary({id:v.id,scheduled_at:v.scheduled_at,completed_at:v.completed_at,local_date:v.local_date}) || v.id !== id ||
      v.kind !== "practice_work_brief" || v.model_used !== false || typeof v.withheld_sources !== "boolean" ||
      typeof v.truncated !== "boolean" || !integer(v.matching_items,200) ||
      !Array.isArray(v.items) || v.items.length !== Math.min(v.matching_items,displayLimit) ||
      !closed(v.counts,"open,overdue,awaiting_acceptance,responsible_unavailable,verified_complete") ||
      !Object.values(v.counts).every(n => integer(n,v.matching_items)) ||
      [v.counts.overdue,v.counts.awaiting_acceptance,v.counts.responsible_unavailable].some(n => n > v.counts.open) ||
      v.counts.open + v.counts.verified_complete > v.matching_items) invalid();
  const seen = new Set<string>();
  for (const item of v.items) {
    const keys="ticket_id,revision_id,payload_hash,version,state,body,due_date,responsible,pending_offer,human_completion";
    const typed=closed(item,keys+",work_kind,ready_for_review");
    if (!(typed||closed(item,keys)) ||
        !uuid(item.ticket_id) || seen.has(item.ticket_id) || !uuid(item.revision_id) ||
        typeof item.payload_hash !== "string" || !/^[0-9a-f]{64}$/.test(item.payload_hash) || !integer(item.version,Number.MAX_SAFE_INTEGER,1) ||
        !["sent","approved","closed","withdrawn","superseded"].includes(item.state) || !text(item.body,180) || !date(item.due_date) ||
        !closed(item.responsible,"id,name,available") || !uuid(item.responsible.id) || !text(item.responsible.name,80) ||
        typeof item.responsible.available !== "boolean" || typeof item.pending_offer !== "boolean" || typeof item.human_completion !== "boolean" ||
        (item.human_completion && item.state !== "closed") ||
        (item.pending_offer && !["sent","approved"].includes(item.state))) invalid();
    if(typed){
      const states:Record<string,string[]>={follow_up:["sent","closed"],visit_preparation:["approved","closed"],
        vendor_delivery:["approved","closed","withdrawn","superseded"]};
      if(typeof item.work_kind!=="string"||!Object.hasOwn(states,item.work_kind)||!states[item.work_kind].includes(item.state)||
          typeof item.ready_for_review!=="boolean"||item.ready_for_review&&
          (item.state!=="approved"||item.work_kind==="follow_up"))invalid();
    }
    seen.add(item.ticket_id);
  }
  // Legacy immutable snapshots have no lane/readiness fields. Their dated
  // states still have exact active/terminal meanings; unknown states fail.
  const opened=v.items.filter((item:BriefItem)=>item.state==="sent"||item.state==="approved");
  const visible={open:opened.length,overdue:opened.filter((item:BriefItem)=>item.due_date<v.local_date).length,
    awaiting_acceptance:opened.filter((item:BriefItem)=>item.pending_offer).length,
    responsible_unavailable:opened.filter((item:BriefItem)=>!item.responsible.available).length,
    verified_complete:v.items.filter((item:BriefItem)=>item.state==="closed"&&item.human_completion).length};
  const remaining=v.matching_items-v.items.length;
  if(Object.entries(visible).some(([key,count])=>v.counts[key]<count||v.counts[key]>count+remaining))invalid();
  return v as WorkBrief;
}

export function parseWorkBrief(raw:unknown,id:string):WorkBrief {
  if(!raw||typeof raw!=="object"||!("contract_version" in raw))return parseLegacyBrief(raw,id);
  if(!closed(raw,"id,scheduled_at,completed_at,local_date,contract_version,snapshot_version,kind,generic,incoming,model_used"))return invalid();
  const v:Record<string,any>=raw;
  if(
    v.contract_version!==2||![1,2].includes(v.snapshot_version)||v.kind!=="practice_work_brief"||v.model_used!==false||
    !closed(v.generic,"items,matching_items,counts,withheld_sources,truncated")||!integer(v.generic.matching_items,200))invalid();
  const incoming=parseIncomingBrief(v.incoming,v.local_date,v.snapshot_version);
  const limit=Math.min(v.generic.matching_items,5+Math.max(0,5-incoming.matching_items));
  if(incoming.items.length!==Math.min(incoming.matching_items,10-limit))invalid();
  const generic=parseLegacyBrief({...v.generic,id:v.id,scheduled_at:v.scheduled_at,completed_at:v.completed_at,
    local_date:v.local_date,kind:v.kind,model_used:false},id,limit);
  if(generic.items.some(item=>incoming.items.some(other=>other.ticket_id===item.ticket_id)))invalid();
  return {...generic,contract_version:2,snapshot_version:v.snapshot_version,incoming};
}

async function request(identity: AuthenticatedWorkspaceIdentity, bot: string, suffix: string, body?: RoutineSave, signal?: AbortSignal): Promise<unknown> {
  if (!ROUTINES_BUILD || !botId(bot)) invalid();
  const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  const controller = new AbortController(), abort = () => controller.abort();
  const timer = setTimeout(abort,30000);
  signal?.addEventListener("abort",abort,{once:true}); if (signal?.aborted) abort();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined, cancelAuth: (() => void) | undefined;
  const cancel = () => {void reader?.cancel().catch(() => {});};
  controller.signal.addEventListener("abort",cancel,{once:true});
  try {
    controller.signal.throwIfAborted();
    const headers = await Promise.race([workspaceAuthHeaders(identity,base),new Promise<never>((_,reject) => {
      cancelAuth = () => reject(new Error("cancelled")); controller.signal.addEventListener("abort",cancelAuth,{once:true});
      if (controller.signal.aborted) cancelAuth();
    })]);
    controller.signal.throwIfAborted();
    if(suffix.startsWith("/runs/"))headers.set("X-Cosmas-Routine-Contract","2");
    const encoded = body === undefined ? undefined : JSON.stringify(body);
    if (encoded && new TextEncoder().encode(encoded).length > 2048) invalid();
    const response = await workspaceFetch(identity,base + "/provider-team/routines/" + bot + suffix, {method:body === undefined ? "GET" : "POST",
      body:encoded, headers, signal:controller.signal, credentials:"omit", redirect:"error", cache:"no-store", referrerPolicy:"no-referrer"});
    if (response.status !== 200) {void response.body?.cancel().catch(() => {}); throw new WorkspaceApiError(response.status);}
    if (response.headers.get("content-type")?.split(";",1)[0].trim() !== "application/json" ||
        !response.headers.get("cache-control")?.split(",").some(v => v.trim().toLowerCase() === "no-store")) {
      void response.body?.cancel().catch(() => {}); invalid();
    }
    reader = response.body?.getReader(); if (!reader) return invalid();
    let size=0; const chunks: Uint8Array[]=[];
    while (true) {controller.signal.throwIfAborted(); const next=await reader.read(); controller.signal.throwIfAborted();
      if (next.done) break; size+=next.value.length; if (size>32768) invalid(); chunks.push(next.value);}
    const bytes=new Uint8Array(size); let offset=0;
    for (const part of chunks) {bytes.set(part,offset);offset+=part.length;}
    assertCurrentDesktopSession(identity);
    return JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
  } catch (cause) {if (cause instanceof WorkspaceApiError) throw cause; return invalid();}
  finally {if (cancelAuth) controller.signal.removeEventListener("abort",cancelAuth);
    void reader?.cancel().catch(() => {});reader?.releaseLock();clearTimeout(timer);
    signal?.removeEventListener("abort",abort);controller.signal.removeEventListener("abort",cancel);}
}
export const routineApi = {
  async read(identity: AuthenticatedWorkspaceIdentity, bot: string, signal?: AbortSignal) {
    return parseRoutine(await request(identity,bot,"",undefined,signal),bot);
  },
  async save(identity: AuthenticatedWorkspaceIdentity, bot: string, body: RoutineSave, signal?: AbortSignal) {
    if (!validRoutineSave(body)) invalid();
    const value = parseRoutine(await request(identity,bot,"",body,signal),bot);
    if (value.revision !== body.expected_revision + 1 || !value.configuration ||
        Object.keys(body.configuration).some(key => JSON.stringify(value.configuration![key as keyof BriefSchedule]) !== JSON.stringify(body.configuration[key as keyof BriefSchedule]))) invalid();
    return value;
  },
  async run(identity: AuthenticatedWorkspaceIdentity, bot: string, id: string, signal?: AbortSignal) {
    if (!uuid(id)) invalid();
    return parseWorkBrief(await request(identity,bot,"/runs/" + id,undefined,signal),id);
  },
};
