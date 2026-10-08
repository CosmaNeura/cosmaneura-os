import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import type {IOSPCMPlugin,IosPcmEvent,IosPrivateRecordingReceipt,IosPrivateRecordingStart} from '../../clients/capture/plugins/ios-pcm/definitions';
import type {CaptureCapabilities} from '../../clients/capture/src/bff/contracts';
import {Capacitor} from '../../clients/capture/node_modules/@capacitor/core';
import {privateIosRecordingSource,prewarmPrivateRecordingNative,invalidatePrivateRecordingNativeReceipt,consumePrivateRecordingNativeReceipt} from '../../clients/capture/src/native/private-recording-source';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>{invalidatePrivateRecordingNativeReceipt();vi.spyOn(Capacitor,'getPlatform').mockReturnValue('ios');vi.spyOn(Capacitor,'isPluginAvailable').mockReturnValue(true);vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
const revision='00000000-0000-4000-8000-000000000010',recordingId='00000000-0000-4000-8000-000000000011',scope='a'.repeat(64);
const consent=()=>({modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:new Date().toISOString(),language:'en-US' as const});
function fixture(){
 let receive:((event:IosPcmEvent)=>void)|undefined;const receipt:IosPrivateRecordingReceipt={receiptId:crypto.randomUUID(),revision,expiresAt:new Date(Date.now()+300000).toISOString()};
 const plugin={preparePrivate:vi.fn(async()=>receipt),startPrivate:vi.fn(async(_options:IosPrivateRecordingStart)=>({sessionToken:'1.synthetic'})),start:vi.fn(async()=>{throw Error('Configured start prohibited');}),getAppState:vi.fn(async()=>({state:'foreground' as const})),confirmCaptureIdle:vi.fn(async()=>({version:1 as const,idle:true})),ready:vi.fn(async()=>({})),heartbeat:vi.fn(async()=>({})),stop:vi.fn(async()=>({finalPcmPacket:null})),acknowledge:vi.fn(async()=>({result:'accepted' as const})),replayPendingPacket:vi.fn(async()=>({result:'stale' as const})),addListener:vi.fn(async(_name:string,listener:(event:IosPcmEvent)=>void)=>{receive=listener;return {remove:async()=>{receive=undefined;}};})} satisfies IOSPCMPlugin;
 return {plugin,receipt,emit:(event:IosPcmEvent)=>receive?.(event)};
}
const limits:CaptureCapabilities={protocol_version:'1.0' as const,media:{media_type:'audio/wav' as const,encoding:'pcm_s16le' as const,sample_rate_hz:16000,channels:1 as const},target_chunk_duration_ms:10000,max_chunks:90,max_envelope_bytes:320044,remaining_aggregate_plaintext_bytes:90*320044,capture_lease_ttl_seconds:900,reservation_window_seconds:900,max_reservations_per_batch:1,upload_concurrency:1};
it('prewarms only account proof and starts only the separate closed private command with fresh one-use intent',async()=>{
 const h=fixture(),proof=await prewarmPrivateRecordingNative({scope,revision},h.plugin);expect(h.plugin.startPrivate).not.toHaveBeenCalled();expect(h.plugin.start).not.toHaveBeenCalled();
 const source=privateIosRecordingSource({scope,recordingId,consent:consent(),receipt:proof},h.plugin),saved:Uint8Array[]=[];
 await source.start({capabilities:limits,onChunk:async c=>{saved.push(c.wavBytes.slice());}});
 expect(h.plugin.startPrivate).toHaveBeenCalledTimes(1);expect(h.plugin.startPrivate.mock.calls[0][0]).toMatchObject({receiptId:proof.receiptId,revision,scope,recordingId,encoding:'pcm_s16le',channels:1,sampleRateHz:16000,targetFramesPerChunk:160000,maximumChunks:90,consent:{all_parties_consented:true}});
 expect(Object.keys(h.plugin.startPrivate.mock.calls[0][0]).sort()).toEqual(['channels','consent','encoding','maximumChunks','receiptId','recordingId','revision','sampleRateHz','scope','startIntent','targetFramesPerChunk']);
 const bytes=new Uint8Array(new ArrayBuffer(32)),view=new DataView(bytes.buffer);for(let i=0;i<16;i++)view.setInt16(i*2,721,true);
 h.emit({kind:'packet',packet:{sessionToken:'1.synthetic',sequenceNumber:0,pcmBase64:btoa(String.fromCharCode(...bytes))}});await vi.waitFor(()=>expect(h.plugin.acknowledge).toHaveBeenCalledTimes(1));await source.stop();expect(saved).toHaveLength(1);expect(new DataView(saved[0].buffer).getInt16(44,true)).toBe(721);
 await expect(source.start({capabilities:limits,onChunk:async()=>{}})).rejects.toThrow();expect(h.plugin.startPrivate).toHaveBeenCalledTimes(1);await source.stop();
});
it.each(['absent','wrong_scope_revision','expired','extra'] as const)('withholds invalid native private prewarm: %s',async kind=>{
 const h=fixture();if(kind==='absent')h.plugin.preparePrivate=undefined as never;
 else if(kind==='wrong_scope_revision')h.plugin.preparePrivate.mockResolvedValue({...h.receipt,revision:crypto.randomUUID()});
 else if(kind==='expired')h.plugin.preparePrivate.mockResolvedValue({...h.receipt,expiresAt:new Date(Date.now()-1).toISOString()});
 else h.plugin.preparePrivate.mockResolvedValue({...h.receipt,extra:true} as never);
 await expect(prewarmPrivateRecordingNative({scope,revision},h.plugin)).rejects.toThrow();expect(h.plugin.startPrivate).not.toHaveBeenCalled();
});
it('coalesces Home/panel preparation without caching tokens and consumes the proof once',async()=>{
 const h=fixture();let release!:(value:IosPrivateRecordingReceipt)=>void;h.plugin.preparePrivate.mockImplementation(()=>new Promise(yes=>{release=yes;}));
 const first=prewarmPrivateRecordingNative({scope,revision},h.plugin),second=prewarmPrivateRecordingNative({scope,revision},h.plugin);expect(h.plugin.preparePrivate).toHaveBeenCalledTimes(1);release(h.receipt);
 const a=await first,b=await second;expect(a).toEqual(b);expect(await prewarmPrivateRecordingNative({scope,revision},h.plugin)).toEqual(a);expect(h.plugin.preparePrivate).toHaveBeenCalledTimes(1);
 expect(consumePrivateRecordingNativeReceipt(a)).toEqual({receiptId:a.receiptId,revision});expect(consumePrivateRecordingNativeReceipt(b)).toBeNull();
 h.plugin.preparePrivate.mockResolvedValue({...h.receipt,receiptId:crypto.randomUUID()});const fresh=await prewarmPrivateRecordingNative({scope,revision},h.plugin);expect(fresh.receiptId).not.toBe(a.receiptId);expect(h.plugin.preparePrivate).toHaveBeenCalledTimes(2);
});
it('invalidates rejected, expired and changed-owner preparation rather than adopting stale receipts',async()=>{
 const h=fixture();h.plugin.preparePrivate.mockRejectedValueOnce(Error('Account proof unavailable'));await expect(prewarmPrivateRecordingNative({scope,revision},h.plugin)).rejects.toThrow();
 const first=await prewarmPrivateRecordingNative({scope,revision},h.plugin);expect(h.plugin.preparePrivate).toHaveBeenCalledTimes(2);invalidatePrivateRecordingNativeReceipt();expect(consumePrivateRecordingNativeReceipt(first)).toBeNull();
 const changed=crypto.randomUUID();h.plugin.preparePrivate.mockResolvedValue({...h.receipt,revision:changed});const other=await prewarmPrivateRecordingNative({scope,revision:changed},h.plugin);expect(consumePrivateRecordingNativeReceipt(first)).toBeNull();expect(consumePrivateRecordingNativeReceipt(other)?.revision).toBe(changed);
});
