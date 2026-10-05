import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {saveHandoffReview,handoffReviewHash,prepareHandoffRevision,verifiedHandoffResult,HandoffReviewRefusal,refusalProvesNoCommit,type HandoffReviewInput,type HandoffReviewReceipt,type HandoffRevisionInput,type ReviewableHandoff} from './handoff-review-api';
import type {Workspace} from './workspace-api';
import {MODEL_WORKSPACE_BYTES} from './model-work-request';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const time='2026-10-02T14:00:00Z',wid=uuid(71),hid=uuid(701),access={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
const sha=async(content:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(content)))].map(n=>n.toString(16).padStart(2,'0')).join('');
async function fixture() {
  const content='Invented encounter. DOB was unavailable. Confirm medication history before follow-up.\nKeep the whole draft 😀.';
  const hash=await sha(content),handoff:ReviewableHandoff={id:hid,origin_entry_id:uuid(600),recipient_role:'follow_up',recipient_name:'Follow-up',
    recipient_agent_id:uuid(102),brief:'Prepare a follow-up draft',context_revision:1,status:'completed',attempt_id:uuid(702),attempt_count:1,
    result_entry_id:uuid(601),result_sha256:hash,error_code:null,attempts:[{id:uuid(702),number:1,status:'completed',error_code:null}]};
  const workspace:Workspace={id:wid,appointment_id:uuid(72),label:'Invented visit',revision:3,model_contract_version:1,model_observed_at:time,
    entries:[{id:uuid(601),revision:3,kind:'handoff_result',content:'Saved handoff',source_label:null,origin:'human',ticket:null,created_at:time,
      reply:{agent_id:uuid(102),agent_name:'Follow-up',role:'follow_up',backend:'synthetic-boundary',context_revision:1,content,citations:[]}}],work_candidates:[],handoffs:[handoff]};
  const body:HandoffReviewInput={expected_revision:3,idempotency_key:'retained-review-key',attempt_id:handoff.attempt_id,
    result_entry_id:handoff.result_entry_id!,result_sha256:hash,decision:'changes_requested',feedback:'Add an owner and due date.'};
  const review:HandoffReviewReceipt={id:uuid(800),attempt_id:body.attempt_id,result_entry_id:body.result_entry_id,result_sha256:hash,
    decision:body.decision,feedback:body.feedback,created_at:time};
  return {workspace,handoff,body,response:{entry_revision:4,request_sha256:await handoffReviewHash(wid,hid,body),feedback_withheld:false,workspace:{...workspace,revision:4,handoffs:[{...handoff,review}]}}};
}
const json=(value:unknown,status=200,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});

it('posts the exact review on the restricted path with fresh credentials and both contract versions',async()=>{
  const f=await fixture(),token=vi.fn().mockResolvedValue('invented-token'),fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json(f.response)));vi.stubGlobal('fetch',fetcher);
  await saveHandoffReview({...access,getToken:token},wid,hid,f.body);await saveHandoffReview({...access,getToken:token},wid,hid,f.body);
  expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${wid}/handoffs/${hid}/review`,`http://127.0.0.1:8018/workspaces/${wid}/handoffs/${hid}/review`]);
  for(const [,init] of fetcher.mock.calls){expect(init.body).toBe(JSON.stringify(f.body));expect(init).toMatchObject({cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'});
    const h=new Headers(init.headers);expect(h.get('X-Cosmas-Model-Contract')).toBe('1');expect(h.get('X-Cosmas-Handoff-Review')).toBe('1');expect(h.get('Authorization')).toBe('Bearer invented-token');expect(h.has('X-Box-Id')).toBe(false);}
  expect(token.mock.calls).toEqual([[{skipCache:true}],[{skipCache:true}]]);
});
it('accepts an idempotent receipt with a later current workspace revision and the exact historical draft',async()=>{
  const f=await fixture();f.response.workspace.revision=9;vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(f.response)));
  await expect(saveHandoffReview(access,wid,hid,f.body)).resolves.toMatchObject({entry_revision:4,workspace:{revision:9}});
});
it('confirms a masked historical review using the exact immutable request commitment without requiring inaccessible feedback or draft bytes',async()=>{
 const f=await fixture(),review=f.response.workspace.handoffs[0].review;
 const value={...f.response,feedback_withheld:true,workspace:{...f.response.workspace,entries:f.response.workspace.entries.map(e=>({...e,content:'',reply:null,google_source_state:'unavailable'})),
  handoffs:[{...f.handoff,review_status:'stale',review:{...review,feedback:'Email access must be checked before viewing this feedback.'}}]}};
 const fetcher=vi.fn().mockResolvedValueOnce(json(value));vi.stubGlobal('fetch',fetcher);
 await expect(saveHandoffReview(access,wid,hid,f.body)).resolves.toMatchObject({feedback_withheld:true,request_sha256:f.response.request_sha256});
 for(const bad of [{...value,request_sha256:'a'.repeat(64)},{...value,feedback_withheld:false},{...value,workspace:{...value.workspace,entries:f.response.workspace.entries}},
  {...value,workspace:{...value.workspace,handoffs:[{...value.workspace.handoffs[0],review_status:'current'}]}}]){
  fetcher.mockResolvedValueOnce(json(bad));await expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status:503});
 }
});
it.each(['workspace_revision_conflict','handoff_result_already_reviewed','handoff_revision_already_requested','handoff_sources_changed'])('recognizes only a closed no-store service refusal: %s',async code=>{
  const f=await fixture();vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json({detail:code},409)));
  const failure=await saveHandoffReview(access,wid,hid,f.body).catch(error=>error);
  expect(failure).toBeInstanceOf(HandoffReviewRefusal);expect(failure).toMatchObject({status:409,code});
  expect(refusalProvesNoCommit(failure)).toBe(code!=='handoff_sources_changed');
});
it.each([{detail:'other_internal_error'},{detail:'workspace_revision_conflict',committed:false},{detail:'workspace_revision_conflict',private_content:'hidden'}])('keeps unknown or unclosed error responses uncertain: %j',async body=>{
  const f=await fixture();vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(body,409)));
  const failure=await saveHandoffReview(access,wid,hid,f.body).catch(error=>error);expect(failure).not.toBeInstanceOf(HandoffReviewRefusal);expect(failure).toMatchObject({status:409});
});
it.each(['workspace','revision','attempt','entry','digest','decision','feedback','draft','missing-review','unknown-receipt','unknown-top','duplicate-key','content-type','no-store','utf8','wrong-status'])('rejects a substituted or malformed review receipt: %s',async fault=>{
  const f=await fixture();const value=f.response as any;let headers:Record<string,string>={},status=200,raw:string|Uint8Array|undefined;
  if(fault==='workspace')value.workspace.id=uuid(99);if(fault==='revision')value.entry_revision=8;
  const review=value.workspace.handoffs[0].review;
  if(fault==='attempt')review.attempt_id=uuid(999);if(fault==='entry')review.result_entry_id=uuid(999);if(fault==='digest')review.result_sha256='a'.repeat(64);
  if(fault==='decision')review.decision='accepted';if(fault==='feedback')review.feedback='Other change';if(fault==='draft')value.workspace.entries[0].reply.content='Shortened';
  if(fault==='missing-review')delete value.workspace.handoffs[0].review;if(fault==='unknown-receipt')review.private_contents='hidden';if(fault==='unknown-top')value.extra='hidden';
  if(fault==='duplicate-key')raw=JSON.stringify(value).replace('"entry_revision":4','"entry_revision":999,"entry_revision":4');
  if(fault==='content-type')headers['Content-Type']='text/plain';if(fault==='no-store')headers['Cache-Control']='public';if(fault==='utf8')raw=new Uint8Array([255]);if(fault==='wrong-status')status=201;
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(raw===undefined?json(value,status,headers):new Response(typeof raw==='string'?raw:new Uint8Array(raw).buffer,{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}})));
  await expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status:503});
});
it('verifies the complete displayed reply against required result metadata without truncation',async()=>{
  const f=await fixture();await expect(verifiedHandoffResult(f.workspace,f.handoff)).resolves.toMatchObject({content:f.workspace.entries[0].reply!.content,sha256:f.body.result_sha256});
  f.workspace.entries[0].reply!.content='Shortened';await expect(verifiedHandoffResult(f.workspace,f.handoff)).resolves.toBeNull();
  delete f.handoff.result_sha256;await expect(verifiedHandoffResult(f.workspace,f.handoff)).resolves.toBeNull();
});
it.each(['workspace-path','handoff-path','blank-feedback','oversized-feedback','invalid-unicode','nul-feedback','invalid-key','oversized-key','bad-hash','unknown-field'])('rejects invalid review input before requesting credentials: %s',async fault=>{
  const f=await fixture(),body={...f.body} as any,token=vi.fn(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  if(fault==='blank-feedback')body.feedback=' \n';if(fault==='oversized-feedback')body.feedback='😀'.repeat(2001);if(fault==='invalid-unicode')body.feedback='\ud800';
  if(fault==='nul-feedback')body.feedback='Bad\0text';if(fault==='invalid-key')body.idempotency_key='invalid.key';if(fault==='oversized-key')body.idempotency_key='x'.repeat(101);
  if(fault==='bad-hash')body.result_sha256='not-a-hash';if(fault==='unknown-field')body.agent_approval=true;
  await expect(saveHandoffReview({...access,getToken:token},fault==='workspace-path'?'../../private':wid,fault==='handoff-path'?'?secret':hid,body)).rejects.toMatchObject({status:422});
  expect(token).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it.each(['https://other.example','http://127.0.0.1:8018/?secret=yes','http://127.0.0.1:8018/#fragment','http://person:password@127.0.0.1:8018'])('rejects an arbitrary API origin before credentials: %s',async base=>{
  const f=await fixture(),token=vi.fn(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);vi.stubEnv('VITE_API_BASE',base);
  await expect(saveHandoffReview({...access,getToken:token},wid,hid,f.body)).rejects.toMatchObject({status:503});expect(token).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it('retains the input snapshot while credentials wait, without accepting a mutated decision',async()=>{
  const f=await fixture();let release!:(value:string)=>void;const fetcher=vi.fn().mockResolvedValue(json(f.response));vi.stubGlobal('fetch',fetcher);
  const saved=saveHandoffReview({...access,getToken:()=>new Promise(resolve=>{release=resolve;})},wid,hid,f.body);f.body.feedback='Mutated after dispatch';release('invented-token');
  await expect(saved).resolves.toMatchObject({entry_revision:4});expect(JSON.parse(fetcher.mock.calls[0][1].body).feedback).toBe('Add an owner and due date.');
});
it('bounds stalled credentials, response streams and digest checks without a late dispatch',async()=>{
  const f=await fixture();vi.useFakeTimers();let release!:(value:string)=>void;const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  const timeout=expect(saveHandoffReview({...access,getToken:()=>new Promise(resolve=>{release=resolve;})},wid,hid,f.body)).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30000);await timeout;release('late-token');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
  fetcher.mockResolvedValue({status:200,ok:true,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body:{getReader:()=>({read:()=>new Promise(()=>{}),cancel:()=>new Promise(()=>{}),releaseLock:()=>{}})}});
  const stream=expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30000);await stream;
  fetcher.mockResolvedValue(json(f.response));vi.stubGlobal('crypto',{subtle:{digest:()=>new Promise(()=>{})}});
  const digest=expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30000);await digest;
});
it('rejects oversized streamed workspaces and changed native authority without displaying private errors',async()=>{
  const f=await fixture();vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(new Uint8Array(MODEL_WORKSPACE_BYTES+1),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
  await expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status:503});
  const token=vi.fn().mockResolvedValue('invented-token'),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(saveHandoffReview({...access,getToken:token,nativeSession:{revision:uuid(42),isCurrent:()=>false}},wid,hid,f.body)).rejects.toMatchObject({status:401});
  expect(token).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it.each([401,403,404,426])('withholds private error content on authority refusal %s',async status=>{
  const f=await fixture();vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('private error contents',{status})));
  await expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status});
});

async function revisionFixture() {
  const f=await fixture();f.body.feedback='Private café follow-up 😀.';f.response.request_sha256=await handoffReviewHash(wid,hid,f.body);const review={...f.response.workspace.handoffs[0].review,feedback:f.body.feedback};
  const body:HandoffRevisionInput={expected_revision:4,idempotency_key:'retained-revision-key',review_id:review.id};
  const next:ReviewableHandoff={...f.handoff,id:uuid(901),origin_entry_id:uuid(902),status:'queued',attempt_id:uuid(903),attempt_count:1,
    result_entry_id:null,result_sha256:null,review:null,attempts:[{id:uuid(903),number:1,status:'queued',error_code:null}],
    revision_request:{parent_handoff_id:hid,review_id:review.id,attempt_id:review.attempt_id,result_entry_id:review.result_entry_id,
      result_sha256:review.result_sha256,feedback:review.feedback}};
  const request={id:uuid(902),revision:5,kind:'conversation' as const,content:'Prepare a revised draft.',source_label:null,origin:'authenticated_human',ticket:null,created_at:time};
  const workspace:Workspace={...f.response.workspace,revision:6,entries:[...f.workspace.entries,request],handoffs:[{...f.handoff,
    review:{...review,revision_handoff_id:next.id}},next]};
  return {...f,body,response:{entry_revision:5,revision_handoff_id:next.id,workspace}};
}
it('records a fresh revised assignment only after verifying the saved change request, frozen sources and same recipient',async()=>{
  const f=await revisionFixture(),fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json(f.response)));vi.stubGlobal('fetch',fetcher);
  await expect(prepareHandoffRevision(access,wid,hid,f.body)).resolves.toMatchObject({entry_revision:5,revision_handoff_id:uuid(901),workspace:{revision:6}});
  expect(fetcher.mock.calls[0][0]).toBe(`http://127.0.0.1:8018/workspaces/${wid}/handoffs/${hid}/revision`);expect(fetcher.mock.calls[0][1].body).toBe(JSON.stringify(f.body));
  const headers=new Headers(fetcher.mock.calls[0][1].headers);expect(headers.get('X-Cosmas-Handoff-Review')).toBe('1');expect(headers.get('X-Cosmas-Model-Contract')).toBe('1');
});
it.each(['parent-id','review-id','prior-attempt','prior-entry','prior-hash','feedback','recipient','origin','origin-kind','origin-author','origin-reply','entry-revision','same-handoff','missing-new','prior-draft','accepted-review'])('rejects a substituted revised assignment: %s',async fault=>{
  const f=await revisionFixture(),value=f.response as any,next=value.workspace.handoffs[1],metadata=next.revision_request;
  if(fault==='parent-id')metadata.parent_handoff_id=uuid(99);if(fault==='review-id')metadata.review_id=uuid(99);
  if(fault==='prior-attempt')metadata.attempt_id=uuid(99);if(fault==='prior-entry')metadata.result_entry_id=uuid(99);if(fault==='prior-hash')metadata.result_sha256='a'.repeat(64);if(fault==='feedback')metadata.feedback='Other';
  if(fault==='recipient')next.recipient_agent_id=uuid(99);if(fault==='origin')next.origin_entry_id=f.handoff.origin_entry_id;if(fault==='origin-kind')value.workspace.entries[1].kind='handoff_result';
  if(fault==='origin-author')value.workspace.entries[1].origin='model';if(fault==='origin-reply')value.workspace.entries[1].reply={...value.workspace.entries[0].reply};if(fault==='entry-revision')value.entry_revision=4;if(fault==='same-handoff')value.revision_handoff_id=hid;
  if(fault==='missing-new')value.workspace.handoffs.pop();if(fault==='prior-draft')value.workspace.entries[0].reply.content='Changed draft';if(fault==='accepted-review')value.workspace.handoffs[0].review.decision='accepted';
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(value)));await expect(prepareHandoffRevision(access,wid,hid,f.body)).rejects.toMatchObject({status:503});
});
it('rejects a revised assignment request with additional claims before fresh credentials',async()=>{
  const f=await revisionFixture(),token=vi.fn(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(prepareHandoffRevision({...access,getToken:token},wid,hid,{...f.body,model_signoff:true} as HandoffRevisionInput)).rejects.toMatchObject({status:422});
  expect(token).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});

it('resolves an immutable generic fax review after revocation using its separate source mask and canonical withheld notice',async()=>{
 const f=await fixture(),review=f.response.workspace.handoffs[0].review;
 const masked={...f.response,feedback_withheld:true,workspace:{...f.response.workspace,entries:f.response.workspace.entries.map(e=>({...e,content:'',reply:null,practice_fax_source_state:'unavailable'})),handoffs:[{...f.handoff,review_status:'stale',review:{...review,feedback:'Check the reviewed fax passage before viewing this feedback.'}}]}};
 const fetcher=vi.fn().mockResolvedValueOnce(json(masked));vi.stubGlobal('fetch',fetcher);await expect(saveHandoffReview(access,wid,hid,f.body)).resolves.toMatchObject({feedback_withheld:true,request_sha256:f.response.request_sha256});
 fetcher.mockResolvedValueOnce(json({...masked,workspace:{...masked.workspace,handoffs:[{...masked.workspace.handoffs[0],review:{...review,feedback:'Email access must be checked before viewing this feedback.'}}]}}));
 await expect(saveHandoffReview(access,wid,hid,f.body)).rejects.toMatchObject({status:503});expect(fetcher).toHaveBeenCalledTimes(2);
});
