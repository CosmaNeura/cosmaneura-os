import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import type {ActiveCaptureState} from '../../clients/capture/src/configured/flow/types';
import {openSavedRecordingRuntime,savedRecordingImportStoreNames} from './saved-recording-runtime';
import {workspaceCaptureBff} from './capture-api';
import type {PrivateRecordingRuntime} from './private-recording-runtime';
import type {PreparedCapture} from './capture-api';

const review=vi.hoisted(()=>({read:vi.fn()}));
const native=vi.hoisted(()=>({list:vi.fn(),get:vi.fn(),create:vi.fn(),compareAndSwap:vi.fn()}));
vi.mock('./capture-api',()=>({workspaceCaptureBff:vi.fn()}));
vi.mock('./creator-review-api',()=>({creatorReviewApi:()=>({read:review.read})}));
vi.mock('../../clients/capture/plugins/secure-queue',()=>({SecureQueue:native}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const workspaceId='20000000-0000-4000-8000-000000000001',sessionId='20000000-0000-4000-8000-000000000002';
const scope='c'.repeat(64),chunks=3;
const admitted:PreparedCapture={status:'prepared',workspace_id:workspaceId,session_id:sessionId,
  consent_record_id:'20000000-0000-4000-8000-000000000003',configured_capture:{schema_version:'1.0',language_mode:'en-US'}};
let held=false,releases=0;
const importStores=()=>savedRecordingImportStoreNames({scope,workspaceId,sessionId});
const flow=()=>EncryptedIndexedDbFlowStore.open({databaseName:importStores().flow});
beforeEach(()=>{
  vi.clearAllMocks();held=false;releases=0;
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('indexedDB',new IDBFactory());
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  vi.stubGlobal('navigator',{locks:{request:async(_name:string,_options:unknown,callback:(lock:unknown)=>Promise<void>)=>{
    if(held)return callback(null);held=true;try{await callback({name:'synthetic capture lock',mode:'exclusive'});}finally{held=false;releases++;}
  }}});
  vi.stubGlobal('fetch',vi.fn().mockRejectedValue(Error('Unexpected synthetic transport')));
  vi.stubEnv('VITE_CAPTURE_UPLOAD_ORIGINS','https://synthetic-upload.example.invalid');
  review.read.mockResolvedValue({status:'uploaded'});native.list.mockResolvedValue({keys:[]});
  for(const method of [native.get,native.create,native.compareAndSwap])method.mockRejectedValue(Error('Unexpected native audio mutation'));
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
function active(patch:Partial<ActiveCaptureState>={}):ActiveCaptureState{
  return {schemaVersion:2,reviewAfterUpload:true,sessionId,
    lease:{protocol_version:'1.0',receipt_id:'20000000-0000-4000-8000-000000000004',lease_id:'20000000-0000-4000-8000-000000000005',
      session_id:sessionId,generation:1,issued_at:'2026-10-09T12:00:00Z',expires_at:'2026-10-09T12:15:00Z'},
    captureAuthorizedUntil:null,aggregatePlaintextBudgetBytes:67108864,phase:'processing',completeIdempotencyKey:'synthetic-completion-key',
    recordedChunks:chunks,recordedPlaintextBytes:736132,startedAt:'2026-10-09T12:00:00Z',...patch};
}
async function seed(value:ActiveCaptureState){const store=await flow();try{await store.putActiveCaptureState(value);}finally{store.close();}}
async function retained(){const store=await flow();try{return await store.getActiveCaptureState();}finally{store.close();}}
function fixture(platform:'desktop'|'ios'='desktop'){
  const bff=Object.fromEntries(['getCapabilities','getAudioEncryptionKey','createConsent','createSession','issueLease','bindAudioKey',
    'reserveChunks','reserveContinuationChunks','completeCapture','getTranscriptionStatus','getTranscript','renewCaptureLease','selectCaptureProfile']
    .map(name=>[name,vi.fn().mockRejectedValue(Error('Unexpected capture operation'))]));
  vi.mocked(workspaceCaptureBff).mockReturnValue(bff as never);
  const audio=[new Uint8Array([1,2]),new Uint8Array([3,4]),new Uint8Array([5,6])];
  const savedChunks=vi.fn(async function*(){for(const wavBytes of audio)yield {wavBytes};});
  const recording={savedChunks} as unknown as PrivateRecordingRuntime;
  let current=true;
  const open=()=>openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform,isCurrent:()=>current});
  return {bff,audio,savedChunks,open,retire:()=>{current=false;}};
}
function noCaptureWork(f:ReturnType<typeof fixture>){
  for(const method of Object.values(f.bff))expect(method).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();expect(f.savedChunks).not.toHaveBeenCalled();
  for(const method of [native.get,native.create,native.compareAndSwap])expect(method).not.toHaveBeenCalled();
}

it.each(['desktop','ios'] as const)('reopens the same encrypted confirmed upload after review fails on %s without resending or deleting audio',async platform=>{
  const proof=active();await seed(proof);const f=fixture(platform),original=f.audio.map(row=>row.slice());
  const first=await f.open();await first.close();expect(held).toBe(false);
  review.read.mockRejectedValue(Error('Synthetic review currently unavailable'));
  const reopened=await f.open();
  try{
    expect(reopened.controller.snapshot).toMatchObject({state:'processing',sessionId,recordedChunks:chunks});
    expect(held).toBe(true);await reopened.transcribe();await reopened.transcribe();
    expect(review.read).not.toHaveBeenCalled();noCaptureWork(f);
    expect(await retained()).toEqual(proof);expect(f.audio).toEqual(original);
  }finally{await reopened.close();}
  expect(held).toBe(false);expect(releases).toBe(2);expect(await retained()).toEqual(proof);
});

it.each(['ready','recording','paused','uploading','completing'] as const)('keeps review-first admission and exact encrypted %s progress when review is unavailable',async phase=>{
  const proof=active({phase,recordedChunks:phase==='ready'?0:phase==='completing'?chunks:chunks-1,
    recordedPlaintextBytes:phase==='ready'?0:491564});
  await seed(proof);const f=fixture();review.read.mockRejectedValue(Error('Synthetic review currently unavailable'));
  await expect(f.open()).rejects.toThrow('Synthetic review currently unavailable');
  expect(review.read).toHaveBeenCalledOnce();noCaptureWork(f);expect(await retained()).toEqual(proof);
  expect(held).toBe(false);expect(releases).toBe(1);
});

it.each(['empty','preparing'] as const)('keeps the authenticated review gate for an %s session',async mode=>{
  let preparation:unknown=null;
  if(mode==='preparing'){
    preparation={schemaVersion:2,mode:'configured_core',sessionId,startedAt:'2026-10-09T12:00:00Z',
      completeIdempotencyKey:'synthetic-completion-key',leaseIdempotencyKey:null,leaseRequest:null};
    const store=await flow();try{await store.putPreparationState(preparation as never);}finally{store.close();}
  }
  const f=fixture();review.read.mockRejectedValue(Error('Synthetic review currently unavailable'));
  await expect(f.open()).rejects.toThrow('Synthetic review currently unavailable');expect(review.read).toHaveBeenCalledOnce();noCaptureWork(f);
  const store=await flow();try{expect(await store.getActiveCaptureState()).toBeNull();expect(await store.getPreparationState()).toEqual(preparation);}finally{store.close();}
  expect(held).toBe(false);expect(releases).toBe(1);
});

it.each(['session','chunks'] as const)('rejects a terminal %s proof mismatch rather than bypassing review or uploading',async mismatch=>{
  const other='20000000-0000-4000-8000-000000000006';const base=active();
  const proof=mismatch==='session'?active({sessionId:other,lease:{...base.lease,session_id:other}}):active({recordedChunks:chunks-1});
  await seed(proof);const f=fixture();
  await expect(f.open()).rejects.toThrow('capture_saved_session_changed');expect(review.read).not.toHaveBeenCalled();noCaptureWork(f);
  expect(await retained()).toEqual(proof);expect(held).toBe(false);expect(releases).toBe(1);
});

it('rejects retired owner access before restoring the terminal view and releases the capture lock',async()=>{
  const proof=active();await seed(proof);const f=fixture();f.retire();
  await expect(f.open()).rejects.toThrow('capture_access_unavailable');expect(review.read).not.toHaveBeenCalled();noCaptureWork(f);
  expect(await retained()).toEqual(proof);expect(held).toBe(false);expect(releases).toBe(1);
});

it('keeps review-first behavior for a legacy terminal record without configured upload confirmation',async()=>{
  const {reviewAfterUpload:_configured,...proof}=active();await seed(proof);const f=fixture();
  review.read.mockRejectedValue(Error('Synthetic review currently unavailable'));
  await expect(f.open()).rejects.toThrow('Synthetic review currently unavailable');expect(review.read).toHaveBeenCalledOnce();noCaptureWork(f);
  expect(await retained()).toEqual(proof);expect(held).toBe(false);expect(releases).toBe(1);
});

it('retains the existing controller policy rejection for an unsupported encrypted terminal schema',async()=>{
  const proof=active({schemaVersion:7});await seed(proof);const f=fixture();
  await expect(f.open()).rejects.toThrow('capture_policy_unavailable');expect(review.read).not.toHaveBeenCalled();noCaptureWork(f);
  expect(await retained()).toEqual(proof);expect(held).toBe(false);expect(releases).toBe(1);
});

it.each(['ready','uploading'] as const)('rejects a foreign retained %s session in this session namespace before any remote read',async phase=>{
  const other='20000000-0000-4000-8000-000000000006',base=active();
  const proof=active({phase,sessionId:other,lease:{...base.lease,session_id:other}});await seed(proof);const f=fixture();
  await expect(f.open()).rejects.toThrow('capture_saved_session_changed');expect(review.read).not.toHaveBeenCalled();noCaptureWork(f);
  expect(await retained()).toEqual(proof);expect(held).toBe(false);expect(releases).toBe(1);
});

it('refuses expired audio with a safe code and never reads chunk bytes',async()=>{
  const ended='2026-11-01T00:00:00.000Z';
  const recording={
    snapshot:{recordingId:sessionId,phase:'sealed',endedAt:ended,createdAt:ended},
    snapshotForLedger:async()=>({recordingId:sessionId,scope,consent:{modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:ended,language:'en-US'},consentIntervals:[],startedAt:ended,phase:'sealed',frames:16,chunks,manifestSHA256:'a'.repeat(64),updatedAt:ended}),
    savedChunks:vi.fn(async function*(){throw Error('audio bytes must not be read');}),
  } as unknown as PrivateRecordingRuntime;
  let current=true;
  await expect(openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>current,audioRetention:{enabled:true,enabledAt:'2026-10-01T00:00:00.000Z',serverNow:ended,fetchedAtDeviceMs:Date.parse(ended)},
    now:()=>Date.parse(ended)+48*60*60*1000})).rejects.toMatchObject({code:'private_recording_audio_expired'});
  expect(recording.savedChunks).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it('skips refuse while transfer key protects, then refuses after transfer key is removed',async()=>{
  const ended='2026-11-01T00:00:00.000Z';
  const recording={
    snapshot:{recordingId:sessionId,phase:'sealed',endedAt:ended,createdAt:ended},
    snapshotForLedger:async()=>({recordingId:sessionId,scope,consent:{modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:ended,language:'en-US'},consentIntervals:[],startedAt:ended,phase:'sealed',frames:16,chunks,manifestSHA256:'a'.repeat(64),updatedAt:ended}),
    savedChunks:vi.fn(async function*(){throw Error('audio bytes must not be read');}),
  } as unknown as PrivateRecordingRuntime;
  const keys=new Set<string>(['transfer:'+sessionId]);
  const store={
    keys:async()=>[...keys],
    read:async(key:string)=>keys.has(key)?{ok:true}:null,
    write:async()=>{},
    delete:async(key:string)=>{keys.delete(key);},
    close:()=>{},
  };
  const policy={enabled:true,enabledAt:'2026-10-01T00:00:00.000Z',serverNow:ended,fetchedAtDeviceMs:Date.parse(ended)};
  const now=()=>Date.parse(ended)+48*60*60*1000;
  // Protected by transfer: — refuse is skipped; open may succeed as review-only.
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,audioRetention:policy,now,store});
  expect(recording.savedChunks).not.toHaveBeenCalled();
  await opened.close();
  await store.delete('transfer:'+sessionId);
  await expect(openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,audioRetention:policy,now,store})).rejects.toMatchObject({code:'private_recording_audio_expired'});
});

it('saved-import store names include sessionId (session-scoped queue, not long-lived workspace queue)',()=>{
  const names=savedRecordingImportStoreNames({scope,workspaceId,sessionId});
  expect(names.flow).toContain(sessionId);
  expect(names.profile).toContain(sessionId);
  expect(names.flow).toBe(`cosmas-saved-flow:v1:${scope}:${workspaceId}:${sessionId}`);
  expect(names.profile).toBe(`cosmas-saved-profile:v1:${scope}:${workspaceId}:${sessionId}`);
  // Browser IndexedDB becomes cosmas-capture-queue:${sessionId} — not the visit workspace queue.
  expect(names.captureQueueOpenArgs.workspaceId).toBe(sessionId);
  expect(names.captureQueueOpenArgs.sessionId).toBe(sessionId);
  expect(names.captureQueueOpenArgs.workspaceId).not.toBe(workspaceId);
});
