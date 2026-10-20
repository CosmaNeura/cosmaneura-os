import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {CaptureSource,CaptureSourceStartOptions,CapturedWavChunk} from '../../clients/capture/src/capture/source';
import {encodePcm16MonoWav} from '../../clients/capture/src/capture/wav';
import {FakeIosNativePcmBridge} from '../../clients/capture/src/native/fake-ios-native-pcm-bridge';
import {IosNativeMicrophoneCaptureSource} from '../../clients/capture/src/native/ios-native-microphone-source';
import {BrowserMicrophoneCaptureSource} from '../../clients/capture/src/audio/browser-microphone-source';
import {acquireCaptureFlowLock,type CaptureFlowLockManager} from '../../clients/capture/src/flow/capture-lock';
import type {SecureQueuePlugin,VersionedSecureQueueRecord} from '../../clients/capture/plugins/secure-queue/definitions';
import {PrivateRecordingRuntime,listPrivateRecordings,openPrivateRecordingStore,validatePrivateRecordingConsent,type PrivateRecordingOptions,type PrivateRecordingManifest,type PrivateRecordingStore} from './private-recording-runtime';
vi.mock('../../clients/capture/src/audio/pcm-capture-worklet.ts?worker&url',()=>({default:'/simulated-os-worklet.js'}));

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const scope='a'.repeat(64),otherScope='b'.repeat(64),workspace='00000000-0000-4000-8000-000000000042';
const consent=()=>({modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:new Date().toISOString(),language:'en-US' as const});
const releases:PrivateRecordingRuntime[]=[];
let idb:IDBFactory;
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);idb=new IDBFactory();vi.stubGlobal('fetch',vi.fn(()=>{throw Error('Private recording must make no HTTP request');}));});
afterEach(async()=>{for(const runtime of releases.splice(0))await runtime.close().catch(()=>{});vi.restoreAllMocks();vi.unstubAllGlobals();});
const request=<T,>(r:IDBRequest<T>)=>new Promise<T>((yes,no)=>{r.onsuccess=()=>yes(r.result);r.onerror=()=>no(r.error);});
const transaction=(t:IDBTransaction)=>new Promise<void>((yes,no)=>{t.oncomplete=()=>yes();t.onabort=t.onerror=()=>no(t.error);});
async function inspect(databaseScope=scope){const db=await request(idb.open('cosmas-private-recording:v1:'+databaseScope,1));const t=db.transaction(['records','metadata'],'readonly'),done=transaction(t),records=await request(t.objectStore('records').getAll()),key=await request(t.objectStore('metadata').get('key'));await done;db.close();return {records,key};}
const store=()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(yes=>{resolve=yes;});return {promise,resolve};}
const wav=(frames=16,sample=1234):CapturedWavChunk=>({sequenceNumber:0,durationMs:frames/16,wavBytes:encodePcm16MonoWav(new Int16Array(Array(frames).fill(sample)),{sampleRateHz:16000,channels:1,targetChunkDurationMs:10000,maxEnvelopeBytes:320044})});
function pcmPacket(frames:number,sample:number){const bytes=new Uint8Array(new ArrayBuffer(frames*2)),view=new DataView(bytes.buffer);for(let i=0;i<frames;i++)view.setInt16(i*2,sample,true);return bytes;}
class ControlledSource implements CaptureSource {
  readonly kind='microphone' as const;options:CaptureSourceStartOptions|null=null;starts=0;stops=0;stopFailures=0;gate:Promise<void>|null=null;
  async start(options:CaptureSourceStartOptions){this.starts++;this.options=options;if(this.gate)await this.gate;}
  async stop(){this.stops++;if(this.stopFailures-->0)throw Error('Simulated OS stop failure');}
  async emit(chunk=wav()){if(!this.options)throw Error('Not started');await this.options.onChunk(chunk);}
}
async function open(source:CaptureSource,options:Partial<PrivateRecordingOptions>={},input:{recordingId?:string;title?:string}={}){
  const runtime=await PrivateRecordingRuntime.open({scope,platform:'desktop',isCurrent:()=>true,openStore:store,createSource:async()=>source,acquireLock:async()=>async()=>{},...options},{...input,title:input.title??'Invented private recording',...(input.recordingId?{}:{consent:consent()})});releases.push(runtime);return runtime;
}
async function blobBytes(blob:Blob):Promise<Uint8Array<ArrayBuffer>>{return new Uint8Array(await new Promise<ArrayBuffer>((yes,no)=>{const r=new FileReader();r.onload=()=>yes(r.result as ArrayBuffer);r.onerror=no;r.readAsArrayBuffer(blob);}));}
const sha=async(bytes:Uint8Array<ArrayBuffer>)=>Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');

it.each([0,1234])('checks saved PCM signal without counting the WAV header as audio (%s)',async sample=>{
  const source=new ControlledSource(),runtime=await open(source);await runtime.start(consent());await source.emit(wav(16,sample));await runtime.stop();
  const exported=await runtime.exportWav();expect(exported.hasNonzeroAudio).toBe(sample!==0);
  expect(exported.durationMs).toBe(1);expect(exported.bytes).toBe(76);expect(fetch).not.toHaveBeenCalled();
});

it('keeps sealed speech audio lineage stable through later notebook organization while the ledger manifest changes',async()=>{
  const source=new ControlledSource(),runtime=await open(source);await runtime.start(consent());await source.emit();await runtime.stop();
  const original=await runtime.snapshotForPrivateTranscript(),ledger=await runtime.snapshotForLedger();await runtime.attachWorkspace(workspace,true);await runtime.rename('Invented organized recording');
  expect(await runtime.snapshotForPrivateTranscript()).toEqual(original);expect((await runtime.snapshotForLedger()).manifestSHA256).not.toBe(ledger.manifestSHA256);expect(runtime.snapshot.workspaceId).toBe(workspace);
});

it('retains the actual interruption reason and clears it on explicit Resume',async()=>{
  const source=new ControlledSource(),runtime=await open(source);await runtime.start(consent());source.options!.onInterruption!('capture_backgrounded');
  await vi.waitFor(()=>expect(runtime.snapshot.phase).toBe('paused'));expect(runtime.snapshot.failure).toBe('capture_backgrounded');
  await runtime.start(consent());expect(runtime.snapshot.phase).toBe('recording');expect(runtime.snapshot.failure).toBeNull();
});

it('prewarms encrypted custody without consent, microphone, manifest or network',async()=>{
  const prepared=await store();expect(await prepared.keys()).toEqual([]);prepared.close();
  const {records,key}=await inspect();expect(records).toEqual([]);expect(key).toMatchObject({type:'secret',extractable:false,algorithm:{name:'AES-GCM',length:256}});
  await expect(webcrypto.subtle.exportKey('raw',key)).rejects.toThrow();expect(fetch).not.toHaveBeenCalled();
});

it('lists encrypted recordings newest first by creation instant with a stable ID tie-break without rewriting custody',async()=>{
  const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
  const timestamps=new Map([
    [1,'2026-10-09T15:00:00.000Z'],
    [2,'2026-10-20T12:00:00.000Z'],
    [3,'2026-10-20T13:00:00.000Z'],
    [4,'2026-10-20T08:00:00.000-04:00'],
  ]);
  const encrypted=await store();
  for(const n of [4,1,3,2]){
    const row:PrivateRecordingManifest={contract:'cosmabot.private-recording.v1',recordingId:id(n),scope,title:`Invented recording ${n}`,
      consent:consent(),consentIntervals:[],workspaceId:null,createdAt:timestamps.get(n)!,updatedAt:'2026-10-21T09:00:00.000Z',phase:'sealed',chunks:[]};
    await encrypted.write('manifest:'+id(n),null,row);
  }
  expect(await encrypted.keys()).toEqual([1,2,3,4].map(n=>'manifest:'+id(n)));encrypted.close();
  const before=await inspect(),rows=await listPrivateRecordings(scope,'desktop',store);
  expect(rows.map(row=>row.recordingId)).toEqual([3,2,4,1].map(id));
  expect(rows.map(row=>row.createdAt)).toEqual([3,2,4,1].map(n=>timestamps.get(n)));
  expect((await inspect()).records).toEqual(before.records);expect(fetch).not.toHaveBeenCalled();
});

it('runs the production desktop getUserMedia/AudioWorklet/resampler path and durably drains private PCM before playback',async()=>{
  // Browser hardware boundaries are simulated; source, resampler, chunker, persistence and WAV export are production code.
  const track=Object.assign(new EventTarget(),{stop:vi.fn()}),node=()=>({connect:vi.fn(),disconnect:vi.fn()}),port={onmessage:null as MessagePort['onmessage'],postMessage:vi.fn()},worklet={...node(),port,onprocessorerror:null};
  const context=Object.assign(new EventTarget(),{sampleRate:32000,state:'suspended' as AudioContextState,destination:node(),audioWorklet:{addModule:vi.fn(async()=>{})},createMediaStreamSource:()=>node(),createGain:()=>({...node(),gain:{value:1}}),resume:async()=>{context.state='running';},close:async()=>{context.state='closed';}});
  const media=vi.fn(async()=>({getTracks:()=>[track],getAudioTracks:()=>[track]} as unknown as MediaStream)),visibility=Object.assign(new EventTarget(),{visibilityState:'visible' as DocumentVisibilityState});
  const source=new BrowserMicrophoneCaptureSource({mediaDevices:{getUserMedia:media},createAudioContext:()=>context as unknown as AudioContext,createAudioWorkletNode:()=>worklet as unknown as AudioWorkletNode,visibilityDocument:visibility,pageLifecycleWindow:new EventTarget(),workletModuleUrl:new URL('https://local.invalid/pcm-worklet.js')});
  const runtime=await open(source);expect(media).not.toHaveBeenCalled();await runtime.start(consent());expect(media).toHaveBeenCalledWith({audio:{autoGainControl:false,channelCount:{ideal:1},echoCancellation:false,noiseSuppression:false,sampleRate:{ideal:16000}},video:false});
  const frames=new ArrayBuffer(32*4),values=new Float32Array(frames);values.fill(0.5);port.onmessage?.call(port as unknown as MessagePort,{data:{type:'pcm',version:1,sequence:0,frames}} as MessageEvent);await runtime.stop();
  expect(track.stop).toHaveBeenCalledTimes(1);expect(context.state).toBe('closed');expect(port.onmessage).toBeNull();expect(values.every(v=>v===0)).toBe(true);const exported=await runtime.exportWav(),bytes=await blobBytes(exported.blob);expect(exported.durationMs).toBe(1);expect(bytes).toHaveLength(76);for(let offset=44;offset<76;offset+=2)expect(new DataView(bytes.buffer).getInt16(offset,true)).toBe(16384);expect(fetch).not.toHaveBeenCalled();
});

it('shares the existing origin-wide microphone lock with encounter capture and never falls back when unavailable',async()=>{
  let held=false;const manager:CaptureFlowLockManager={async request(_name,options,callback){expect(options).toEqual({mode:'exclusive',ifAvailable:true});if(held)return callback(null);held=true;try{return await callback({name:'cosmaneura-capture-active-flow-v1',mode:'exclusive'});}finally{held=false;}}};
  const encounterRelease=await acquireCaptureFlowLock(manager),source=new ControlledSource(),runtime=await open(source,{acquireLock:()=>acquireCaptureFlowLock(manager)});await expect(runtime.start(consent())).rejects.toThrow();expect(source.starts).toBe(0);await encounterRelease();await runtime.start(consent());await expect(acquireCaptureFlowLock(manager)).rejects.toThrow();await runtime.stop();const next=await acquireCaptureFlowLock(manager);await next();
});

it('drains actual iOS PCM adapter packets into AES-GCM, pauses/resumes, exports playable WAV and reopens without starting audio',async()=>{
  // The OS seam generates synthetic PCM; packet handling, WAV conversion, AES-GCM and recovery are production code.
  const bridge=new FakeIosNativePcmBridge(),source=new IosNativeMicrophoneCaptureSource(bridge),runtime=await open(source);
  expect(bridge.startCalls).toBe(0);await runtime.start(consent());expect(runtime.snapshot.phase).toBe('recording');
  const full=pcmPacket(160000,1234);await bridge.emitPcmPacket({sequenceNumber:0,pcmBytes:full});expect(full.every(v=>v===0)).toBe(true);
  const tail=pcmPacket(16,-321);bridge.setFinalPcmPacket({sequenceNumber:1,pcmBytes:tail});await runtime.pause();
  expect(runtime.snapshot).toMatchObject({phase:'paused',recordedChunks:2,elapsedSeconds:10.001,transcription:'not_requested'});expect(tail.every(v=>v===0)).toBe(true);
  await runtime.start(consent());bridge.setFinalPcmPacket({sequenceNumber:0,pcmBytes:pcmPacket(32,4321)});await runtime.stop();
  const exported=await runtime.exportWav(),bytes=await blobBytes(exported.blob),view=new DataView(bytes.buffer);
  expect(exported).toMatchObject({bytes:320140,durationMs:10003});expect(exported.sha256).toBe(await sha(bytes));expect(view.getUint32(40,true)).toBe(320096);expect(view.getInt16(44,true)).toBe(1234);expect(view.getInt16(320044,true)).toBe(-321);expect(view.getInt16(320076,true)).toBe(4321);
  const iterator=runtime.savedChunks(),first=await iterator.next();if(first.done)throw Error('Missing saved PCM');const retained=first.value.wavBytes;expect(retained.some(v=>v!==0)).toBe(true);await iterator.return(undefined);expect(retained.every(v=>v===0)).toBe(true);
  await runtime.attachWorkspace(workspace,true);await runtime.attachWorkspace(workspace,true);await expect(runtime.attachWorkspace(crypto.randomUUID(),true)).rejects.toThrow();
  const saved=runtime.snapshot;await runtime.close();const reopened=await open(source,{}, {recordingId:saved.recordingId});expect(reopened.snapshot).toEqual(saved);expect(bridge.startCalls).toBe(2);
  const rows=await listPrivateRecordings(scope,'desktop',store);expect(rows).toHaveLength(1);expect(rows[0]).toMatchObject({phase:'sealed',workspaceId:workspace,recordedChunks:3});
  const {records,key}=await inspect();expect(records).toHaveLength(4);expect(key.extractable).toBe(false);for(const row of records){expect(Object.keys(row).sort()).toEqual(['ciphertext','key','nonce','revision']);expect(row.ciphertext).toBeInstanceOf(ArrayBuffer);expect(row.nonce).toHaveLength(12);expect(JSON.stringify(row)).not.toContain('Invented private recording');}
  expect(fetch).not.toHaveBeenCalled();
});

it('preserves original attestation and requires new explicit full consent for every recording interval',async()=>{
  const source=new ControlledSource(),runtime=await open(source),first=consent();await runtime.start(first);await runtime.pause();
  const stale={...first,granted_at:new Date(Date.now()-300001).toISOString()};await expect(runtime.start(stale)).rejects.toThrow();
  const second={...consent(),language:'en-US+es-US' as const,modality:'phone' as const,participant_regions:['US-NY','US-CA']};await runtime.start(second);await runtime.stop();
  const s=await store(),saved=await s.read('manifest:'+runtime.snapshot.recordingId) as PrivateRecordingManifest;s.close();expect(saved.consent.language).toBe('en-US');expect(saved.consentIntervals).toEqual([first,second]);expect(source.starts).toBe(2);
});

it.each([
  {all_parties_consented:false},{method:'implicit'},{language:'fr-FR'},{participant_regions:['invalid']},{participant_regions:['US-NY','US-NY']},{granted_at:'2026-10-08T12:00:00Z'},{granted_at:new Date(Date.now()+3600000).toISOString()},{extra:'unreviewed'}
])('refuses incomplete or broadened consent before creating an audio source: %j',async changed=>{
  const source=new ControlledSource(),runtime=await open(source);expect(()=>validatePrivateRecordingConsent({...consent(),...changed})).toThrow();await expect(runtime.start({...consent(),...changed} as never)).rejects.toThrow();expect(source.starts).toBe(0);
});

it('stops while microphone permission is pending and rejects late Start completion',async()=>{
  const source=new ControlledSource(),gate=deferred();source.gate=gate.promise;const runtime=await open(source);const starting=runtime.start(consent());await vi.waitFor(()=>expect(source.starts).toBe(1));
  await runtime.stop();expect(source.stops).toBe(1);expect(runtime.snapshot.phase).toBe('sealed');gate.resolve();await starting;expect(runtime.snapshot.phase).toBe('sealed');
  const late=wav();await expect(source.emit(late)).rejects.toThrow();expect(late.wavBytes.every(v=>v===0)).toBe(true);
});

it('reports only current startup progress, isolates observers and never persists stages',async()=>{
  const source=new ControlledSource(),gate=deferred();source.gate=gate.promise;
  let current=true;const runtime=await open(source,{isCurrent:()=>current});
  const observed:string[]=[];runtime.subscribe(value=>{if(value.startupStage)observed.push(value.startupStage);});
  const unsubscribe=runtime.subscribe(value=>{if(value.startupStage)throw Error('Synthetic observer failure');});
  const starting=runtime.start(consent());await vi.waitFor(()=>expect(source.starts).toBe(1));
  const first=source.options!;first.onStartupStage?.('microphone_permission');
  expect(runtime.snapshot).toMatchObject({phase:'starting',startupStage:'microphone_permission'});
  current=false;first.onStartupStage?.('audio_engine');expect(runtime.snapshot.startupStage).toBe('microphone_permission');current=true;
  await runtime.pause();expect(runtime.snapshot.startupStage).toBeNull();
  first.onStartupStage?.('audio_engine');expect(runtime.snapshot.startupStage).toBeNull();gate.resolve();await starting;
  source.gate=null;await runtime.start(consent());first.onStartupStage?.('native_session');
  expect(runtime.snapshot).toMatchObject({phase:'recording',startupStage:null});
  source.options!.onStartupStage?.('audio_engine');expect(runtime.snapshot.startupStage).toBeNull();
  expect(observed).toContain('physical_exclusion');expect(observed).toContain('preparing_storage');expect(observed).toContain('microphone_permission');
  await runtime.stop();unsubscribe();
  const saved=await store();expect(await saved.read('manifest:'+runtime.snapshot.recordingId)).not.toHaveProperty('startupStage');saved.close();
  expect((await listPrivateRecordings(scope,'desktop',store))[0].startupStage).toBeNull();
});

it('stops physical input before a held encrypted status write while retaining exclusion',async()=>{
  const encrypted=await store(),gate=deferred();let writing=false;
  const guarded:PrivateRecordingStore={read:key=>encrypted.read(key),keys:()=>encrypted.keys(),close:()=>encrypted.close(),write:async(key,expected,value)=>{
    if((value as PrivateRecordingManifest).phase==='stopping'){writing=true;await gate.promise;}await encrypted.write(key,expected,value);
  }};
  const source=new ControlledSource(),release=vi.fn(async()=>{}),runtime=await open(source,{openStore:async()=>guarded,acquireLock:async()=>release});
  await runtime.start(consent());const stopping=runtime.stop();
  expect(source.stops).toBe(1);await vi.waitFor(()=>expect(writing).toBe(true));expect(release).not.toHaveBeenCalled();
  const other=new ControlledSource(),second=await open(other);await expect(second.start(consent())).rejects.toThrow();expect(other.starts).toBe(0);
  gate.resolve();await stopping;expect(runtime.snapshot.phase).toBe('sealed');expect(release).toHaveBeenCalledOnce();
});

it('observes immediate stop rejection while a status write is held and retains its exact owner',async()=>{
  const encrypted=await store(),gate=deferred();let writing=false;
  const guarded:PrivateRecordingStore={read:key=>encrypted.read(key),keys:()=>encrypted.keys(),close:()=>encrypted.close(),write:async(key,expected,value)=>{
    if((value as PrivateRecordingManifest).phase==='stopping'&&!writing){writing=true;await gate.promise;}await encrypted.write(key,expected,value);
  }};
  const source=new ControlledSource(),release=vi.fn(async()=>{}),runtime=await open(source,{openStore:async()=>guarded,acquireLock:async()=>release});
  await runtime.start(consent());source.stopFailures=1;const stopping=runtime.stop(),rejected=expect(stopping).rejects.toThrow('Simulated OS stop failure');
  await vi.waitFor(()=>expect(writing).toBe(true));expect(source.stops).toBe(1);expect(release).not.toHaveBeenCalled();
  gate.resolve();await rejected;expect(runtime.snapshot.phase).toBe('stop_unconfirmed');expect(release).not.toHaveBeenCalled();
  await runtime.stop();expect(source.stops).toBe(2);expect(release).toHaveBeenCalledOnce();
});

it('holds the single capture owner after unconfirmed physical stop and retries the exact producer',async()=>{
  const source=new ControlledSource(),release=vi.fn(async()=>{}),runtime=await open(source,{acquireLock:async()=>release});await runtime.start(consent());source.stopFailures=1;
  await expect(runtime.stop()).rejects.toThrow();expect(runtime.snapshot.phase).toBe('stop_unconfirmed');expect(release).not.toHaveBeenCalled();
  const other=new ControlledSource(),second=await open(other);await expect(second.start(consent())).rejects.toThrow();expect(other.starts).toBe(0);
  await runtime.stop();expect(source.stops).toBe(2);expect(source.starts).toBe(1);expect(release).toHaveBeenCalledTimes(1);await second.start(consent());await second.stop();
});

it('does not start a producer after Stop during source factory preparation',async()=>{
  const source=new ControlledSource(),gate=deferred(),factory=vi.fn(async()=>{await gate.promise;return source;});const runtime=await open(source,{createSource:factory});const starting=runtime.start(consent());const rejected=expect(starting).rejects.toThrow();await vi.waitFor(()=>expect(factory).toHaveBeenCalledTimes(1));await runtime.stop();gate.resolve();await rejected;expect(source.starts).toBe(0);expect(runtime.snapshot.phase).toBe('sealed');
});

it('zeroes rejected audio and stops on owner identity loss without leaking saved content',async()=>{
  let current=true;const controller=new AbortController(),source=new ControlledSource(),runtime=await open(source,{isCurrent:()=>current,signal:controller.signal});await runtime.start(consent());current=false;controller.abort();
  const chunk=wav();await expect(source.emit(chunk)).rejects.toThrow();expect(chunk.wavBytes.every(v=>v===0)).toBe(true);await vi.waitFor(()=>expect(source.stops).toBe(1));await expect(runtime.exportWav()).rejects.toThrow();expect(fetch).not.toHaveBeenCalled();
});

it('refuses lost encrypted keys without replacing ciphertext or establishing new custody',async()=>{
  const runtime=await open(new ControlledSource());await runtime.close();const before=await inspect(),db=await request(idb.open('cosmas-private-recording:v1:'+scope,1)),t=db.transaction('metadata','readwrite'),done=transaction(t);t.objectStore('metadata').delete('key');await done;db.close();
  await expect(store()).rejects.toThrow();const after=await inspect();expect(after.records).toEqual(before.records);expect(after.key).toBeUndefined();
});

it('withholds corrupted saved audio and prevents a different account from adopting the same recording',async()=>{
  const source=new ControlledSource(),runtime=await open(source);await runtime.start(consent());await source.emit();await runtime.stop();
  const s=await store(),key='chunk:'+runtime.snapshot.recordingId+':0',row=await s.read(key) as Record<string,unknown>;await s.write(key,row,{...row,sha256:'f'.repeat(64)});s.close();await expect(runtime.exportWav()).rejects.toThrow();
  const foreignStore=()=>openPrivateRecordingStore(otherScope,'desktop',{indexedDB:idb,crypto:webcrypto});await expect(PrivateRecordingRuntime.open({scope:otherScope,platform:'desktop',isCurrent:()=>true,openStore:foreignStore},{recordingId:runtime.snapshot.recordingId,title:'Foreign account'})).rejects.toThrow();expect(await listPrivateRecordings(otherScope,'desktop',foreignStore)).toEqual([]);
});

it('preserves an orphan chunk after manifest CAS failure and never silently overwrites it or restarts',async()=>{
  const inner=await store();let fail=false;const wrapped:PrivateRecordingStore={read:k=>inner.read(k),keys:()=>inner.keys(),close:()=>inner.close(),write:async(k,e,v)=>{if(fail&&k.startsWith('manifest:')&&(v as PrivateRecordingManifest).chunks.length>0)throw Error('Simulated lost manifest commit');await inner.write(k,e,v);}};
  const source=new ControlledSource(),runtime=await open(source,{openStore:async()=>wrapped});await runtime.start(consent());fail=true;const chunk=wav();await expect(source.emit(chunk)).rejects.toThrow();expect(chunk.wavBytes.every(v=>v===0)).toBe(true);expect(runtime.snapshot.recordedChunks).toBe(0);expect(await inner.keys()).toContain('chunk:'+runtime.snapshot.recordingId+':0');await runtime.stop();expect(runtime.snapshot.phase).toBe('interrupted');await expect(runtime.start(consent())).rejects.toThrow();expect(source.starts).toBe(1);
});

it.each([false,true])('requires process-wide idle proof to recover an interrupted manifest, idle=%s',async idle=>{
  const source=new ControlledSource(),runtime=await open(source),id=runtime.snapshot.recordingId;await runtime.close();const s=await store(),saved=await s.read('manifest:'+id) as PrivateRecordingManifest;await s.write('manifest:'+id,saved,{...saved,phase:'recording'});s.close();
  const probe:CaptureSource={kind:'microphone',start:vi.fn(),stop:vi.fn(),confirmRecoveryClosed:vi.fn(async()=>idle)};
  if(idle){const restored=await open(probe,{}, {recordingId:id});expect(restored.snapshot.phase).toBe('interrupted');expect(probe.start).not.toHaveBeenCalled();expect(probe.stop).not.toHaveBeenCalled();}
  else await expect(open(probe,{}, {recordingId:id})).rejects.toThrow();
});

it('uses native SecureQueue create/CAS and resolves a lost write response by exact readback',async()=>{
  // This injected native boundary tests opaque device-store protocol, not Keychain encryption or hardware audio.
  const records=new Map<string,VersionedSecureQueueRecord>();let lose=false;const missing=()=>Object.assign(Error('Missing native fixture record'),{code:'SECURE_QUEUE_NOT_FOUND'});
  const plugin:SecureQueuePlugin={get:async({key})=>{const row=records.get(key);if(!row)throw missing();return structuredClone(row);},list:async()=>({keys:[...records.keys()]}),put:async()=>{throw Error('Unversioned write prohibited');},create:async value=>{if(records.has(value.key))throw Error('Conflict');records.set(value.key,{...value,revision:'1'});if(lose){lose=false;throw Error('Lost response');}return {revision:'1'};},compareAndSwap:async value=>{const old=records.get(value.key);if(!old||old.revision!==value.expectedRevision)throw Error('Conflict');const revision=String(BigInt(old.revision)+1n);records.set(value.key,{key:value.key,data:value.data,revision});if(lose){lose=false;throw Error('Lost response');}return {revision};},delete:async()=>{throw Error('Deletion prohibited');},clear:async()=>{throw Error('Clear prohibited');}};
  const native=()=>openPrivateRecordingStore(scope,'ios',{native:plugin,crypto:webcrypto});const source=new ControlledSource(),runtime=await open(source,{platform:'ios',openStore:native});lose=true;await runtime.start(consent());lose=true;await source.emit();await runtime.stop();const result=await runtime.exportWav();expect(result.durationMs).toBe(1);expect([...records.keys()].every(k=>k.startsWith('cosmas-private-recording:v1:'+scope+':'))).toBe(true);
  const foreign=await openPrivateRecordingStore(otherScope,'ios',{native:plugin});expect(await foreign.keys()).toEqual([]);foreign.close();expect(fetch).not.toHaveBeenCalled();
});

it('can close a stopped recording again after access changes without reopening audio',async()=>{
  let current=true;const source=new ControlledSource(),runtime=await open(source,{isCurrent:()=>current});
  await runtime.start(consent());await source.emit();await runtime.close();current=false;
  await runtime.close();expect(source.stops).toBe(1);expect(runtime.snapshot.recordedChunks).toBe(1);
  expect(fetch).not.toHaveBeenCalled();
});
