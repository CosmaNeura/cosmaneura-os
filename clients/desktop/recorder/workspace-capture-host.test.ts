import {mkdtemp,rm,readFile,readdir} from 'node:fs/promises';
import {realpathSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {afterEach,expect,it,vi} from 'vitest';
import {installWorkspaceDesktopCapture} from './workspace-capture-host';
import {NativeProviderPresentation} from './native-provider-presentation';
import {NativeProcessPCMDriver} from './native-process-driver';
import {DesktopProviderRecorder} from './provider-recorder';
import {InMemoryRecordingIndicator} from './recording-indicator';
import {HttpCiphertextUploadTarget} from '../../capture/src/bff/upload-target';
import {MockCaptureService} from '../../capture/src/configured/mock-bff/state';
import {connectDesktopRecorderView,DESKTOP_RECORDER_CHANNELS} from '../../capture/src/configured/provider/desktop-recorder-view';

type Options=Parameters<typeof installWorkspaceDesktopCapture>[0];
type Handler=Parameters<Options['ipc']['handle']>[1];
const workspaceId='10000000-0000-4000-8000-000000000001',revision='20000000-0000-4000-8000-000000000002';
const cleanup:(()=>Promise<void>|void)[]=[];
afterEach(async()=>{for(const close of cleanup.reverse())await close();cleanup.length=0;vi.restoreAllMocks();vi.useRealTimers();});

async function fixture(){
  const directory=await mkdtemp(join(realpathSync(tmpdir()),'cosmas-workspace-recorder-'));
  cleanup.push(()=>rm(directory,{recursive:true,force:true}));
  const service=new MockCaptureService();
  const person={appointment_id:'invented-appointment',practitioner_id:'invented-creator',patient_id:'invented-patient'};
  const consent=service.createConsent({...person,participant_regions:['US-NY'],modality:'in_person',method:'verbal_attestation',
    all_parties_consented:true,granted_at:new Date().toISOString()},'consent');
  const session=service.createSession({...person,consent_record_id:consent.id,modality:'in_person'},'session');
  let status=session.status;
  const calls:{kind:string;key:string;payload:unknown}[]=[];
  const request=vi.fn(async(request:Request)=>{
    expect(request.headers.get('X-Cosmas-Desktop-Session')).toBe(revision);
    if(new URL(request.url).pathname==='/api/provider-team/identity')return Response.json({contract_version:1,
      box_id:workspaceId,actor_id:'30000000-0000-4000-8000-000000000003',recovery_scope:'a'.repeat(64)});
    const body=await request.json();const op=body.operation,key=body.idempotency_key;
    expect(body.session_id).toBe(session.id);calls.push({kind:op.kind,key,payload:op.payload});
    let receipt:unknown;
    switch(op.kind){
      case 'creator_review':receipt={schema_version:'1.0',session_id:session.id,status,source:null,working:null,review_queue:null};break;
      // Current Scribe publishes ordinary capture capabilities and no profile API.
      case 'capabilities':receipt={...service.capabilities(),max_chunks:2048,remaining_aggregate_plaintext_bytes:402653184};break;
      case 'encryption_key':receipt=service.audioEncryptionKey();break;
      case 'bind_key':receipt=service.bindSessionAudioKey(session.id,op.payload,key);break;
      case 'issue_lease':receipt=service.issueLease(op.payload,key);break;
      case 'renew_lease':receipt=service.renewLease(op.lease_id,op.payload,key);break;
      case 'reserve_chunks':receipt=service.reserveChunks(op.payload,key);break;
      case 'authorize_upload':receipt=service.authorizeUpload(op.object_id,op.payload,key);break;
      case 'chunk_receipt':receipt=service.chunkReceipt(op.object_id);break;
      case 'register_chunk':receipt=service.registerChunk(op.payload,key);break;
      case 'complete':receipt=service.completeCapture(op.payload,key);status='uploaded';break;
      case 'transcription_status':receipt=service.transcriptionStatus();break;
      case 'transcript':receipt=service.transcript();break;
      default:throw Error('Unexpected fixture operation: '+op.kind);
    }
    return Response.json({workspace_id:workspaceId,session_id:session.id,operation:op.kind,receipt});
  });
  vi.spyOn(HttpCiphertextUploadTarget.prototype,'putCompleteEnvelope').mockImplementation(async(url,envelope)=>{
    const parsed=new URL(url);service.putEnvelope(parsed.pathname.split('/').at(-1)!,parsed.searchParams.get('receipt')!,envelope);
  });
  const indicator=new InMemoryRecordingIndicator(),dispose=vi.fn(async()=>{});
  const selectWindow=vi.fn(async()=>({application:'com.google.Chrome' as const,processID:1,windowID:1}));
  vi.spyOn(NativeProviderPresentation,'open').mockResolvedValue({publish:indicator.publish.bind(indicator),
    selectWindow,dispose,onEvent:()=>()=>{}} as unknown as NativeProviderPresentation);
  const availability=vi.spyOn(NativeProcessPCMDriver.prototype,'getAvailability').mockResolvedValue(true);
  const permissions=vi.spyOn(NativeProcessPCMDriver.prototype,'requestPermissions').mockImplementation(async()=>{availability.mockResolvedValue(true);return true;});
  let emit:()=>Promise<void>=async()=>{throw Error('Audio has not started');};const physicalStops:string[]=[];
  const extensions:{maximumChunks:number;leaseGeneration:number}[]=[];
  const start=vi.spyOn(NativeProcessPCMDriver.prototype,'start').mockImplementation((_configuration,sink)=>{
    const mark={hostTimeNanoseconds:'1000000000',microphonePrerollNanoseconds:'0',systemPrerollNanoseconds:'0'};
    let active=false,frames=0;
    emit=async()=>{expect(active).toBe(true);for(let index=0;index<40;index++){
      const firstFrame=frames;frames+=4000;
      await sink.onPcmPacket({firstFrame,pcmBytes:new Uint8Array(8000).fill(17)});
    }};
    return {ready:Promise.resolve(mark),activate:()=>{active=true;},extend:async value=>{
      expect(active).toBe(true);extensions.push(value);
    },stop:async({mode})=>{
      physicalStops.push(mode);active=false;
      return mode==='discard'?null:{start:mark,endHostTimeNanoseconds:String(1_000_000_000+frames*62_500),outputFrames:frames,
        microphoneTailNanoseconds:'0',systemTailNanoseconds:'0'};
    }};
  });
  let state={phase:'ready',revision},denyStop=false;
  const authListeners=new Set<(value:typeof state)=>void>();
  let grant:Record<string,unknown>={};
  const sourceRequest=vi.fn(async(method:string,payload:Record<string,unknown>,publicRevision?:string)=>{
    if(method==='sourceIdle'){expect(publicRevision).toBe(revision);expect(payload).toEqual({});return {idle:true};}
    if(method==='sourcePrepare'){
      expect(publicRevision).toBe(revision);
      grant={captureSessionId:session.id,actorId:person.practitioner_id,consentRecordId:consent.id,consentStatus:'granted',
        sessionStatus:'authorized',source:'desktop_companion',sourceLeaseId:crypto.randomUUID()};
      return {grant,processFence:{epoch:crypto.randomUUID(),coordinatorDevice:'1',coordinatorInode:'1',captureDevice:'1',captureInode:'2'}};
    }
    if(method==='sourceAuthorize'){
      expect(payload.sourceLeaseId).toBe(grant.sourceLeaseId);expect(publicRevision).toBe(revision);
      const expiresAt=new Date(Date.now()+15_000).toISOString();
      return {schemaVersion:1,decision:'authorized',...grant,issuedAt:new Date().toISOString(),expiresAt,
        captureCapability:{capabilityId:crypto.randomUUID(),secret:'invented-private-start-capability',expiresAt}};
    }
    if(method==='sourceStopped'){expect(physicalStops.length).toBeGreaterThan(0);if(denyStop)throw Error('Invented lost stop response');}
    return null;
  });
  const handlers=new Map<string,Handler>(),listeners=new Set<(value:unknown)=>void>(),messages:unknown[]=[];
  const frame={url:'app://cosmas/index.html'},event={sender:{id:7,mainFrame:frame},senderFrame:frame};
  const renderer={id:7,mainFrame:frame,isDestroyed:()=>false,send:(_channel:string,value:unknown)=>{
    messages.push(structuredClone(value));for(const listener of listeners)listener(structuredClone(value));},on:()=>{},removeListener:()=>{}};
  const options:Options={auth:{getState:async()=>state,snapshot:()=>state,sourceRequest,subscribe:fn=>{authListeners.add(fn);return()=>authListeners.delete(fn);}},
    ipc:{handle:(name,fn)=>{handlers.set(name,fn);},removeHandler:name=>{handlers.delete(name);}},renderer,directory,
    apiOrigin:'https://cosmas.invalid',uploadOrigins:['http://127.0.0.1:4174'],request,isSessionActive:()=>true,
    // Invented custody only: this never calls Keychain or Electron safeStorage.
    protection:{isEncryptionAvailable:()=>true,encryptString:value=>Buffer.from(value),decryptString:value=>value.toString()},
    audio:{helperPath:'/unused-invented-audio',helperSha256:'0'.repeat(64)},
    presentation:{helperPath:'/unused-invented-indicator',helperSha256:'0'.repeat(64)}};
  let host=installWorkspaceDesktopCapture(options);cleanup.push(()=>host.close());
  const open=async()=>{
    const value=await handlers.get('cosmas:workspace-capture:open:v1')!(event,{requestId:crypto.randomUUID(),workspaceId,sessionId:session.id,revision});
    messages.push(value);return value;
  };
  const view=()=>connectDesktopRecorderView({request:value=>handlers.get(DESKTOP_RECORDER_CHANNELS.request)!(event,structuredClone(value)),
    subscribe:listener=>{listeners.add(listener);return()=>listeners.delete(listener);}},session.id,new AbortController().signal);
  return {open,view,start,extensions,selectWindow,calls,sourceRequest,indicator,dispose,messages,permissions,availability,emit:()=>emit(),host:()=>host,
    sessionId:session.id,markBrowserStopped:()=>{physicalStops.push('browser-tracks-stopped');},
    privateInvoke:(channel:string,value:unknown)=>handlers.get(channel)!(event,value),
    denyStop:(value:boolean)=>{denyStop=value;},reopen:async()=>{await host.close();host=installWorkspaceDesktopCapture(options);},
    loseAuth:()=>{state={phase:'signed_out',revision:crypto.randomUUID()};authListeners.forEach(fn=>fn(state));},
    saved:async()=>{const dir=join(directory,'native-recordings');return Promise.all((await readdir(dir)).filter(n=>n.endsWith('.sqlite')).map(n=>readFile(join(dir,n))));}};
}

const privateConsent=()=>({modality:'in_person',participant_regions:['US-NY'],method:'verbal_attestation',all_parties_consented:true,granted_at:new Date(Date.now()-1000).toISOString(),language:'en-US'});
it('private microphone admission excludes clinical open and requires exact physical-source release',async()=>{
  const f=await fixture(),requestId=crypto.randomUUID(),recordingId=crypto.randomUUID();
  const command={requestId,recordingId,revision,consent:privateConsent()};
  expect(f.host().allowsRendererMicrophone()).toBe(false);
  const permit=await f.privateInvoke('cosmas:private-capture:acquire:v1',command) as {permitId:string};
  expect(f.host().allowsRendererMicrophone()).toBe(true);expect(f.calls).toEqual([]);expect(f.start).not.toHaveBeenCalled();
  expect(await f.privateInvoke('cosmas:private-capture:acquire:v1',command)).toEqual(permit);
  await expect(f.privateInvoke('cosmas:private-capture:acquire:v1',{...command,recordingId:crypto.randomUUID()})).rejects.toThrow();
  await expect(f.open()).rejects.toThrow();
  await expect(f.privateInvoke('cosmas:private-capture:release:v1',{requestId:crypto.randomUUID(),permitId:crypto.randomUUID()})).rejects.toThrow();
  const release={requestId:crypto.randomUUID(),permitId:permit.permitId};await f.privateInvoke('cosmas:private-capture:release:v1',release);
  await f.privateInvoke('cosmas:private-capture:release:v1',release);expect(f.host().allowsRendererMicrophone()).toBe(false);
  await f.open();await expect(f.privateInvoke('cosmas:private-capture:acquire:v1',{...command,requestId:crypto.randomUUID()})).rejects.toThrow();
  expect(f.host().allowsRendererMicrophone()).toBe(false); // Native meeting does not grant renderer audio.
});
it('unknown native journal and authentication loss never establish microphone admission',async()=>{
  const f=await fixture(),command={requestId:crypto.randomUUID(),recordingId:crypto.randomUUID(),revision,consent:privateConsent()};
  f.sourceRequest.mockRejectedValueOnce(Error('Unknown native journal'));
  await expect(f.privateInvoke('cosmas:private-capture:acquire:v1',command)).rejects.toThrow();expect(f.host().allowsRendererMicrophone()).toBe(false);
  const permit=await f.privateInvoke('cosmas:private-capture:acquire:v1',{...command,requestId:crypto.randomUUID()}) as {permitId:string};f.loseAuth();expect(f.host().allowsRendererMicrophone()).toBe(false);
  expect(f.messages).toContainEqual({permitId:permit.permitId});
  await expect(f.host().close()).rejects.toThrow();
  await f.privateInvoke('cosmas:private-capture:release:v1',{requestId:crypto.randomUUID(),permitId:permit.permitId});
});
it('configured browser microphone obtains native authority and retains exact stop custody on a lost reply',async()=>{
  const f=await fixture(),command={requestId:crypto.randomUUID(),revision,workspaceId,sessionId:f.sessionId,leaseId:crypto.randomUUID(),leaseReceiptId:crypto.randomUUID(),leaseGeneration:1,captureAuthorizedUntil:new Date(Date.now()+90000).toISOString(),firstSequenceNumber:0};
  const permit=await f.privateInvoke('cosmas:clinical-microphone:acquire:v1',command) as {permitId:string;admitted:boolean};
  expect(permit.admitted).toBe(true);expect(f.host().allowsRendererMicrophone()).toBe(true);expect(f.selectWindow).not.toHaveBeenCalled();expect(f.start).not.toHaveBeenCalled();
  await f.privateInvoke('cosmas:clinical-microphone:active:v1',{requestId:crypto.randomUUID(),permitId:permit.permitId});
  expect(JSON.stringify(permit)).not.toMatch(/secret|capability|grant|processFence/);await expect(f.open()).rejects.toThrow();
  f.markBrowserStopped();f.denyStop(true);const release={requestId:crypto.randomUUID(),permitId:permit.permitId};
  await expect(f.privateInvoke('cosmas:clinical-microphone:release:v1',release)).rejects.toThrow();expect(f.host().allowsRendererMicrophone()).toBe(false);
  f.denyStop(false);await f.privateInvoke('cosmas:clinical-microphone:release:v1',release);expect(f.sourceRequest.mock.calls.filter(c=>c[0]==='sourceStopped')).toHaveLength(2);
});
it('a clinical browser permit whose native Start deadline elapsed denies media before and after the active acknowledgment',async()=>{
  vi.useFakeTimers({toFake:['Date']});vi.setSystemTime(new Date());
  const f=await fixture(),command={requestId:crypto.randomUUID(),revision,workspaceId,sessionId:f.sessionId,leaseId:crypto.randomUUID(),leaseReceiptId:crypto.randomUUID(),leaseGeneration:1,captureAuthorizedUntil:new Date(Date.now()+90000).toISOString(),firstSequenceNumber:0};
  const permit=await f.privateInvoke('cosmas:clinical-microphone:acquire:v1',command) as {permitId:string};expect(f.host().allowsRendererMicrophone()).toBe(true);
  vi.setSystemTime(Date.now()+16000);expect(f.host().allowsRendererMicrophone()).toBe(false);
  await expect(f.privateInvoke('cosmas:clinical-microphone:active:v1',{requestId:crypto.randomUUID(),permitId:permit.permitId})).rejects.toThrow();
  f.markBrowserStopped();await f.privateInvoke('cosmas:clinical-microphone:release:v1',{requestId:crypto.randomUUID(),permitId:permit.permitId});
});

it('runs the combined desktop recording controls, explicit continuation and saved upload recovery',async()=>{
  const f=await fixture();await f.open();const view=await f.view();
  expect(f.start).not.toHaveBeenCalled();expect(f.selectWindow).not.toHaveBeenCalled();
  await view.controller.startRecording();await f.emit();await f.emit();
  expect(view.controller.snapshot.recordedChunks).toBe(2);
  await view.controller.pauseRecording!();expect(f.indicator.current()?.visible).toBe(false);
  await view.controller.resumeRecording!();expect(f.start).toHaveBeenCalledTimes(1);
  await view.controller.startRecording();await f.emit();await view.controller.pauseRecording!();
  const key=f.calls.find(c=>c.kind==='bind_key');expect(f.calls.filter(c=>c.kind==='bind_key')).toHaveLength(1);
  expect(f.calls.filter(c=>c.kind==='renew_lease')).toHaveLength(1);
  // Reopen the actual encrypted SQLite journal in a new main host.
  await f.reopen();await f.open();const restored=await f.view();
  expect(restored.controller.snapshot.recordedChunks).toBe(3);expect(f.start).toHaveBeenCalledTimes(2);
  await restored.controller.stopRecording();expect(restored.controller.snapshot.state).toBe('processing');
  expect(f.calls.filter(c=>c.kind==='bind_key')).toEqual([key]);
  expect(f.calls.filter(c=>c.kind==='complete')).toHaveLength(1);
  expect(JSON.stringify(f.messages)).not.toMatch(/invented-private-start-capability|wrapped_dek|pcmBytes|windowID|helperPath|processFence/);
  for(const data of await f.saved())expect(data.includes(Buffer.alloc(64,17))).toBe(false);
});

it('requests first-install permissions only from the explicit action and still waits for Start',async()=>{
  const f=await fixture();f.availability.mockResolvedValue(false);await f.open();const view=await f.view();
  expect(view.controller.snapshot.desktop?.phase).toBe('permission_required');
  expect(f.permissions).not.toHaveBeenCalled();expect(f.sourceRequest).not.toHaveBeenCalled();
  await view.controller.refreshPermissions!();expect(f.permissions).toHaveBeenCalledTimes(1);
  expect(view.controller.snapshot.desktop?.phase).toBe('ready');expect(f.start).not.toHaveBeenCalled();
  await view.controller.startRecording();await f.emit();expect(f.start).toHaveBeenCalledTimes(1);
});

it('records the full one-hour desktop limit against the standard API with one source and encrypted audio',async()=>{
  const finish=vi.spyOn(DesktopProviderRecorder.prototype,'stopRecording');
  vi.useFakeTimers({toFake:['Date']});vi.setSystemTime(new Date());
  const f=await fixture();await f.open();const view=await f.view();
  expect(f.calls.some(c=>c.kind==='select_capture_profile'||c.kind==='capture_profile')).toBe(false);
  await view.controller.startRecording();
  for(let i=0;i<360;i++){
    vi.setSystemTime(Date.now()+10_000);await f.emit();
    if([83,168,253,338].includes(i))await vi.waitFor(()=>expect(f.extensions).toHaveLength([83,168,253,338].indexOf(i)+1));
    if((i+1)%90===0)console.info('Synthetic desktop hour: encrypted chunks',i+1);
  }
  expect(view.controller.snapshot.recordedChunks).toBe(360);expect(f.start).toHaveBeenCalledOnce();
  expect(f.extensions.map(e=>e.leaseGeneration)).toEqual([2,3,4,5]);
  expect(f.extensions.at(-1)?.maximumChunks).toBe(360);
  expect(view.controller.snapshot.remainingBudgetSeconds).toBe(0);
  console.info('Synthetic desktop hour: completing upload');
  try {await view.controller.stopRecording();} catch(error) {
    await finish.mock.results.at(-1)?.value;throw error;
  }
  expect(view.controller.snapshot.state).toBe('processing');
  expect(f.calls.filter(c=>c.kind==='renew_lease')).toHaveLength(4);
  expect(f.calls.filter(c=>c.kind==='complete')).toHaveLength(1);
  expect(JSON.stringify(f.messages)).not.toMatch(/leaseReceiptId|reservationBatchId|runId|pcmBytes|processFence/);
},120_000);

it('retains the same native stop owner when quitting loses its stop response',async()=>{
  const f=await fixture();await f.open();const view=await f.view();await view.controller.startRecording();await f.emit();
  f.denyStop(true);await expect(f.host().close()).rejects.toThrow();expect(f.dispose).not.toHaveBeenCalled();
  const original=f.sourceRequest.mock.calls.filter(c=>c[0]==='sourceStopped').at(-1)![1];
  f.denyStop(false);await f.host().close();expect(f.dispose).toHaveBeenCalledTimes(1);
  expect(f.sourceRequest.mock.calls.filter(c=>c[0]==='sourceStopped').at(-1)![1]).toEqual(original);
  expect(f.calls.filter(c=>c.kind==='complete')).toHaveLength(0);
});
