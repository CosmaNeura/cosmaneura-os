/**
 * Panel persist/relaunch contract against the real saved-recording runtime.
 * Hole 1: import must never delete transfer:<recordingId> (breaks CAS persist).
 */
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import type {ActiveCaptureState} from '../../clients/capture/src/configured/flow/types';
import {base64UrlEncode,encodeChunkAdditionalDataBase64Url,encodeEnvelope} from '../../clients/capture/protocol/generated';
import {
  attachEncryptedEnvelope,
  createReservedRecord,
  markRegistered,
  markUploaded,
  markUploading,
} from '../../clients/capture/src/queue/records';
import {EncryptedIndexedDbQueueStorage} from '../../clients/capture/src/storage/encrypted-indexeddb';
import {workspaceCaptureBff} from './capture-api';
import {captureQueueDatabaseName} from './capture-storage';
import {
  clearTransferRetentionReleased,
  isAudioRetentionProtected,
  isTransferRetentionReleased,
  openPrivateRecordingStore,
  transferRetentionReleasedKey,
  type PrivateRecordingRuntime,
  type PrivateRecordingStore,
} from './private-recording-runtime';
import {importSavedChunks,openSavedRecordingRuntime,PROVEN_COMPLETE_REVIEW_STATUSES,savedRecordingImportQueueDatabaseName,savedRecordingImportStoreNames} from './saved-recording-runtime';
import type {PreparedCapture} from './capture-api';
import {persistSavedRecordingTransfer} from './SavedRecordingTranscriptionPanel';
import type {SavedRecordingEntry} from './session/recording-model';
import type {SavedRecordingSource} from './saved-recording-source';

const review=vi.hoisted(()=>({read:vi.fn()}));
const native=vi.hoisted(()=>({list:vi.fn(),get:vi.fn(),create:vi.fn(),compareAndSwap:vi.fn()}));
vi.mock('./capture-api',()=>({workspaceCaptureBff:vi.fn()}));
vi.mock('./creator-review-api',()=>({creatorReviewApi:()=>({read:review.read})}));
vi.mock('../../clients/capture/plugins/secure-queue',()=>({SecureQueue:native}));

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const workspaceId='30000000-0000-4000-8000-000000000001';
const sessionId='30000000-0000-4000-8000-000000000002';
const recordingId=sessionId;
const scope='a'.repeat(64);
const chunks=3;
const admitted:PreparedCapture={status:'prepared',workspace_id:workspaceId,session_id:sessionId,
  consent_record_id:'30000000-0000-4000-8000-000000000003',configured_capture:{schema_version:'1.0',language_mode:'en-US'}};

/** Pre-PR transfer shape (v1) — no release marker, closed key set. */
function legacyTransfer(patch:Record<string,unknown>={}){
  return {
    contract:'cosmas.saved-transfer.v1' as const,
    recording_id:recordingId,
    workspace_id:workspaceId,
    scope,
    link_request:null,
    receipt:null,
    admission:null,
    admitted:null,
    ...patch,
  };
}

function active(patch:Partial<ActiveCaptureState>={}):ActiveCaptureState{
  return {schemaVersion:2,reviewAfterUpload:true,sessionId,
    lease:{protocol_version:'1.0',receipt_id:'30000000-0000-4000-8000-000000000004',lease_id:'30000000-0000-4000-8000-000000000005',
      session_id:sessionId,generation:1,issued_at:'2026-10-09T12:00:00Z',expires_at:'2026-10-09T12:15:00Z'},
    captureAuthorizedUntil:null,aggregatePlaintextBudgetBytes:67108864,phase:'processing',completeIdempotencyKey:'synthetic-completion-key',
    recordedChunks:chunks,recordedPlaintextBytes:736132,startedAt:'2026-10-09T12:00:00Z',...patch};
}

const importStores=()=>savedRecordingImportStoreNames({scope,workspaceId,sessionId});
async function seedFlow(value:ActiveCaptureState){
  const store=await EncryptedIndexedDbFlowStore.open({databaseName:importStores().flow});
  try{await store.putActiveCaptureState(value);}finally{store.close();}
}

const entry:SavedRecordingEntry={recordingId,scope,platform:'desktop'};

async function relaunchResume(store:PrivateRecordingStore){
  return store.read('transfer:'+recordingId);
}

let held=false;
beforeEach(()=>{
  vi.clearAllMocks();held=false;
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('indexedDB',new IDBFactory());
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  vi.stubGlobal('navigator',{locks:{request:async(_name:string,_options:unknown,callback:(lock:unknown)=>Promise<void>)=>{
    if(held)return callback(null);held=true;try{await callback({name:'synthetic capture lock',mode:'exclusive'});}finally{held=false;}
  }}});
  vi.stubGlobal('fetch',vi.fn().mockRejectedValue(Error('Unexpected synthetic transport')));
  vi.stubEnv('VITE_CAPTURE_UPLOAD_ORIGINS','https://synthetic-upload.example.invalid');
  review.read.mockResolvedValue({status:'uploaded'});
  native.list.mockResolvedValue({keys:[]});
  for(const method of [native.get,native.create,native.compareAndSwap])method.mockRejectedValue(Error('Unexpected native audio mutation'));
  const bff=Object.fromEntries(['getCapabilities','getAudioEncryptionKey','createConsent','createSession','issueLease','bindAudioKey',
    'reserveChunks','reserveContinuationChunks','completeCapture','getTranscriptionStatus','getTranscript','renewCaptureLease','selectCaptureProfile']
    .map(name=>[name,vi.fn().mockRejectedValue(Error('Unexpected capture operation'))]));
  vi.mocked(workspaceCaptureBff).mockReturnValue(bff as never);
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});

function sealedRecording(savedChunks:PrivateRecordingRuntime['savedChunks']):PrivateRecordingRuntime{
  const ended='2026-10-09T12:00:00.000Z';
  return {
    snapshot:{recordingId,phase:'sealed',endedAt:ended,createdAt:ended,recordedChunks:chunks,workspaceId},
    snapshotForLedger:async()=>({recordingId,scope,consent:{modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:ended,language:'en-US'},consentIntervals:[],startedAt:ended,phase:'sealed',frames:16,chunks,manifestSHA256:'a'.repeat(64),updatedAt:ended}),
    savedChunks,
  } as unknown as PrivateRecordingRuntime;
}

const retentionOn={enabled:true,enabledAt:'2026-10-01T00:00:00.000Z',serverNow:'2026-10-09T12:00:00.000Z',fetchedAtDeviceMs:Date.parse('2026-10-09T12:00:00.000Z')};

/** Seed one registered row into the session-scoped import queue (exact confirmed count = 1). */
async function seedConfirmedImportRow(){
  const objectId='30000000-0000-4000-8000-000000000099';
  const storage=await EncryptedIndexedDbQueueStorage.open({databaseName:captureQueueDatabaseName(sessionId)});
  try{
    const reserved=createReservedRecord({
      protocolVersion:'1.0',objectId,sessionId,channel:'microphone',sequenceNumber:0,
      createdAt:'2026-10-09T12:00:00.000Z',
      additionalAuthenticatedData:encodeChunkAdditionalDataBase64Url({
        tenantId:sessionId,sessionId,objectId,channel:'microphone',sequenceNumber:0,
      }),
    },{reservation:'synthetic-reservation',uploadAuthorization:'synthetic-upload',uploadAuthorizationGeneration:1,registration:'synthetic-registration'});
    expect(await storage.create(reserved)).toBe(true);
    const envelope=encodeEnvelope({
      schema_version:'1.0',content_encryption:'A256GCM',
      nonce:base64UrlEncode(new Uint8Array(12).fill(1)),media_type:'audio/wav',
    },new Uint8Array(16).fill(2));
    const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',envelope as BufferSource)),
      b=>b.toString(16).padStart(2,'0')).join('');
    const encrypted=attachEncryptedEnvelope(reserved,envelope,sha256);
    expect(await storage.compareAndSwap(objectId,1,encrypted)).toBe(true);
    const uploading=markUploading(encrypted);
    expect(await storage.compareAndSwap(objectId,2,uploading)).toBe(true);
    const uploaded=markUploaded(uploading);
    expect(await storage.compareAndSwap(objectId,3,uploaded)).toBe(true);
    const registered=markRegistered(uploaded,{chunkId:objectId,sha256,byteLength:envelope.byteLength,registeredAt:'2026-10-09T12:01:00.000Z'});
    expect(await storage.compareAndSwap(objectId,4,registered)).toBe(true);
  }finally{storage.close();}
}

it('panel persist and relaunch-resume work after successful import (real runtime; transfer: kept)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer();
  await store.write('transfer:'+recordingId,null,prior);
  await seedFlow(active());
  const recording=sealedRecording(vi.fn(async function*(){throw Error('confirmed upload must not read audio');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  // Confirmed-upload processing proof: transcribe completes without reading chunk bytes.
  await opened.transcribe();
  await opened.close();
  // Transfer row must still exist for panel CAS; release marker ends sweep protection only.
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(true);
  expect(await isAudioRetentionProtected(store,recordingId)).toBe(false);
  // Real panel persist path (validate + CAS). Keep a valid empty v1 shape (no partial admitted).
  const next=legacyTransfer();
  await persistSavedRecordingTransfer(store,entry,workspaceId,prior,next);
  expect(await relaunchResume(store)).toEqual(next);
  store.close();
  const relaunched=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  expect(await relaunchResume(relaunched)).toEqual(next);
  relaunched.close();
});

it('panel persist and relaunch-resume work after failed import (real runtime; transfer: kept)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer();
  await store.write('transfer:'+recordingId,null,prior);
  await seedFlow(active());
  let current=true;
  const recording=sealedRecording(vi.fn(async function*(){throw Error('must not read audio on failed import');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>current,store,audioRetention:retentionOn});
  // Restored processing is proven completion → release marker at open; transfer: row stays for CAS.
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(true);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  // Sticky-rejection guard: after .finally clears task, a later call runs fresh (succeeds once current).
  current=false;
  await expect(opened.transcribe()).rejects.toMatchObject({code:'capture_access_unavailable'});
  current=true;
  await opened.transcribe();
  await opened.close();
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  const next=legacyTransfer();
  await persistSavedRecordingTransfer(store,entry,workspaceId,prior,next);
  expect(await relaunchResume(store)).toEqual(next);
  store.close();
});

it('pre-PR legacy transfer shape survives restored processing import and panel persist/resume',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  // Old shape: transfer: row only — no transfer-retention-released: key exists yet.
  // Store may hold legacy receipt-shaped rows; persist path validates closed v1 without partial receipt.
  const prior=legacyTransfer();
  await store.write('transfer:'+recordingId,null,prior);
  expect(await store.read(transferRetentionReleasedKey(recordingId))).toBeNull();
  await seedFlow(active()); // restored processing path (not reviewOnly)
  const recording=sealedRecording(vi.fn(async function*(){throw Error('processing path must not read audio');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  expect(opened.reviewOnly).toBe(false);
  await opened.transcribe();
  await opened.close();
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  const next=legacyTransfer();
  await persistSavedRecordingTransfer(store,entry,workspaceId,prior,next);
  expect(await relaunchResume(store)).toEqual(next);
  store.close();
});

it('with retention policy off, web panel/runtime deletes nothing on transfer:',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer();
  await store.write('transfer:'+recordingId,null,prior);
  const deleted:string[]=[];
  const realDelete=store.delete.bind(store);
  store.delete=async(key:string)=>{deleted.push(key);return realDelete(key);};
  await seedFlow(active()); // restored processing path (not reviewOnly)
  const recording=sealedRecording(vi.fn(async function*(){throw Error('processing path must not read audio');}));
  // Absent / off policy — live users tonight.
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:{enabled:false}});
  expect(opened.reviewOnly).toBe(false);
  await opened.transcribe();
  await opened.close();
  expect(deleted.filter(k=>k.startsWith('transfer:'))).toEqual([]);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
  expect(await store.read(transferRetentionReleasedKey(recordingId))).toBeNull();
  const next=legacyTransfer();
  await persistSavedRecordingTransfer(store,entry,workspaceId,prior,next);
  expect(await relaunchResume(store)).toEqual(next);
  store.close();
});

it('true reviewOnly branch releases protection without reading chunks',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer({admitted});
  await store.write('transfer:'+recordingId,null,prior);
  // No seeded flow → restore fails; review status uploaded → reviewOnly=true.
  review.read.mockResolvedValue({status:'uploaded'});
  const recording=sealedRecording(vi.fn(async function*(){throw Error('reviewOnly must not read audio');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  expect(opened.reviewOnly).toBe(true);
  await opened.transcribe();
  await opened.close();
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(true);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  store.close();
});

it('mid-upload importSavedChunks failure pauses and rethrows without completing',async()=>{
  let recorded=0;
  const controller={
    get snapshot(){return {state:recorded>=chunks?'paused':'recording',recordedChunks:recorded,sessionId};},
    startRecording:async()=>{},
    pauseRecording:async()=>{},
    prepareContinuation:async()=>{},
    stopRecording:async()=>{throw new Error('stop must not run after mid-feed failure');},
    resumePendingWork:async()=>{throw new Error('resume must not run');},
  };
  const source={feed:async(first:number)=>{
    if(first===0){recorded=1;return 1;}
    throw Object.assign(new Error('Synthetic mid-upload failure'),{code:'capture_chunk_position_conflict'});
  }} as unknown as SavedRecordingSource;
  await expect(importSavedChunks(controller as never,source,chunks,()=>true))
    .rejects.toMatchObject({code:'capture_chunk_position_conflict'});
  expect(recorded).toBe(1);
});

it('clearTransferRetentionReleased restores protection for renew-consent re-import',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer({admitted});
  await store.write('transfer:'+recordingId,null,prior);
  const {markTransferRetentionReleased}=await import('./private-recording-runtime');
  await markTransferRetentionReleased(store,recordingId,'2026-10-09T12:00:00.000Z');
  expect(await isAudioRetentionProtected(store,recordingId)).toBe(false);
  await clearTransferRetentionReleased(store,recordingId);
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
  expect(await isAudioRetentionProtected(store,recordingId)).toBe(true);
  store.close();
});

it('releaseUploadedCapture deletes session import-queue DB only when retention is effective',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  await store.write('transfer:'+recordingId,null,legacyTransfer({admitted}));
  await seedFlow(active());
  const recording=sealedRecording(vi.fn(async function*(){throw Error('confirmed upload must not read audio');}));
  const deleteSpy=vi.spyOn(indexedDB,'deleteDatabase');
  const on=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  await on.releaseUploadedCapture();
  expect(deleteSpy).toHaveBeenCalledWith(savedRecordingImportQueueDatabaseName(sessionId));
  await on.close();
  store.close();
});

it('second releaseUploadedCapture with retention on returns early; close skips deactivate',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  await store.write('transfer:'+recordingId,null,legacyTransfer({admitted}));
  await seedFlow(active());
  const recording=sealedRecording(vi.fn(async function*(){throw Error('confirmed upload must not read audio');}));
  const on=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  const releaseSpy=vi.spyOn(on.controller,'releaseUploadedCapture');
  const deactivateSpy=vi.spyOn(on.controller,'deactivate');
  await on.releaseUploadedCapture();
  expect(releaseSpy).toHaveBeenCalledTimes(1);
  await on.releaseUploadedCapture(); // second Continue — must not touch closed storage
  expect(releaseSpy).toHaveBeenCalledTimes(1);
  await on.close();
  expect(deactivateSpy).not.toHaveBeenCalled();
  store.close();
});

it('concurrent releaseUploadedCapture runs once and closes the import queue once',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  await store.write('transfer:'+recordingId,null,legacyTransfer({admitted}));
  await seedFlow(active());
  const recording=sealedRecording(vi.fn(async function*(){throw Error('confirmed upload must not read audio');}));
  const on=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  let finish!:()=>void;
  const releaseSpy=vi.spyOn(on.controller,'releaseUploadedCapture').mockImplementation(
    ()=>new Promise<void>(resolve=>{finish=()=>resolve();}));
  const deleteSpy=vi.spyOn(indexedDB,'deleteDatabase');
  const first=on.releaseUploadedCapture();
  const second=on.releaseUploadedCapture();
  await Promise.resolve();
  expect(releaseSpy).toHaveBeenCalledTimes(1);
  finish();
  await Promise.all([first,second]);
  expect(releaseSpy).toHaveBeenCalledTimes(1);
  expect(deleteSpy).toHaveBeenCalledTimes(1);
  expect(deleteSpy).toHaveBeenCalledWith(savedRecordingImportQueueDatabaseName(sessionId));
  await on.close();
  store.close();
});

it('with retention off, releaseUploadedCapture matches main (queue stays; real uploadProgress after release/re-release/close/reopen)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  await store.write('transfer:'+recordingId,null,legacyTransfer({admitted}));
  await seedFlow(active());
  await seedConfirmedImportRow(); // real registered row — uploadProgress must read exact count 1
  const recording=sealedRecording(vi.fn(async function*(){throw Error('confirmed upload must not read audio');}));
  const deleteSpy=vi.spyOn(indexedDB,'deleteDatabase');
  const first=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:{enabled:false}});
  await first.releaseUploadedCapture();
  await first.releaseUploadedCapture(); // second Continue after Return — must not hit closed storage
  expect(deleteSpy).not.toHaveBeenCalled();
  const progress=await first.uploadProgress();
  expect(progress).toEqual({confirmed:1,total:chunks,reference:null});
  await first.close();
  // Reopen after close — same off-path contract; confirmed row persists (queue DB not dropped).
  await seedFlow(active());
  const second=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:{enabled:false}});
  await second.releaseUploadedCapture();
  const again=await second.uploadProgress();
  expect(again).toEqual({confirmed:1,total:chunks,reference:null});
  expect(deleteSpy).not.toHaveBeenCalled();
  await second.close();
  store.close();
});

it.each(['failed','cancelled'] as const)('with retention off, %s opens reviewOnly without releasing',async status=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer({admitted});
  await store.write('transfer:'+recordingId,null,prior);
  review.read.mockResolvedValue({status});
  const recording=sealedRecording(vi.fn(async function*(){throw Error(status+' must not read audio');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:{enabled:false}});
  expect(opened.reviewOnly).toBe(true);
  await opened.transcribe(); // reviewOnly + not provenComplete → no release
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
  expect(await isAudioRetentionProtected(store,recordingId)).toBe(true);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  await opened.close();
  store.close();
});

it.each([...PROVEN_COMPLETE_REVIEW_STATUSES])('allowlisted status %s opens reviewOnly and releases at open',async status=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer({admitted});
  await store.write('transfer:'+recordingId,null,prior);
  review.read.mockResolvedValue({status});
  const recording=sealedRecording(vi.fn(async function*(){throw Error(status+' must not read audio');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  expect(opened.reviewOnly).toBe(true);
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(true);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  await opened.close();
  store.close();
});

it('failed/cancelled/unknown with retention on open reviewOnly but do not release at open',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer({admitted});
  await store.write('transfer:'+recordingId,null,prior);
  const recording=sealedRecording(vi.fn(async function*(){throw Error('failed status must not read audio');}));
  for(const status of ['failed','cancelled','unknown_status'] as const){
    review.read.mockResolvedValue({status});
    const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
      scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
    expect(opened.reviewOnly).toBe(true);
    await opened.transcribe();
    expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
    expect(await isAudioRetentionProtected(store,recordingId)).toBe(true);
    await opened.close();
  }
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  store.close();
});

it('admitted transfer mid-upload (no proven completion) does not release; stays protected past deadline',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  const prior=legacyTransfer({admitted});
  await store.write('transfer:'+recordingId,null,prior);
  // Partial / in-flight: restore fails; capturing status blocks reviewOnly — open throws before any release.
  review.read.mockResolvedValue({status:'capturing'});
  const recording=sealedRecording(vi.fn(async function*(){throw Error('partial must not read audio');}));
  const pastDeadline=()=>Date.parse('2026-10-09T12:00:00.000Z')+48*60*60*1000;
  await expect(openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn,now:pastDeadline}))
    .rejects.toMatchObject({code:'capture_saved_session_changed'});
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
  expect(await isAudioRetentionProtected(store,recordingId)).toBe(true);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  store.close();
});
