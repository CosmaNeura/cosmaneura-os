import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {SecureQueuePlugin,VersionedSecureQueueRecord} from '../../clients/capture/plugins/secure-queue/definitions';
import {openPrivateRecordingStore,sweepExpiredPrivateRecordingAudio,type PrivateRecordingManifest,type PrivateRecordingStore} from './private-recording-runtime';
import {privateRecordingLedgerKey} from './private-recording-ledger';
import {
  AUDIO_DELETED_STUB_CONTRACT,
  AUDIO_RETENTION_CLOCK_SKEW_MS,
  AUDIO_RETENTION_MS,
  AUDIO_TOMBSTONE_CONTRACT,
  audioRetentionAnchor,
  audioRetentionEffective,
  audioRetentionLabel,
  buildAudioDeletedStub,
  buildAudioTombstone,
  deletePrivateRecordingAudio,
  EXPIRED_AUDIO_REFUSED,
  normalizeAudioRetentionPolicy,
  refuseExpiredAudio,
  sweepPrivateRecordingAudio,
} from './private-recording-retention';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const scope='d'.repeat(64),otherScope='e'.repeat(64);
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const consent=()=>({modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:'2026-11-01T12:00:00.000Z',language:'en-US' as const});
/** enabledAt at/before ended so deadline stays endedAt+48h for classic clock tests. */
const policy={enabled:true as const,hours:48,warnHours:36,enabledAt:'2026-10-01T00:00:00.000Z'};
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
  await deletePrivateRecordingAudio(store,id(3),2);
  expect(await store.read('manifest:'+id(3))).toBeNull();
  expect(await store.read('chunk:'+id(3)+':1')).toBeNull();
  await deletePrivateRecordingAudio(store,id(3),2); // idempotent retry
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

it('offline then sweep on launch deletes expired audio',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  await seed(store,manifest(id(5),ended));
  store.close();
  // Device offline: no sweep. Reopen = launch.
  const relaunch=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  expect((await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store:relaunch,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS})).deleted).toEqual([id(5)]);
  relaunch.close();
});

it('sign-out sweep removes expired audio only',async()=>{
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  const base=Date.parse('2026-11-01T00:00:00.000Z');
  await seed(store,manifest(id(6),new Date(base).toISOString()));
  await seed(store,manifest(id(7),new Date(base+AUDIO_RETENTION_MS/2).toISOString()));
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
  const noAt={enabled:true as const,hours:48,warnHours:36};
  const badAt={enabled:true as const,hours:48,warnHours:36,enabledAt:'not-a-date'};
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

it('grandfathering: 30-day-old recording waits until flip+48h',async()=>{
  const flip='2026-11-15T12:00:00.000Z',flipMs=Date.parse(flip);
  const oldEnded='2026-10-16T12:00:00.000Z'; // 30 days before flip
  const grandpa={enabled:true as const,hours:48,warnHours:36,enabledAt:flip};
  const row=manifest(id(16),oldEnded);
  expect(audioRetentionAnchor(row,flipMs+AUDIO_RETENTION_MS-1,grandpa)?.expired).toBe(false);
  expect(audioRetentionLabel(row,flipMs+AUDIO_RETENTION_MS-1,grandpa)?.text)
    .toBe('Audio is removed from this device about 1 h from now; transcript and notes are kept.');
  expect(audioRetentionAnchor(row,flipMs+AUDIO_RETENTION_MS,grandpa)?.expired).toBe(true);
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,row);
  expect((await sweepPrivateRecordingAudio({store,scope,policy:grandpa,now:()=>flipMs+AUDIO_RETENTION_MS-1,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(16))).not.toBeNull();
  expect((await sweepPrivateRecordingAudio({store,scope,policy:grandpa,now:()=>flipMs+AUDIO_RETENTION_MS,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([id(16)]);
  expect(await store.read('manifest:'+id(16))).toBeNull();
  store.close();
});

it('clock skew over bound → no delete and no expired refuse',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const deviceNow=start+AUDIO_RETENTION_MS;
  const skewed={...policy,serverNow:new Date(deviceNow+AUDIO_RETENTION_CLOCK_SKEW_MS+1).toISOString()};
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(17),ended));
  expect((await sweepPrivateRecordingAudio({store,scope,policy:skewed,now:()=>deviceNow,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([]);
  expect(await store.read('manifest:'+id(17))).not.toBeNull();
  refuseExpiredAudio(manifest(id(17),ended),deviceNow,skewed); // must not throw
  store.close();
});

it('serverNow within skew bound drives effective clock for delete',async()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const serverAtDeadline=start+AUDIO_RETENTION_MS;
  const deviceBehind=serverAtDeadline-60_000; // 1 min behind, within 5 min
  const aligned={...policy,serverNow:new Date(serverAtDeadline).toISOString()};
  const store=await openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto});
  await seed(store,manifest(id(18),ended));
  expect((await sweepPrivateRecordingAudio({store,scope,policy:aligned,now:()=>deviceBehind,
    parseManifest:(value)=>value as PrivateRecordingManifest})).deleted).toEqual([id(18)]);
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

it('normalizeAudioRetentionPolicy maps snake_case and rejects invalid raw',()=>{
  expect(normalizeAudioRetentionPolicy(null)).toBeNull();
  expect(normalizeAudioRetentionPolicy(undefined)).toBeNull();
  expect(normalizeAudioRetentionPolicy('nope')).toBeNull();
  expect(normalizeAudioRetentionPolicy({enabled:false})).toEqual({enabled:false});
  expect(normalizeAudioRetentionPolicy({
    enabled:true,
    hours:48,
    warn_hours:36,
    enabled_at:'2026-11-15T00:00:00.000Z',
    server_now:'2026-11-16T00:00:00.000Z',
  })).toEqual({
    enabled:true,
    hours:48,
    warnHours:36,
    enabledAt:'2026-11-15T00:00:00.000Z',
    serverNow:'2026-11-16T00:00:00.000Z',
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
});
