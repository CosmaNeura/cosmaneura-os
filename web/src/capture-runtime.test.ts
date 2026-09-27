import {beforeEach,afterEach,expect,it,vi} from "vitest";
import {IDBFactory} from "../../clients/capture/node_modules/fake-indexeddb";
import {openCaptureRuntime} from "./capture-runtime";
import {openNativeCaptureRuntime} from "./native-capture-runtime";
import {openConfiguredWorkspaceRuntime} from "./configured-capture-runtime";
import {isIosNativePlatform} from "../../clients/capture/src/capture-source-factory";
import {EncryptedIndexedDbFlowStore as Profiles} from "../../clients/capture/src/flow/encrypted-store";
import {EncryptedIndexedDbQueueStorage} from "../../clients/capture/src/storage/encrypted-indexeddb";
import {CaptureQueue} from "../../clients/capture/src/queue";
import {encodeChunkAdditionalDataBase64Url} from "../../clients/capture/protocol/generated";
import {SecureQueue} from "../../clients/capture/plugins/secure-queue";
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");
const workspaceId="20000000-0000-4000-8000-000000000001",sessionId="20000000-0000-4000-8000-000000000002";
const identity={mode:"clerk_jwt" as const,getToken:async()=>null,nativeSession:{revision:sessionId,isCurrent:()=>true}};
const configured={schema_version:"1.0" as const,language_mode:"en-US" as const};
vi.mock("./native-capture-runtime",()=>({openNativeCaptureRuntime:vi.fn()}));
vi.mock("./configured-capture-runtime",()=>({openConfiguredWorkspaceRuntime:vi.fn()}));
vi.mock("../../clients/capture/src/capture-source-factory",()=>({IOS_NATIVE_PCM_CAPTURE_ENABLED:true,
  isIosNativePlatform:vi.fn(),createCaptureSource:vi.fn().mockResolvedValue({kind:"microphone",start:vi.fn(),stop:vi.fn()})}));
vi.mock("../../clients/capture/src/flow/capture-lock",()=>({acquireCaptureFlowLock:async()=>async()=>{}}));
vi.mock("../../clients/capture/plugins/secure-queue",()=>({SecureQueue:{list:vi.fn(),get:vi.fn()}}));
beforeEach(()=>{
  vi.clearAllMocks();vi.stubGlobal("crypto",webcrypto);vi.stubGlobal("indexedDB",new IDBFactory());
  vi.stubGlobal("ArrayBuffer",structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal("Uint8Array",structuredClone(new Uint8Array(0)).constructor);
  vi.stubEnv("VITE_CAPTURE_UPLOAD_ORIGINS","https://synthetic.invalid");
  vi.mocked(isIosNativePlatform).mockResolvedValue(true);
  vi.mocked(SecureQueue.list).mockResolvedValue({keys:[]});
  vi.mocked(openNativeCaptureRuntime).mockImplementation(async options=>({close:options.release} as never));
  vi.mocked(openConfiguredWorkspaceRuntime).mockImplementation(async options=>({close:async()=>{
    options.profiles.close();options.queue.close();await options.unlock();
  }} as never));
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
const profiles=()=>Profiles.open({databaseName:`cosmas-capture-flow:${workspaceId}`});

it("selects native custody for a fresh iPhone encounter and persists that selection across reopening",async()=>{
  const first=await openCaptureRuntime(workspaceId,sessionId,identity,configured);
  await first.close();
  const p=await profiles();expect(await p.getCaptureStorageOwner(sessionId)).toBe("owned:native");
  await expect(p.claimQueueStorageKind(sessionId,"native")).rejects.toThrow("queue_storage_profile_changed");
  await expect(p.claimDesktopCaptureStorage(sessionId)).rejects.toThrow("queue_storage_profile_changed");
  p.close();
  const second=await openCaptureRuntime(workspaceId,sessionId,identity,configured);await second.close();
  expect(openNativeCaptureRuntime).toHaveBeenCalledTimes(2);
  expect(openConfiguredWorkspaceRuntime).not.toHaveBeenCalled();
});

it("keeps an existing configured native queue on its original controller",async()=>{
  const p=await profiles();await p.claimQueueStorageKind(sessionId,"native");await p.claimConfiguredCaptureStorage(sessionId,"native");p.close();
  const runtime=await openCaptureRuntime(workspaceId,sessionId,identity,configured);await runtime.close();
  expect(openConfiguredWorkspaceRuntime).toHaveBeenCalledOnce();
  expect(openNativeCaptureRuntime).not.toHaveBeenCalled();
});

it("does not replace browser ciphertext when a native app opens the same visit",async()=>{
  const storage=await EncryptedIndexedDbQueueStorage.open({databaseName:`cosmas-capture-queue:${workspaceId}`});
  const queue=new CaptureQueue(storage),objectId=crypto.randomUUID();
  await queue.reserve({protocolVersion:"1.0",objectId,sessionId,channel:"microphone",sequenceNumber:0,
    additionalAuthenticatedData:encodeChunkAdditionalDataBase64Url({tenantId:workspaceId,objectId,sessionId,channel:"microphone",sequenceNumber:0}),
    createdAt:"2026-09-27T12:00:00.000Z"},crypto.randomUUID());
  storage.close();
  await expect(openCaptureRuntime(workspaceId,sessionId,identity,configured)).rejects.toThrow();
  expect(openNativeCaptureRuntime).not.toHaveBeenCalled();
  const p=await profiles();expect(await p.getCaptureStorageOwner(sessionId)).toBeNull();p.close();
});

it("retains native selection after a failed attachment and refuses a browser or desktop fallback",async()=>{
  vi.mocked(openNativeCaptureRuntime).mockRejectedValueOnce(new Error("native offline"));
  await expect(openCaptureRuntime(workspaceId,sessionId,identity,configured)).rejects.toThrow("native offline");
  vi.mocked(isIosNativePlatform).mockResolvedValue(false);
  await expect(openCaptureRuntime(workspaceId,sessionId,identity,configured)).rejects.toThrow();
  vi.mocked(isIosNativePlatform).mockResolvedValue(true);
  await expect(openCaptureRuntime(workspaceId,sessionId,identity,configured,"desktop_meeting")).rejects.toThrow();
  expect(openConfiguredWorkspaceRuntime).not.toHaveBeenCalled();
});

it("leaves a fresh browser encounter on the browser controller",async()=>{
  vi.mocked(isIosNativePlatform).mockResolvedValue(false);
  const runtime=await openCaptureRuntime(workspaceId,sessionId,identity,configured);await runtime.close();
  expect(openConfiguredWorkspaceRuntime).toHaveBeenCalledOnce();
  expect(openNativeCaptureRuntime).not.toHaveBeenCalled();
});
