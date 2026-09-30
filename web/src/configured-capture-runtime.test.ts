import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import {openConfiguredWorkspaceRuntime} from './configured-capture-runtime';
import {workspaceCaptureBff} from './capture-api';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./capture-api',()=>({CAPTURE_LONG_VISITS_BUILD:true,workspaceCaptureBff:vi.fn()}));
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
    selectCaptureProfile:vi.fn().mockRejectedValue(new Error('profile endpoint absent'))};
  vi.mocked(workspaceCaptureBff).mockReturnValue(bff as never);
  const source={kind:'microphone' as const,start:vi.fn(),stop:vi.fn()};
  const open=()=>openConfiguredWorkspaceRuntime({workspaceId,sessionId,identity:{mode:'clerk_jwt',getToken:async()=>null},
    native:false,source,profiles:{claimConfiguredCaptureStorage:async()=>{}} as never,
    queue:{kind:'indexeddb',storage:{},close:()=>{}} as never,upload:{} as never,
    abort:new AbortController(),unlock:async()=>{}});
  return {bff,source,open};
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
