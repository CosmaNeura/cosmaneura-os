import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {PrivateRecordingLedgerController} from './private-recording-ledger';
import {openPrivateRecordingStore,type PrivateRecordingStore,type PrivateRecordingRuntime} from './private-recording-runtime';
import {privateRecordingApi,type PrivateRecordingIntent,type PrivateRecordingReceipt} from './private-recording-api';
import {vendorCanonical,vendorSha256} from './vendor-contract';
import type {Workspace,ProviderTeam} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const localScope='a'.repeat(64);let scope:string,team:ProviderTeam,workspace:Workspace,idb:IDBFactory,store:PrivateRecordingStore,current:boolean;
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const snapshot=():Awaited<ReturnType<PrivateRecordingRuntime['snapshotForLedger']>>=>({recordingId:id(2),scope:localScope,
  consent:{modality:'in_person',participant_regions:['US-NY'],method:'verbal_attestation',all_parties_consented:true,granted_at:'2026-10-08T00:00:00.000Z',language:'en-US'},consentIntervals:[],startedAt:'2026-10-08T00:00:01.000Z',phase:'recording',frames:16,chunks:1,manifestSHA256:'b'.repeat(64),updatedAt:'2026-10-08T00:00:02.000Z'});
const controller=()=>new PrivateRecordingLedgerController({identity,team,workspace,store,scope:localScope,isCurrent:()=>current});
function receipt(v:PrivateRecordingIntent):PrivateRecordingReceipt{return {contract:'cosmas.private-recording.v1',custody:'local_device_metadata',recording_id:id(3),local_recording_id:id(2),workspace_id:id(1),workspace_revision:1,owner_id:id(11),box_id:id(10),agent_id:id(12),team_revision_id:id(13),recovery_scope:scope,attach_sha256:v.request_sha256,started_at:v.request.started_at,created_at:'2026-10-08T00:00:02Z',state:'unfinished',finish:null,link:null,upstream_capture_admitted:false,audio_uploaded:false,transcription_started:false};}
beforeEach(async()=>{
  vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);current=true;idb=new IDBFactory();
  scope=await vendorSha256(new TextEncoder().encode(vendorCanonical({contract:'cosmas-private-drafts-v1',box_id:id(10),owner_id:id(11)})));
  team={revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[{role:'scribe',name:'Scribe',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[{role:'scribe',agent_id:id(12),name:'Scribe',initials:'S',description:'',prompt:'',capabilities:[]}]};
  workspace={id:id(1),appointment_id:null,label:'Private',revision:1,entries:[],work_candidates:[],private_draft:{title:'Private',state:'unlinked',link_receipt_id:null,linked_at:null}};
  store=await openPrivateRecordingStore(localScope,'desktop',{indexedDB:idb,crypto:webcrypto});
});
afterEach(()=>{store.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('seals intent before dispatch, reopens lost reply, checks without POST and retries only exact retained intent',async()=>{
  const commands:PrivateRecordingIntent[]=[];
  const submit=vi.spyOn(privateRecordingApi,'attach').mockImplementation(async(_identity,v)=>{commands.push(v);const retained=await store.read('ledger:'+id(2));expect(retained).toMatchObject({state:'attach_pending',uncertain:true,attach:v});throw Error('lost reply');});
  const c=controller();await expect(c.attach(snapshot())).rejects.toThrow();expect(submit).toHaveBeenCalledTimes(1);
  store.close();store=await openPrivateRecordingStore(localScope,'desktop',{indexedDB:idb,crypto:webcrypto});const reopened=controller();await expect(reopened.attach(snapshot())).rejects.toThrow();expect(submit).toHaveBeenCalledTimes(1);
  vi.spyOn(privateRecordingApi,'resolve').mockResolvedValue({outcome:'not_found',recording:null});expect((await reopened.checkSaved(id(2))).retry_ready).toBe(true);expect(submit).toHaveBeenCalledTimes(1);
  submit.mockImplementation(async(_identity,v)=>{commands.push(v);return receipt(v);});expect((await reopened.retryExact(id(2))).state).toBe('attached');expect(commands[1]).toEqual(commands[0]);
  const request=<T,>(r:IDBRequest<T>)=>new Promise<T>((resolve,reject)=>{r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
  const db=await request(idb.open('cosmas-private-recording:v1:'+localScope)),rows=await request(db.transaction('records','readonly').objectStore('records').getAll());db.close();
  expect(rows).toHaveLength(1);expect(rows[0].ciphertext).toBeInstanceOf(ArrayBuffer);expect(JSON.stringify(rows)).not.toContain('idempotency_key');expect(JSON.stringify(rows)).not.toContain('US-NY');
});
it('recovers a lost finish reply by GET with no second finish submission',async()=>{
  vi.spyOn(privateRecordingApi,'attach').mockImplementation(async(_identity,v)=>receipt(v));const c=controller();await c.attach(snapshot());
  const finish=vi.spyOn(privateRecordingApi,'finish').mockRejectedValue(Error('lost saved response'));
  await expect(c.finish({...snapshot(),phase:'sealed'})).rejects.toThrow();const pending=await c.readCurrent(id(2));expect(pending?.finish).not.toBeNull();
  const saved={...pending!.receipt!,state:'finished' as const,finish:{receipt_id:id(5),request_sha256:pending!.finish!.request_sha256,manifest_sha256:'b'.repeat(64),chunks:1,frames:16,ended_at:'2026-10-08T00:00:02Z'}};
  vi.spyOn(privateRecordingApi,'read').mockResolvedValue(saved);expect((await c.checkSaved(id(2))).state).toBe('finished');expect(finish).toHaveBeenCalledTimes(1);
});
it('refuses stop-unconfirmed or empty PCM outcomes and changed identity before network',async()=>{
  const submit=vi.spyOn(privateRecordingApi,'attach').mockImplementation(async(_identity,v)=>receipt(v)),finish=vi.spyOn(privateRecordingApi,'finish');const c=controller();await c.attach(snapshot());
  await expect(c.finish({...snapshot(),phase:'stop_unconfirmed'})).rejects.toThrow();await expect(c.finish({...snapshot(),phase:'sealed',chunks:0,frames:0})).rejects.toThrow();expect(finish).not.toHaveBeenCalled();
  current=false;await expect(c.checkSaved(id(2))).rejects.toThrow();expect(submit).toHaveBeenCalledTimes(1);
});
