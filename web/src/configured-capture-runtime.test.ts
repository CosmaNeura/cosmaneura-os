import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import {openConfiguredWorkspaceRuntime} from './configured-capture-runtime';
import {workspaceCaptureBff} from './capture-api';
import {BffResponseError} from '../../clients/capture/src/bff/http-client';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./capture-api',()=>({CAPTURE_LONG_VISITS_BUILD:true,CAPTURE_RECOVERY_BUILD:true,workspaceCaptureBff:vi.fn()}));
vi.mock('./creator-review-api',()=>({creatorReviewApi:()=>({read:async()=>({status:'created'})})}));
const workspaceId='20000000-0000-4000-8000-000000000001',sessionId='20000000-0000-4000-8000-000000000002';
const flow=()=>EncryptedIndexedDbFlowStore.open({databaseName:`cosmas-configured-flow:v1:${workspaceId}`});
beforeEach(()=>{
  vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('indexedDB',new IDBFactory());
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
function fixture(){
  const bff={getAudioEncryptionKey:vi.fn().mockRejectedValue(new Error('key service unavailable')),
    selectCaptureProfile:vi.fn().mockRejectedValue(new Error('profile endpoint absent')),
    getCaptureLeaseState:vi.fn().mockResolvedValue({session_id:sessionId,session_status:'created',current_lease:null,lease_closed:false}),
    getCapabilities:vi.fn().mockResolvedValue({protocol_version:'1.0',media:{media_type:'audio/wav',encoding:'pcm_s16le',channels:1,sample_rate_hz:16000},
      target_chunk_duration_ms:10000,max_envelope_bytes:327680,max_chunks:1000,remaining_aggregate_plaintext_bytes:67108864,
      capture_lease_ttl_seconds:900,reservation_window_seconds:900,max_reservations_per_batch:90,upload_concurrency:2})};
  vi.mocked(workspaceCaptureBff).mockReturnValue(bff as never);
  const source={kind:'microphone' as const,start:vi.fn(),stop:vi.fn()};
  const rows=vi.fn().mockResolvedValue([]),unlock=vi.fn(),abort=new AbortController();
  const open=()=>openConfiguredWorkspaceRuntime({workspaceId,sessionId,identity:{mode:'clerk_jwt',getToken:async()=>null},
    native:false,source,profiles:{claimConfiguredCaptureStorage:async()=>{},close:()=>{}} as never,
    queue:{kind:'indexeddb',storage:{listMetadata:rows},close:()=>{}} as never,upload:{} as never,abort,unlock});
  return {bff,source,open,rows,unlock,abort};
}
async function saveProfile(){
  const store=await flow();
  const saved={schemaVersion:5 as const,mode:'configured_core' as const,sessionId,
    startedAt:new Date().toISOString(),completeIdempotencyKey:crypto.randomUUID(),leaseIdempotencyKey:null,leaseRequest:null,
    profileSelection:{request:{schema_version:'1.0' as const,profile_id:'visit-60m-v1' as const,channels:['microphone' as const]},
      idempotencyKey:crypto.randomUUID(),receipt:null}};
  await store.putPreparationState(saved);store.close();return saved;
}

it('reaches standard key setup without a profile endpoint and retains a recoverable continuous preparation',async()=>{
  const f=fixture();
  await expect(f.open()).rejects.toThrow('key service unavailable');
  expect(f.bff.selectCaptureProfile).not.toHaveBeenCalled();
  expect(f.bff.getAudioEncryptionKey).toHaveBeenCalledOnce();
  const store=await flow(),saved=await store.getPreparationState();store.close();
  expect(saved).toMatchObject({mode:'configured_core',schemaVersion:7,sessionId});
  expect(saved).not.toHaveProperty('profileSelection');
  expect(f.source.start).not.toHaveBeenCalled();
});

it('offers an explicit empty recovery, retains the original intent and retries standard setup without starting audio',async()=>{
  const saved=await saveProfile(),f=fixture();
  f.bff.selectCaptureProfile.mockRejectedValue(new BffResponseError(409,'capture_source_unavailable',null));
  const runtime=await f.open();
  expect(runtime.recoveryOnly).toBe(true);expect(runtime.controller.snapshot.state).toBe('ready');
  expect(f.bff.getAudioEncryptionKey).not.toHaveBeenCalled();
  const before=await flow();expect(await before.getPreparationState()).toEqual(saved);before.close();
  await expect(runtime.controller.startRecording()).rejects.toThrow();
  await expect(runtime.continuePreparation!()).rejects.toThrow('key service unavailable');
  await expect(runtime.continuePreparation!()).rejects.toThrow('key service unavailable');
  expect(f.bff.getCaptureLeaseState).toHaveBeenCalledTimes(2);
  expect(f.bff.selectCaptureProfile).toHaveBeenCalledOnce();expect(f.bff.getAudioEncryptionKey).toHaveBeenCalledTimes(2);
  const after=await flow(),actual=await after.getPreparationState();after.close();
  const {profileSelection:_,...rest}=saved;expect(actual).toEqual({...rest,schemaVersion:7});
  expect(f.source.start).not.toHaveBeenCalled();
  await runtime.close();expect(f.unlock).toHaveBeenCalledOnce();
  await expect(runtime.continuePreparation!()).rejects.toThrow();
});

it.each(['audio','lease','closed lease','wrong session','status','budget','profile-capacity','authority','uncertain'])(
  'preserves the exact preparation when recovery proof fails: %s',async reason=>{
    const saved=await saveProfile(),f=fixture();
    f.bff.selectCaptureProfile.mockRejectedValue(new BffResponseError(409,'capture_source_unavailable',null));
    if(reason==='audio')f.rows.mockResolvedValue([{state:'encrypted'}]);
    if(reason==='lease')f.bff.getCaptureLeaseState.mockResolvedValue({current_lease:{}});
    if(reason==='closed lease')f.bff.getCaptureLeaseState.mockResolvedValue({session_id:sessionId,session_status:'created',current_lease:null,lease_closed:true});
    if(reason==='wrong session')f.bff.getCaptureLeaseState.mockResolvedValue({session_id:workspaceId,session_status:'created',current_lease:null,lease_closed:false});
    if(reason==='status')f.bff.getCaptureLeaseState.mockResolvedValue({session_id:sessionId,session_status:'uploaded',current_lease:null,lease_closed:false});
    if(reason==='budget'||reason==='profile-capacity'){
      const caps=await f.bff.getCapabilities();f.bff.getCapabilities.mockResolvedValue({...caps,
        ...(reason==='budget'?{remaining_aggregate_plaintext_bytes:1}:{max_chunks:720})});
    }
    if(reason==='authority')f.bff.getCaptureLeaseState.mockRejectedValue(new BffResponseError(403,'capture_access_unavailable',null));
    if(reason==='uncertain')f.bff.selectCaptureProfile.mockRejectedValue(new BffResponseError(503,'capture_request_unconfirmed',null));
    await expect(f.open()).rejects.toThrow();
    const store=await flow();expect(await store.getPreparationState()).toEqual(saved);store.close();
    expect(f.bff.getAudioEncryptionKey).not.toHaveBeenCalled();expect(f.source.start).not.toHaveBeenCalled();
  });

it.each(['new audio','aborted access'])('rechecks the proof on Continue preparation after %s',async reason=>{
  const saved=await saveProfile(),f=fixture();
  f.bff.selectCaptureProfile.mockRejectedValue(new BffResponseError(409,'capture_source_unavailable',null));
  const runtime=await f.open();
  if(reason==='new audio')f.rows.mockResolvedValue([{state:'reserved'}]);else f.abort.abort();
  await expect(runtime.continuePreparation!()).rejects.toThrow();
  const store=await flow();expect(await store.getPreparationState()).toEqual(saved);store.close();
  expect(f.bff.getAudioEncryptionKey).not.toHaveBeenCalled();await runtime.close();
});

it('keeps a saved profile request and its retry key when that endpoint is unavailable',async()=>{
  const f=fixture(),store=await flow();
  const saved={schemaVersion:5 as const,mode:'configured_core' as const,sessionId,
    startedAt:new Date().toISOString(),completeIdempotencyKey:crypto.randomUUID(),leaseIdempotencyKey:null,leaseRequest:null,
    profileSelection:{request:{schema_version:'1.0' as const,profile_id:'visit-60m-v1' as const,channels:['microphone' as const]},
      idempotencyKey:crypto.randomUUID(),receipt:null}};
  await store.putPreparationState(saved);store.close();
  await expect(f.open()).rejects.toThrow('profile endpoint absent');
  expect(f.bff.selectCaptureProfile).toHaveBeenCalledWith(sessionId,saved.profileSelection.request,
    {idempotencyKey:saved.profileSelection.idempotencyKey});
  expect(f.bff.getAudioEncryptionKey).not.toHaveBeenCalled();
  const reopened=await flow();expect(await reopened.getPreparationState()).toEqual(saved);reopened.close();
  expect(f.source.start).not.toHaveBeenCalled();
});
