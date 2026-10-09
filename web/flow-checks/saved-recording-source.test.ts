// @vitest-environment node
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {PrivateRecordingRuntime,openPrivateRecordingStore} from '../src/private-recording-runtime';
import {SavedRecordingSource} from '../src/saved-recording-source';
import {importSavedChunks} from '../src/saved-recording-runtime';
import {CaptureFlowController} from '../../clients/capture/src/configured/flow/controller';
import {EncryptedIndexedDbFlowStore} from '../../clients/capture/src/configured/flow/encrypted-store';
import {EncryptedIndexedDbQueueStorage} from '../../clients/capture/src/storage/encrypted-indexeddb';
import {CaptureQueue} from '../../clients/capture/src/queue/capture-queue';
import {BffCaptureQueueTransport} from '../../clients/capture/src/bff/queue-transport';
import {HttpCaptureBff} from '../../clients/capture/src/bff/http-client';
import {HttpCiphertextUploadTarget} from '../../clients/capture/src/bff/upload-target';
import {createMockBffServer} from '../../clients/capture/src/configured/mock-bff/server';
import {encodePcm16MonoWav} from '../../clients/capture/src/capture/wav';
import type {CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import type {AddressInfo} from 'node:net';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let idb:IDBFactory;
const scope='a'.repeat(64),consent=()=>({modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:new Date().toISOString(),language:'en-US' as const});
beforeEach(()=>{idb=new IDBFactory();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('indexedDB',idb);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);
  vi.stubGlobal('navigator',{locks:{request:async(_name:string,_options:unknown,callback:(lock:unknown)=>unknown)=>callback({name:'owned-synthetic-lock'})}});
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});

it.each([3,91])('imports %s verified private chunks through actual encrypted queue, preserves original audio and resumes the same transfer',async total=>{
  let options:CaptureSourceStartOptions|undefined,starts=0,current=true;
  const recording=await PrivateRecordingRuntime.open({scope,platform:'desktop',isCurrent:()=>current,
    openStore:()=>openPrivateRecordingStore(scope,'desktop',{indexedDB:idb,crypto:webcrypto}),acquireLock:async()=>async()=>{},
    createSource:async()=>({kind:'microphone',start:async o=>{options=o;starts++;},stop:async()=>{}})},
    {title:'Invented synthetic audio',consent:consent()});
  const server=createMockBffServer();await new Promise<void>((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  const origin='http://127.0.0.1:'+(server.address() as AddressInfo).port;
  const flowName=crypto.randomUUID(),queueName=crypto.randomUUID();
  let flow=await EncryptedIndexedDbFlowStore.open({databaseName:flowName,indexedDB:idb,crypto:webcrypto});
  let storage=await EncryptedIndexedDbQueueStorage.open({databaseName:queueName,indexedDB:idb,crypto:webcrypto});
  const bff=new HttpCaptureBff((input,init)=>fetch(typeof input==='string'?new URL(input,origin):input,init));
  let controller:CaptureFlowController|undefined;
  try{
    await recording.start(consent());
    for(let i=0;i<total;i++){
      if(i===90){await recording.pause();await recording.start(consent());}
      const samples=new Int16Array(Array(160).fill(i+1234));
      await options!.onChunk({sequenceNumber:i%90,durationMs:10,wavBytes:encodePcm16MonoWav(samples,{sampleRateHz:16000,channels:1,targetChunkDurationMs:10000,maxEnvelopeBytes:320044})});
    }
    await recording.stop();const before=await recording.snapshotForLedger();
    const person={appointment_id:'invented-appointment',practitioner_id:'invented-provider',patient_id:'invented-patient'};
    const c=await bff.createConsent({...person,...consent()},{idempotencyKey:'saved-source-consent'});
    const session=await bff.createSession({...person,consent_record_id:c.id,modality:'in_person'},{idempotencyKey:'saved-source-session'});
    const source=new SavedRecordingSource(recording,()=>current);
    const make=()=>new CaptureFlowController({bff,flowStore:flow,queue:new CaptureQueue(storage,{crypto:webcrypto}),source,
      queueTransport:new BffCaptureQueueTransport(bff,new HttpCiphertextUploadTarget([origin])),crypto:webcrypto});
    controller=make();await controller.prepareConfigured(session.id);
    const complete=bff.completeCapture.bind(bff),submit=vi.spyOn(bff,'completeCapture').mockImplementationOnce(async(...args)=>{await complete(...args);throw Error('lost completion reply');});
    await expect(importSavedChunks(controller,source,total,()=>current)).rejects.toThrow('lost completion reply');
    const retained=await flow.getActiveCaptureState();expect(retained?.recordedChunks).toBe(total);expect(controller.snapshot.recordedChunks).toBe(total);
    await controller.deactivate();flow.close();storage.close();
    flow=await EncryptedIndexedDbFlowStore.open({databaseName:flowName,indexedDB:idb,crypto:webcrypto});
    storage=await EncryptedIndexedDbQueueStorage.open({databaseName:queueName,indexedDB:idb,crypto:webcrypto});
    controller=make();expect(await controller.restore()).toBe(true);
    await importSavedChunks(controller,source,total,()=>current);
    expect(controller.snapshot.state).toBe('processing');expect(submit).toHaveBeenCalledTimes(2);
    expect(submit.mock.calls[0]).toEqual(submit.mock.calls[1]);
    const rows=await storage.listMetadata();expect(rows.filter(r=>r.reservation.sequenceNumber<total).every(r=>r.state==='purged')).toBe(true);
    expect(await recording.snapshotForLedger()).toEqual(before);expect(starts).toBe(total===91?2:1);
    let count=0;for await(const chunk of recording.savedChunks()){expect(new DataView(chunk.wavBytes.buffer).getInt16(44,true)).toBe(count+1234);count++;}expect(count).toBe(total);
  }finally{current=false;await controller?.deactivate().catch(()=>{});flow.close();storage.close();await recording.close();await new Promise<void>((resolve,reject)=>server.close(e=>e?reject(e):resolve()));}
},20000);

it('refuses changed ownership before reading any saved audio',async()=>{
  const read=vi.fn(),source=new SavedRecordingSource({savedChunks:read},()=>false);
  await expect(source.start({capabilities:{} as never,onChunk:async()=>{}})).rejects.toThrow();expect(read).not.toHaveBeenCalled();
});
