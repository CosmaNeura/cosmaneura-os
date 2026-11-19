import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {SecureQueuePlugin,VersionedSecureQueueRecord} from '../../clients/capture/plugins/secure-queue/definitions';
import {audioSweepSkipIds,isAudioRetentionProtected,isTransferRetentionReleased,listPrivateRecordings,markTransferRetentionReleased,openPrivateRecordingStore,PrivateRecordingRuntime,sweepExpiredPrivateRecordingAudio,type PrivateRecordingManifest,type PrivateRecordingStore} from './private-recording-runtime';
import {privateRecordingLedgerKey} from './private-recording-ledger';
import {
  AUDIO_DELETED_STUB_CONTRACT,
  AUDIO_DELETED_USER_MESSAGE,
  AUDIO_RETENTION_ARMED_CONTRACT,
  AUDIO_RETENTION_ARMED_KEY,
  AUDIO_RETENTION_CLOCK_SKEW_MS,
  AUDIO_RETENTION_HOURS,
  AUDIO_RETENTION_MS,
  AUDIO_TOMBSTONE_CONTRACT,
  audioRetentionAnchor,
  audioRetentionEffective,
  audioRetentionLabel,
  buildAudioDeletedStub,
  buildAudioTombstone,
  clearDeviceArmedAt,
  deletePrivateRecordingAudio,
  EXPIRED_AUDIO_REFUSED,
  normalizeAudioRetentionPolicy,
  readDeviceArmedAt,
  readOrStampDeviceArmedAt,
  refuseExpiredAudio,
  resolveArmedAudioRetentionPolicy,
  resolveAudioRetentionClock,
  sweepPrivateRecordingAudio,
  type AudioRetentionPolicy,
} from './private-recording-retention';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const scope='d'.repeat(64),otherScope='e'.repeat(64);
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const consent=()=>({modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:'2026-11-01T12:00:00.000Z',language:'en-US' as const});

/** Enabled policy with aligned server/device clocks (offset 0 → effectiveNow tracks injected now). */
function policyOn(opts:{enabledAt:string;now?:number;deviceArmedAt?:string;serverNow?:string;fetchedAtDeviceMs?:number}):AudioRetentionPolicy{
  const now=opts.now??Date.parse(opts.enabledAt);
  const fetchedAtDeviceMs=opts.fetchedAtDeviceMs??now;
  const serverNow=opts.serverNow??new Date(fetchedAtDeviceMs).toISOString();
  return {
    enabled:true,
    hours:48,
    warnHours:36,
    enabledAt:opts.enabledAt,
    serverNow,
    fetchedAtDeviceMs,
    ...(opts.deviceArmedAt?{deviceArmedAt:opts.deviceArmedAt}:{}),
  };
}

/** enabledAt at/before ended so deadline stays endedAt+48h for classic clock tests. */
const policy=policyOn({enabledAt:'2026-10-01T00:00:00.000Z',now:Date.parse('2026-11-01T00:00:00.000Z')});
let idb:IDBFactory;
beforeEach(()=>{
  vi.stubGlobal('crypto',webcrypto);
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);
  vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  idb=new IDBFactory();
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

function manifest(recordingId:string,endedAt:string,phase:PrivateRecordingManifest['phase']='sealed',chunks=1):PrivateRecordingManifest{
  return {contract:'cosmabot.private-recording.v1',recordingId,scope,title:'Synthetic visit A',consent:consent(),consentIntervals:[],
    workspaceId:null,createdAt:endedAt,updatedAt:endedAt,endedAt,phase,
    chunks:Array.from({length:chunks},(_,sequence)=>({sequence,sha256:'a'.repeat(64),bytes:76,durationMs:1}))};
}

async function seed(store:PrivateRecordingStore,row:PrivateRecordingManifest,extra:Record<string,unknown>={}){
  await store.write('manifest:'+row.recordingId,null,row);
  for(const chunk of row.chunks){
    await store.write(`chunk:${row.recordingId}:${chunk.sequence}`,null,
      {contract:'cosmabot.private-pcm.v1',recordingId:row.recordingId,scope,sequence:chunk.sequence,sha256:chunk.sha256,durationMs:chunk.durationMs,data:'AA=='});
  }
  for(const [key,value] of Object.entries(extra))await store.write(key,null,value);
}

/** Pre-stamp device armedAt so runtime sweep does not push the deadline to "now". */
async function armAt(store:PrivateRecordingStore,atMs:number){
  await readOrStampDeviceArmedAt(store,atMs);
}

it('keeps audio at 47:59:59 and deletes at 48:00:00 with an injected clock',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(1),ended));
  const keep=await sweepPrivateRecordingAudio({store,scope,policy,now:()=>start+AUDIO_RETENTION_MS-1,
    parseManifest:(value)=>value as PrivateRecordingManifest});
  expect(keep.deleted).toEqual([]);
  expect(await store.read('manifest:'+id(1))).not.toBeNull();
  expect(await store.read('chunk:'+id(1)+':0')).not.toBeNull();
  const gone=await sweepPrivateRecordingAudio({store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest});
  expect(gone.deleted).toEqual([id(1)]);
  expect(await store.read('manifest:'+id(1))).toBeNull();
  expect(await store.read('chunk:'+id(1)+':0')).toBeNull();
  expect(await store.read('audio-deleted:'+id(1))).toMatchObject({contract:AUDIO_DELETED_STUB_CONTRACT,phase:'audio_deleted'});
  store.close();
});

it('SecureQueue fake deletes at 48:00:00 and keeps at 47:59:59',async()=>{
  const records=new Map<string,VersionedSecureQueueRecord>();
  const native:SecureQueuePlugin={
    async list(){return {keys:[...records.keys()]};},
    async get({key}){const row=records.get(key);if(!row)throw Object.assign(new Error('missing'),{code:'SECURE_QUEUE_NOT_FOUND'});return row;},
    async put({key,data}){const row={key,revision:'1',data};records.set(key,row);return {revision:row.revision};},
    async create({key,data}){if(records.has(key))throw Error('exists');const row={key,revision:'1',data};records.set(key,row);return {revision:row.revision};},
    async compareAndSwap({key,data,expectedRevision}){const prior=records.get(key);if(!prior||prior.revision!==expectedRevision)throw Error('cas');const row={key,revision:String(Number(expectedRevision)+1),data};records.set(key,row);return {revision:row.revision};},
    async delete({key}){const deleted=records.delete(key);return {deleted};},
    async clear(){const cleared=records.size;records.clear();return {cleared};},
  };
  const store=await openPrivateRecordingStore(scope,'ios',{crypto:webcrypto,native});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(2),ended));
  await armAt(store,Date.parse(policy.enabledAt!));
  expect((await sweepExpiredPrivateRecordingAudio(scope,'ios',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS-1})).deleted).toEqual([]);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'ios',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([id(2)]);
  expect(await store.read('manifest:'+id(2))).toBeNull();
  store.close();
});

it('finishes a crash mid-delete on retry without resurrecting chunks',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z';
  await seed(store,manifest(id(3),ended, 'sealed',2));
  await store.delete('chunk:'+id(3)+':0'); // crash after first chunk
  expect(await store.read('chunk:'+id(3)+':0')).toBeNull();
  expect(await store.read('chunk:'+id(3)+':1')).not.toBeNull();
  expect(await store.read('manifest:'+id(3))).not.toBeNull();
  await deletePrivateRecordingAudio(store,id(3),2,{scope});
  expect(await store.read('manifest:'+id(3))).toBeNull();
  expect(await store.read('chunk:'+id(3)+':1')).toBeNull();
  expect(await store.read('audio-deleted:'+id(3))).toMatchObject({contract:AUDIO_DELETED_STUB_CONTRACT});
  await deletePrivateRecordingAudio(store,id(3),2,{scope}); // idempotent retry
  store.close();
});

it('seals an in-progress recording at the deadline then deletes',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const active=manifest(id(4),ended,'recording');
  await seed(store,active);
  let sealed=false;
  const result=await sweepPrivateRecordingAudio({store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest,
    sealInProgress:async(recordingId)=>{
      sealed=true;
      const next={...active,phase:'sealed' as const,endedAt:ended,updatedAt:ended};
      await store.write('manifest:'+recordingId,active,next);
      return next;
    }});
  expect(sealed).toBe(true);
  expect(result.deleted).toEqual([id(4)]);
  expect(await store.read('manifest:'+id(4))).toBeNull();
  store.close();
});

it('skips active recording when sealInProgress is missing or returns null',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(40),ended,'recording'));
  expect((await sweepPrivateRecordingAudio({store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(40))).not.toBeNull();
  expect((await sweepPrivateRecordingAudio({store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest,
    sealInProgress:async()=>null})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(40))).not.toBeNull();
  store.close();
});

it('offline then sweep on next open deletes expired audio',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(5),ended));
  await armAt(store,Date.parse(policy.enabledAt!));
  store.close();
  // Device offline: no sweep. Next panel/store open can delete.
  const relaunch=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store:relaunch,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([id(5)]);
  relaunch.close();
});

it('sign-out sweep removes expired audio only',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const base=Date.parse('2026-11-01T00:00:00.000Z');
  await seed(store,manifest(id(6),new Date(base).toISOString()));
  await seed(store,manifest(id(7),new Date(base+AUDIO_RETENTION_MS/2).toISOString()));
  await armAt(store,Date.parse(policy.enabledAt!));
  const now=()=>base+AUDIO_RETENTION_MS;
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now})).deleted).toEqual([id(6)]);
  expect(await store.read('manifest:'+id(7))).not.toBeNull();
  expect(await store.read('chunk:'+id(7)+':0')).not.toBeNull();
  store.close();
});

it('replayed or restored expired recordingId is deleted again on sight',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended),now=()=>start+AUDIO_RETENTION_MS;
  await seed(store,manifest(id(8),ended));
  await armAt(store,Date.parse(policy.enabledAt!));
  await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now});
  await seed(store,manifest(id(8),ended)); // restored/replayed
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now})).deleted).toEqual([id(8)]);
  expect(await store.read('manifest:'+id(8))).toBeNull();
  store.close();
});

it('cross-scope isolation: sweep only touches its own scope',async()=>{
  const a=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const b=await openPrivateRecordingStore(otherScope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const rowA=manifest(id(9),ended);const rowB={...manifest(id(10),ended),scope:otherScope};
  await seed(a,rowA);await seed(b,rowB);
  await armAt(a,Date.parse(policy.enabledAt!));
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store:a,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([id(9)]);
  expect(await b.read('manifest:'+id(10))).not.toBeNull();
  expect(await b.read('chunk:'+id(10)+':0')).not.toBeNull();
  a.close();b.close();
});

it('transcripts and ledgers survive audio deletion',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const ledgerKey=privateRecordingLedgerKey(id(11));
  const transcriptKey='private-transcript:'+id(11);
  const ledger={contract:'cosmas.private-recording.ledger.v1',recording_id:id(11),kept:true};
  const transcript={contract:'cosmabot.private-transcript.v1',text:'Synthetic visit A notes'};
  await seed(store,manifest(id(11),ended),{[ledgerKey]:ledger,[transcriptKey]:transcript,['visit-binding:'+id(11)]:{kept:true}});
  await armAt(store,Date.parse(policy.enabledAt!));
  await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS});
  expect(await store.read('manifest:'+id(11))).toBeNull();
  expect(await store.read('chunk:'+id(11)+':0')).toBeNull();
  expect(await store.read(ledgerKey)).toEqual(ledger);
  expect(await store.read(transcriptKey)).toEqual(transcript);
  expect(await store.read('visit-binding:'+id(11))).toEqual({kept:true});
  store.close();
});

it('either switch off means no deletion and no label',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const row=manifest(id(12),ended);
  expect(audioRetentionEffective({enabled:false})).toBe(false);
  expect(audioRetentionEffective(null)).toBe(false);
  expect(audioRetentionEffective(undefined)).toBe(false);
  expect(audioRetentionEffective({enabled:'yes' as unknown as boolean})).toBe(false);
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS,{enabled:false})).toBeNull();
  expect(audioRetentionLabel(row,start+AUDIO_RETENTION_MS/2,{enabled:false})).toBeNull();
  expect(audioRetentionLabel(row,start+AUDIO_RETENTION_MS/2,policy)?.text)
    .toBe('Audio is removed from this device about 24 h from now; transcript and notes are kept.');
  expect(audioRetentionLabel(row,start+36*60*60*1000+1,policy)?.warn).toBe(true);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,row);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:{enabled:false},now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([]);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:null,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(12))).not.toBeNull();
  expect(await store.read('chunk:'+id(12)+':0')).not.toBeNull();
  store.close();
});

it('absent enabledAt means no deletion and no label (fail closed)',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const row=manifest(id(120),ended);
  const noAt=policyOn({enabledAt:'2026-10-01T00:00:00.000Z'});
  delete (noAt as {enabledAt?:string}).enabledAt;
  const badAt=policyOn({enabledAt:'not-a-date',now:start});
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS,noAt)).toBeNull();
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS,badAt)).toBeNull();
  expect(audioRetentionLabel(row,start+AUDIO_RETENTION_MS/2,noAt)).toBeNull();
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,row);
  expect((await sweepPrivateRecordingAudio({store,scope,policy:noAt,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect((await sweepPrivateRecordingAudio({store,scope,policy:badAt,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(120))).not.toBeNull();
  store.close();
});

it('refuseExpiredAudio uses a safe failure code with no audio bytes',()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  try{
    refuseExpiredAudio(manifest(id(13),ended),start+AUDIO_RETENTION_MS,policy);
    expect.unreachable();
  }catch(error){
    expect(error).toMatchObject({code:EXPIRED_AUDIO_REFUSED});
    expect(JSON.stringify(error)).not.toMatch(/AA==|wav|pcm/i);
  }
  refuseExpiredAudio(manifest(id(13),ended),start+AUDIO_RETENTION_MS-1,policy);
});

it('metadata write does not push the deadline when endedAt is set',()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const row={...manifest(id(14),ended),updatedAt:'2026-11-10T00:00:00.000Z'};
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS,policy)?.expired).toBe(true);
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS-1,policy)?.expired).toBe(false);
});

it('legacy manifest without endedAt falls back to updatedAt',()=>{
  const updated='2026-11-01T00:00:00.000Z',start=Date.parse(updated);
  const row={...manifest(id(15),updated),endedAt:null as unknown as undefined};
  delete (row as {endedAt?:string}).endedAt;
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS-1,policy)?.expired).toBe(false);
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS,policy)?.expired).toBe(true);
});

it('cutover: recording with old endedAt waits until max(anchor, enabledAt)+48h',async()=>{
  const flip='2026-11-15T12:00:00.000Z',flipMs=Date.parse(flip);
  const oldEnded='2026-10-16T12:00:00.000Z'; // ended before Box enabled_at
  const cutover=policyOn({enabledAt:flip,now:flipMs});
  const row=manifest(id(16),oldEnded);
  expect(audioRetentionAnchor(row,flipMs+AUDIO_RETENTION_MS-1,cutover)?.expired).toBe(false);
  expect(audioRetentionLabel(row,flipMs+AUDIO_RETENTION_MS-1,cutover)?.text)
    .toBe('Audio is removed from this device about 1 h from now; transcript and notes are kept.');
  expect(audioRetentionAnchor(row,flipMs+AUDIO_RETENTION_MS,cutover)?.expired).toBe(true);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,row);
  expect((await sweepPrivateRecordingAudio({store,scope,policy:cutover,now:()=>flipMs+AUDIO_RETENTION_MS-1,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(16))).not.toBeNull();
  expect((await sweepPrivateRecordingAudio({store,scope,policy:cutover,now:()=>flipMs+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([id(16)]);
  expect(await store.read('manifest:'+id(16))).toBeNull();
  store.close();
});

it('missing serverNow refuses delete (H7 fail closed)',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const noServer={enabled:true as const,hours:48,warnHours:36,enabledAt:'2026-10-01T00:00:00.000Z',fetchedAtDeviceMs:start};
  expect(resolveAudioRetentionClock(noServer,start+AUDIO_RETENTION_MS).allowDelete).toBe(false);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(170),ended));
  expect((await sweepPrivateRecordingAudio({store,scope,policy:noServer,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  refuseExpiredAudio(manifest(id(170),ended),start+AUDIO_RETENTION_MS,noServer);
  store.close();
});

it('clock skew over 5 min at fetch → no delete and no expired refuse',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const deviceAtFetch=start;
  const skewed=policyOn({
    enabledAt:'2026-10-01T00:00:00.000Z',
    fetchedAtDeviceMs:deviceAtFetch,
    serverNow:new Date(deviceAtFetch+AUDIO_RETENTION_CLOCK_SKEW_MS+1).toISOString(),
  });
  expect(resolveAudioRetentionClock(skewed,start+AUDIO_RETENTION_MS).allowDelete).toBe(false);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(17),ended));
  expect((await sweepPrivateRecordingAudio({store,scope,policy:skewed,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(17))).not.toBeNull();
  refuseExpiredAudio(manifest(id(17),ended),start+AUDIO_RETENTION_MS,skewed); // must not throw
  store.close();
});

it('aligned fetch then device advances 10 min still deletes at effective deadline (H7 offset)',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const fetchDevice=start; // serverNow ≈ device at fetch
  const aligned=policyOn({
    enabledAt:'2026-10-01T00:00:00.000Z',
    fetchedAtDeviceMs:fetchDevice,
    serverNow:new Date(fetchDevice).toISOString(),
  });
  const tenMin=10*60*1000;
  // Device advanced 10 min after fetch; deadline is start+48h → need device at deadline+10min? No:
  // offset=0 so effectiveNow=deviceNow. Advance device 10 min from an earlier point and still hit deadline.
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(18),ended));
  // At fetch+10min, still before deadline → keep
  expect((await sweepPrivateRecordingAudio({store,scope,policy:aligned,now:()=>fetchDevice+tenMin,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  // Advance device to deadline (10 min after a "would-be" early check); offset keeps tracking
  expect((await sweepPrivateRecordingAudio({store,scope,policy:aligned,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([id(18)]);
  store.close();
});

it('server ahead within skew at fetch: offset tracks so device-behind still deletes',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const serverAtDeadline=start+AUDIO_RETENTION_MS;
  const deviceAtFetch=serverAtDeadline-60_000; // 1 min behind at fetch
  const aligned=policyOn({
    enabledAt:'2026-10-01T00:00:00.000Z',
    fetchedAtDeviceMs:deviceAtFetch,
    serverNow:new Date(serverAtDeadline).toISOString(),
  });
  // offset = +60s; at same device time as fetch, effective = serverAtDeadline → delete
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(181),ended));
  expect((await sweepPrivateRecordingAudio({store,scope,policy:aligned,now:()=>deviceAtFetch,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([id(181)]);
  store.close();
});

it('Box-first then process: deviceArmedAt gates until flip+48h (H1)',async()=>{
  const flip='2026-11-15T12:00:00.000Z',flipMs=Date.parse(flip);
  const enabledLongAgo='2026-10-16T12:00:00.000Z'; // Box enabled_at before device arm
  const oldEnded='2026-09-01T12:00:00.000Z';
  const armed=policyOn({enabledAt:enabledLongAgo,deviceArmedAt:flip,now:flipMs});
  const row=manifest(id(26),oldEnded);
  expect(audioRetentionAnchor(row,flipMs+AUDIO_RETENTION_MS-1,armed)?.expired).toBe(false);
  expect(audioRetentionLabel(row,flipMs+AUDIO_RETENTION_MS-1,armed)?.text)
    .toBe('Audio is removed from this device about 1 h from now; transcript and notes are kept.');
  expect(audioRetentionAnchor(row,flipMs+AUDIO_RETENTION_MS,armed)?.expired).toBe(true);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,row);
  expect((await sweepPrivateRecordingAudio({store,scope,policy:armed,now:()=>flipMs+AUDIO_RETENTION_MS-1,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(26))).not.toBeNull();
  expect((await sweepPrivateRecordingAudio({store,scope,policy:armed,now:()=>flipMs+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([id(26)]);
  expect(await store.read('manifest:'+id(26))).toBeNull();
  store.close();
});

it('readOrStampDeviceArmedAt stamps once and never moves armedAt later',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const first=Date.parse('2026-11-15T12:00:00.000Z');
  const armedAt=await readOrStampDeviceArmedAt(store,first);
  expect(armedAt).toBe(new Date(first).toISOString());
  expect(await store.read(AUDIO_RETENTION_ARMED_KEY)).toEqual({
    contract:AUDIO_RETENTION_ARMED_CONTRACT,
    armedAt,
  });
  expect(await store.read(AUDIO_RETENTION_ARMED_KEY)).not.toHaveProperty('title');
  const later=await readOrStampDeviceArmedAt(store,first+AUDIO_RETENTION_MS);
  expect(later).toBe(armedAt);
  expect(await store.read(AUDIO_RETENTION_ARMED_KEY)).toEqual({contract:AUDIO_RETENTION_ARMED_CONTRACT,armedAt});
  // Runtime sweep merges stamped armedAt into policy before delete decisions.
  const ended='2026-10-01T00:00:00.000Z';
  await seed(store,manifest(id(27),ended));
  const pol=policyOn({enabledAt:'2026-09-01T00:00:00.000Z',now:first});
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{
    store,audioRetention:pol,now:()=>first+AUDIO_RETENTION_MS-1,
  })).deleted).toEqual([]); // max(anchor, enabledAt, armedAt=first)+48h
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{
    store,audioRetention:pol,now:()=>first+AUDIO_RETENTION_MS,
  })).deleted).toEqual([id(27)]);
  store.close();
});

it('policy-off clears armed stamp; re-enable gets a fresh grace window (H2)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const first=Date.parse('2026-10-01T00:00:00.000Z');
  const oldEnded='2026-09-01T00:00:00.000Z';
  await seed(store,manifest(id(40),oldEnded));
  const on=policyOn({enabledAt:'2026-09-15T00:00:00.000Z',now:first});
  const armed=await resolveArmedAudioRetentionPolicy(store,on,first);
  expect(armed?.deviceArmedAt).toBe(new Date(first).toISOString());
  expect(await readDeviceArmedAt(store)).toBe(new Date(first).toISOString());
  // Kill switch: observing policy off must clear the stamp.
  await resolveArmedAudioRetentionPolicy(store,{enabled:false},first+AUDIO_RETENTION_MS);
  expect(await readDeviceArmedAt(store)).toBeNull();
  expect(await store.read(AUDIO_RETENTION_ARMED_KEY)).toBeNull();
  // Re-enable later: fresh armedAt, old audio kept until newArm+48h (not first+48h).
  const reenable=first+AUDIO_RETENTION_MS+60_000;
  const again=policyOn({enabledAt:'2026-09-15T00:00:00.000Z',now:reenable});
  const restamped=await resolveArmedAudioRetentionPolicy(store,again,reenable);
  expect(restamped?.deviceArmedAt).toBe(new Date(reenable).toISOString());
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{
    store,audioRetention:again,now:()=>reenable+AUDIO_RETENTION_MS-1,
  })).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(40))).not.toBeNull();
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{
    store,audioRetention:again,now:()=>reenable+AUDIO_RETENTION_MS,
  })).deleted).toEqual([id(40)]);
  store.close();
});

it('unknown/null/missing-enabledAt leaves armed stamp alone (no clear, no stamp)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const first=Date.parse('2026-10-01T00:00:00.000Z');
  const stamped=new Date(first).toISOString();
  await readOrStampDeviceArmedAt(store,first);
  expect(await readDeviceArmedAt(store)).toBe(stamped);
  expect(await resolveArmedAudioRetentionPolicy(store,null,first+60_000)).toBeNull();
  expect(await readDeviceArmedAt(store)).toBe(stamped);
  expect(await resolveArmedAudioRetentionPolicy(store,undefined,first+60_000)).toBeUndefined();
  expect(await readDeviceArmedAt(store)).toBe(stamped);
  // enabled without enabledAt: reuse existing stamp, do not clear or invent a new one.
  const missingAt=await resolveArmedAudioRetentionPolicy(store,{enabled:true},first+60_000);
  expect(missingAt).toEqual({enabled:true,deviceArmedAt:stamped});
  expect(await readDeviceArmedAt(store)).toBe(stamped);
  // Failed-clock / no allowDelete also leaves stamp, does not invent a new one.
  const skewed=policyOn({
    enabledAt:'2026-09-01T00:00:00.000Z',
    fetchedAtDeviceMs:first,
    serverNow:new Date(first+AUDIO_RETENTION_CLOCK_SKEW_MS+1).toISOString(),
  });
  expect(resolveAudioRetentionClock(skewed,first).allowDelete).toBe(false);
  await resolveArmedAudioRetentionPolicy(store,skewed,first);
  expect(await readDeviceArmedAt(store)).toBe(stamped);
  store.close();
});

it('sweep returns early without opening a store when policy is absent/unknown',async()=>{
  const openStore=vi.fn(async()=>{throw new Error('store must not open for unknown policy');});
  expect(await sweepExpiredPrivateRecordingAudio(scope,'desktop',{audioRetention:null,openStore})).toEqual({deleted:[],inspected:0});
  expect(await sweepExpiredPrivateRecordingAudio(scope,'desktop',{audioRetention:undefined,openStore})).toEqual({deleted:[],inspected:0});
  expect(await sweepExpiredPrivateRecordingAudio(scope,'desktop',{audioRetention:{enabled:'maybe' as never},openStore})).toEqual({deleted:[],inspected:0});
  expect(openStore).not.toHaveBeenCalled();
});

it('stamps armedAt only when allowDelete, using effectiveNowMs not raw device clock (H2)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const deviceNow=Date.parse('2026-11-15T12:00:00.000Z');
  const serverAhead=deviceNow+60_000; // +1 min → effectiveNow = deviceNow+60s
  const skewed=policyOn({
    enabledAt:'2026-10-01T00:00:00.000Z',
    fetchedAtDeviceMs:deviceNow,
    serverNow:new Date(deviceNow+AUDIO_RETENTION_CLOCK_SKEW_MS+1).toISOString(),
  });
  expect(resolveAudioRetentionClock(skewed,deviceNow).allowDelete).toBe(false);
  const noStamp=await resolveArmedAudioRetentionPolicy(store,skewed,deviceNow);
  expect(noStamp?.deviceArmedAt).toBeUndefined();
  expect(await readDeviceArmedAt(store)).toBeNull();
  const aligned=policyOn({
    enabledAt:'2026-10-01T00:00:00.000Z',
    fetchedAtDeviceMs:deviceNow,
    serverNow:new Date(serverAhead).toISOString(),
  });
  const stamped=await resolveArmedAudioRetentionPolicy(store,aligned,deviceNow);
  // effectiveNowMs = deviceNow + (serverAhead - deviceNow) = serverAhead
  expect(stamped?.deviceArmedAt).toBe(new Date(serverAhead).toISOString());
  expect(stamped?.deviceArmedAt).not.toBe(new Date(deviceNow).toISOString());
  store.close();
});

it('open refuse and snapshot label honor device armed grace for Box-first flip (H2)',async()=>{
  const flip='2026-11-15T12:00:00.000Z',flipMs=Date.parse(flip);
  const enabledLongAgo='2026-10-16T12:00:00.000Z';
  const oldEnded='2026-09-01T12:00:00.000Z';
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const row=manifest(id(41),oldEnded);
  await seed(store,row);
  const bag={current:policyOn({enabledAt:enabledLongAgo,now:flipMs})};
  // Device first armed at flip (Box enabled long ago). Open must merge that stamp.
  await resolveArmedAudioRetentionPolicy(store,bag.current,flipMs);
  store.close();
  const duringGrace=flipMs+AUDIO_RETENTION_MS-1;
  // Unarmed bag alone would treat enabledAt+48h as expired; armed grace keeps it open.
  expect(audioRetentionLabel(row,duringGrace,bag.current)).toBeNull();
  const runtime=await PrivateRecordingRuntime.open({
    scope,platform:'desktop',isCurrent:()=>true,
    openStore:()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto}),
    getAudioRetention:()=>bag.current,now:()=>duringGrace,
  },{recordingId:id(41),title:'Synthetic Box-first'});
  expect(runtime.snapshot.retentionLabel).toMatch(/Audio is removed from this device about/);
  await runtime.close();
  // After armed grace, refuse on open.
  await expect(PrivateRecordingRuntime.open({
    scope,platform:'desktop',isCurrent:()=>true,
    openStore:()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto}),
    getAudioRetention:()=>bag.current,now:()=>flipMs+AUDIO_RETENTION_MS,
  },{recordingId:id(41),title:'Synthetic Box-first'})).rejects.toMatchObject({code:EXPIRED_AUDIO_REFUSED});
});

it('clearDeviceArmedAt removes the stamp key',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await readOrStampDeviceArmedAt(store,Date.parse('2026-11-15T12:00:00.000Z'));
  expect(await readDeviceArmedAt(store)).not.toBeNull();
  await clearDeviceArmedAt(store);
  expect(await readDeviceArmedAt(store)).toBeNull();
  store.close();
});

it('unreadable transfer-retention-released marker keeps protection (fail closed)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(42),ended));
  await armAt(store,Date.parse(policy.enabledAt!));
  await store.write('transfer:'+id(42),null,{contract:'cosmas.saved-transfer.v1',recording_id:id(42)});
  await markTransferRetentionReleased(store,id(42),'2026-11-03T00:00:00.000Z');
  const markerKey='transfer-retention-released:'+id(42);
  const realRead=store.read.bind(store);
  store.read=async(key:string)=>{if(key===markerKey)throw new Error('Synthetic marker unread');return realRead(key);};
  expect((await audioSweepSkipIds(store)).has(id(42))).toBe(true);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([]);
  store.close();
});

it('poison manifest does not block later deletes',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(19),ended));
  await seed(store,manifest(id(20),ended));
  const failures:string[]=[];
  const result=await sweepPrivateRecordingAudio({
    store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value,recordingId)=>{
      if(recordingId===id(19))throw new Error('poison manifest');
      return value as PrivateRecordingManifest;
    },
    recordFailure:(recordingId)=>failures.push(recordingId),
  });
  expect(failures).toEqual([id(19)]);
  expect(result.deleted).toEqual([id(20)]);
  expect(await store.read('manifest:'+id(19))).not.toBeNull();
  expect(await store.read('manifest:'+id(20))).toBeNull();
  store.close();
});

it('throwing store.delete mid-loop does not stop later recordings',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(21),ended));
  await seed(store,manifest(id(22),ended));
  const realDelete=store.delete.bind(store);
  store.delete=async(key:string)=>{
    if(key.startsWith('chunk:'+id(21)+':')||key==='manifest:'+id(21))throw new Error('delete boom');
    return realDelete(key);
  };
  const failures:string[]=[];
  const result=await sweepPrivateRecordingAudio({
    store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest,
    recordFailure:(recordingId)=>failures.push(recordingId),
  });
  expect(failures).toEqual([id(21)]);
  expect(result.deleted).toEqual([id(22)]);
  expect(await store.read('manifest:'+id(22))).toBeNull();
  store.close();
});

it('shouldSkipRecording skips and onDeleted fires after successful delete',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(23),ended));
  await seed(store,manifest(id(24),ended));
  const deletedHooks:string[]=[];
  const result=await sweepPrivateRecordingAudio({
    store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest,
    shouldSkipRecording:(recordingId)=>recordingId===id(23),
    onDeleted:async(recordingId)=>{deletedHooks.push(recordingId);},
  });
  expect(result.deleted).toEqual([id(24)]);
  expect(deletedHooks).toEqual([id(24)]);
  expect(await store.read('manifest:'+id(23))).not.toBeNull();
  store.close();
});

it('normalizeAudioRetentionPolicy maps snake_case, pins hours to 48, stamps fetchedAtDeviceMs',()=>{
  const fetchMs=1_700_000_000_000;
  expect(normalizeAudioRetentionPolicy(null)).toBeNull();
  expect(normalizeAudioRetentionPolicy(undefined)).toBeNull();
  expect(normalizeAudioRetentionPolicy('nope')).toBeNull();
  expect(normalizeAudioRetentionPolicy({enabled:false})).toEqual({enabled:false});
  expect(normalizeAudioRetentionPolicy({
    enabled:true,
    hours:72,
    warn_hours:36,
    enabled_at:'2026-11-15T00:00:00.000Z',
    server_now:'2026-11-16T00:00:00.000Z',
  },fetchMs)).toEqual({
    enabled:true,
    hours:AUDIO_RETENTION_HOURS,
    warnHours:36,
    enabledAt:'2026-11-15T00:00:00.000Z',
    serverNow:'2026-11-16T00:00:00.000Z',
    fetchedAtDeviceMs:fetchMs,
  });
});

it('tombstone and audio-deleted stub contracts omit title',()=>{
  const tomb=buildAudioTombstone(id(25),'2026-11-17T00:00:00.000Z','deleted');
  expect(tomb).toEqual({
    contract:AUDIO_TOMBSTONE_CONTRACT,
    recordingId:id(25),
    deletedAt:'2026-11-17T00:00:00.000Z',
    outcome:'deleted',
  });
  expect(tomb).not.toHaveProperty('title');
  const failed=buildAudioTombstone(id(25),'2026-11-17T00:00:00.000Z','failed');
  expect(failed.outcome).toBe('failed');
  const stub=buildAudioDeletedStub(id(25),scope,'2026-11-17T00:00:00.000Z');
  expect(stub).toEqual({
    contract:AUDIO_DELETED_STUB_CONTRACT,
    recordingId:id(25),
    scope,
    phase:'audio_deleted',
    updatedAt:'2026-11-17T00:00:00.000Z',
  });
  expect(AUDIO_DELETED_USER_MESSAGE).toBe('Audio deleted on this device; transcript and notes kept.');
});

it('refuseExpiredAudio skip option and transfer protection gate delete',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const row=manifest(id(26),ended);
  refuseExpiredAudio(row,start+AUDIO_RETENTION_MS,policy,{skip:true}); // must not throw
  try{refuseExpiredAudio(row,start+AUDIO_RETENTION_MS,policy);expect.unreachable();}
  catch(error){expect(error).toMatchObject({code:EXPIRED_AUDIO_REFUSED,message:AUDIO_DELETED_USER_MESSAGE});}
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,row);
  await armAt(store,Date.parse(policy.enabledAt!));
  await store.write('transfer:'+id(26),null,{contract:'cosmas.saved-transfer.v1',recording_id:id(26)});
  expect(await isAudioRetentionProtected(store,id(26))).toBe(true);
  expect((await audioSweepSkipIds(store)).has(id(26))).toBe(true);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(26))).not.toBeNull();
  // Protection ends via release marker — transfer: row stays for panel CAS persist.
  await markTransferRetentionReleased(store,id(26),'2026-11-03T00:00:00.000Z');
  expect(await isTransferRetentionReleased(store,id(26))).toBe(true);
  expect(await store.read('transfer:'+id(26))).not.toBeNull();
  expect(await isAudioRetentionProtected(store,id(26))).toBe(false);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([id(26)]);
  store.close();
});

it('unreadable ledger rows are skipped (fail closed for delete)',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(27),ended));
  await armAt(store,Date.parse(policy.enabledAt!));
  const ledgerKey=privateRecordingLedgerKey(id(27));
  await store.write(ledgerKey,null,{state:'attach_pending'});
  const realRead=store.read.bind(store);
  store.read=async(key:string)=>{if(key===ledgerKey)throw new Error('Synthetic ledger unread');return realRead(key);};
  expect((await audioSweepSkipIds(store)).has(id(27))).toBe(true);
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([]);
  expect(await realRead('manifest:'+id(27))).not.toBeNull();
  store.close();
});

it('opens audio-deleted stub without manifest and surfaces exact user message',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const updatedAt='2026-11-17T00:00:00.000Z';
  await store.write('audio-deleted:'+id(28),null,buildAudioDeletedStub(id(28),scope,updatedAt));
  store.close();
  const runtime=await PrivateRecordingRuntime.open({scope,platform:'desktop',isCurrent:()=>true,
    openStore:()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto})},
    {recordingId:id(28),title:'Synthetic deleted clip'});
  expect(runtime.snapshot).toMatchObject({phase:'audio_deleted',retentionLabel:AUDIO_DELETED_USER_MESSAGE,failure:AUDIO_DELETED_USER_MESSAGE});
  await runtime.close();
  const rows=await listPrivateRecordings(scope,'desktop',()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto}));
  expect(rows[0]).toMatchObject({recordingId:id(28),phase:'audio_deleted',retentionLabel:AUDIO_DELETED_USER_MESSAGE});
});

it('admitted transfer with partial upload past deadline remounts protected and openable',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(50),ended),{
    ['transfer:'+id(50)]:{contract:'cosmas.saved-transfer.v1',recording_id:id(50),admitted:true},
  });
  await armAt(store,Date.parse(policy.enabledAt!));
  const past=()=>start+AUDIO_RETENTION_MS;
  // Without transfer protection this would refuse; with unreleased transfer: open succeeds.
  const first=await PrivateRecordingRuntime.open({
    scope,platform:'desktop',isCurrent:()=>true,
    openStore:async()=>store,getAudioRetention:()=>policy,now:past,
  },{recordingId:id(50),title:'Synthetic mid-upload'});
  expect(first.snapshot.phase).toBe('sealed');
  expect(await isTransferRetentionReleased(store,id(50))).toBe(false);
  expect(await isAudioRetentionProtected(store,id(50))).toBe(true);
  await first.close();
  // Remount after close: still protected, still openable, still no release marker.
  const remountStore=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const remount=await PrivateRecordingRuntime.open({
    scope,platform:'desktop',isCurrent:()=>true,
    openStore:async()=>remountStore,getAudioRetention:()=>policy,now:past,
  },{recordingId:id(50),title:'Synthetic mid-upload'});
  expect(remount.snapshot.phase).toBe('sealed');
  expect(await isTransferRetentionReleased(remountStore,id(50))).toBe(false);
  expect(await isAudioRetentionProtected(remountStore,id(50))).toBe(true);
  await remount.close();
});

it('live getAudioRetention getter is consulted each time (not a stale open capture)',async()=>{
  const bag:{current:AudioRetentionPolicy|null|undefined}={current:{enabled:false}};
  const source={kind:'microphone' as const,async start(){},async stop(){}};
  const fresh=()=>({...consent(),granted_at:new Date().toISOString()});
  const runtime=await PrivateRecordingRuntime.open({scope,platform:'desktop',isCurrent:()=>true,
    openStore:()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto}),
    createSource:async()=>source as never,acquireLock:async()=>async()=>{},
    getAudioRetention:()=>bag.current,now:()=>Date.now()},
    {title:'Synthetic live policy',consent:fresh()});
  expect(runtime.snapshot.retentionLabel??null).toBeNull();
  bag.current=policyOn({enabledAt:'2026-11-01T00:00:00.000Z',now:Date.now()});
  await runtime.start(fresh());
  await runtime.stop();
  // Getter flipped on after open; seal pins endedAt and label appears from live policy.
  expect(runtime.snapshot.retentionLabel).toMatch(/Audio is removed from this device about/);
  bag.current={enabled:false};
  expect(runtime.snapshot.retentionLabel??null).toBeNull();
  await runtime.close();
});
