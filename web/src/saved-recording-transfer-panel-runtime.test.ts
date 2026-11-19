/**
 * Panel persist/relaunch contract against the real saved-recording runtime.
 * Hole 1: import must never delete transfer:<recordingId> (breaks CAS persist).
 */
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import type {ActiveCaptureState} from '../../clients/capture/src/configured/flow/types';
import {workspaceCaptureBff} from './capture-api';
import {
  isAudioRetentionProtected,
  isTransferRetentionReleased,
  openPrivateRecordingStore,
  transferRetentionReleasedKey,
  type PrivateRecordingRuntime,
  type PrivateRecordingStore,
} from './private-recording-runtime';
import {openSavedRecordingRuntime,savedRecordingImportStoreNames} from './saved-recording-runtime';
import type {PreparedCapture} from './capture-api';

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

/** Same CAS write the panel's persist() uses (SavedRecordingTranscriptionPanel.tsx:213-214). */
async function panelPersist(store:PrivateRecordingStore,prior:unknown,next:unknown){
  await store.write('transfer:'+recordingId,prior,next);
}

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
  const next=legacyTransfer({admitted});
  await panelPersist(store,prior,next);
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
  // Owner retires mid-import → terminal failure before release marker; transfer: must remain.
  current=false;
  await expect(opened.transcribe()).rejects.toMatchObject({code:'capture_access_unavailable'});
  current=true;
  await opened.close();
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
  expect(await isAudioRetentionProtected(store,recordingId)).toBe(true);
  const next=legacyTransfer({admitted});
  await panelPersist(store,prior,next);
  expect(await relaunchResume(store)).toEqual(next);
  store.close();
});

it('pre-PR legacy transfer shape survives import and still supports panel persist/resume',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:indexedDB as IDBFactory,crypto:webcrypto});
  // Old shape: transfer: row only — no transfer-retention-released: key exists yet.
  const prior=legacyTransfer({receipt:{local_recording_id:recordingId,state:'linked_metadata'}});
  await store.write('transfer:'+recordingId,null,prior);
  expect(await store.read(transferRetentionReleasedKey(recordingId))).toBeNull();
  await seedFlow(active());
  const recording=sealedRecording(vi.fn(async function*(){throw Error('review-only must not read audio');}));
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:retentionOn});
  await opened.transcribe();
  await opened.close();
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  const next=legacyTransfer({receipt:prior.receipt,admitted});
  await panelPersist(store,prior,next);
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
  await seedFlow(active());
  const recording=sealedRecording(vi.fn(async function*(){throw Error('review-only must not read audio');}));
  // Absent / off policy — live users tonight.
  const opened=await openSavedRecordingRuntime({workspaceId,admitted,identity:{mode:'clerk_jwt',getToken:async()=>null},
    scope,recording,chunks,platform:'desktop',isCurrent:()=>true,store,audioRetention:{enabled:false}});
  await opened.transcribe();
  await opened.close();
  expect(deleted.filter(k=>k.startsWith('transfer:'))).toEqual([]);
  expect(await store.read('transfer:'+recordingId)).toEqual(prior);
  expect(await isTransferRetentionReleased(store,recordingId)).toBe(false);
  expect(await store.read(transferRetentionReleasedKey(recordingId))).toBeNull();
  const next=legacyTransfer({admitted});
  await panelPersist(store,prior,next);
  expect(await relaunchResume(store)).toEqual(next);
  store.close();
});
