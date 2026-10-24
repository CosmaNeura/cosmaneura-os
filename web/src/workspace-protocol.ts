import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {hostedWorkspaceRequested} from './hosted-workspace';

export const WORKSPACE_PROTOCOL_HEADER='X-Cosmas-Workspace-Protocol';
export const REQUIRED_WORKSPACE_CONTRACTS:Readonly<Record<string,number>>=Object.freeze({
  workspace:1,draft_recovery:2,team:4,activity:2,model:1,handoff_review:2,routine:2,
  practice_access:1,practice_members:1,practice_setup:1,vendor:1,vendor_setup:1,finance:1,
  finance_setup:1,portal_setup:1,portal_work:1,membership:1,inbox:1,
  inbox_handoff:1,core_record:1,core_connection:1,research:1,
  scheduling_login:1,google_connection:1,microsoft_connection:1,google_messages:1,google_calendar:1,scheduling_patient:1,private_draft:1,
});
export type WorkspaceCompatibility={contract_version:1;workspace_protocol:1;requests_require_protocol:true;contracts:Record<string,number>};
const updateRequired=()=>new WorkspaceApiError(426,'workspace_protocol_required');
// A pause is not identity loss. Existing editors retain exact unconfirmed work on 503.
const workPaused=()=>new WorkspaceApiError(503,'workspace_protocol_required');

export function validateWorkspaceCompatibility(value:unknown):WorkspaceCompatibility {
  if(!value || typeof value!=='object' || Array.isArray(value))throw updateRequired();
  const item=value as Record<string,unknown>,contracts=item.contracts;
  if(Object.keys(item).sort().join(',')!=='contract_version,contracts,requests_require_protocol,workspace_protocol' ||
    item.contract_version!==1 || item.workspace_protocol!==1 || item.requests_require_protocol!==true ||
    !contracts || typeof contracts!=='object' || Array.isArray(contracts))throw updateRequired();
  const entries=Object.entries(contracts);
  if(entries.length>64 || entries.some(([key,version])=>! /^[a-z][a-z0-9_]{0,63}$/.test(key) ||
    !Number.isSafeInteger(version) || (version as number)<1 || (version as number)>1000) ||
    Object.entries(REQUIRED_WORKSPACE_CONTRACTS).some(([key,version])=>
      !Object.hasOwn(contracts,key) || (contracts as Record<string,unknown>)[key]!==version))throw updateRequired();
  // A Messages candidate must qualify its inbox before opening the workspace.
  // Ordinary Workspace builds remain compatible during the staged rollout.
  if(import.meta.env.VITE_MESSAGES_ENABLED==='true' && (contracts as Record<string,unknown>).conversations!==1)throw updateRequired();
  return value as WorkspaceCompatibility;
}

type Phase='pending'|'ready'|'blocked';
type State={phase:Phase;generation:number;listeners:Set<()=>void>};
const scopes=new WeakMap<object,State>();
function state(identity:WorkspaceIdentity):State {
  let current=scopes.get(identity);
  if(!current){current={phase:'pending',generation:0,listeners:new Set()};scopes.set(identity,current);}
  return current;
}
export const workspaceProtocolPhase=(identity:WorkspaceIdentity):Phase=>hostedWorkspaceRequested()?state(identity).phase:'ready';
export const workspaceProtocolGeneration=(identity:WorkspaceIdentity)=>state(identity).generation;
export function subscribeWorkspaceProtocol(identity:WorkspaceIdentity,listener:()=>void) {
  const current=state(identity);current.listeners.add(listener);return ()=>{current.listeners.delete(listener);};
}
function changed(current:State){for(const listener of current.listeners)listener();}
function block(identity:WorkspaceIdentity){const current=state(identity);current.phase='blocked';current.generation++;changed(current);}
export function admitWorkspaceProtocol(identity:WorkspaceIdentity,generation:number) {
  const current=state(identity);
  if(current.generation!==generation)throw updateRequired();
  current.phase='ready';changed(current);
}
export function requireWorkspaceProtocol(identity:WorkspaceIdentity) {
  if(workspaceProtocolPhase(identity)!=='ready')throw workPaused();
}
function currentIdentity(identity:WorkspaceIdentity) {
  return !('mode' in identity) || (identity.mode==='desktop_native' ? identity.isCurrent() :
    !identity.nativeSession || identity.nativeSession.isCurrent());
}
function cancel(response:Response){try{void response.body?.cancel().catch(()=>{});}catch{/* Do not wait on a discarded response. */}}

async function fetchWorkspace(url:string,init:RequestInit):Promise<Response> {
  try { return await fetch(url,init); }
  catch(cause) {
    if(cause instanceof TypeError&&!init.signal?.aborted)throw new WorkspaceApiError(503,'workspace_unreachable');
    throw cause;
  }
}

/** Shared API dispatch guard; local editing, encrypted custody and recording Stop stay available. */
export async function workspaceFetch(identity:WorkspaceIdentity|undefined,url:string,init:RequestInit,compatibility=false):Promise<Response> {
  if(!hostedWorkspaceRequested())return fetchWorkspace(url,init);
  if(!identity || !('mode' in identity) || !currentIdentity(identity))throw new WorkspaceApiError(401);
  const mismatch=compatibility?updateRequired:workPaused;
  if(!compatibility)requireWorkspaceProtocol(identity);
  const generation=state(identity).generation;
  if(new Headers(init.headers).get(WORKSPACE_PROTOCOL_HEADER)!=='1'){block(identity);throw mismatch();}
  init.signal?.throwIfAborted();
  const response=await fetchWorkspace(url,init);
  if(init.signal?.aborted || !currentIdentity(identity)){cancel(response);throw new WorkspaceApiError(401);}
  // An upstream outage may return a proxy error without application headers.
  // It is not proof of an incompatible server. Successful data must be identified.
  const protocol=response.headers.get(WORKSPACE_PROTOCOL_HEADER);
  if(response.status===426 || compatibility && response.status===404 ||
    protocol!==null && protocol!=='1' || response.status>=200 && response.status<300 && protocol!=='1') {
    cancel(response);block(identity);throw mismatch();
  }
  if(state(identity).generation!==generation && ![401,403].includes(response.status)) {
    cancel(response);throw mismatch();
  }
  return response;
}
