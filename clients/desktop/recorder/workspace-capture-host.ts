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
import {parseBackendCaptureGrant,parseStartAuthorityDecision} from './protocol';
import {parseNativeProcessFence, type NativeProcessFence} from './native-process-fence';
import {processRecordingLease,createRecordingLeaseOwner,type RecordingLeaseOwner} from './recording-lease';

const OPEN = 'cosmas:workspace-capture:open:v1';
const PRIVATE_ACQUIRE='cosmas:private-capture:acquire:v1',PRIVATE_RELEASE='cosmas:private-capture:release:v1',PRIVATE_IDLE='cosmas:private-capture:idle:v1',PRIVATE_REVOKED='cosmas:private-capture:revoked:v1';
const CLINICAL_ACQUIRE='cosmas:clinical-microphone:acquire:v1',CLINICAL_RELEASE='cosmas:clinical-microphone:release:v1',CLINICAL_ACTIVE='cosmas:clinical-microphone:active:v1';
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
  auth:Auth;ipc:Ipc;renderer:Renderer&{forcefullyCrashRenderer?():void};directory:string;apiOrigin:string;
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
export function installWorkspaceDesktopCapture(options:Options):{close():Promise<void>;allowsRendererMicrophone():boolean} {
  if(typeof window!=='undefined'||process.platform!=='darwin')throw unavailable();
  let owner:Owned|undefined,opening:Promise<unknown>|undefined,closed=false;
  type PrivateOwner={requestId:string;command:string;permitId:string;revision:string;lease:RecordingLeaseOwner;expiresAt:number;admitted:boolean;retiring:boolean;clinical?:{preparationId:string;sourceLeaseId?:string;authorizationRequested:boolean;startExpiresAt?:number;started?:boolean};timer?:ReturnType<typeof setTimeout>;crash?:ReturnType<typeof setTimeout>};
  let privateOwner:PrivateOwner|undefined;
  const releasedPrivate=new Set<string>();
  const usedPrivateRequests=new Set<string>();
  const privateCurrent=(p:PrivateOwner)=>!closed&&privateOwner===p&&!p.retiring&&p.admitted&&p.expiresAt>Date.now()&&(!p.clinical||p.clinical.started===true||(p.clinical.startExpiresAt??0)>Date.now())&&!options.renderer.isDestroyed()&&options.renderer.mainFrame.url==='app://cosmas/index.html'&&options.auth.snapshot().phase==='ready'&&options.auth.snapshot().revision===p.revision;
  const releasePrivate=(p:PrivateOwner)=>{if(privateOwner!==p)return;clearTimeout(p.timer);clearTimeout(p.crash);processRecordingLease.release(p.lease);releasedPrivate.add(p.permitId);privateOwner=undefined;};
  const revokePrivate=()=>{const p=privateOwner;if(!p||p.retiring)return;p.retiring=true;
    if(options.renderer.isDestroyed()){releasePrivate(p);return;}
    options.renderer.send(PRIVATE_REVOKED as Parameters<Renderer['send']>[0],{permitId:p.permitId});
    // Auth loss/deadline cannot depend indefinitely on a responsive renderer.
    // Destroying its process closes its OS microphone tracks; keep the permit
    // until that closure event or the exact source's confirmed release.
    p.crash=setTimeout(()=>{if(privateOwner===p&&!options.renderer.isDestroyed())options.renderer.forcefullyCrashRenderer?.();},2000);p.crash.unref?.();
  };
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
    if(privateOwner)throw unavailable();
    const value=exact(payload,['workspaceId','sessionId','revision','requestId']);
    const workspaceId=uuid(value.workspaceId as string),sessionId=uuid(value.sessionId as string),revision=uuid(value.revision as string);
    const requestId=uuid(value.requestId as string),state=await options.auth.getState();
    if(closed||privateOwner||state.phase!=='ready'||state.revision!==revision)throw unavailable();
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
    frame(event);if(opening||privateOwner)throw unavailable();
    opening=open(payload);try{const result=await opening;frame(event);return result;}finally{opening=undefined;}
  });
  options.ipc.handle(PRIVATE_ACQUIRE as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);const value=exact(payload,['requestId','revision','recordingId','consent']);
    const requestId=uuid(value.requestId as string),revision=uuid(value.revision as string);uuid(value.recordingId as string);privateConsent(value.consent);
    const command=createHash('sha256').update(JSON.stringify([requestId,revision,value.recordingId,value.consent])).digest('hex');
    if(privateOwner){if(privateOwner.requestId===requestId&&privateOwner.command===command&&privateCurrent(privateOwner))return {requestId,permitId:privateOwner.permitId,revision,expiresAt:new Date(privateOwner.expiresAt).toISOString()};throw unavailable();}
    if(owner||opening||usedPrivateRequests.has(requestId)||usedPrivateRequests.size>=10000)throw unavailable();
    const state=options.auth.snapshot();if(state.phase!=='ready'||state.revision!==revision)throw unavailable();
    const p:PrivateOwner={requestId,command,permitId:crypto.randomUUID(),revision,lease:createRecordingLeaseOwner(),expiresAt:Date.now()+900000,admitted:false,retiring:false};
    processRecordingLease.acquire(p.lease);privateOwner=p;usedPrivateRequests.add(requestId);
    try{const proof=exact(await options.auth.sourceRequest('sourceIdle',{},revision),['idle']);frame(event);
      if(proof.idle!==true||closed||privateOwner!==p||p.retiring||owner||opening||options.auth.snapshot().phase!=='ready'||options.auth.snapshot().revision!==revision)throw unavailable();
      p.admitted=true;p.timer=setTimeout(revokePrivate,Math.max(1,p.expiresAt-Date.now()));p.timer.unref?.();
      return {requestId,permitId:p.permitId,revision,expiresAt:new Date(p.expiresAt).toISOString()};
    }catch(error){releasePrivate(p);throw error;}
  });
  options.ipc.handle(PRIVATE_RELEASE as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);const value=exact(payload,['requestId','permitId']);uuid(value.requestId as string);const permitId=uuid(value.permitId as string);
    if(privateOwner){if(privateOwner.permitId!==permitId||privateOwner.clinical)throw unavailable();releasePrivate(privateOwner);}else if(!releasedPrivate.has(permitId))throw unavailable();return {requestId:value.requestId,released:true};
  });
  options.ipc.handle(CLINICAL_ACQUIRE as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);const value=exact(payload,['requestId','revision','workspaceId','sessionId','leaseId','leaseReceiptId','leaseGeneration','captureAuthorizedUntil','firstSequenceNumber']);
    for(const k of ['requestId','revision','workspaceId','sessionId','leaseId','leaseReceiptId'])uuid(value[k] as string);
    const requestId=value.requestId as string,revision=value.revision as string,deadline=Date.parse(value.captureAuthorizedUntil as string);
    if(!Number.isSafeInteger(value.leaseGeneration)||Number(value.leaseGeneration)<1||!Number.isSafeInteger(value.firstSequenceNumber)||Number(value.firstSequenceNumber)<0||Number(value.firstSequenceNumber)>=360||!Number.isFinite(deadline)||deadline<=Date.now()||deadline>Date.now()+900000||owner||opening)throw unavailable();
    const command=createHash('sha256').update(JSON.stringify(value)).digest('hex');
    if(privateOwner){if(privateOwner.command===command&&privateOwner.clinical)return {requestId,permitId:privateOwner.permitId,revision,expiresAt:new Date(privateOwner.expiresAt).toISOString(),admitted:privateCurrent(privateOwner)};throw unavailable();}
    if(usedPrivateRequests.has(requestId)||usedPrivateRequests.size>=10000||options.auth.snapshot().phase!=='ready'||options.auth.snapshot().revision!==revision)throw unavailable();
    const p:PrivateOwner={requestId,command,permitId:crypto.randomUUID(),revision,lease:createRecordingLeaseOwner(),expiresAt:deadline,admitted:false,retiring:false,clinical:{preparationId:crypto.randomUUID(),authorizationRequested:false}};
    processRecordingLease.acquire(p.lease);privateOwner=p;usedPrivateRequests.add(requestId);
    try{const {requestId:_,revision:__,...metadata}=value;
      const prepared=exact(await options.auth.sourceRequest('sourcePrepare',{...metadata,preparationId:p.clinical!.preparationId},revision),['grant','processFence']);frame(event);
      const grant=parseBackendCaptureGrant(prepared.grant);if(grant.captureSessionId!==value.sessionId)throw unavailable();p.clinical!.sourceLeaseId=grant.sourceLeaseId;
      if(privateOwner!==p||p.retiring||options.auth.snapshot().revision!==revision)throw unavailable();p.clinical!.authorizationRequested=true;
      const decision=parseStartAuthorityDecision(await options.auth.sourceRequest('sourceAuthorize',{sourceLeaseId:grant.sourceLeaseId},revision));frame(event);
      if(decision.decision!=='authorized'||decision.captureSessionId!==grant.captureSessionId||decision.sourceLeaseId!==grant.sourceLeaseId||decision.actorId!==grant.actorId||decision.consentRecordId!==grant.consentRecordId||Date.parse(decision.expiresAt)<=Date.now()||Date.parse(decision.expiresAt)>Date.now()+15000||privateOwner!==p||p.retiring||options.auth.snapshot().phase!=='ready'||options.auth.snapshot().revision!==revision)throw unavailable();
      decision.captureCapability.secret='';p.clinical!.startExpiresAt=Date.parse(decision.expiresAt);p.admitted=true;p.timer=setTimeout(revokePrivate,Math.max(1,p.expiresAt-Date.now()));p.timer.unref?.();
      return {requestId,permitId:p.permitId,revision,expiresAt:new Date(p.expiresAt).toISOString(),admitted:true};
    }catch{p.retiring=true;/* Native journal/owner stays until exact source closure retry. */return {requestId,permitId:p.permitId,revision,expiresAt:new Date(p.expiresAt).toISOString(),admitted:false};}
  });
  options.ipc.handle(CLINICAL_ACTIVE as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);const value=exact(payload,['requestId','permitId']);uuid(value.requestId as string);const id=uuid(value.permitId as string),p=privateOwner;
    if(!p?.clinical||p.permitId!==id||!privateCurrent(p)||!p.clinical.started&&(p.clinical.startExpiresAt??0)<=Date.now())throw unavailable();p.clinical.started=true;
    return {requestId:value.requestId,active:true};
  });
  options.ipc.handle(CLINICAL_RELEASE as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);const value=exact(payload,['requestId','permitId']);uuid(value.requestId as string);const permitId=uuid(value.permitId as string),p=privateOwner;
    if(p){if(p.permitId!==permitId||!p.clinical)throw unavailable();p.retiring=true;
      if(p.clinical.sourceLeaseId&&p.clinical.authorizationRequested)await options.auth.sourceRequest('sourceStopped',{sourceLeaseId:p.clinical.sourceLeaseId});
      else await options.auth.sourceRequest('sourcePreparationRelease',{preparationId:p.clinical.preparationId});releasePrivate(p);
    }else if(!releasedPrivate.has(permitId))throw unavailable();return {requestId:value.requestId,released:true};
  });
  options.ipc.handle(PRIVATE_IDLE as Parameters<Ipc['handle']>[0],async(event,payload)=>{
    frame(event);const value=exact(payload,['requestId','revision']),revision=uuid(value.revision as string);uuid(value.requestId as string);
    if(owner||opening||privateOwner||options.auth.snapshot().phase!=='ready'||options.auth.snapshot().revision!==revision)throw unavailable();
    const proof=exact(await options.auth.sourceRequest('sourceIdle',{},revision),['idle']);frame(event);
    if(proof.idle!==true||owner||opening||privateOwner||options.auth.snapshot().revision!==revision)throw unavailable();return {requestId:value.requestId,idle:true};
  });
  const rendererClosed=()=>{if(privateOwner)releasePrivate(privateOwner);};
  const rendererLeaving=()=>revokePrivate();
  options.renderer.on('destroyed',rendererClosed);options.renderer.on('render-process-gone',rendererClosed);options.renderer.on('will-navigate',rendererLeaving);
  const removeAuth=options.auth.subscribe(state=>{
    if(privateOwner&&(state.phase!=='ready'||state.revision!==privateOwner.revision))revokePrivate();
    if(owner&&(state.phase!=='ready'||state.revision!==owner.revision))void closeOwner().catch(()=>{});
  });
  return {allowsRendererMicrophone:()=>!!privateOwner&&privateCurrent(privateOwner),
    close:async()=>{revokePrivate();if(privateOwner&&!options.renderer.isDestroyed())throw unavailable();closed=true;
      for(const channel of [OPEN,PRIVATE_ACQUIRE,PRIVATE_RELEASE,PRIVATE_IDLE,CLINICAL_ACQUIRE,CLINICAL_RELEASE,CLINICAL_ACTIVE])options.ipc.removeHandler(channel as Parameters<Ipc['removeHandler']>[0]);removeAuth();
      options.renderer.removeListener('destroyed',rendererClosed);options.renderer.removeListener('render-process-gone',rendererClosed);options.renderer.removeListener('will-navigate',rendererLeaving);
      await opening?.catch(()=>{});await closeOwner();}};
}
function privateConsent(value:unknown){const v=exact(value,['modality','participant_regions','method','all_parties_consented','granted_at','language']);
  if(v.all_parties_consented!==true||v.method!=='verbal_attestation'||!['in_person','virtual','phone'].includes(String(v.modality))||!['en-US','en-US+es-US'].includes(String(v.language))||!Array.isArray(v.participant_regions)||!v.participant_regions.length||v.participant_regions.length>16||new Set(v.participant_regions).size!==v.participant_regions.length||!v.participant_regions.every(r=>typeof r==='string'&&/^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$/.test(r))||typeof v.granted_at!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(v.granted_at)||new Date(v.granted_at).toISOString()!==v.granted_at||Date.parse(v.granted_at)>Date.now()||Date.now()-Date.parse(v.granted_at)>300000)throw unavailable();
}
function exact(value:unknown,keys:string[]):Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!==keys.sort().join(','))throw unavailable();
  return value as Record<string,unknown>;
}
function unavailable():Error{return new Error('Desktop recording is unavailable. Saved audio is retained.');}
