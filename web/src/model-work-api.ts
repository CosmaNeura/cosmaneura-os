import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError, type Workspace, type WorkspaceIdentity} from "./workspace-api";
import {assertCurrentDesktopSession, workspaceAuthHeaders} from "./workspace-auth-headers";
import {permittedWorkspaceApi} from "./workspace-origin";
import {teamClosed, teamUuid} from "./team-setup-request";
import {exactModelObservation, MODEL_RECEIPT_BYTES, MODEL_REQUEST_BYTES, MODEL_RETRY_BYTES, MODEL_WORKSPACE_BYTES, validModelObservation, validModelOperation,
  validModelWorkspace, validRetryObservation, type HandoffRetryObservation, type ModelOperation, type ModelRequestObservation} from "./model-work-request";

const ERRORS=new Set(["model_contract_required","model_contract_unsupported","team_work_limit","model_attempt_in_progress","bot_resource_restricted","team_resource_changed",
  "session_prep_analysis_unavailable","session_prep_analysis_too_large","invalid_session_prep_analysis","session_prep_not_ready","session_prep_context_changed","session_prep_request_conflict","session_prep_unavailable","bot_source_unavailable","model_request_too_large","invalid_membership_analysis","membership_analysis_too_large","membership_analysis_unavailable","membership_bot_required","membership_selection_required","invalid_inbox_analysis","inbox_analysis_too_large","inbox_analysis_unavailable","inbox_bot_required","inbox_human_review_required","inbox_selection_required","invalid_research_analysis","research_analysis_too_large","research_bot_required","source_changed","idempotency_conflict","workspace_revision_conflict","team_revision_conflict","invalid_workspace_request","invalid_team_request",
  "bot_unavailable","model_unavailable","workspace_not_found","workspace_forbidden","invalid_model_work_request","invalid_model_request","model_observation_unavailable"]);
type Receipt=ModelRequestObservation|HandoffRetryObservation;

/** Credentials, HTTP stream and asynchronous receipt checks share this deadline. */
async function bounded<T>(identity:WorkspaceIdentity,path:string,body:unknown|undefined,inputLimit:number,outputLimit:number,validate:(value:unknown,status:number)=>Promise<T>,signal?:AbortSignal,timeoutMs=30000):Promise<T> {
  const controller=new AbortController(),abort=()=>controller.abort(),deadline=Date.now()+timeoutMs;
  const check=()=>{if(Date.now()>=deadline)controller.abort();controller.signal.throwIfAborted();};
  const timer=setTimeout(abort,timeoutMs);signal?.addEventListener("abort",abort,{once:true});if(signal?.aborted)abort();
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined,onAbort:(()=>void)|undefined;
  const cancel=(stream:{cancel:()=>Promise<unknown>}|undefined|null)=>{try{void stream?.cancel().catch(()=>{});}catch{/* Cancellation cannot delay or replace the outcome. */}};
  const stopRead=()=>cancel(reader);controller.signal.addEventListener("abort",stopRead,{once:true});
  const interrupted=new Promise<never>((_,reject)=>{onAbort=()=>reject(new WorkspaceApiError(503));controller.signal.addEventListener("abort",onAbort,{once:true});});
  const wait=<V,>(promise:Promise<V>)=>Promise.race([promise,interrupted]);
  try {
    check();
    const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,"")||"http://127.0.0.1:8000";
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==="true",window.location.href))throw new WorkspaceApiError(503);
    const encoded=body===undefined?undefined:JSON.stringify(body);
    if(encoded!==undefined&&new TextEncoder().encode(encoded).length>inputLimit)throw new WorkspaceApiError(422,"model_request_too_large");
    let headers:Headers;
    if("mode" in identity){headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));assertCurrentDesktopSession(identity);}
    else headers=new Headers({"Content-Type":"application/json","X-Box-Id":identity.boxId,"X-Actor-Principal-Id":identity.actorId});
    check();headers.set("X-Cosmas-Model-Contract","1");
    const response=await wait(workspaceFetch(identity,base+path,{method:encoded===undefined?"GET":"POST",body:encoded,headers,signal:controller.signal,
      cache:"no-store",credentials:"omit",redirect:"error",referrerPolicy:"no-referrer"}));
    if("mode" in identity)assertCurrentDesktopSession(identity);check();
    if([401,403,404,426].includes(response.status)){cancel(response.body);throw new WorkspaceApiError(response.status);}
    if(response.headers.get("content-type")?.split(";",1)[0].trim().toLowerCase()!=="application/json"||
      !response.headers.get("cache-control")?.split(",").some(v=>v.trim().toLowerCase()==="no-store")) {
      cancel(response.body);throw new WorkspaceApiError(response.ok?503:response.status);
    }
    reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);
    const chunks:Uint8Array[]=[];let size=0;
    while(true){check();const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;
      if(size>outputLimit)throw new WorkspaceApiError(503);chunks.push(part.value);}
    const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
    let value:unknown;try{value=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));}catch{throw new WorkspaceApiError(503);}
    if("mode" in identity)assertCurrentDesktopSession(identity);check();
    if(response.status!==200&&!(response.status===409&&validModelObservation(value))){
      const code=teamClosed(value,"detail")&&typeof value.detail==="string"&&ERRORS.has(value.detail)?value.detail:undefined;
      throw new WorkspaceApiError(response.ok?503:response.status,code);
    }
    const result=await wait(validate(value,response.status));check();if("mode" in identity)assertCurrentDesktopSession(identity);return result;
  }catch(cause){if(cause instanceof WorkspaceApiError)throw cause;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener("abort",abort);controller.signal.removeEventListener("abort",stopRead);if(onAbort)controller.signal.removeEventListener("abort",onAbort);
    if(reader){const owned=reader;try{void owned.cancel().catch(()=>{}).finally(()=>{try{owned.releaseLock();}catch{/* The discarded read may still settle. */}});}catch{/* Cancellation must not replace the outcome. */}}controller.abort();}
}

async function command(identity:WorkspaceIdentity,id:string,operation:ModelOperation,resolve:boolean,signal?:AbortSignal):Promise<Receipt>{
  if(!teamUuid(id)||!validModelOperation(operation))throw new WorkspaceApiError(422);
  const path=operation.type==="ask"?`/workspaces/${id}/conversation`:`/workspaces/${id}/handoffs/${operation.handoffId}/retry`;
  return bounded(identity,path+(resolve?"/resolve":""),operation.body,operation.type==="ask"?MODEL_REQUEST_BYTES:MODEL_RETRY_BYTES,MODEL_RECEIPT_BYTES,async(value,status)=>{
    if(!await exactModelObservation(value,id,operation))throw new WorkspaceApiError(503);
    if(operation.type==="ask") {
      if(!validModelObservation(value)||resolve&&status!==200||!resolve&&(status===200?value.outcome!=="saved":value.outcome==="saved"||value.outcome==="not_found"))throw new WorkspaceApiError(503);
    }else if(!validRetryObservation(value)||status!==200||!resolve&&value.outcome!=="recorded")throw new WorkspaceApiError(503);
    return value as Receipt;
  },signal,!resolve&&operation.type==="ask"&&operation.body.session_prep_analysis?90000:30000);
}
export const modelWorkApi={
  submit:(identity:WorkspaceIdentity,id:string,operation:ModelOperation,signal?:AbortSignal)=>command(identity,id,operation,false,signal),
  resolve:(identity:WorkspaceIdentity,id:string,operation:ModelOperation,signal?:AbortSignal)=>command(identity,id,operation,true,signal),
  async readWorkspace(identity:WorkspaceIdentity,id:string,signal?:AbortSignal):Promise<Workspace>{
    if(!teamUuid(id))throw new WorkspaceApiError(422);
    return bounded(identity,`/workspaces/${id}`,undefined,0,MODEL_WORKSPACE_BYTES,async(value,status)=>{
      if(status!==200||!await validModelWorkspace(value,id))throw new WorkspaceApiError(503);return value as Workspace;
    },signal);
  },
};
