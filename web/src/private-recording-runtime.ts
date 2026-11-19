import {vendorCanonical} from './vendor-contract';
import type {CaptureSource, CaptureSourceStartupStage, CapturedWavChunk} from '../../clients/capture/src/capture/source';
import type {CaptureCapabilities} from '../../clients/capture/src/bff/contracts';
import {acquireCaptureFlowLock,type ReleaseCaptureFlowLock} from '../../clients/capture/src/flow/capture-lock';
import type {CaptureAttestation,CaptureLanguage} from './capture-api';
import type {SecureQueuePlugin} from '../../clients/capture/plugins/secure-queue/definitions';
import type {IosPrivateRecordingReceipt} from '../../clients/capture/plugins/ios-pcm/definitions';
import {
  AUDIO_DELETED_STUB_CONTRACT,
  AUDIO_DELETED_USER_MESSAGE,
  audioRetentionEffective,
  audioRetentionEnabledAtMs,
  audioRetentionLabel,
  buildAudioTombstone,
  deletePrivateRecordingAudio,
  refuseExpiredAudio,
  resolveArmedAudioRetentionPolicy,
  sweepPrivateRecordingAudio,
  type AudioRetentionClock,
  type AudioRetentionPolicy,
} from './private-recording-retention';

const UUID=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const HASH=/^[a-f0-9]{64}$/;
const MAX_CHUNKS=360, MAX_BYTES=MAX_CHUNKS*320044;
const unavailable=()=>new Error('Private recording unavailable');
function need(condition:unknown):asserts condition {if(!condition)throw unavailable();}
const encode=(value:unknown)=>new TextEncoder().encode(JSON.stringify(value));
const hash=async(bytes:Uint8Array<ArrayBuffer>)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
let owner:PrivateRecordingRuntime|null=null;
/** Retention ON only with usable enabledAt — gates endedAt writes and delete/label. */
const retentionOn=(p:AudioRetentionPolicy|null|undefined)=>audioRetentionEnabledAtMs(p)!==null;
/** Active mic owner recording id; panel/sweep skip in-flight captures. */
export function activePrivateRecordingId():string|null{return owner?.snapshot.recordingId??null;}

export type PrivateRecordingPhase='ready'|'starting'|'recording'|'pausing'|'paused'|'stopping'|'sealed'|'interrupted'|'stop_unconfirmed'|'audio_deleted';
export type PrivateRecordingStartupStage=CaptureSourceStartupStage|'preparing_storage';
export type PrivateRecordingManifest={contract:'cosmabot.private-recording.v1';recordingId:string;scope:string;title:string;
  consent:CaptureAttestation&{language:CaptureLanguage};consentIntervals:(CaptureAttestation&{language:CaptureLanguage})[];workspaceId:string|null;createdAt:string;updatedAt:string;
  /** Optional seal/last-audio instant. Old records omit it; retention falls back to updatedAt. */
  endedAt?:string;phase:Exclude<PrivateRecordingPhase,'audio_deleted'>;
  chunks:{sequence:number;sha256:string;bytes:number;durationMs:number}[]};
export type PrivateRecordingSnapshot={recordingId:string;title:string;createdAt?:string;endedAt?:string;phase:PrivateRecordingPhase;elapsedSeconds:number;recordedChunks:number;
  inputLevel?:number;recordedBytes:number;workspaceId:string|null;busy:boolean;localOnly:true;transcription:'not_requested';failure:string|null;startupStage:PrivateRecordingStartupStage|null;
  /** Present only when both retention switches are on. */
  retentionLabel?:string|null;retentionWarn?:boolean};
export interface PrivateRecordingStore {
  read(key:string):Promise<unknown|null>;
  keys():Promise<string[]>;
  write(key:string,expected:unknown|null,value:unknown):Promise<void>;
  /** Remove one key. Idempotent when missing. Audio retention uses this for chunks/manifest only. */
  delete(key:string):Promise<void>;
  close():void;
}
export type PrivateRecordingOptions={scope:string;isCurrent:()=>boolean;signal?:AbortSignal;platform:'ios'|'desktop';
  /** Tests may inject actual PCM adapters/storage; production uses the bundled OS sources and encrypted store. */
  createSource?:(context?:{recordingId:string;scope:string;consent:CaptureAttestation&{language:CaptureLanguage}})=>Promise<CaptureSource>;openStore?:()=>Promise<PrivateRecordingStore>;acquireLock?:()=>Promise<ReleaseCaptureFlowLock>;
  nativePreparation?:()=>Pick<IosPrivateRecordingReceipt,'receiptId'|'revision'>|null;
  /** T1: both process+Box switches. Absent/unknown/false means no deletion. */
  audioRetention?:AudioRetentionPolicy|null;
  /** Live policy getter; preferred over a one-shot `audioRetention` capture. */
  getAudioRetention?:()=>AudioRetentionPolicy|null|undefined;
  now?:AudioRetentionClock;
};
export type PrivateRecordingNativeReceipt=IosPrivateRecordingReceipt;
export async function prewarmPrivateRecordingNative(options:{scope:string;revision:string}):Promise<PrivateRecordingNativeReceipt>{
  return (await import('../../clients/capture/src/native/private-recording-source')).prewarmPrivateRecordingNative(options);
}

export async function consumePrivateRecordingNativeReceipt(receipt:PrivateRecordingNativeReceipt):Promise<Pick<PrivateRecordingNativeReceipt,'receiptId'|'revision'>|null>{
  return (await import('../../clients/capture/src/native/private-recording-source')).consumePrivateRecordingNativeReceipt(receipt);
}
export async function invalidatePrivateRecordingNativeReceipt():Promise<void>{
  (await import('../../clients/capture/src/native/private-recording-source')).invalidatePrivateRecordingNativeReceipt();
}

export function validatePrivateRecordingConsent(value:unknown):asserts value is CaptureAttestation&{language:CaptureLanguage} {
  need(closed(value,'modality,participant_regions,method,all_parties_consented,granted_at,language')&&value.all_parties_consented===true&&value.method==='verbal_attestation'&&['in_person','virtual','phone'].includes(String(value.modality))&&['en-US','en-US+es-US'].includes(String(value.language)));
  need(typeof value.granted_at==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(value.granted_at)&&new Date(value.granted_at).toISOString()===value.granted_at&&Date.parse(value.granted_at)<=Date.now());
  need(Array.isArray(value.participant_regions)&&value.participant_regions.length<=16&&new Set(value.participant_regions).size===value.participant_regions.length&&value.participant_regions.every(r=>typeof r==='string'&&/^[A-Z]{2}(?:-[A-Z0-9]{1,3})?$/.test(r)));
}

function manifest(value:unknown,scope:string,id:string):PrivateRecordingManifest {
  const base='chunks,consent,consentIntervals,contract,createdAt,phase,recordingId,scope,title,updatedAt,workspaceId';
  const withEnded=(base+',endedAt').split(',').sort().join(',');
  const required=base.split(',').sort().join(',');
  need(!!value&&typeof value==='object'&&!Array.isArray(value));
  const keys=Object.keys(value as object).sort().join(',');
  need((keys===required||keys===withEnded)&&(value as {contract:unknown}).contract==='cosmabot.private-recording.v1'&&(value as {scope:unknown}).scope===scope&&(value as {recordingId:unknown}).recordingId===id&&UUID.test(id));
  const row=value as Record<string,unknown>;
  need(typeof row.title==='string'&&row.title.trim()===row.title&&row.title.length>0&&row.title.length<=160&&!/[\u0000-\u001f]/.test(row.title));
  validatePrivateRecordingConsent(row.consent);need(Array.isArray(row.consentIntervals)&&row.consentIntervals.length<=1000);row.consentIntervals.forEach(validatePrivateRecordingConsent);need(row.workspaceId===null||typeof row.workspaceId==='string'&&UUID.test(row.workspaceId));
  need(['createdAt','updatedAt'].every(k=>typeof row[k]==='string'&&Number.isFinite(Date.parse(row[k] as string))));
  if('endedAt' in row)need(typeof row.endedAt==='string'&&Number.isFinite(Date.parse(row.endedAt)));
  need(typeof row.phase==='string'&&['ready','starting','recording','pausing','paused','stopping','sealed','interrupted','stop_unconfirmed'].includes(row.phase));
  need(Array.isArray(row.chunks)&&row.chunks.length<=MAX_CHUNKS);
  let total=0;
  (row.chunks as unknown[]).forEach((chunk:unknown,index:number)=>{
    need(closed(chunk,'sequence,sha256,bytes,durationMs')&&chunk.sequence===index&&typeof chunk.sha256==='string'&&HASH.test(chunk.sha256)&&Number.isSafeInteger(chunk.bytes)&&Number(chunk.bytes)>=46&&Number(chunk.bytes)<=320044&&typeof chunk.durationMs==='number'&&chunk.durationMs>0&&chunk.durationMs<=10000);
    total+=Number(chunk.bytes);
  });
  need(total<=MAX_BYTES);
  return structuredClone(row) as PrivateRecordingManifest;
}
function displayTitle(value:unknown,scope:string,id:string):string|null {
  if(value===null)return null;
  need(closed(value,'contract,scope,recordingId,title')&&value.contract==='cosmabot.recording-title.v1'&&value.scope===scope&&value.recordingId===id&&typeof value.title==='string'&&value.title===value.title.trim()&&value.title.length>0&&value.title.length<=160&&!/[\u0000-\u001f]/.test(value.title));
  return value.title as string;
}
function pcm(bytes:Uint8Array<ArrayBuffer>,durationMs:number):void {
  need(bytes.buffer instanceof ArrayBuffer&&bytes.byteOffset===0&&bytes.byteLength===bytes.buffer.byteLength&&bytes.length>=46&&bytes.length<=320044);
  const d=new DataView(bytes.buffer),text=(offset:number,count:number)=>String.fromCharCode(...bytes.subarray(offset,offset+count));
  need(text(0,4)==='RIFF'&&d.getUint32(4,true)===bytes.length-8&&text(8,4)==='WAVE'&&text(12,4)==='fmt '&&d.getUint32(16,true)===16&&d.getUint16(20,true)===1&&d.getUint16(22,true)===1&&d.getUint32(24,true)===16000&&d.getUint32(28,true)===32000&&d.getUint16(32,true)===2&&d.getUint16(34,true)===16&&text(36,4)==='data'&&d.getUint32(40,true)===bytes.length-44&&(bytes.length-44)%2===0&&durationMs===(bytes.length-44)/32);
}
function base64(bytes:Uint8Array):string {let text='';for(const byte of bytes)text+=String.fromCharCode(byte);return btoa(text);}
function decode(value:unknown,maximum:number):Uint8Array<ArrayBuffer>{need(typeof value==='string'&&value.length<=Math.ceil(maximum/3)*4&&/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value));const bytes=Uint8Array.from(atob(value),c=>c.charCodeAt(0));need(bytes.length<=maximum&&base64(bytes)===value);return bytes;}

/** No CaptureBff, fetch, patient ID, lease, reservation, upload or model admission exists in this runtime. */
export class PrivateRecordingRuntime {
  private source:CaptureSource|null=null;
  private inputLevel=0;
  private releaseLock:ReleaseCaptureFlowLock|null=null;
  private generation=0;
  private stopFlight:Promise<void>|null=null;
  private chain:Promise<void>=Promise.resolve();
  private listeners=new Set<(snapshot:PrivateRecordingSnapshot)=>void>();
  private active=true;
  private storageFailed=false;
  private intervalSequence=0;
  private failure:string|null=null;
  private startupStage:PrivateRecordingStartupStage|null=null;
  private audioDeleted=false;
  /** Device armedAt resolved once at open; merged into live policy for label/refuse parity with sweep. */
  private deviceArmedAt:string|null=null;
  private constructor(private options:PrivateRecordingOptions,private store:PrivateRecordingStore,private saved:PrivateRecordingManifest,private displayTitle:string|null=null){options.signal?.addEventListener('abort',this.onAbort,{once:true});}
  /** Live policy each call; merges resolved deviceArmedAt so label honors the grace window. */
  private policy():AudioRetentionPolicy|null|undefined{
    const base=this.options.getAudioRetention?this.options.getAudioRetention():this.options.audioRetention;
    if(!retentionOn(base))return base;
    return this.deviceArmedAt?{...base!,deviceArmedAt:this.deviceArmedAt}:base;
  }
  static async open(options:PrivateRecordingOptions,input:{recordingId?:string;title:string;consent?:CaptureAttestation&{language:CaptureLanguage}}):Promise<PrivateRecordingRuntime>{
    need(HASH.test(options.scope)&&options.isCurrent()&&!options.signal?.aborted);
    if(input.consent)validatePrivateRecordingConsent(input.consent);const id=input.recordingId??crypto.randomUUID();need(UUID.test(id));
    // Capture once for back-compat when only `audioRetention` is supplied (no live getter).
    const resolved:PrivateRecordingOptions=options.getAudioRetention?options:{...options,audioRetention:options.audioRetention};
    const bag=()=>resolved.getAudioRetention?resolved.getAudioRetention():resolved.audioRetention;
    const store=await(options.openStore?.()??openPrivateRecordingStore(options.scope,options.platform));
    try{
      need(options.isCurrent()&&!options.signal?.aborted);
      const nowMs=options.now?.()??Date.now();
      // Resolve armed once per open so refuse/label agree with sweep; clears stamp when policy off.
      const armed=await resolveArmedAudioRetentionPolicy(store,bag(),nowMs);
      const armedAt=typeof armed?.deviceArmedAt==='string'?armed.deviceArmedAt:null;
      let saved=await store.read('manifest:'+id);
      if(saved===null){
        const stub=await store.read('audio-deleted:'+id);
        if(stub&&typeof stub==='object'&&(stub as {contract?:unknown}).contract===AUDIO_DELETED_STUB_CONTRACT
          &&(stub as {recordingId?:unknown}).recordingId===id&&(stub as {scope?:unknown}).scope===options.scope
          &&(stub as {phase?:unknown}).phase==='audio_deleted'){
          const updatedAt=typeof (stub as {updatedAt?:unknown}).updatedAt==='string'?(stub as {updatedAt:string}).updatedAt:new Date(nowMs).toISOString();
          const renamed=displayTitle(await store.read('display-title:'+id),options.scope,id);
          const placeholder:PrivateRecordingManifest={contract:'cosmabot.private-recording.v1',recordingId:id,scope:options.scope,title:input.title||'Private recording',
            consent:{modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:updatedAt,language:'en-US'},
            consentIntervals:[],workspaceId:null,createdAt:updatedAt,updatedAt,phase:'sealed',chunks:[]};
          const runtime=new PrivateRecordingRuntime(resolved,store,placeholder,renamed);
          runtime.audioDeleted=true;runtime.failure=AUDIO_DELETED_USER_MESSAGE;runtime.deviceArmedAt=armedAt;return runtime;
        }
        validatePrivateRecordingConsent(input.consent);const now=new Date(nowMs).toISOString();saved={contract:'cosmabot.private-recording.v1',recordingId:id,scope:options.scope,title:input.title,consent:structuredClone(input.consent),consentIntervals:[],workspaceId:null,createdAt:now,updatedAt:now,phase:'ready',chunks:[]};manifest(saved,options.scope,id);await store.write('manifest:'+id,null,saved);}
      const checked=manifest(saved,options.scope,id),renamed=displayTitle(await store.read('display-title:'+id),options.scope,id);need(options.isCurrent()&&!options.signal?.aborted);
      // A prior renderer's active phase cannot establish physical cessation or auto-resume.
      if(['starting','recording','pausing','stopping','stop_unconfirmed'].includes(checked.phase)){
        const source=await(options.createSource?.()??privateRecordingRecoverySource(options.platform));need(source.kind==='microphone'&&!owner&&await source.confirmRecoveryClosed?.()===true);
        need(options.isCurrent()&&!options.signal?.aborted);
        const updatedAt=new Date(nowMs).toISOString();
        const next:PrivateRecordingManifest={...checked,phase:'interrupted' as const,updatedAt,
          ...(retentionOn(armed)?{endedAt:checked.endedAt??updatedAt}:{})};
        await store.write('manifest:'+id,checked,next);
        const runtime=new PrivateRecordingRuntime(resolved,store,next,renamed);runtime.deviceArmedAt=armedAt;return runtime;
      }
      if(retentionOn(armed))refuseExpiredAudio(checked,nowMs,armed);
      const runtime=new PrivateRecordingRuntime(resolved,store,checked,renamed);runtime.deviceArmedAt=armedAt;return runtime;
    }catch(error){store.close();throw error;}
  }
  get snapshot():PrivateRecordingSnapshot{
    const base={recordingId:this.saved.recordingId,title:this.displayTitle??this.saved.title,createdAt:this.saved.createdAt,endedAt:this.saved.endedAt,phase:this.audioDeleted?'audio_deleted' as const:this.saved.phase,inputLevel:this.saved.phase==='recording'?this.inputLevel:0,
      elapsedSeconds:this.saved.chunks.reduce((sum,c)=>sum+c.durationMs,0)/1000,recordedChunks:this.saved.chunks.length,
      recordedBytes:this.saved.chunks.reduce((sum,c)=>sum+c.bytes,0),workspaceId:this.saved.workspaceId,busy:['starting','pausing','stopping'].includes(this.saved.phase),localOnly:true as const,transcription:'not_requested' as const,failure:this.failure,startupStage:this.startupStage};
    if(this.audioDeleted)return {...base,retentionLabel:AUDIO_DELETED_USER_MESSAGE,retentionWarn:false};
    if(!retentionOn(this.policy()))return base;
    const label=audioRetentionLabel(this.saved,this.clock(),this.policy());
    return {...base,retentionLabel:label?.text??null,retentionWarn:label?.warn??false};
  }
  subscribe(listener:(snapshot:PrivateRecordingSnapshot)=>void):()=>void{this.current();this.listeners.add(listener);listener(this.snapshot);return()=>this.listeners.delete(listener);}
  private publish(){for(const listener of this.listeners)try{listener(this.snapshot);}catch{/* Observer isolation. */}}
  private reportStartup(stage:PrivateRecordingStartupStage,ticket:number,source?:CaptureSource){
    if(!this.active||!this.options.isCurrent()||this.options.signal?.aborted||ticket!==this.generation||this.stopFlight||source&&(this.source!==source||this.startupStage===null))return;
    this.startupStage=stage;this.publish();
  }
  private current(){need(this.active&&this.options.isCurrent()&&!this.options.signal?.aborted);}
  private async makeSource(consent:CaptureAttestation&{language:CaptureLanguage}){const context={recordingId:this.saved.recordingId,scope:this.saved.scope,consent};
    const source=await(this.options.createSource?.(context)??privateRecordingSource(this.options.platform,context,this.options.nativePreparation?.()??null));need(source.kind==='microphone');return source;}
  private enqueue(task:()=>Promise<void>):Promise<void>{const next=this.chain.catch(()=>{}).then(task);this.chain=next;return next;}
  private clock(){return this.options.now?.()??Date.now();}
  private stamp(){return new Date(this.clock()).toISOString();}
  private async update(phase:Exclude<PrivateRecordingPhase,'audio_deleted'>){await this.enqueue(async()=>{
    const updatedAt=this.stamp();
    // Terminal phases pin endedAt once when retention is ON. Metadata-only never moves it.
    const pin=retentionOn(this.policy())&&['sealed','interrupted','stop_unconfirmed'].includes(phase);
    const next:PrivateRecordingManifest={...this.saved,phase,updatedAt,
      ...(pin?{endedAt:this.saved.endedAt??updatedAt}:{})};
    await this.store.write('manifest:'+this.saved.recordingId,this.saved,next);this.saved=next;this.publish();
  });}
  async start(consent:CaptureAttestation&{language:CaptureLanguage}):Promise<void>{
    validatePrivateRecordingConsent(consent);need(Date.now()-Date.parse(consent.granted_at)<=300000);
    this.current();need(!this.storageFailed&&!this.source&&!this.stopFlight&&(!owner||owner===this)&&['ready','paused','interrupted'].includes(this.saved.phase)&&this.saved.chunks.length<MAX_CHUNKS);
    owner=this;const ticket=++this.generation;
    this.failure=null;
    try{
      this.reportStartup('physical_exclusion',ticket);
      const release=await(this.options.acquireLock?.()??acquireCaptureFlowLock());
      if(ticket!==this.generation){await release();return;}this.releaseLock=release;this.current();
      this.reportStartup('preparing_storage',ticket);
      await this.enqueue(async()=>{const next:PrivateRecordingManifest={...this.saved,consentIntervals:[...this.saved.consentIntervals,structuredClone(consent)],phase:'starting' as const,updatedAt:this.stamp()};need(next.consentIntervals.length<=1000);await this.store.write('manifest:'+this.saved.recordingId,this.saved,next);this.saved=next;this.publish();});this.intervalSequence=0;
      const source=await this.makeSource(consent);this.current();need(ticket===this.generation);this.source=source;
      const remaining=Math.min(90,MAX_CHUNKS-this.saved.chunks.length);
      // These are local PCM adapter bounds, not fabricated Core capabilities/lease receipts.
      const limits:CaptureCapabilities={protocol_version:'1.0',media:{media_type:'audio/wav',encoding:'pcm_s16le',sample_rate_hz:16000,channels:1},
        target_chunk_duration_ms:10000,max_chunks:remaining,max_envelope_bytes:320044,remaining_aggregate_plaintext_bytes:remaining*320044,
        capture_lease_ttl_seconds:900,reservation_window_seconds:900,max_reservations_per_batch:1,upload_concurrency:1};
      await source.start({capabilities:limits,onChunk:chunk=>this.acceptChunk(chunk,ticket),
        onInputLevel:level=>{if(this.active&&this.options.isCurrent()&&ticket===this.generation&&this.source===source&&Number.isFinite(level)){this.inputLevel=Math.max(0,Math.min(1,level));this.publish();}},
        onStartupStage:stage=>{if(['native_session','physical_exclusion','microphone_permission','audio_engine'].includes(stage)&&this.saved.phase==='starting')this.reportStartup(stage,ticket,source);},
        onInterruption:code=>{this.failure=code;void this.pause().catch(()=>{});},onError:()=>{this.failure='audio_source_failed';void this.pause().catch(()=>{});},
        onWindowClosed:()=>{void this.pause().catch(()=>{});}});
      this.current();if(ticket!==this.generation||this.stopFlight)return;this.startupStage=null;await this.update('recording');
    }catch(error){
      if(ticket===this.generation)this.startupStage=null;
      this.failure??=error&&typeof error==='object'&&'code' in error&&['audio_capture_permission_denied','audio_capture_device_unavailable'].includes(String(error.code))?String(error.code):'recording_start_unconfirmed';
      if(this.source)await this.halt(false).catch(()=>{});
      else if(ticket===this.generation){await this.release();await this.update('interrupted');}
      throw error;
    }
  }
  private async acceptChunk(chunk:CapturedWavChunk,ticket:number){
    const bytes=chunk.wavBytes;
    try{
      this.current();need(ticket===this.generation&&!this.storageFailed&&chunk.sequenceNumber===this.intervalSequence);pcm(bytes,chunk.durationMs);const digest=await hash(bytes);
      await this.enqueue(async()=>{
        this.current();need(ticket===this.generation&&this.saved.chunks.length<MAX_CHUNKS&&this.snapshot.recordedBytes+bytes.length<=MAX_BYTES);
        const sequence=this.saved.chunks.length,key='chunk:'+this.saved.recordingId+':'+sequence;
        const record={contract:'cosmabot.private-pcm.v1',recordingId:this.saved.recordingId,scope:this.saved.scope,sequence,sha256:digest,durationMs:chunk.durationMs,data:base64(bytes)};
        // An orphan chunk after an interrupted manifest CAS is never overwritten or counted as committed.
        await this.store.write(key,null,record);
        const updatedAt=this.stamp();
        // Last audio write anchors retention when ON; metadata cannot push the deadline.
        const next:PrivateRecordingManifest={...this.saved,updatedAt,chunks:[...this.saved.chunks,{sequence,sha256:digest,bytes:bytes.length,durationMs:chunk.durationMs}],
          ...(retentionOn(this.policy())?{endedAt:updatedAt}:{})};
        await this.store.write('manifest:'+this.saved.recordingId,this.saved,next);this.saved=next;this.intervalSequence++;this.publish();
      });
    }catch(error){this.storageFailed=true;this.failure='audio_storage_unconfirmed';throw error;}
    finally{bytes.fill(0);}
  }
  async rename(title:string):Promise<void>{
    this.current();need(['sealed','paused','interrupted'].includes(this.saved.phase));
    const key='display-title:'+this.saved.recordingId,prior=await this.store.read(key);
    const next={contract:'cosmabot.recording-title.v1',scope:this.saved.scope,recordingId:this.saved.recordingId,title:title.trim()};
    displayTitle(next,this.saved.scope,this.saved.recordingId);this.current();
    await this.store.write(key,prior,next);this.current();this.displayTitle=next.title;this.publish();
  }
  pause():Promise<void>{return this.halt(false);}
  stop():Promise<void>{return this.halt(true);}
  private halt(seal:boolean):Promise<void>{
    if(this.startupStage!==null){this.startupStage=null;this.publish();}
    if(this.stopFlight)return this.stopFlight.then(()=>seal&&this.saved.phase!=='sealed'?this.halt(true):undefined);
    if(!this.source){need(this.active);if(this.saved.phase==='sealed')return Promise.resolve();++this.generation;return this.release().then(()=>this.update(seal?'sealed':'paused'));}
    const source=this.source;
    const task=(async()=>{
      // Stop is usable during permission/start and never waits for Start to settle.
      // Observe rejection immediately, while durable status writes may still be pending.
      const stopped=(()=>{try{return source.stop().then(()=>({ok:true as const}),error=>({ok:false as const,error}));}catch(error){return Promise.resolve({ok:false as const,error});}})();
      await this.update(seal?'stopping':'pausing').catch(()=>{this.storageFailed=true;this.failure='audio_storage_unconfirmed';});
      const result=await stopped;
      if(!result.ok){this.failure='physical_stop_unconfirmed';await this.update('stop_unconfirmed').catch(()=>{});throw result.error;}
      await this.chain.catch(()=>{});this.source=null;await this.release();++this.generation;
      try{await this.update(this.storageFailed?'interrupted':seal?'sealed':'paused');}
      catch(error){this.storageFailed=true;this.failure='audio_storage_unconfirmed';throw error;}
    })();this.stopFlight=task;void task.finally(()=>{if(this.stopFlight===task)this.stopFlight=null;}).catch(()=>{});return task;
  }
  /** Inspect saved audio locally; callers must perform a separate explicit patient-link workflow before transfer. */
  async *savedChunks(first=0):AsyncGenerator<{sequence:number;sha256:string;wavBytes:Uint8Array<ArrayBuffer>},void,unknown> {
    this.current();need(!this.source&&['sealed','paused','interrupted'].includes(this.saved.phase));
    need(Number.isSafeInteger(first)&&first>=0&&first<=this.saved.chunks.length);
    for(const expected of this.saved.chunks.slice(first)){this.current();const row=await this.store.read('chunk:'+this.saved.recordingId+':'+expected.sequence);
      need(closed(row,'contract,recordingId,scope,sequence,sha256,durationMs,data')&&row.contract==='cosmabot.private-pcm.v1'&&row.recordingId===this.saved.recordingId&&row.scope===this.saved.scope&&row.sequence===expected.sequence&&row.sha256===expected.sha256&&row.durationMs===expected.durationMs);
      const bytes=decode(row.data,320044);try{pcm(bytes,expected.durationMs);need(bytes.length===expected.bytes&&await hash(bytes)===expected.sha256);this.current();yield {sequence:expected.sequence,sha256:expected.sha256,wavBytes:bytes};}finally{bytes.fill(0);}}
  }
  /** A human-confirmed OS private-notebook mapping. Does not upload, transcribe or link a patient. */
  async attachWorkspace(workspaceId:string,confirmed:true):Promise<void>{
    this.current();need(confirmed===true&&UUID.test(workspaceId));
    await this.enqueue(async()=>{this.current();need(this.saved.workspaceId===null||this.saved.workspaceId===workspaceId);if(this.saved.workspaceId===workspaceId)return;
      // Metadata-only: do not update endedAt (deadline must not move).
      const next:PrivateRecordingManifest={...this.saved,workspaceId,updatedAt:this.stamp()};await this.store.write('manifest:'+this.saved.recordingId,this.saved,next);this.saved=next;this.publish();});
  }
  /** Build a verified private WAV for local playback/download. No network or automatic transfer. */
  async exportWav():Promise<{blob:Blob;sha256:string;bytes:number;durationMs:number;hasNonzeroAudio:boolean}>{
    this.current();need(!this.source&&this.saved.chunks.length>0&&['sealed','paused','interrupted'].includes(this.saved.phase));
    const length=this.saved.chunks.reduce((sum,c)=>sum+c.bytes-44,0),out=new Uint8Array(44+length),view=new DataView(out.buffer);
    const put=(offset:number,text:string)=>{for(let i=0;i<text.length;i++)out[offset+i]=text.charCodeAt(i);};
    put(0,'RIFF');view.setUint32(4,out.length-8,true);put(8,'WAVE');put(12,'fmt ');view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);put(36,'data');view.setUint32(40,length,true);
    try{let offset=44;for await(const chunk of this.savedChunks()){out.set(chunk.wavBytes.subarray(44),offset);offset+=chunk.wavBytes.length-44;}this.current();need(offset===out.length);const sha256=await hash(out),hasNonzeroAudio=out.subarray(44).some(value=>value!==0);return {blob:new Blob([out],{type:'audio/wav'}),sha256,bytes:out.length,durationMs:length/32,hasNonzeroAudio};}
    finally{out.fill(0);}
  }
  async close():Promise<void>{if(!this.active)return;await this.stop();this.active=false;this.options.signal?.removeEventListener('abort',this.onAbort);this.listeners.clear();this.store.close();}
  /** Metadata-only durable source commitment; ledger hash excludes endedAt (retention clock). */
  async snapshotForLedger():Promise<{recordingId:string;scope:string;consent:PrivateRecordingManifest['consent'];consentIntervals:PrivateRecordingManifest['consentIntervals'];startedAt:string|null;phase:PrivateRecordingPhase;frames:number;chunks:number;manifestSHA256:string;updatedAt:string}>{
    this.current();await this.chain;this.current();const retained=structuredClone(this.saved);delete retained.endedAt;
    const bytes=encode(retained);
    try{return {recordingId:retained.recordingId,scope:retained.scope,consent:retained.consent,consentIntervals:retained.consentIntervals,startedAt:retained.consentIntervals[0]?.granted_at??null,phase:retained.phase,frames:retained.chunks.reduce((n,c)=>n+(c.bytes-44)/2,0),chunks:retained.chunks.length,manifestSHA256:await hash(bytes),updatedAt:retained.updatedAt};}finally{bytes.fill(0);}
  }
  /** Stable sealed-audio lineage excludes later display/title/notebook organization. Ledger semantics remain unchanged. */
  async snapshotForPrivateTranscript():Promise<{recordingId:string;scope:string;consent:PrivateRecordingManifest['consent'];phase:PrivateRecordingPhase;frames:number;chunks:number;audioSHA256:string}>{
    this.current();await this.chain;this.current();need(!this.source&&this.saved.phase==='sealed');const retained=structuredClone(this.saved);
    const bytes=new TextEncoder().encode(vendorCanonical({contract:'cosmabot.private-speech-source.v1',recordingId:retained.recordingId,scope:retained.scope,createdAt:retained.createdAt,consent:retained.consent,consentIntervals:retained.consentIntervals,chunks:retained.chunks}));
    try{const audioSHA256=await hash(bytes);this.current();return {recordingId:retained.recordingId,scope:retained.scope,consent:retained.consent,phase:retained.phase,frames:retained.chunks.reduce((n,c)=>n+(c.bytes-44)/2,0),chunks:retained.chunks.length,audioSHA256};}finally{bytes.fill(0);}
  }
  private async release(){const release=this.releaseLock;this.releaseLock=null;if(owner===this)owner=null;await release?.();}
  private onAbort=()=>{void this.pause().catch(()=>{});};
}

async function privateRecordingRecoverySource(platform:'ios'|'desktop'):Promise<CaptureSource>{
  if(platform==='ios'){const {createCapacitorIosNativeMicrophoneCaptureSource}=await import('../../clients/capture/src/native/capacitor-ios-native-pcm-bridge');return createCapacitorIosNativeMicrophoneCaptureSource();}
  return privateRecordingSource(platform);
}
export async function privateRecordingSource(platform:'ios'|'desktop',context?:{recordingId:string;scope:string;consent:CaptureAttestation&{language:CaptureLanguage}},receipt:Pick<IosPrivateRecordingReceipt,'receiptId'|'revision'>|null=null):Promise<CaptureSource>{
  if(platform==='ios'){need(context&&receipt);const {privateIosRecordingSource}=await import('../../clients/capture/src/native/private-recording-source');return privateIosRecordingSource({...context,receipt});}
  const {BrowserMicrophoneCaptureSource}=await import('../../clients/capture/src/audio/browser-microphone-source');
  const {privateDesktopRecordingSource}=await import('./private-recording-desktop');
  return privateDesktopRecordingSource(new BrowserMicrophoneCaptureSource(),context);
}

/** Same device-only native SecureQueue custody; desktop gets a separate AES-GCM origin store. */
export async function openPrivateRecordingStore(scope:string,platform:'ios'|'desktop',deps:{indexedDB?:IDBFactory;crypto?:Crypto;native?:SecureQueuePlugin}={}):Promise<PrivateRecordingStore>{
  need(HASH.test(scope));
  const crypt=deps.crypto??globalThis.crypto;need(crypt?.subtle);
  const name='cosmas-private-recording:v1:'+scope;
  const validKey=(key:string)=>key==='audio-retention-armed'||/^(?:(?:manifest|ledger|transfer|transfer-retention-released|visit-binding|display-title|private-transcript|audio-tombstone|audio-deleted):[a-f0-9-]{36}|chunk:[a-f0-9-]{36}:[0-9]{1,3})$/.test(key);
  const serialize=(value:unknown)=>{const bytes=encode(value);need(bytes.length<=450000);return bytes;};
  if(platform==='ios'){
    const plugin=deps.native??(await import('../../clients/capture/plugins/secure-queue')).SecureQueue;
    let active=true;
    const read=async(key:string)=>{need(active&&validKey(key));try{const row=await plugin.get({key:name+':'+key});need(row.key===name+':'+key&&/^[1-9][0-9]*$/.test(row.revision));const bytes=decode(row.data,450000);try{return {revision:row.revision,value:JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes))};}finally{bytes.fill(0);}}catch(error){if(error&&typeof error==='object'&&'code'in error&&error.code==='SECURE_QUEUE_NOT_FOUND')return null;throw error;}};
    return {keys:async()=>{need(active);const result=await plugin.list();need(Array.isArray(result.keys)&&result.keys.length<=10000);return result.keys.filter(k=>k.startsWith(name+':')).map(k=>k.slice(name.length+1));},read:async key=>(await read(key))?.value??null,write:async(key,expected,value)=>{
      const prior=await read(key);need(JSON.stringify(prior?.value??null)===JSON.stringify(expected));const bytes=serialize(value),data=base64(bytes);bytes.fill(0);
      try{if(prior)await plugin.compareAndSwap({key:name+':'+key,data,expectedRevision:prior.revision});else await plugin.create({key:name+':'+key,data});}
      catch(error){const observed=await read(key);if(JSON.stringify(observed?.value)!==JSON.stringify(value))throw error;}
    },delete:async(key)=>{need(active&&validKey(key));const prior=await read(key);if(prior===null)return;await plugin.delete({key:name+':'+key});},close(){active=false;}};
  }
  const factory=deps.indexedDB??globalThis.indexedDB;need(factory);
  const result=<T,>(request:IDBRequest<T>)=>new Promise<T>((resolve,reject)=>{request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(unavailable());});
  const done=(tx:IDBTransaction)=>new Promise<void>((resolve,reject)=>{tx.oncomplete=()=>resolve();tx.onabort=tx.onerror=()=>reject(unavailable());});
  const request=factory.open(name,1);request.onupgradeneeded=()=>{request.result.createObjectStore('records',{keyPath:'key'});request.result.createObjectStore('metadata');};
  request.onblocked=()=>request.onerror?.(new Event('error'));
  const db=await result(request);let active=true;db.onversionchange=()=>{active=false;db.close();};
  try{
    const tx=db.transaction('metadata','readonly'),settled=done(tx),existing=await result(tx.objectStore('metadata').get('key'));await settled;
    let key=existing as CryptoKey|undefined;
    if(!key){const records=db.transaction('records','readonly'),counted=done(records),count=await result(records.objectStore('records').count());await counted;need(count===0);
      const generated=await crypt.subtle.generateKey({name:'AES-GCM',length:256},false,['encrypt','decrypt']);const write=db.transaction('metadata','readwrite'),committed=done(write),current=write.objectStore('metadata').get('key');current.onsuccess=()=>{if(current.result)key=current.result as CryptoKey;else{key=generated;write.objectStore('metadata').add(generated,'key');}};await committed;}
    need(key&&key.type==='secret'&&!key.extractable&&key.algorithm.name==='AES-GCM'&&(key.algorithm as AesKeyAlgorithm).length===256&&key.usages.includes('encrypt')&&key.usages.includes('decrypt'));const cipher=key;
    const read=async(id:string)=>{need(active&&validKey(id));const tx=db.transaction('records','readonly'),committed=done(tx),row=await result(tx.objectStore('records').get(id));await committed;if(!row)return null;
      need(closed(row,'key,revision,nonce,ciphertext')&&row.key===id&&Number.isSafeInteger(row.revision)&&Number(row.revision)>0&&row.nonce instanceof Uint8Array&&row.nonce.length===12&&row.ciphertext instanceof ArrayBuffer&&row.ciphertext.byteLength<=450016);
      const plain=new Uint8Array(await crypt.subtle.decrypt({name:'AES-GCM',iv:new Uint8Array(row.nonce),additionalData:encode([name,id,row.revision])},cipher,row.ciphertext));
      try{return {revision:Number(row.revision),value:JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(plain))};}finally{plain.fill(0);}};
    return {keys:async()=>{need(active);const tx=db.transaction('records','readonly'),settled=done(tx),keys=await result(tx.objectStore('records').getAllKeys());await settled;need(keys.length<=10000&&keys.every(k=>typeof k==='string'));return keys as string[];},read:async id=>(await read(id))?.value??null,write:async(id,expected,value)=>{const prior=await read(id);need(JSON.stringify(prior?.value??null)===JSON.stringify(expected));const revision=(prior?.revision??0)+1,nonce=crypt.getRandomValues(new Uint8Array(12)),plain=serialize(value);let ciphertext:ArrayBuffer;
      try{ciphertext=await crypt.subtle.encrypt({name:'AES-GCM',iv:nonce,additionalData:encode([name,id,revision])},cipher,plain);}finally{plain.fill(0);}
      const tx=db.transaction('records','readwrite'),committed=done(tx),lookup=tx.objectStore('records').get(id);lookup.onsuccess=()=>{if((lookup.result?.revision??null)!==(prior?.revision??null)){tx.abort();return;}tx.objectStore('records').put({key:id,revision,nonce,ciphertext});};await committed;
    },delete:async(id)=>{need(active&&validKey(id));const prior=await read(id);if(prior===null)return;
      const tx=db.transaction('records','readwrite'),committed=done(tx),lookup=tx.objectStore('records').get(id);
      lookup.onsuccess=()=>{if(!lookup.result)return;if(lookup.result.revision!==prior.revision){tx.abort();return;}tx.objectStore('records').delete(id);};await committed;
    },close(){active=false;db.close();}};
  }catch(error){db.close();throw error;}
}

export type ListPrivateRecordingsOptions={
  openStore?:()=>Promise<PrivateRecordingStore>;
  audioRetention?:AudioRetentionPolicy|null;
  now?:AudioRetentionClock;
  /** Extra recording ids to skip (e.g. the panel's currently open recording). */
  skipRecordingIds?:Iterable<string>;
};

/** Marker written only after a confirmed import success while retention is on. Never deletes transfer:. */
export const TRANSFER_RETENTION_RELEASED_CONTRACT='cosmabot.private-recording-transfer-retention-released.v1';
export function transferRetentionReleasedKey(recordingId:string){return 'transfer-retention-released:'+recordingId;}
export async function isTransferRetentionReleased(store:PrivateRecordingStore,recordingId:string):Promise<boolean>{
  const row=await store.read(transferRetentionReleasedKey(recordingId));
  return !!row&&typeof row==='object'&&(row as {contract?:unknown}).contract===TRANSFER_RETENTION_RELEASED_CONTRACT;
}
/** Ends transfer protection without deleting the panel's transfer:<id> row. */
export async function markTransferRetentionReleased(store:PrivateRecordingStore,recordingId:string,releasedAtIso:string):Promise<void>{
  const key=transferRetentionReleasedKey(recordingId),prior=await store.read(key);
  await store.write(key,prior,{contract:TRANSFER_RETENTION_RELEASED_CONTRACT,recordingId,releasedAt:releasedAtIso});
}
/** Clear release marker so a renew-consent re-import is protected again until success. */
export async function clearTransferRetentionReleased(store:PrivateRecordingStore,recordingId:string):Promise<void>{
  try{await store.delete(transferRetentionReleasedKey(recordingId));}catch{/* best-effort */}
}

/**
 * Skip active owner, ledger attach/finish pending, and in-flight transfer imports.
 * transfer: protects only while present AND not retention-released. Unreadable ledger/marker → skip.
 */
export async function audioSweepSkipIds(store:PrivateRecordingStore,extra?:Iterable<string>):Promise<Set<string>>{
  const skip=new Set<string>();const active=activePrivateRecordingId();if(active)skip.add(active);
  if(extra)for(const id of extra)if(id)skip.add(id);
  for(const key of await store.keys()){
    if(key.startsWith('transfer:')){
      const recordingId=key.slice('transfer:'.length);
      try{
        if(!(await isTransferRetentionReleased(store,recordingId)))skip.add(recordingId);
      }catch{skip.add(recordingId);}
      continue;
    }
    if(!key.startsWith('ledger:'))continue;
    try{
      const row=await store.read(key);const state=row&&typeof row==='object'&&'state' in row?String((row as {state:unknown}).state):'';
      if(state==='attach_pending'||state==='finish_pending')skip.add(key.slice(7));
    }catch{skip.add(key.slice(7));}
  }
  return skip;
}

/** True when sweep/refuse must not delete this recording (owner, pending ledger, or unreleased transfer). */
export async function isAudioRetentionProtected(store:PrivateRecordingStore,recordingId:string):Promise<boolean>{
  return (await audioSweepSkipIds(store)).has(recordingId);
}

async function writeAudioTombstone(store:PrivateRecordingStore,id:string,outcome:'deleted'|'failed',iso:string){
  const key='audio-tombstone:'+id,prior=await store.read(key);
  await store.write(key,prior,buildAudioTombstone(id,iso,outcome));
}

/** Shared sweep hooks: skip in-flight work; tombstone on success (stub written before manifest delete). */
function audioSweepHooks(store:PrivateRecordingStore,_scope:string,now:AudioRetentionClock,skip:Set<string>){
  return {
    shouldSkipRecording:(recordingId:string)=>skip.has(recordingId),
    onDeleted:async(recordingId:string)=>{
      // Overwrites any prior failed tombstone at the same key.
      await writeAudioTombstone(store,recordingId,'deleted',new Date(now()).toISOString());
    },
    recordFailure:(recordingId:string)=>{void writeAudioTombstone(store,recordingId,'failed',new Date(now()).toISOString()).catch(()=>{});},
  };
}

/** Resolve armed policy once (stamp/clear) so list/sweep labels match open refuse. */
async function policyWithDeviceArmed(
  store:PrivateRecordingStore,
  policy:AudioRetentionPolicy|null|undefined,
  nowMs:number,
):Promise<AudioRetentionPolicy|null|undefined>{
  return resolveArmedAudioRetentionPolicy(store,policy,nowMs);
}

/** Sweep expired audio for one scope. No-op when policy is off. Sign-out uses the same path. */
export async function sweepExpiredPrivateRecordingAudio(
  scope:string,
  platform:'ios'|'desktop',
  options:ListPrivateRecordingsOptions&{
    sealInProgress?:(recordingId:string)=>Promise<PrivateRecordingManifest|null>;
    store?:PrivateRecordingStore;
  }={},
):Promise<{deleted:string[];inspected:number}>{
  need(HASH.test(scope));
  const owned=options.store===undefined;
  const store=options.store??await(options.openStore?.()??openPrivateRecordingStore(scope,platform));
  const clock=options.now??(()=>Date.now());
  try{
    // Always resolve: policy-off clears the armed stamp so a later re-enable gets a fresh grace window.
    const policy=await policyWithDeviceArmed(store,options.audioRetention,clock());
    if(!retentionOn(policy))return {deleted:[],inspected:0};
    const skip=await audioSweepSkipIds(store,options.skipRecordingIds);
    return await sweepPrivateRecordingAudio({
      store,scope,policy,now:clock,sealInProgress:options.sealInProgress,
      parseManifest:(value,recordingId)=>manifest(value,scope,recordingId),...audioSweepHooks(store,scope,clock,skip),
    });
  }finally{if(owned)store.close();}
}

/** After mic close/stop: open a store and sweep. Panel wires this post-close. */
export async function sweepPrivateRecordingAudioAfterClose(
  scope:string,platform:'ios'|'desktop',options:ListPrivateRecordingsOptions={},
):Promise<{deleted:string[];inspected:number}>{
  return sweepExpiredPrivateRecordingAudio(scope,platform,options);
}

export async function listPrivateRecordings(scope:string,platform:'ios'|'desktop',openStore?:(()=>Promise<PrivateRecordingStore>)|ListPrivateRecordingsOptions):Promise<PrivateRecordingSnapshot[]> {
  need(HASH.test(scope));
  const options:ListPrivateRecordingsOptions=typeof openStore==='function'?{openStore}:openStore??{};
  const store=await(options.openStore?.()??openPrivateRecordingStore(scope,platform));
  const clock=options.now??(()=>Date.now());const nowMs=clock();
  try{
    // Resolve once (also clears armed stamp when policy is off).
    const policy=await policyWithDeviceArmed(store,options.audioRetention,nowMs);
    const on=retentionOn(policy);
    if(on){const skip=await audioSweepSkipIds(store,options.skipRecordingIds);await sweepPrivateRecordingAudio({
      store,scope,policy,now:clock,parseManifest:(value,recordingId)=>manifest(value,scope,recordingId),
      ...audioSweepHooks(store,scope,clock,skip),
    });}
    const all=await store.keys();need(all.filter(k=>k.startsWith('manifest:')||k.startsWith('audio-deleted:')).length<=1000);
    const rows:(PrivateRecordingSnapshot&{createdAt:string})[]=[];
    const manifestIds=new Set(all.filter(k=>k.startsWith('manifest:')).map(k=>k.slice(9)));
    for(const key of all){
      if(key.startsWith('manifest:')){
        const row=manifest(await store.read(key),scope,key.slice(9));
        const label=on?audioRetentionLabel(row,nowMs,policy):null;
        rows.push({recordingId:row.recordingId,title:displayTitle(await store.read('display-title:'+row.recordingId),scope,row.recordingId)??row.title,createdAt:row.createdAt,endedAt:row.endedAt,phase:row.phase,elapsedSeconds:row.chunks.reduce((n,c)=>n+c.durationMs,0)/1000,recordedChunks:row.chunks.length,recordedBytes:row.chunks.reduce((n,c)=>n+c.bytes,0),workspaceId:row.workspaceId,busy:false,localOnly:true,transcription:'not_requested',failure:null,startupStage:null,
          ...(on?{retentionLabel:label?.text??null,retentionWarn:label?.warn??false}:{})});
        continue;
      }
      if(!key.startsWith('audio-deleted:'))continue;
      const raw=await store.read(key);if(!raw||typeof raw!=='object')continue;
      const stub=raw as {contract?:unknown;recordingId?:unknown;scope?:unknown;phase?:unknown;updatedAt?:unknown};
      if(stub.contract!==AUDIO_DELETED_STUB_CONTRACT||stub.scope!==scope||stub.phase!=='audio_deleted'||typeof stub.recordingId!=='string'||!UUID.test(stub.recordingId)||typeof stub.updatedAt!=='string')continue;
      const id=stub.recordingId;
      if(manifestIds.has(id))continue; // stub written before manifest delete — avoid duplicate rows mid-crash
      const title=displayTitle(await store.read('display-title:'+id),scope,id)??'Private recording';
      rows.push({recordingId:id,title,createdAt:stub.updatedAt,phase:'audio_deleted',elapsedSeconds:0,recordedChunks:0,recordedBytes:0,workspaceId:null,busy:false,localOnly:true,transcription:'not_requested',failure:AUDIO_DELETED_USER_MESSAGE,startupStage:null,
        retentionLabel:AUDIO_DELETED_USER_MESSAGE,retentionWarn:false});
    }
    return rows.sort((a,b)=>Date.parse(b.createdAt)-Date.parse(a.createdAt)||(a.recordingId<b.recordingId?-1:a.recordingId>b.recordingId?1:0));
  }finally{store.close();}
}

export {deletePrivateRecordingAudio,refuseExpiredAudio,audioRetentionEffective,AUDIO_DELETED_USER_MESSAGE};
export type {AudioRetentionPolicy,AudioRetentionClock};
