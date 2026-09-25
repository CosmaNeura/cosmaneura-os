import {expect,it,vi} from 'vitest';
import {continuousOwner,continuousPermit} from './continuous-capture';
import {DesktopPcmCaptureSource} from './pcm-capture-source';
import type {DesktopPCMDriver} from './native-pcm-driver';
import type {CaptureCapabilities} from '../../capture/src/bff/contracts';

const owner=continuousOwner({runId:'10000000-0000-4000-8000-000000000001',generation:1,hardMaximumChunks:360});
const now=1_800_000_000_000,deadline=now+60_000;
const request={leaseReceiptId:crypto.randomUUID(),leaseGeneration:2,captureAuthorizedUntil:new Date(now+900_000).toISOString(),
  reservationBatchId:crypto.randomUUID(),firstSequenceNumber:84,reservationCount:90,maximumChunks:174};
const permit={runId:owner.runId,generation:2,expiresAt:now+10_000,previousCaptureAuthorizedUntil:deadline,
  captureAuthorizedUntil:now+900_000,maximumChunks:174};

it('requires the same live native owner, next generation, exact reservation and cumulative budget',()=>{
  expect(continuousPermit(permit,owner,1,deadline,89,request,now)).toEqual(permit);
  for(const change of [{runId:crypto.randomUUID()},{generation:3},{maximumChunks:361},{maximumChunks:89},
    {expiresAt:now},{expiresAt:deadline+1},{previousCaptureAuthorizedUntil:deadline+10},
    {captureAuthorizedUntil:now+900_100},{secret:'forbidden'}]){
    expect(()=>continuousPermit({...permit,...change},owner,1,deadline,89,request,now)).toThrow();
  }
  expect(()=>continuousPermit(permit,owner,1,deadline,89,request,deadline)).toThrow();
  expect(()=>continuousPermit(permit,{...owner,hardMaximumChunks:170},1,deadline,89,request,now)).toThrow();
});

it('preserves partial PCM and sequence through two extensions, including audio before the acknowledgment',async()=>{
  // Tiny generated samples after invented all-parties consent; no OS source.
  const consent={allPartiesAgreed:true};expect(consent.allPartiesAgreed).toBe(true);
  let sink!:Parameters<DesktopPCMDriver['start']>[1],offset=0;
  const emit=async(samples:number[])=>{
    const bytes=new Uint8Array(samples.length*2),view=new DataView(bytes.buffer);
    samples.forEach((value,index)=>view.setInt16(index*2,value,true));
    const firstFrame=offset;offset+=samples.length;await sink.onPcmPacket({firstFrame,pcmBytes:bytes});
    expect(bytes.every(v=>v===0)).toBe(true);
  };
  const mark={hostTimeNanoseconds:'1000000000',microphonePrerollNanoseconds:'0',systemPrerollNanoseconds:'0'};
  const packet=Array.from({length:16},(_,i)=>[5,6,7,8][i%4]!);
  const extend=vi.fn(async()=>{await emit(packet);});
  const start=vi.fn((_config:Parameters<DesktopPCMDriver['start']>[0],target:typeof sink)=>{
    sink=target;return {ready:Promise.resolve(mark),activate:()=>{},extend,stop:async()=>({start:mark,
      endHostTimeNanoseconds:String(1_000_000_000+offset*62500),outputFrames:offset,microphoneTailNanoseconds:'0',systemTailNanoseconds:'0'})};
  });
  const coverage=vi.fn(async()=>{}),source=new DesktopPcmCaptureSource({getAvailability:async()=>true,
    supportsContinuousCapture:async()=>true,start},coverage);
  const chunks:{sequence:number;samples:number[]}[]=[];
  const caps={protocol_version:'1.0',media:{media_type:'audio/wav',encoding:'pcm_s16le',channels:1,sample_rate_hz:16000},
    target_chunk_duration_ms:1,max_chunks:1,max_envelope_bytes:327680,remaining_aggregate_plaintext_bytes:268435456,
    capture_lease_ttl_seconds:900,reservation_window_seconds:900,max_reservations_per_batch:90,upload_concurrency:2} as CaptureCapabilities;
  expect(await source.supportsContinuousCapture()).toBe(true);
  await source.start({capabilities:caps,onChunk:async chunk=>{
    const view=new DataView(chunk.wavBytes.buffer);const samples=[];
    for(let i=44;i<chunk.wavBytes.length;i+=2)samples.push(view.getInt16(i,true));
    chunks.push({sequence:chunk.sequenceNumber,samples});
  }});
  const initial=Array.from({length:8},(_,i)=>[1,2][i%2]!);await emit(initial);
  await source.extend({...request,maximumChunks:2});
  await source.extend({...request,leaseGeneration:3,maximumChunks:3});
  await source.stop();
  expect(start).toHaveBeenCalledOnce();expect(extend).toHaveBeenCalledTimes(2);
  expect(chunks.map(c=>c.sequence)).toEqual([0,1,2]);
  expect(chunks.map(c=>c.samples.length)).toEqual([16,16,8]);
  expect(chunks.flatMap(c=>c.samples)).toEqual([...initial,...packet,...packet]);
  expect(coverage).toHaveBeenCalledTimes(2);
  await expect(source.extend({...request,maximumChunks:4})).rejects.toThrow();
});
