import {workspaceFetch} from './workspace-protocol';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {parseVendorJson,vendorCanonical,vendorSha256,vendorUuid} from './vendor-contract';
import {botAddress,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
import type {CaptureAttestation} from './capture-api';

export type PrivateRecordingAttach={idempotency_key:string;local_recording_id:string;expected_workspace_revision:number;
  bot:{address:string;team_revision:number};consent:CaptureAttestation;started_at:string};
export type PrivateRecordingIntent={contract:'cosmas.private-recording.intent.v1';workspace_id:string;agent_id:string;
  recovery_scope:string;request:PrivateRecordingAttach;request_sha256:string};
export type PrivateRecordingFinish={idempotency_key:string;capture_state:'finished'|'interrupted'|'unknown';
  manifest_sha256:string|null;chunks:number|null;frames:number|null;ended_at:string|null};
export type PrivateRecordingFinishIntent={request:PrivateRecordingFinish;request_sha256:string};
export type PrivateRecordingLinkRequest={idempotency_key:string;expected_workspace_revision:number;workspace_link_receipt_id:string};
export type PrivateRecordingReceipt={contract:'cosmas.private-recording.v1';custody:'local_device_metadata';
  recording_id:string;local_recording_id:string;workspace_id:string;workspace_revision:number;owner_id:string;box_id:string;
  agent_id:string;team_revision_id:string;recovery_scope:string;attach_sha256:string;started_at:string;created_at:string;
  state:'unfinished'|'finished'|'interrupted'|'unknown'|'linked_metadata';
  finish:null|{receipt_id:string;request_sha256:string;manifest_sha256:string|null;chunks:number|null;frames:number|null;ended_at:string|null};
  link:null|{receipt_id:string;workspace_link_receipt_id:string;source_sha256:string;request_sha256:string};
  upstream_capture_admitted:false;audio_uploaded:false;transcription_started:false};
export type PrivateRecordingResolution={outcome:'not_found'|'saved';recording:PrivateRecordingReceipt|null};
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const integer=(v:unknown,max:number,min=1):v is number=>Number.isSafeInteger(v)&&Number(v)>=min&&Number(v)<=max;
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&
  Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
function need(v:unknown):asserts v {if(!v)throw new WorkspaceApiError(503,'private_recording_unavailable');}
// Match Pydantic's canonical UTC JSON, including six fractional digits when nonzero.
function utc(v:string):string {
  need(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(v)&&Number.isFinite(Date.parse(v)));
  const [whole,fraction='']=v.slice(0,-1).split('.');
  need(new Date(v).toISOString().slice(0,19)===whole);
  return whole+(Number(fraction)?'.'+fraction.padEnd(6,'0'):'')+'Z';
}
const sha=(v:unknown)=>vendorSha256(new TextEncoder().encode(vendorCanonical(v)));
const digest=(kind:string,request:unknown)=>sha({contract:'cosmas.private-recording.'+kind+'.v1',request});
function attachRequest(v:unknown):asserts v is PrivateRecordingAttach {
  need(closed(v,'idempotency_key,local_recording_id,expected_workspace_revision,bot,consent,started_at')&&
    vendorUuid(v.idempotency_key)&&vendorUuid(v.local_recording_id)&&integer(v.expected_workspace_revision,2147483647)&&
    closed(v.bot,'address,team_revision')&&(v.bot.address==='scribe'||vendorUuid(v.bot.address))&&integer(v.bot.team_revision,2147483647));
  const c=v.consent;need(closed(c,'modality,participant_regions,method,all_parties_consented,granted_at')&&
    ['in_person','virtual','phone'].includes(String(c.modality))&&c.method==='verbal_attestation'&&c.all_parties_consented===true&&
    Array.isArray(c.participant_regions)&&c.participant_regions.length<=20&&
    c.participant_regions.every(r=>typeof r==='string'&&/^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$/.test(r))&&
    new Set(c.participant_regions).size===c.participant_regions.length&&vendorCanonical(c.participant_regions)===vendorCanonical([...c.participant_regions].sort())&&
    typeof c.granted_at==='string'&&utc(c.granted_at)===c.granted_at&&typeof v.started_at==='string'&&utc(v.started_at)===v.started_at&&
    Date.parse(c.granted_at)<=Date.parse(v.started_at));
}
function teamBinding(team:ProviderTeam,address:string,agentId:string,scope:string,revision:number) {
  need(hash(scope)&&team.recovery_scope===scope&&team.revision===revision);
  const bot=team.configuration.bots.find(b=>botAddress(b)===address),member=team.members.find(b=>botAddress(b)===address);
  need(bot?.role==='scribe'&&bot.enabled&&!bot.retired&&member?.role==='scribe'&&member.agent_id===agentId&&vendorUuid(agentId));
}
export async function createPrivateRecordingIntent(team:ProviderTeam,workspace:Workspace,localId:string,
  consent:CaptureAttestation,startedAt:string,address='scribe'):Promise<PrivateRecordingIntent> {
  need(workspace.private_draft?.state==='unlinked'&&workspace.appointment_id===null&&vendorUuid(workspace.id));
  const member=team.members.find(b=>botAddress(b)===address),agent=member?.agent_id,scope=team.recovery_scope;
  need(vendorUuid(agent)&&hash(scope));teamBinding(team,address,agent,scope,team.revision);
  const request:PrivateRecordingAttach={idempotency_key:crypto.randomUUID(),local_recording_id:localId,
    expected_workspace_revision:workspace.revision,bot:{address,team_revision:team.revision},
    consent:{...consent,participant_regions:[...consent.participant_regions].sort(),granted_at:utc(consent.granted_at)},started_at:utc(startedAt)};
  attachRequest(request);
  return {contract:'cosmas.private-recording.intent.v1',workspace_id:workspace.id,agent_id:agent,recovery_scope:scope,request,request_sha256:await digest('attach',request)};
}
export async function validatePrivateRecordingIntent(v:PrivateRecordingIntent,team:ProviderTeam) {
  need(closed(v,'contract,workspace_id,agent_id,recovery_scope,request,request_sha256')&&v.contract==='cosmas.private-recording.intent.v1'&&vendorUuid(v.workspace_id)&&hash(v.request_sha256));
  attachRequest(v.request);teamBinding(team,v.request.bot.address,v.agent_id,v.recovery_scope,v.request.bot.team_revision);
  need(await digest('attach',v.request)===v.request_sha256);
}
function finishRequest(v:unknown):asserts v is PrivateRecordingFinish {
  need(closed(v,'idempotency_key,capture_state,manifest_sha256,chunks,frames,ended_at')&&vendorUuid(v.idempotency_key)&&['finished','interrupted','unknown'].includes(String(v.capture_state)));
  if(v.capture_state==='unknown')need(v.manifest_sha256===null&&v.chunks===null&&v.frames===null&&v.ended_at===null);
  else need(hash(v.manifest_sha256)&&integer(v.chunks,1000)&&integer(v.frames,115200000)&&typeof v.ended_at==='string'&&utc(v.ended_at)===v.ended_at);
}
export async function createPrivateRecordingFinishIntent(input:PrivateRecordingFinish):Promise<PrivateRecordingFinishIntent> {
  const request={...input,ended_at:input.ended_at===null?null:utc(input.ended_at)};finishRequest(request);
  return {request,request_sha256:await digest('finish',request)};
}
export async function parsePrivateRecordingReceipt(value:unknown,selection:PrivateRecordingIntent):Promise<PrivateRecordingReceipt> {
  need(closed(value,'contract,custody,recording_id,local_recording_id,workspace_id,workspace_revision,owner_id,box_id,agent_id,team_revision_id,recovery_scope,attach_sha256,started_at,created_at,state,finish,link,upstream_capture_admitted,audio_uploaded,transcription_started')&&
    value.contract==='cosmas.private-recording.v1'&&value.custody==='local_device_metadata'&&vendorUuid(value.recording_id)&&vendorUuid(value.owner_id)&&vendorUuid(value.box_id)&&vendorUuid(value.team_revision_id)&&
    value.workspace_id===selection.workspace_id&&value.local_recording_id===selection.request.local_recording_id&&value.workspace_revision===selection.request.expected_workspace_revision&&value.agent_id===selection.agent_id&&
    value.recovery_scope===selection.recovery_scope&&value.attach_sha256===selection.request_sha256&&typeof value.started_at==='string'&&Date.parse(value.started_at)===Date.parse(selection.request.started_at)&&
    typeof value.created_at==='string'&&Number.isFinite(Date.parse(value.created_at))&&value.upstream_capture_admitted===false&&value.audio_uploaded===false&&value.transcription_started===false&&
    ['unfinished','finished','interrupted','unknown','linked_metadata'].includes(String(value.state)));
  need(await sha({contract:'cosmas-private-drafts-v1',box_id:value.box_id,owner_id:value.owner_id})===selection.recovery_scope);
  if(value.state==='unfinished')need(value.finish===null&&value.link===null);
  else {
    const f=value.finish;need(closed(f,'receipt_id,request_sha256,manifest_sha256,chunks,frames,ended_at')&&vendorUuid(f.receipt_id)&&hash(f.request_sha256));
    if(value.state==='unknown')need(f.manifest_sha256===null&&f.chunks===null&&f.frames===null&&f.ended_at===null&&value.link===null);
    else need(hash(f.manifest_sha256)&&integer(f.chunks,1000)&&integer(f.frames,115200000)&&typeof f.ended_at==='string'&&Number.isFinite(Date.parse(f.ended_at)));
    if(value.state==='linked_metadata')need(closed(value.link,'receipt_id,workspace_link_receipt_id,source_sha256,request_sha256')&&vendorUuid(value.link.receipt_id)&&vendorUuid(value.link.workspace_link_receipt_id)&&hash(value.link.source_sha256)&&hash(value.link.request_sha256));
    else need(value.link===null);
  }
  return value as PrivateRecordingReceipt;
}
async function request(identity:AuthenticatedWorkspaceIdentity,path:string,body:unknown|undefined,signal?:AbortSignal):Promise<unknown> {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000),abort=()=>controller.abort();
  signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  let reader:ReadableStreamDefaultReader<Uint8Array>|undefined;
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));void interrupted.catch(()=>{});
  const wait=<T,>(v:Promise<T>)=>Promise.race([v,interrupted]);
  const check=()=>{controller.signal.throwIfAborted();assertCurrentDesktopSession(identity);if(identity.mode==='clerk_jwt'&&identity.nativeSession&&!identity.nativeSession.isCurrent())throw new WorkspaceApiError(401);};
  try {
    check();const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
    need(permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href));
    const encoded=body===undefined?undefined:vendorCanonical(body);need(encoded===undefined||new TextEncoder().encode(encoded).length<=4096);
    const headers=await wait(workspaceAuthHeaders(identity,base));check();headers.set('X-Cosmas-Private-Recording','1');
    const response=await wait(workspaceFetch(identity,base+path,{method:body===undefined?'GET':'POST',body:encoded,headers,signal:controller.signal,cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'}));check();
    need(!response.redirected&&response.headers.get('content-type')?.split(';',1)[0].trim()==='application/json'&&response.headers.get('cache-control')?.split(',').some(v=>v.trim()==='no-store'));
    reader=response.body?.getReader();need(reader);const parts:Uint8Array[]=[];let size=0;
    while(true){const part=await wait(reader.read());check();if(part.done)break;size+=part.value.length;need(size<=(response.ok?16384:2048));parts.push(part.value);}
    const bytes=new Uint8Array(size);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
    const value=parseVendorJson(new TextDecoder('utf-8',{fatal:true}).decode(bytes));check();
    if(!response.ok)throw new WorkspaceApiError(response.status);return value;
  }catch(error){if(error instanceof WorkspaceApiError)throw error;throw new WorkspaceApiError(503);}
  finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);try{void reader?.cancel().catch(()=>{});reader?.releaseLock();}catch{/* Retain exact requests on interrupted observation. */}controller.abort();}
}
const root=(v:PrivateRecordingIntent)=>'/workspaces/'+v.workspace_id+'/private-recordings';
export const privateRecordingApi={
  async link(identity:AuthenticatedWorkspaceIdentity,v:PrivateRecordingIntent,team:ProviderTeam,recordingId:string,body:PrivateRecordingLinkRequest,signal?:AbortSignal){
    await validatePrivateRecordingIntent(v,team);need(vendorUuid(recordingId)&&closed(body,'idempotency_key,expected_workspace_revision,workspace_link_receipt_id')&&vendorUuid(body.idempotency_key)&&vendorUuid(body.workspace_link_receipt_id)&&integer(body.expected_workspace_revision,2147483647));
    const result=await parsePrivateRecordingReceipt(await request(identity,root(v)+'/'+recordingId+'/link',body,signal),v);
    need(result.recording_id===recordingId&&result.link?.request_sha256===await digest('link',body)&&result.link.workspace_link_receipt_id===body.workspace_link_receipt_id);return result;
  },
  async attach(identity:AuthenticatedWorkspaceIdentity,v:PrivateRecordingIntent,team:ProviderTeam,signal?:AbortSignal){await validatePrivateRecordingIntent(v,team);return parsePrivateRecordingReceipt(await request(identity,root(v),v.request,signal),v);},
  async resolve(identity:AuthenticatedWorkspaceIdentity,v:PrivateRecordingIntent,team:ProviderTeam,signal?:AbortSignal):Promise<PrivateRecordingResolution>{
    await validatePrivateRecordingIntent(v,team);const value=await request(identity,root(v)+'/resolve',v.request,signal);need(closed(value,'outcome,recording'));
    if(value.outcome==='not_found'){need(value.recording===null);return {outcome:'not_found',recording:null};}
    need(value.outcome==='saved');return {outcome:'saved',recording:await parsePrivateRecordingReceipt(value.recording,v)};
  },
  async read(identity:AuthenticatedWorkspaceIdentity,v:PrivateRecordingIntent,team:ProviderTeam,recordingId:string,signal?:AbortSignal){
    await validatePrivateRecordingIntent(v,team);need(vendorUuid(recordingId));const result=await parsePrivateRecordingReceipt(await request(identity,root(v)+'/'+recordingId,undefined,signal),v);need(result.recording_id===recordingId);return result;
  },
  async finish(identity:AuthenticatedWorkspaceIdentity,v:PrivateRecordingIntent,team:ProviderTeam,recordingId:string,finish:PrivateRecordingFinishIntent,signal?:AbortSignal){
    await validatePrivateRecordingIntent(v,team);need(vendorUuid(recordingId)&&closed(finish,'request,request_sha256'));finishRequest(finish.request);need(await digest('finish',finish.request)===finish.request_sha256);
    const result=await parsePrivateRecordingReceipt(await request(identity,root(v)+'/'+recordingId+'/finish',finish.request,signal),v);
    need(result.recording_id===recordingId&&result.finish?.request_sha256===finish.request_sha256&&
      (result.state===finish.request.capture_state||result.state==='linked_metadata')&&
      result.finish.manifest_sha256===finish.request.manifest_sha256&&result.finish.chunks===finish.request.chunks&&result.finish.frames===finish.request.frames&&
      (result.finish.ended_at===null?finish.request.ended_at===null:Date.parse(result.finish.ended_at)===Date.parse(finish.request.ended_at??'')));
    return result;
  },
};
