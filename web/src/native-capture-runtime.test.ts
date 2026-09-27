import {beforeEach,afterEach,expect,it,vi} from "vitest";
import {openNativeCaptureRuntime} from "./native-capture-runtime";
import {nativeRecordingPlugin} from "../../clients/capture/src/native/owned-recorder-plugin";
import {SecureQueue} from "../../clients/capture/plugins/secure-queue";
import {workspaceCaptureBff} from "./capture-api";
import {creatorReviewApi} from "./creator-review-api";
import {recordingFixture,syntheticWorkspace as workspaceId,syntheticSession as sessionId,syntheticRecovery}
  from "../../clients/capture/src/native/owned-recorder.fixture";
import {NativePluginQueueStorage,type NativeQueuePlugin} from "../../clients/capture/src/storage/native-plugin";
import {scopedNativeRecordingPlugin} from "./capture-storage";
import {CaptureQueue} from "../../clients/capture/src/queue";
import {encodeEnvelope,base64UrlEncode,encodeChunkAdditionalDataBase64Url}
  from "../../clients/capture/protocol/generated";
import type {CaptureBff} from "../../clients/capture/src/bff/contracts";
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");

vi.mock("../../clients/capture/src/native/owned-recorder-plugin",()=>({nativeRecordingPlugin:{
  openProviderRecording:vi.fn(),providerRecordingCommand:vi.fn()}}));
vi.mock("../../clients/capture/plugins/secure-queue",()=>({SecureQueue:{create:vi.fn(),get:vi.fn(),list:vi.fn(),compareAndSwap:vi.fn()}}));
vi.mock("./capture-api",()=>({workspaceCaptureBff:vi.fn()}));
vi.mock("./creator-review-api",()=>({creatorReviewApi:vi.fn()}));

beforeEach(()=>{
  vi.clearAllMocks();vi.stubGlobal("crypto",webcrypto);
  vi.stubGlobal("navigator",{locks:{request:async(_name:unknown,_options:unknown,callback:()=>Promise<unknown>)=>callback()}});
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
async function fixture() {
  const f=recordingFixture(),abort=new AbortController(),revision=crypto.randomUUID();
  let current=true;
  const identity={mode:"clerk_jwt" as const,getToken:async()=>null,nativeSession:{revision,isCurrent:()=>current}};
  const values=new Map<string,{data:string;revision:string}>();
  const plugin:NativeQueuePlugin={
    create:async ({key,data})=>{if(values.has(key))throw {code:"SECURE_QUEUE_ALREADY_EXISTS"};values.set(key,{data,revision:"1"});return {revision:"1"};},
    get:async ({key})=>{const v=values.get(key);if(!v)throw {code:"SECURE_QUEUE_NOT_FOUND"};return {key,...v};},
    list:async()=>({keys:[...values.keys()]}),
    compareAndSwap:async ({key,data,expectedRevision})=>{const v=values.get(key);if(!v||v.revision!==expectedRevision)throw {code:"SECURE_QUEUE_REVISION_CONFLICT"};
      const revision=String(Number(v.revision)+1);values.set(key,{data,revision});return {revision};},
  };
  for(const method of ["create","get","list","compareAndSwap"] as const)vi.mocked(SecureQueue[method]).mockImplementation(plugin[method] as never);
  vi.mocked(nativeRecordingPlugin.openProviderRecording).mockImplementation(async request=>{
    expect(request).toEqual({workspaceId,sessionId,revision,requestId:expect.any(String)});
    return f.port.open(sessionId,request.requestId);
  });
  vi.mocked(nativeRecordingPlugin.providerRecordingCommand).mockImplementation(async request=>{
    expect(request.revision).toBe(revision);return f.port.command(request);
  });
  const unused=async():Promise<never>=>{throw new Error("Unexpected renderer key/lease/source work");};
  const bff:CaptureBff={getAudioEncryptionKey:unused,createConsent:unused,createSession:unused,bindSessionAudioKey:unused,
    getCapabilities:unused,issueLease:unused,renewLease:unused,reserveChunks:unused,authorizeUpload:unused,
    getChunkReceipt:unused,registerChunk:unused,completeCapture:unused,getTranscriptionStatus:unused,getTranscript:unused};
  vi.mocked(workspaceCaptureBff).mockReturnValue(bff as never);
  const read=vi.fn().mockResolvedValue({status:"created"});
  vi.mocked(creatorReviewApi).mockReturnValue({read} as never);
  const upload={putCompleteEnvelope:vi.fn().mockResolvedValue(undefined)},release=vi.fn().mockResolvedValue(undefined);
  return {f,abort,identity,values,bff,read,upload,release,retireIdentity:()=>{current=false;},
    queue:new CaptureQueue(new NativePluginQueueStorage(scopedNativeRecordingPlugin(plugin,syntheticRecovery,workspaceId,sessionId),sessionId)),
    open:()=>openNativeCaptureRuntime({workspaceId,sessionId,identity,upload,abort,release})};
}

it("connects the native screen, uploads ciphertext, confirms receipts and opens the existing review state",async()=>{
  const h=await fixture(),runtime=await h.open(),createdAt="2026-09-27T12:00:00.000Z";
  await runtime.controller.startRecording();
  expect(runtime.controller.snapshot.state).toBe("recording");
  const objectId=crypto.randomUUID(),aad=encodeChunkAdditionalDataBase64Url({tenantId:crypto.randomUUID(),objectId,sessionId,channel:"microphone",sequenceNumber:0});
  await h.queue.reserve({protocolVersion:"1.0",objectId,sessionId,channel:"microphone",sequenceNumber:0,additionalAuthenticatedData:aad,createdAt},crypto.randomUUID());
  const encrypted=await h.queue.encrypt(objectId,encodeEnvelope({schema_version:"1.0",content_encryption:"A256GCM",
    nonce:base64UrlEncode(new Uint8Array(12)),media_type:"audio/wav"},new Uint8Array(48)));
  const completeIntent=crypto.randomUUID();
  h.f.set({phase:"sealed",recordedChunks:1,recordedPlaintextBytes:612,completion:{
    idempotencyKey:completeIntent,leaseId:crypto.randomUUID(),leaseGeneration:1,finalSequence:0}});
  h.bff.getChunkReceipt=vi.fn().mockResolvedValue({state:"reserved",reservation:{protocol_version:"1.0",object_id:objectId,
    session_id:sessionId,channel:"microphone",sequence_number:0,additional_authenticated_data:aad,created_at:createdAt}});
  h.bff.authorizeUpload=vi.fn().mockResolvedValue({protocol_version:"1.0",object_id:objectId,additional_authenticated_data:aad,
    upload_url:"https://synthetic.invalid/audio",expires_at:"2099-01-01T00:00:00.000Z"});
  h.bff.registerChunk=vi.fn().mockImplementation(async(_session,request)=>({id:crypto.randomUUID(),session_id:sessionId,
    ...request,registered_at:createdAt}));
  h.bff.completeCapture=vi.fn().mockImplementation(async()=>{
    expect(h.f.commands.at(-1)?.kind).toBe("close");
    expect((await h.queue.get(objectId))?.state).toBe("purged");
    return {id:sessionId,status:"uploaded"};
  });
  await runtime.controller.stopRecording();
  expect(h.upload.putCompleteEnvelope).toHaveBeenCalledOnce();
  expect(h.upload.putCompleteEnvelope.mock.calls[0][1].byteLength).toBe(encrypted.byteLength);
  expect(h.bff.registerChunk).toHaveBeenCalledOnce();
  expect(h.bff.completeCapture).toHaveBeenCalledWith(sessionId,expect.any(Object),{idempotencyKey:completeIntent});
  expect(runtime.controller.snapshot.state).toBe("processing");
  await runtime.releaseUploadedCapture!();
  expect([...h.values.keys()][0]).toContain(`cosmas-provider-queue:v1:${syntheticRecovery}:${workspaceId}:${sessionId}:`);
  await runtime.close();
});

it("unmounts without stopping the native source and rejects commands after identity retirement",async()=>{
  const h=await fixture(),runtime=await h.open();
  await runtime.controller.startRecording();
  h.retireIdentity();
  await expect(runtime.controller.pauseRecording!()).rejects.toThrow();
  await runtime.close();
  expect(h.f.commands.map(c=>c.kind)).toEqual(["start"]);
  expect(h.release).toHaveBeenCalledOnce();
});

it("reopens a completed native visit directly into transcript and SOAP review without another native owner",async()=>{
  const h=await fixture();h.read.mockResolvedValue({status:"transcript_ready"});
  const runtime=await h.open();
  expect(runtime.controller.snapshot.state).toBe("processing");
  expect(nativeRecordingPlugin.openProviderRecording).not.toHaveBeenCalled();
  await runtime.releaseUploadedCapture!();await runtime.close();
});

it("scopes native ciphertext by recovery account, workspace AND session without fetching foreign records",async()=>{
  const h=await fixture();
  h.values.set(`cosmas-provider-queue:v1:${crypto.randomUUID()}:${workspaceId}:${sessionId}:${crypto.randomUUID()}`,{data:"invalid",revision:"1"});
  h.values.set(`cosmas-provider-queue:v1:${syntheticRecovery}:${crypto.randomUUID()}:${sessionId}:${crypto.randomUUID()}`,{data:"invalid",revision:"1"});
  const runtime=await h.open();
  expect(SecureQueue.get).not.toHaveBeenCalled();
  await runtime.close();
});
