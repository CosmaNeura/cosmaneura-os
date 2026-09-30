import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {request} from './capture-api';
import {coreConnectionApi} from './core-connection-api';
import {parseExistingScribeSource,parseScribeSourcePacket,readExistingScribeSource,saveScribeSourcePacket,type ScribeSourceRequest} from './scribe-source-api';

const wid='00000000-0000-4000-8000-000000000001',sid='00000000-0000-4000-8000-000000000002',tid='00000000-0000-4000-8000-000000000003';
const gid='00000000-0000-4000-8000-000000000004',key='00000000-0000-4000-8000-000000000005',eid='00000000-0000-4000-8000-000000000006';
const selection={version:1 as const,session_id:sid,source_transcript_version:1,working_transcript_id:tid,working_transcript_version:2,snapshot_sha256:'a'.repeat(64)};
const body:ScribeSourceRequest={idempotency_key:key,expected_revision:1,selection,reviewed:true,share_with_team:true};
function recording(){
  const segment={source_segment_id:gid,source_segment_version:1,speaker_id:gid,speaker_role:'patient',source_locale:'en-US',start_ms:0,end_ms:1000,content:'Invented encounter only.'};
  return {contract_version:1,workspace_id:wid,status:'available',selection,review:{schema_version:'1.0',session_id:sid,status:'transcript_ready',translation_progress:[],
    source:{schema_version:'1.0',source_transcript_version:1,language_mode:'en-US',transcription_adapter_id:'test',transcription_model_profile_id:'test',normalization_profile_id:'test',segments:[{...segment,locale_confidence:1.0}]},
    working:{schema_version:'1.0',working_transcript_id:tid,working_transcript_version:2,source_transcript_version:1,note_ready:true,blockers:[],segments:[{...segment,resolution:'english_source'}]},
    review_queue:{schema_version:'1.0',session_id:sid,source_transcript_version:1,working_transcript_id:tid,working_transcript_version:2,status:'complete',items:[]}}};
}
const json=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
const identity=()=>({mode:'clerk_jwt' as const,getToken:vi.fn().mockResolvedValue('synthetic-token')});
beforeEach(async()=>{const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();});

it('looks up the current recording without admission or recording consent',async()=>{
  const access=identity(),fetcher=vi.fn().mockResolvedValue(json(recording()));vi.stubGlobal('fetch',fetcher);
  const result=await readExistingScribeSource(wid,access);
  expect(result.selection).toEqual(selection);expect(fetcher).toHaveBeenCalledOnce();
  const [url,options]=fetcher.mock.calls[0];expect(url).toContain(`/workspaces/${wid}/capture/existing`);
  expect(Object.keys(JSON.parse(options.body))).toEqual(['idempotency_key']);
  expect(options).toMatchObject({method:'POST',cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'});
});
it('accepts unavailable and processing states without an import selection',async()=>{
  expect(await parseExistingScribeSource({contract_version:1,workspace_id:wid,status:'not_prepared',review:null,selection:null},wid)).toMatchObject({selection:null});
  const value=recording();
  expect(await parseExistingScribeSource({...value,selection:null,review:{schema_version:'1.0',session_id:sid,status:'processing',source:null,working:null,review_queue:null,translation_progress:[]}},wid)).toMatchObject({selection:null});
});
it('rejects foreign, mixed-version, malformed and falsely ready source receipts',async()=>{
  const value=recording();
  for(const changed of [{...value,workspace_id:sid},{...value,extra:true},{...value,selection:null},
    {...value,selection:{...selection,session_id:tid}},{...value,selection:{...selection,working_transcript_version:3}},
    {...value,selection:{...selection,snapshot_sha256:'invalid'}},
    {...value,review:{...value.review,working:{...value.review.working,note_ready:false}}}])
    await expect(parseExistingScribeSource(changed,wid)).rejects.toMatchObject({code:'scribe_source_receipt_invalid'});
});
it('validates source packet request bytes before credentials for browser and native clients',async()=>{
  const access=identity(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  for(const changed of [{...body,reviewed:false},{...body,share_with_team:false},{...body,transcript:'Never a client-supplied source'},{...body,selection:{...selection,access_token:'private'}}])
    await expect(request(wid,'source-packets',access,changed)).rejects.toMatchObject({status:422});
  expect(access.getToken).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it('checks every saved packet part and retains the exact immutable save key',async()=>{
  const content='Reviewed invented transcript';
  const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(content)))].map(byte=>byte.toString(16).padStart(2,'0')).join('');
  const entry={id:eid,kind:'evidence',revision:2,content};
  const response={entry_id:eid,entry_revision:2,entries:[{entry_id:eid,entry_revision:2,content_sha256:digest}],snapshot_sha256:selection.snapshot_sha256,
    workspace:{id:wid,appointment_id:gid,label:'Invented visit',revision:2,entries:[entry],work_candidates:[],model_contract_version:1,model_observed_at:'2026-09-30T18:00:00Z'}};
  const fetcher=vi.fn().mockResolvedValue(json(response));vi.stubGlobal('fetch',fetcher);
  expect((await saveScribeSourcePacket(wid,identity(),body)).entry_id).toBe(eid);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual(body);
  for(const changed of [{...response,snapshot_sha256:'b'.repeat(64)},{...response,entry_revision:3},
    {...response,entries:[response.entries[0],response.entries[0]]},{...response,entries:[{...response.entries[0],content_sha256:'b'.repeat(64)}]},
    {...response,workspace:{...response.workspace,id:sid}},{...response,workspace:{...response.workspace,entries:[]}}])
    await expect(parseScribeSourcePacket(changed,wid,body)).rejects.toMatchObject({code:'scribe_source_receipt_invalid'});
});
it('keeps known source-change errors useful and hides arbitrary server details',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(json({detail:'scribe_source_changed'},409)).mockResolvedValueOnce(json({detail:'private encounter sentinel'},503));vi.stubGlobal('fetch',fetcher);
  await expect(saveScribeSourcePacket(wid,identity(),body)).rejects.toMatchObject({status:409,code:'scribe_source_changed'});
  await expect(saveScribeSourcePacket(wid,identity(),body)).rejects.toMatchObject({status:503,code:'capture_request_unconfirmed'});
});
it('retains only the new allowlisted Core discovery errors',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(json({detail:'core_existing_recording_conflict'},409)).mockResolvedValueOnce(json({detail:'core_scribe_encounter_unavailable'},503)).mockResolvedValueOnce(json({detail:'private source error'},503));vi.stubGlobal('fetch',fetcher);
  const command={action:'connection' as const,request_nonce:key};
  await expect(coreConnectionApi.read(identity(),command)).rejects.toMatchObject({status:409,code:'core_existing_recording_conflict'});
  await expect(coreConnectionApi.read(identity(),command)).rejects.toMatchObject({status:503,code:'core_scribe_encounter_unavailable'});
  await expect(coreConnectionApi.read(identity(),command)).rejects.toMatchObject({status:502,code:undefined});
});
