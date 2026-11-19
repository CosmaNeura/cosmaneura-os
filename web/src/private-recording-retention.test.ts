import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import type {SecureQueuePlugin,VersionedSecureQueueRecord} from '../../clients/capture/plugins/secure-queue/definitions';
import {openPrivateRecordingStore,sweepExpiredPrivateRecordingAudio,type PrivateRecordingManifest,type PrivateRecordingStore} from './private-recording-runtime';
import {privateRecordingLedgerKey} from './private-recording-ledger';
import {
  AUDIO_RETENTION_MS,
  audioRetentionAnchor,
  audioRetentionEffective,
  audioRetentionLabel,
  deletePrivateRecordingAudio,
  EXPIRED_AUDIO_REFUSED,
  refuseExpiredAudio,
  sweepPrivateRecordingAudio,
} from './private-recording-retention';

const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const scope='d'.repeat(64),otherScope='e'.repeat(64);
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const consent=()=>({modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:'2026-11-01T12:00:00.000Z',language:'en-US' as const});
const policy={enabled:true as const,hours:48,warnHours:36};
let idb:IDBFactory;
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);idb=new IDBFactory();});
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
    parseManifest:(value,recordingId)=>value as PrivateRecordingManifest});
  expect(keep.deleted).toEqual([]);
  expect(await store.read('manifest:'+id(1))).not.toBeNull();
  expect(await store.read('chunk:'+id(1)+':0')).not.toBeNull();
  const gone=await sweepPrivateRecordingAudio({store,scope,policy,now:()=>start+AUDIO_RETENTION_MS,
    parseManifest:(value,recordingId)=>value as PrivateRecordingManifest});
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
    async create({key,data}){if(records.has(key))throw Error('exists');const row={key,revision:'1',data};records.set(key,row);return row;},
    async compareAndSwap({key,data,expectedRevision}){const prior=records.get(key);if(!prior||prior.revision!==expectedRevision)throw Error('cas');const row={key,revision:String(Number(expectedRevision)+1),data};records.set(key,row);return row;},
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
  await seed(store,manifest(id(11),ended),{[ledgerKey]:ledger,[transcriptKey]:transcript,'visit-binding:'+id(11):{kept:true}});
  await sweepExpiredPrivateRecordingAudio(scope,'desktop',{store,audioRetention:policy,now:()=>start+AUDIO_RETENTION_MS});
  expect(await store.read('manifest:'+id(11))).toBeNull();
  expect(await store.read('chunk:'+id(11)+':0')).toBeNull();
  expect(await store.read(ledgerKey)).toEqual(ledger);
  expect(await store.read(transcriptKey)).toEqual(transcript);
  expect(await store.read('visit-binding:'+id(11))).toEqual({kept:true});
  store.close();
});

it('either switch off means no deletion and no label',()=>{
  const ended='2026-11-01T00:00:00.000Z',start=Date.parse(ended);
  const row=manifest(id(12),ended);
  expect(audioRetentionEffective({enabled:false})).toBe(false);
  expect(audioRetentionEffective(null)).toBe(false);
  expect(audioRetentionEffective(undefined)).toBe(false);
  expect(audioRetentionEffective({enabled:'yes' as unknown as boolean})).toBe(false);
  expect(audioRetentionAnchor(row,start+AUDIO_RETENTION_MS,{enabled:false})).toBeNull();
  expect(audioRetentionLabel(row,start+AUDIO_RETENTION_MS/2,{enabled:false})).toBeNull();
  expect(audioRetentionLabel(row,start+AUDIO_RETENTION_MS/2,policy)?.text).toMatch(/^deletes in \d+ h$/);
  expect(audioRetentionLabel(row,start+36*60*60*1000+1,policy)?.warn).toBe(true);
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
