import {expect,it,vi} from 'vitest';
import type {CaptureSource,CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import {privateDesktopRecordingSource} from './private-recording-desktop';
const revision='10000000-0000-4000-8000-000000000001',permitId='10000000-0000-4000-8000-000000000002';
const context={recordingId:'10000000-0000-4000-8000-000000000003',consent:{modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:new Date(Date.now()-1000).toISOString(),language:'en-US' as const}};
function fixture(){let listener:(value:{permitId:string})=>void=()=>{},allow=true,starting:Promise<void>|null=null;
  const source={kind:'microphone' as const,start:vi.fn(async()=>{if(starting)await starting;}),stop:vi.fn(async()=>{if(!allow)throw Error('Physical closure unknown');})} satisfies CaptureSource;
  const port={enabled:true,privateAcquire:vi.fn(async(v:{requestId:string;revision:string})=>({requestId:v.requestId,revision:v.revision,permitId,expiresAt:new Date(Date.now()+900000).toISOString()})),privateRelease:vi.fn(async(v:{requestId:string})=>({requestId:v.requestId,released:true})),privateIdle:vi.fn(async(v:{requestId:string})=>({requestId:v.requestId,idle:true})),onPrivateRevoked:(callback:typeof listener)=>{listener=callback;return()=>{listener=()=>{};};}};
  const result=privateDesktopRecordingSource(source,context,{port,auth:{getState:async()=>({phase:'ready',revision})}});
  return {result,source,port,revoke:()=>listener({permitId}),denyStop:()=>{allow=false;},allowStop:()=>{allow=true;},deferStart:()=>{let resolve!:()=>void;starting=new Promise<void>(r=>{resolve=r;});return resolve;}};
}
const options:CaptureSourceStartOptions={capabilities:{protocol_version:'1.0',media:{media_type:'audio/wav',encoding:'pcm_s16le',sample_rate_hz:16000,channels:1},target_chunk_duration_ms:10000,max_chunks:90,max_envelope_bytes:320044,remaining_aggregate_plaintext_bytes:90*320044,capture_lease_ttl_seconds:900,reservation_window_seconds:900,max_reservations_per_batch:1,upload_concurrency:1},onChunk:async()=>{}};
it('uses exact main-process consent/revision admission before audio and releases after producer closure',async()=>{
  const f=fixture();await f.result.start(options);expect(f.port.privateAcquire).toHaveBeenCalledOnce();expect(f.source.start).toHaveBeenCalledOnce();
  expect(f.port.privateAcquire.mock.calls[0]![0]).toMatchObject({revision,recordingId:context.recordingId,consent:context.consent});
  expect(f.port.privateRelease).not.toHaveBeenCalled();await f.result.stop();expect(f.source.stop).toHaveBeenCalledOnce();expect(f.port.privateRelease).toHaveBeenCalledOnce();
  expect(f.source.stop.mock.invocationCallOrder[0]).toBeLessThan(f.port.privateRelease.mock.invocationCallOrder[0]!);
});
it('refuses unknown native admission before microphone access',async()=>{
  const f=fixture();f.port.privateAcquire.mockRejectedValueOnce(Error('Retained native owner'));
  await expect(f.result.start(options)).rejects.toThrow();expect(f.source.start).not.toHaveBeenCalled();expect(f.port.privateRelease).not.toHaveBeenCalled();
});
it('keeps main-process permit after uncertain physical stop and retries that exact permit',async()=>{
  const f=fixture();await f.result.start(options);f.denyStop();await expect(f.result.stop()).rejects.toThrow();expect(f.port.privateRelease).not.toHaveBeenCalled();
  f.allowStop();await f.result.stop();expect(f.port.privateRelease.mock.calls[0]![0]).toMatchObject({permitId});
});
it('revoked permit stops physical audio before main release without a panel callback',async()=>{
  const f=fixture();await f.result.start(options);f.revoke();await vi.waitFor(()=>expect(f.port.privateRelease).toHaveBeenCalledOnce());expect(f.source.stop).toHaveBeenCalledOnce();
});
it('pending microphone permission cannot release exclusion before its late result is fenced',async()=>{
  const f=fixture(),complete=f.deferStart();const start=f.result.start(options);await vi.waitFor(()=>expect(f.source.start).toHaveBeenCalledOnce());
  await expect(f.result.stop()).rejects.toThrow();expect(f.port.privateRelease).not.toHaveBeenCalled();complete();await start;expect(f.port.privateRelease).toHaveBeenCalledOnce();
});
it('recovery asks the native journal for real idle rather than accepting a fresh browser adapter',async()=>{
  const f=fixture();expect(await f.result.confirmRecoveryClosed?.()).toBe(true);expect(f.port.privateIdle).toHaveBeenCalledOnce();
  f.port.privateIdle.mockRejectedValueOnce(Error('Recovery required'));await expect(f.result.confirmRecoveryClosed?.()).rejects.toThrow();
});
