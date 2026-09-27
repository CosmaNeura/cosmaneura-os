import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {WorkspaceCaptureBff} from '../../capture/src/bff/workspace-client';
import {BffResponseError} from '../../capture/src/bff/http-client';
import {HttpCiphertextUploadTarget} from '../../capture/src/bff/upload-target';
import {parseCreatorReview} from '../../scribe-review/creator-review-api';
import {DesktopProviderRecorder, type PreparedDesktopCapture} from './provider-recorder';
import {DesktopProviderRecorderIpc} from './provider-recorder-ipc';
import {NativeProviderPresentation} from './native-provider-presentation';
import {DurableDesktopRecordStore, uuid} from './durable-record-store';
import {DurableDesktopFlowStore} from './durable-flow-store';
import {DurableDesktopQueueStorage} from './durable-queue-store';
import {DurableDesktopCoverage} from './durable-provider-records';
import {openDeviceCustody, type DeviceProtection} from './device-custody';
import {parseBackendCaptureGrant} from './protocol';
import {parseNativeProcessFence, type NativeProcessFence} from './native-process-fence';

const OPEN = 'cosmas:workspace-capture:open:v1';
const serviceCodes=new Set(['capture_consent_required','capture_consent_unavailable','capture_request_conflict',
  'capture_in_progress','capture_session_changed','capture_context_changed','capture_connection_required',
  'core_capture_access_unavailable','capture_source_unavailable']);
interface State {phase:string;revision:string}
interface Auth {
  getState():Promise<State>; snapshot():State;
  subscribe(listener:(state:State)=>void):()=>void;
  sourceRequest(method:string,payload:Record<string,unknown>,revision?:string):Promise<unknown>;
}
type Ipc = ConstructorParameters<typeof DesktopProviderRecorderIpc>[0];
type Renderer = ConstructorParameters<typeof DesktopProviderRecorderIpc>[1];
interface Options {
  auth:Auth;ipc:Ipc;renderer:Renderer;directory:string;apiOrigin:string;
  protection:DeviceProtection;uploadOrigins:readonly string[];
  audio:{helperPath:string;helperSha256:string};presentation:{helperPath:string;helperSha256:string};
  /** Existing main-process proxy supplies fresh native auth and bounded HTTP. */
  request(request:Request):Promise<Response>;
  isSessionActive():boolean;
}
interface Source {preparationId:string;sourceLeaseId?:string;retiring:boolean;processFence?:NativeProcessFence;prepared?:PreparedDesktopCapture}
interface Owned {
  workspaceId:string;sessionId:string;revision:string;abort:AbortController;
  recorder?:DesktopProviderRecorder;ipc?:DesktopProviderRecorderIpc;store?:DurableDesktopRecordStore;
  custody?:Awaited<ReturnType<typeof openDeviceCustody>>;presentation?:NativeProviderPresentation;
  removePresentation?:()=>void;closing?:Promise<void>;sources:Set<Source>;
  constructed:Promise<void>;
}

/** One recorder for the authenticated combined desktop workspace. Opening
 * checks OS ownership before private storage; only Start can acquire audio. */
export function installWorkspaceDesktopCapture(options:Options):{close():Promise<void>} {
  if(typeof window!=='undefined'||process.platform!=='darwin')throw unavailable();
  let owner:Owned|undefined,opening:Promise<unknown>|undefined,closed=false;
  const frame=(event:{sender:{id:number;mainFrame:unknown};senderFrame:unknown})=>{
    if(closed||options.renderer.isDestroyed()||event.sender.id!==options.renderer.id||
      event.senderFrame!==event.sender.mainFrame||options.renderer.mainFrame.url!=='app://cosmas/index.html')throw unavailable();
  };
  const current=(o:Owned)=>{
    const state=options.auth.snapshot();
    if(closed||owner!==o||o.abort.signal.aborted||state.phase!=='ready'||state.revision!==o.revision)throw unavailable();
  };
  const retire=async(o:Owned,stopped:boolean)=>{
    for(const source of o.sources){
      if(source.sourceLeaseId&&!source.retiring)
        await options.auth.sourceRequest(stopped?'sourceStopped':'sourceRelease',{sourceLeaseId:source.sourceLeaseId});
      else {source.retiring=true;await options.auth.sourceRequest('sourcePreparationRelease',{preparationId:source.preparationId});}
      o.sources.delete(source);
    }
  };
  const closeOwner=(o=owner):Promise<void>=>{
    if(!o)return Promise.resolve();
    o.abort.abort();
    return o.closing??=(async()=>{
      await o.constructed;
      // Failed physical/server stop retains this owner and its encrypted store.
      await o.ipc?.dispose();await o.recorder?.deactivate();await retire(o,false);
      await o.presentation?.dispose();o.removePresentation?.();o.store?.close();await o.custody?.release();
      if(owner===o)owner=undefined;
    })().catch(error=>{o.closing=undefined;throw error;});
  };
  const request=async(o:Owned,path:string,body?:unknown,identity=false,signal?:AbortSignal)=>{
    current(o);
    const response=await options.request(new Request('app://cosmas/api'+path,{method:body===undefined?'GET':'POST',
      headers:{'Content-Type':'application/json','X-Cosmas-Desktop-Session':o.revision,
        'X-Cosmas-Workspace-Protocol':'1','X-Cosmas-Draft-Recovery':'2',...(identity?{'X-Cosmas-Team-Contract':'2'}:{})},
      body:body===undefined?undefined:JSON.stringify(body),signal:signal?AbortSignal.any([o.abort.signal,signal]):o.abort.signal}));
    current(o);
    const value:unknown=await response.json();current(o);
    if(response.status!==200){
      const code=value&&typeof value==='object'&&'detail' in value&&typeof value.detail==='string'&&serviceCodes.has(value.detail)
        ?value.detail:'capture_request_unconfirmed';
      throw new BffResponseError(response.status,code,null);
    }
    return value;
  };
  const review=async(o:Owned)=>{
    const result=exact(await request(o,`/workspaces/${o.workspaceId}/capture/operations`,{
      session_id:o.sessionId,idempotency_key:crypto.randomUUID(),operation:{kind:'creator_review'}}),
      ['workspace_id','session_id','operation','receipt']);
    if(result.workspace_id!==o.workspaceId||result.session_id!==o.sessionId||result.operation!=='creator_review')throw unavailable();
    return parseCreatorReview(result.receipt,o.sessionId);
  };
  const prepareSource=async(o:Owned,prepared:PreparedDesktopCapture)=>{
    current(o);
    for(const prior of o.sources)if(!prior.sourceLeaseId||prior.retiring){
      prior.retiring=true;await options.auth.sourceRequest('sourcePreparationRelease',{preparationId:prior.preparationId});
      o.sources.delete(prior);
    }
    current(o);const source:Source={preparationId:crypto.randomUUID(),retiring:false};o.sources.add(source);
    const raw=exact(await options.auth.sourceRequest('sourcePrepare',{
      preparationId:source.preparationId,workspaceId:o.workspaceId,sessionId:o.sessionId,
      leaseId:prepared.captureLeaseId,leaseReceiptId:prepared.leaseReceiptId,leaseGeneration:prepared.captureLeaseGeneration,
      captureAuthorizedUntil:prepared.captureAuthorizedUntil,
      ...(prepared.firstSequenceNumber?{firstSequenceNumber:prepared.firstSequenceNumber}:{})},o.revision),['grant','processFence']);
    const grant=parseBackendCaptureGrant(raw.grant);
    if(grant.captureSessionId!==o.sessionId||source.retiring)throw unavailable();
    source.sourceLeaseId=grant.sourceLeaseId;source.processFence=parseNativeProcessFence(raw.processFence);
    source.prepared=prepared;current(o);
    return {grant,status:'created' as const};
  };
  const open=async(payload:unknown)=>{
    const value=exact(payload,['workspaceId','sessionId','revision','requestId']);
    const workspaceId=uuid(value.workspaceId as string),sessionId=uuid(value.sessionId as string),revision=uuid(value.revision as string);
    const requestId=uuid(value.requestId as string),state=await options.auth.getState();
    if(closed||state.phase!=='ready'||state.revision!==revision)throw unavailable();
    if(owner?.workspaceId===workspaceId&&owner.sessionId===sessionId&&owner.revision===revision&&owner.recorder?.availableForView)
      return {requestId,workspaceId,sessionId};
    await closeOwner();
    let constructed:()=>void=()=>{};
    const o:Owned={workspaceId,sessionId,revision,abort:new AbortController(),sources:new Set(),
      constructed:new Promise(resolve=>{constructed=resolve;})};owner=o;
    try{
      const view=await review(o); // Authorizes this appointment before reading any local audio.
      const identity=exact(await request(o,'/provider-team/identity',undefined,true),['contract_version','box_id','actor_id','recovery_scope']);
      uuid(identity.box_id as string);uuid(identity.actor_id as string);
      if(identity.contract_version!==1||typeof identity.recovery_scope!=='string'||!/^[a-f0-9]{64}$/.test(identity.recovery_scope))throw unavailable();
      // A deterministic storage namespace, not an authorization grant.
      const scope=createHash('sha256').update(`cosmas-desktop-native:v1:${options.apiOrigin}:${identity.recovery_scope}`).digest();
      scope[6]=(scope[6]!&15)|128;scope[8]=(scope[8]!&63)|128;
      const hex=scope.subarray(0,16).toString('hex'),recoveryScope=`${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
      const directory=join(options.directory,'native-recordings');
      o.custody=await openDeviceCustody(directory,options.protection,{recoveryScope,workspaceId},o.abort.signal);current(o);
      o.store=await DurableDesktopRecordStore.open({directory,recoveryScope,workspaceId,key:o.custody.key});current(o);
      const flow=new DurableDesktopFlowStore(o.store.namespace('capture-flow'));
      const prior=await flow.getActiveCaptureState(),preparing=await flow.getPreparationState();
      if(prior&&prior.sessionId!==sessionId||preparing&&preparing.sessionId!==sessionId)throw unavailable();
      // Completed sessions without local work reopen directly in creator review.
      if(!prior&&!preparing&&!['created','capturing'].includes(view.status)){
        constructed();await closeOwner(o);return {requestId,workspaceId,sessionId,reviewOnly:true};
      }
      o.presentation=await NativeProviderPresentation.open({...options.presentation,enabled:true,
        isSessionActive:()=>!o.abort.signal.aborted&&options.isSessionActive()});current(o);
      const queue=new DurableDesktopQueueStorage(o.store.namespace(`queue:${sessionId}`),sessionId);
      const coverage=new DurableDesktopCoverage(o.store.namespace('coverage'),sessionId);
      const bff=new WorkspaceCaptureBff(workspaceId,sessionId,(body,signal)=>request(o,`/workspaces/${workspaceId}/capture/operations`,body,false,signal));
      o.recorder=await DesktopProviderRecorder.open({enabled:true,sessionId,signal:o.abort.signal,
        profiles:bff,standardContinuousCapture:true,
        createBff:()=>bff,authorizePreparation:async()=>({sessionId,status:(await review(o)).status}),
        authorizeMount:prepared=>prepareSource(o,prepared),
        authority:{authorizeStart:async grant=>{
          current(o);if(![...o.sources].some(s=>s.sourceLeaseId===grant.sourceLeaseId&&!s.retiring))throw unavailable();
          const decision=await options.auth.sourceRequest('sourceAuthorize',{sourceLeaseId:grant.sourceLeaseId},revision);current(o);return decision;
        }},indicator:o.presentation,flowStore:flow,createSessionKey:flow.createSessionKey,queueStorage:queue,
        uploadTarget:new HttpCiphertextUploadTarget([...options.uploadOrigins]),coverage,
        native:{...options.audio,isSessionActive:()=>!o.abort.signal.aborted&&options.isSessionActive(),continuation:{
          getOwner:()=>{
            current(o);const sources=[...o.sources],source=sources[0];
            if(sources.length!==1||!source?.sourceLeaseId||!source.prepared||source.retiring)throw unavailable();
            return {runId:source.sourceLeaseId,generation:source.prepared.captureLeaseGeneration,
              hardMaximumChunks:360-(source.prepared.firstSequenceNumber??0)};
          },
          authorize:async extension=>{
            current(o);const sources=[...o.sources],source=sources[0];
            if(sources.length!==1||!source?.sourceLeaseId||source.retiring)throw unavailable();
            const {maximumChunks:_,...request}=extension;
            const permit=await options.auth.sourceRequest('sourceExtend',{sourceLeaseId:source.sourceLeaseId,...request},revision);
            current(o);if(source.retiring||!o.sources.has(source))throw unavailable();return permit;
          },
        },getProcessFence:()=>{
          current(o);const sources=[...o.sources];if(sources.length!==1||!sources[0]?.processFence||sources[0].retiring)throw unavailable();
          return sources[0].processFence;
        }},selectWindow:o.presentation.selectWindow,retireSource:()=>retire(o,true),release:async()=>{}});
      current(o);
      o.removePresentation=o.presentation.onEvent(event=>{
        if(event.kind==='stop_requested'&&event.sessionId===sessionId)void o.recorder?.pauseRecording().catch(()=>{});
        else if(event.kind==='failed')void closeOwner(o).catch(()=>{});
      });
      o.ipc=new DesktopProviderRecorderIpc(options.ipc,options.renderer,o.recorder);o.ipc.install();
      return {requestId,workspaceId,sessionId};
    }catch(error){constructed();await closeOwner(o);throw error;}finally{constructed();}
  };
  options.ipc.handle(OPEN as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);if(opening)throw unavailable();
    opening=open(payload);try{const result=await opening;frame(event);return result;}finally{opening=undefined;}
  });
  const removeAuth=options.auth.subscribe(state=>{
    if(owner&&(state.phase!=='ready'||state.revision!==owner.revision))void closeOwner().catch(()=>{});
  });
  return {close:async()=>{closed=true;options.ipc.removeHandler(OPEN as Parameters<Ipc['removeHandler']>[0]);removeAuth();
    await opening?.catch(()=>{});await closeOwner();}};
}
function exact(value:unknown,keys:string[]):Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!==keys.sort().join(','))throw unavailable();
  return value as Record<string,unknown>;
}
function unavailable():Error{return new Error('Desktop recording is unavailable. Saved audio is retained.');}
