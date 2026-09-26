import {workspaceFetch} from './workspace-protocol';
import {WORKSPACE_AUTHENTICATED_BUILD, WORKSPACE_BUILD, WorkspaceApiError, type AuthenticatedWorkspaceIdentity, type PracticeWorkItem} from "./workspace-api";
import {assertCurrentDesktopSession, workspaceAuthHeaders} from "./workspace-auth-headers";
import {prepClosed as closed, prepUuid, prepHash, prepText, prepDate, validPrepWorkRequest, type PrepWorkRequest} from "./prep-work-request";
export const PREP_WORK_BUILD = WORKSPACE_BUILD && WORKSPACE_AUTHENTICATED_BUILD &&
  import.meta.env.VITE_WORKSPACE_PREP_ENABLED === "true" && import.meta.env.VITE_WORKSPACE_PREP_WORK_ENABLED === "true";
export type PrepWorkItem = PracticeWorkItem & {work_kind:"visit_preparation";ready_for_review:boolean;proposed_snapshot_sha256:string};
export type PrepWorkResult = {entry_revision:number;item:PrepWorkItem};
export type PrepWorkCatalog = {entry_revision:number;items:PrepWorkItem[]};
function invalid():never {throw new WorkspaceApiError(503);}
const natural=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>=0;
const instant=(v:unknown)=>typeof v==="string"&&/(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v));
const person=(v:unknown)=>closed(v,"id,name,available")&&prepUuid(v.id)&&prepText(v.name,200)&&typeof v.available==="boolean";
function item(v:unknown,ticket?:string):PrepWorkItem {
  if(!closed(v,"ticket_id,version,revision_id,payload_hash,state,body,due_date,expected_outcome,viewer_id,originator,responsible,pending_offer,handoffs,receipts,work_kind,ready_for_review,proposed_snapshot_sha256")||
    !prepUuid(v.ticket_id)||ticket&&v.ticket_id!==ticket||!natural(v.version)||Number(v.version)<1||!prepUuid(v.revision_id)||!prepHash(v.payload_hash)||
    !["pending_approval","approved","rejected","closed"].includes(String(v.state))||!prepText(v.body,4000)||!prepDate(v.due_date)||!prepText(v.expected_outcome,500)||
    !prepUuid(v.viewer_id)||!person(v.originator)||!person(v.responsible)||v.work_kind!=="visit_preparation"||typeof v.ready_for_review!=="boolean"||
    !prepHash(v.proposed_snapshot_sha256)||!Array.isArray(v.handoffs)||v.handoffs.length>1000||!Array.isArray(v.receipts)||v.receipts.length>1000)invalid();
  if(v.pending_offer!==null&&(!closed(v.pending_offer,"id,from,to")||!prepUuid(v.pending_offer.id)||!person(v.pending_offer.from)||!person(v.pending_offer.to)))invalid();
  const seen=new Set<string>();
  for(const h of v.handoffs) {
    if(!closed(h,"id,kind,actor,from,to,offer_id,created_at")||!prepUuid(h.id)||seen.has(h.id)||
      !["offer","accept","decline","recall","reclaim"].includes(String(h.kind))||!person(h.actor)||!person(h.from)||!person(h.to)||
      !(h.offer_id===null||prepUuid(h.offer_id))||!instant(h.created_at))invalid();
    seen.add(h.id);
  }
  for(const r of v.receipts) {
    if(!closed(r,"id,kind,content,actor,created_at")||!prepUuid(r.id)||seen.has(r.id)||
      !["internal_publication","ready_for_review","provider_verification"].includes(String(r.kind))||!prepText(r.content,4000)||!person(r.actor)||!instant(r.created_at))invalid();
    seen.add(r.id);
  }
  if((v.originator as {id:string}).id!==v.viewer_id)invalid();
  if(v.ready_for_review&&(v.state!=="approved"||!v.receipts.some(r=>r.kind==="ready_for_review"))||
    v.state==="closed"&&!v.receipts.some(r=>r.kind==="provider_verification"))invalid();
  return v as PrepWorkItem;
}
function result(v:unknown,ticket?:string):PrepWorkResult {
  if(!closed(v,"entry_revision,item")||!natural(v.entry_revision))invalid();
  return {entry_revision:Number(v.entry_revision),item:item(v.item,ticket)};
}
async function request(workspace: string, identity: AuthenticatedWorkspaceIdentity, suffix: string,
  body?: unknown, signal?: AbortSignal): Promise<unknown> {
  if (!PREP_WORK_BUILD || !prepUuid(workspace)) invalid();
  const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, "") || "http://127.0.0.1:8000";
  const controller = new AbortController(), abort = () => controller.abort();
  const timer = setTimeout(abort, 30000);
  signal?.addEventListener("abort", abort, {once: true}); if (signal?.aborted) abort();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  const cancel = () => {void reader?.cancel().catch(() => {});};
  controller.signal.addEventListener("abort", cancel, {once: true});
  let cancelAuth: (() => void) | undefined;
  try {
    controller.signal.throwIfAborted();
    const headers = await Promise.race([workspaceAuthHeaders(identity, base), new Promise<never>((_, reject) => {
      cancelAuth = () => reject(new Error("cancelled"));
      controller.signal.addEventListener("abort", cancelAuth, {once: true}); if (controller.signal.aborted) cancelAuth();
    })]);
    controller.signal.throwIfAborted();
    const encoded = body === undefined ? undefined : JSON.stringify(body);
    if (encoded && new TextEncoder().encode(encoded).length > (suffix === "" ? 32768 : 2048)) invalid();
    const response = await workspaceFetch(identity,base + "/workspaces/" + workspace + "/prep-work" + suffix, {
      method: body === undefined ? "GET" : "POST", body: encoded, headers, signal: controller.signal,
      credentials: "omit", redirect: "error", cache: "no-store", referrerPolicy: "no-referrer"});
    if (response.status !== 200) {void response.body?.cancel().catch(() => {}); throw new WorkspaceApiError(response.status);}
    if (response.headers.get("content-type")?.split(";", 1)[0].trim() !== "application/json" ||
      !response.headers.get("cache-control")?.split(",").some(v => v.trim().toLowerCase() === "no-store")) {
      void response.body?.cancel().catch(() => {}); invalid();
    }
    reader = response.body?.getReader(); if (!reader) invalid();
    let size = 0; const chunks: Uint8Array[] = [];
    while (true) {
      controller.signal.throwIfAborted(); const next = await reader.read(); controller.signal.throwIfAborted();
      if (next.done) break; size += next.value.length;
      if (size > 1048576) {void reader.cancel().catch(() => {}); invalid();} chunks.push(next.value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const part of chunks) {bytes.set(part, offset); offset += part.length;}
    assertCurrentDesktopSession(identity);
    return JSON.parse(new TextDecoder("utf-8", {fatal: true}).decode(bytes));
  } catch (cause) {if (cause instanceof WorkspaceApiError) throw cause; return invalid();}
  finally {
    if (cancelAuth) controller.signal.removeEventListener("abort", cancelAuth);
    void reader?.cancel().catch(() => {}); reader?.releaseLock(); clearTimeout(timer);
    signal?.removeEventListener("abort", abort); controller.signal.removeEventListener("abort", cancel);
  }
}
export const prepWorkApi={
  async catalog(workspace:string,identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal):Promise<PrepWorkCatalog> {
    const v=await request(workspace,identity,"",undefined,signal);
    if(!closed(v,"entry_revision,items")||!natural(v.entry_revision)||!Array.isArray(v.items)||v.items.length>50)invalid();
    const items=v.items.map(i=>item(i));
    if(new Set(items.map(i=>i.ticket_id)).size!==items.length)invalid();
    return {entry_revision:Number(v.entry_revision),items};
  },
  async read(workspace:string,identity:AuthenticatedWorkspaceIdentity,ticket:string,signal?:AbortSignal):Promise<PrepWorkResult> {
    if(!prepUuid(ticket))invalid();
    return result(await request(workspace,identity,"/"+ticket,undefined,signal),ticket);
  },
  async save(workspace:string,identity:AuthenticatedWorkspaceIdentity,command:PrepWorkRequest,signal?:AbortSignal):Promise<PrepWorkResult> {
    if(!validPrepWorkRequest(command))invalid();
    const v=result(await request(workspace,identity,command.kind==="create"?"":"/"+command.ticket+"/"+command.kind,command.body,signal),
      command.kind==="create"?undefined:command.ticket);
    if(command.kind==="create") {
      if(v.item.body!==command.body.body||v.item.due_date!==command.body.due_date||v.item.expected_outcome!==command.body.expected_outcome||
        v.item.proposed_snapshot_sha256!==command.body.snapshot_sha256)invalid();
    } else {
      if(v.item.revision_id!==command.body.revision_id||v.item.payload_hash!==command.body.payload_hash)invalid();
      const proof=(kind:string)=>v.item.receipts.some(r=>r.kind===kind&&r.actor.id===v.item.originator.id);
      if(command.kind==="verify"&&(v.item.state!=="closed"||!proof("provider_verification")))invalid();
      if(command.kind==="decide"&&(command.body.choice==="reject"?v.item.state!=="rejected":
        !["approved","closed"].includes(v.item.state)||!proof("internal_publication")))invalid();
    }
    return v;
  },
};
