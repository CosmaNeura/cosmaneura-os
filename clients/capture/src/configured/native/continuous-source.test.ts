import {expect, it, vi} from "vitest";
import {CapacitorIosNativePcmBridge} from "./capacitor-ios-native-pcm-bridge";
import {IosNativeMicrophoneCaptureSource} from "./ios-native-microphone-source";
import type {IOSPCMPlugin, IosPcmEvent} from "./capacitor-pcm";
import type {CaptureSourceExtension} from "../capture";
import {MockCaptureService} from "../mock-bff/state";

const extension:CaptureSourceExtension={leaseReceiptId:"11111111-1111-4111-8111-111111111111",
  leaseGeneration:2,captureAuthorizedUntil:new Date(Date.now()+60_000).toISOString(),
  reservationBatchId:"22222222-2222-4222-8222-222222222222",firstSequenceNumber:1,reservationCount:3,maximumChunks:4};

function setup(){
  const token="1.synthetic", chunks:number[]=[], events:string[]=[];
  let listener:(value:IosPcmEvent)=>void=()=>{};
  const plugin:IOSPCMPlugin={
    getAppState:async()=>({state:"foreground"}),
    getCaptureCapabilities:async()=>({version:1,renewableAuthority:false,configuredRenewal:true}),
    start:vi.fn(async()=>({sessionToken:token})),ready:async()=>({}),heartbeat:async()=>({}),
    stop:vi.fn(async()=>({finalPcmPacket:null})),
    acknowledge:vi.fn(async()=>({result:"accepted" as const})),replayPendingPacket:async()=>({result:"already_acknowledged"}),
    addListener:async(_name,callback)=>{listener=callback;return{remove:async()=>{}};},
    extend:vi.fn(async value=>({sessionToken:value.sessionToken,leaseGeneration:value.extension.leaseGeneration,
      captureAuthorizedUntil:value.extension.captureAuthorizedUntil,maximumChunks:4})),
  };
  const source=new IosNativeMicrophoneCaptureSource(new CapacitorIosNativePcmBridge(plugin,60_000));
  const packet=async(sequenceNumber:number)=>{
    listener({kind:"packet",packet:{sessionToken:token,sequenceNumber,pcmBase64:Buffer.alloc(640,17).toString("base64")}});
    await vi.waitFor(()=>expect(plugin.acknowledge).toHaveBeenCalledWith({sessionToken:token,sequenceNumber}));
    await new Promise<void>(resolve=>setImmediate(resolve));
  };
  const start=()=>source.start({capabilities:{...new MockCaptureService().capabilities(),max_chunks:2},
    onChunk:async chunk=>{chunks.push(chunk.sequenceNumber);},onError:code=>{events.push(code);}});
  return{plugin,source,packet,start,chunks,events};
}

it("keeps one PCM session across renewal, including delivery before the extension reply",async()=>{
  const s=setup();
  try{
    expect(await s.source.supportsContinuousCapture()).toBe(true);
    await s.start();await s.packet(0);expect(s.chunks).toEqual([0]);
    await s.packet(1);expect(s.chunks).toEqual([0,1]);
    vi.mocked(s.plugin.extend!).mockImplementationOnce(async value=>{
      expect(Object.keys(value.extension).sort()).toEqual(["captureAuthorizedUntil","firstSequenceNumber",
        "leaseGeneration","leaseReceiptId","reservationBatchId","reservationCount"]);
      await s.packet(2);expect(s.chunks).toEqual([0,1,2]);
      return{sessionToken:value.sessionToken,leaseGeneration:2,captureAuthorizedUntil:extension.captureAuthorizedUntil,maximumChunks:4};
    });
    await s.source.extend(extension);
    await s.packet(3);expect(s.chunks).toEqual([0,1,2,3]);
    expect(s.plugin.start).toHaveBeenCalledOnce();expect(s.plugin.stop).not.toHaveBeenCalled();
    expect(s.events).toEqual([]);
  }finally{await s.source.stop();}
});

it("stops the same native session when an extension acknowledges another owner window",async()=>{
  const s=setup();
  try{
    await s.start();vi.mocked(s.plugin.extend!).mockResolvedValueOnce({sessionToken:"2.other",leaseGeneration:2,
      captureAuthorizedUntil:extension.captureAuthorizedUntil,maximumChunks:4});
    await expect(s.source.extend(extension)).rejects.toThrow();
    await vi.waitFor(()=>expect(s.plugin.stop).toHaveBeenCalled());
    expect(s.plugin.start).toHaveBeenCalledOnce();expect(s.events).toContain("capture_source_failed");
  }finally{await s.source.stop();}
});
