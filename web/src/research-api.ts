import {workspaceFetch} from './workspace-protocol';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson} from './vendor-contract';
import {teamUuid} from './team-setup-request';
import {RESEARCH_DEADLINE_MS,RESEARCH_REQUEST_BYTES,RESEARCH_RESPONSE_BYTES,RESEARCH_HISTORY_BYTES,validResearchSearch,validResearchSave,validateResearchCatalog,validateResearchHistory,validateResearchSavedHistory,validateResearchObservation,validateResearchSaved,type ResearchCatalog,type ResearchSearch,type ResearchObservation,type ResearchSave,type ResearchSaved,type ResearchHistory,type ResearchSavedHistory} from './research-contract';
export type ResearchPort={
 catalog(identity:AuthenticatedWorkspaceIdentity,signal?:AbortSignal):Promise<ResearchCatalog>;
 history(identity:AuthenticatedWorkspaceIdentity,workspace:string,bot:string,signal?:AbortSignal,before?:string):Promise<ResearchHistory>;
 savedHistory(identity:AuthenticatedWorkspaceIdentity,workspace:string,bot:string,signal?:AbortSignal,before?:string):Promise<ResearchSavedHistory>;
 search(identity:AuthenticatedWorkspaceIdentity,workspace:string,body:ResearchSearch,signal?:AbortSignal):Promise<ResearchObservation>;
 resolve(identity:AuthenticatedWorkspaceIdentity,workspace:string,body:ResearchSearch,signal?:AbortSignal):Promise<ResearchObservation>;
 save(identity:AuthenticatedWorkspaceIdentity,workspace:string,run:string,body:ResearchSave,signal?:AbortSignal):Promise<ResearchSaved>;
 resolveSave(identity:AuthenticatedWorkspaceIdentity,workspace:string,run:string,body:ResearchSave,signal?:AbortSignal):Promise<ResearchSaved>;
};
const stop=(value:{cancel:()=>Promise<unknown>}|null|undefined)=>{try{void value?.cancel().catch(()=>{});}catch{/* Best effort after bounded request. */}};
async function request<T>(identity:AuthenticatedWorkspaceIdentity,path:string,body:unknown|undefined,maximum:number,validate:(value:unknown)=>T|Promise<T>,signal?:AbortSignal):Promise<T>{
 const controller=new AbortController(),deadline=performance.now()+RESEARCH_DEADLINE_MS;
 let response:Response|undefined,reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
 const abort=()=>controller.abort(),interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>{stop(reader);if(!reader)stop(response?.body);reject(new WorkspaceApiError(503));},{once:true}));
 void interrupted.catch(()=>{});const wait=<V,>(value:Promise<V>)=>Promise.race([value,interrupted]);
 const check=()=>{if(performance.now()>=deadline)abort();controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
 const timer=setTimeout(abort,RESEARCH_DEADLINE_MS);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
 try{
  check();const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  if(base.includes('?')||base.includes('#')||!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const encoded=body===undefined?undefined:JSON.stringify(body);if(encoded!==undefined&&new TextEncoder().encode(encoded).byteLength>RESEARCH_REQUEST_BYTES)throw new WorkspaceApiError(422);
  const headers=await wait(workspaceAuthHeaders(identity,base).catch(()=>{throw new WorkspaceApiError(401);}));check();headers.set('X-Cosmas-Research-Contract','1');headers.set('Accept','application/json');headers.set('Content-Type','application/json');
  const url=base+path;response=await wait(workspaceFetch(identity,url,{method:body===undefined?'GET':'POST',body:encoded,headers,signal:controller.signal,credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'}).then(value=>{if(controller.signal.aborted){stop(value.body);throw new WorkspaceApiError(503);}return value;}));check();
  if(!response)throw new WorkspaceApiError(502);const length=response.headers.get('content-length');
  if(response.redirected||response.type==='opaque'||response.type==='opaqueredirect'||response.url&&response.url!==url||response.headers.get('content-type')?.split(';',1)[0].trim().toLowerCase()!=='application/json'||!response.headers.get('cache-control')?.split(',').some(s=>s.trim().toLowerCase()==='no-store')||response.headers.has('content-encoding')||length!==null&&(!/^(?:0|[1-9][0-9]*)$/.test(length)||Number(length)>maximum))throw new WorkspaceApiError(502);
  reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(502);const bytes=new Uint8Array(maximum);let size=0;
  for(;;){check();const part=await wait(reader.read());check();if(part.done)break;if(Object.prototype.toString.call(part.value)!=='[object Uint8Array]'||part.value.byteLength>maximum-size)throw new WorkspaceApiError(502);bytes.set(part.value,size);size+=part.value.byteLength;}
  if(length!==null&&Number(length)!==size)throw new WorkspaceApiError(502);
  const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes.subarray(0,size)));check();
  if(response.status!==200)throw new WorkspaceApiError([401,403,404,409,422,426,503,504].includes(response.status)?response.status:502,response.status===404&&value&&typeof value==='object'&&'detail' in value&&value.detail==='research_not_found'?'research_not_found':undefined);
  const result=await wait(Promise.resolve(validate(value)));check();return result;
 }catch(error){if(controller.signal.aborted)throw new WorkspaceApiError(503);if(response&&[401,403].includes(response.status))throw new WorkspaceApiError(response.status);if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(502);}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);stop(reader);if(!reader)stop(response?.body);try{reader?.releaseLock();}catch{/* Abandoned read may settle later. */}controller.abort();}
}
const workspacePath=(workspace:string)=>{if(!teamUuid(workspace))throw new WorkspaceApiError(422);return '/workspaces/'+workspace+'/research';};
const historyQuery=(bot:string,before?:string)=>{if(!teamUuid(bot)||before!==undefined&&!teamUuid(before))throw new WorkspaceApiError(422);return '?bot='+bot+(before===undefined?'':'&before='+before);};
export const researchApi:ResearchPort={
 catalog:(identity,signal)=>request(identity,'/research/catalog',undefined,RESEARCH_RESPONSE_BYTES,validateResearchCatalog,signal),
 history:(identity,workspace,bot,signal,before)=>request(identity,workspacePath(workspace)+historyQuery(bot,before),undefined,RESEARCH_HISTORY_BYTES,v=>validateResearchHistory(v,workspace,bot),signal),
 savedHistory:(identity,workspace,bot,signal,before)=>request(identity,workspacePath(workspace)+'/saved'+historyQuery(bot,before),undefined,RESEARCH_RESPONSE_BYTES,v=>validateResearchSavedHistory(v,workspace,bot),signal),
 search:(identity,workspace,body,signal)=>{if(!validResearchSearch(body))throw new WorkspaceApiError(422);return request(identity,workspacePath(workspace)+'/search',body,RESEARCH_RESPONSE_BYTES,v=>validateResearchObservation(v,workspace,body),signal);},
 resolve:(identity,workspace,body,signal)=>{if(!validResearchSearch(body))throw new WorkspaceApiError(422);return request(identity,workspacePath(workspace)+'/resolve',{contract_version:1,idempotency_key:body.idempotency_key},RESEARCH_RESPONSE_BYTES,v=>validateResearchObservation(v,workspace,body),signal);},
 save:(identity,workspace,run,body,signal)=>{if(!teamUuid(run)||!validResearchSave(body))throw new WorkspaceApiError(422);return request(identity,workspacePath(workspace)+'/'+run+'/save',body,RESEARCH_RESPONSE_BYTES,v=>validateResearchSaved(v,workspace,run,body),signal);},
 resolveSave:(identity,workspace,run,body,signal)=>{if(!teamUuid(run)||!validResearchSave(body))throw new WorkspaceApiError(422);return request(identity,workspacePath(workspace)+'/'+run+'/save/resolve',{contract_version:1,idempotency_key:body.idempotency_key},RESEARCH_RESPONSE_BYTES,v=>validateResearchSaved(v,workspace,run,body),signal);},
};
