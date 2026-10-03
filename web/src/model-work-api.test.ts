import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {modelWorkApi} from './model-work-api';
import {admissionFixture,conversationFixture,modelReceipt,modelUuid,pendingWorkspace,retryReceipt} from './model-work-test-fixture';
import {MODEL_RECEIPT_BYTES,MODEL_WORKSPACE_BYTES} from './model-work-request';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const access={mode:'clerk_jwt' as const,getToken:async()=> 'invented-private-token'};
const op={type:'ask' as const,body:conversationFixture},id=modelUuid(71);
const json=(value:unknown,status=200,headers:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...headers}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8018');});
afterEach(()=>{vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
it('uses exact submit/resolve paths and bodies with model-only negotiation and fresh credentials',async()=>{
  const receipt=await modelReceipt(),token=vi.fn().mockResolvedValue('invented-private-token'),fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json(receipt)));vi.stubGlobal('fetch',fetcher);
  await modelWorkApi.submit({...access,getToken:token},id,op);await modelWorkApi.resolve({...access,getToken:token},id,op);
  expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${id}/conversation`,`http://127.0.0.1:8018/workspaces/${id}/conversation/resolve`]);
  for(const call of fetcher.mock.calls){const init=call[1] as RequestInit;expect(init.body).toBe(JSON.stringify(op.body));const h=new Headers(init.headers);
    expect(h.get('X-Cosmas-Model-Contract')).toBe('1');expect(h.has('X-Cosmas-Team-Contract')).toBe(false);expect(h.has('X-Box-Id')).toBe(false);
    expect(init).toMatchObject({cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'});}
  expect(token.mock.calls).toEqual([[{skipCache:true}],[{skipCache:true}]]);
});
it('returns a strict unresolved409 as retained state and distinguishes safe pre-admission refusal',async()=>{
  const saved=await modelReceipt(),running={...saved,outcome:'running',saved_entry:null,admission:admissionFixture('running')};
  const fetcher=vi.fn().mockResolvedValueOnce(json(running,409)).mockResolvedValueOnce(json({detail:'team_work_limit'},409));vi.stubGlobal('fetch',fetcher);
  await expect(modelWorkApi.submit(access,id,op)).resolves.toMatchObject({outcome:'running'});
  await expect(modelWorkApi.submit(access,id,op)).rejects.toMatchObject({status:409,code:'team_work_limit'});
});
it('retries and resolves the original handoff command without substituting a current attempt key',async()=>{
  const body={expected_revision:2,previous_attempt_id:modelUuid(702),idempotency_key:'saved-retry-key'},handoffId=modelUuid(701);
  const value=await retryReceipt(body,id,handoffId),fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json(value)));vi.stubGlobal('fetch',fetcher);
  const retry={type:'retry' as const,handoffId,body};await modelWorkApi.submit(access,id,retry);await modelWorkApi.resolve(access,id,retry);
  expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${id}/handoffs/${handoffId}/retry`,`http://127.0.0.1:8018/workspaces/${id}/handoffs/${handoffId}/retry/resolve`]);
  expect(fetcher.mock.calls.every(c=>(c[1] as RequestInit).body===JSON.stringify(body))).toBe(true);
});
it.each([
  ['handoff_source_context_too_large','Select fewer saved sources'],
  ['handoff_source_contract_unavailable','Check Chief’s tools'],
])('shows an actionable source refusal for %s without retrying',async(code,next)=>{
  const fetcher=vi.fn().mockResolvedValue(json({detail:code},422));vi.stubGlobal('fetch',fetcher);
  const error=await modelWorkApi.submit(access,id,op).catch(value=>value);
  expect(error).toMatchObject({status:422,code});
  expect(error.message).toContain('Your recording and saved notes are retained.');
  expect(error.message).toContain(next);expect(fetcher).toHaveBeenCalledTimes(1);
});
it.each(['workspace','key','digest','unknown-field','wrong-status','content-type','no-store','utf8'])('rejects bad negotiated receipt: %s',async fault=>{
  const value=await modelReceipt() as any;let headers:Record<string,string>={},status=200;
  if(fault==='workspace')value.workspace_id=modelUuid(99);if(fault==='key')value.idempotency_key='wrong-model-key';if(fault==='digest')value.request_sha256='b'.repeat(64);
  if(fault==='unknown-field')value.private_prompt='hidden';if(fault==='wrong-status')status=201;if(fault==='content-type')headers['Content-Type']='text/plain';if(fault==='no-store')headers['Cache-Control']='public';
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(fault==='utf8'?new Response(new Uint8Array([255]),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}):json(value,status,headers)));
  await expect(modelWorkApi.submit(access,id,op)).rejects.toMatchObject({status:503});
});
it('only resolve accepts a no-admission not_found result',async()=>{
  const saved=await modelReceipt(),value={...saved,outcome:'not_found',saved_entry:null};vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>Promise.resolve(json(value))));
  await expect(modelWorkApi.resolve(access,id,op)).resolves.toMatchObject({outcome:'not_found'});
  await expect(modelWorkApi.submit(access,id,op)).rejects.toMatchObject({status:503});
});
it('rejects invalid paths/oversized requests before credentials',async()=>{
  const token=vi.fn(),fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  await expect(modelWorkApi.submit({...access,getToken:token},'../../private',op)).rejects.toMatchObject({status:422});
  await expect(modelWorkApi.submit({...access,getToken:token},id,{...op,body:{...op.body,content:' '.repeat(65536)+'x'}})).rejects.toMatchObject({status:422});
  expect(token).not.toHaveBeenCalled();expect(fetcher).not.toHaveBeenCalled();
});
it('bounds stalled credentials and prevents dispatch after their late resolution',async()=>{
  vi.useFakeTimers();let release!:(v:string)=>void;const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);
  const check=expect(modelWorkApi.submit({...access,getToken:()=>new Promise(r=>{release=r;})},id,op)).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30000);await check;release('late-private-token');await vi.advanceTimersByTimeAsync(1);expect(fetcher).not.toHaveBeenCalled();
});
it('keeps hash validation within the same deadline and abandons nonsettling cancellation',async()=>{
  const value=await modelReceipt();vi.useFakeTimers();vi.stubGlobal('crypto',{subtle:{digest:()=>new Promise(()=>{})}});
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(json(value)));
  const check=expect(modelWorkApi.submit(access,id,op)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(75000);await check;
  const body={getReader:()=>({read:()=>new Promise(()=>{}),cancel:()=>new Promise(()=>{}),releaseLock:()=>{}})};
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue({status:200,ok:true,headers:new Headers({'Content-Type':'application/json','Cache-Control':'no-store'}),body}));
  const stalled=expect(modelWorkApi.resolve(access,id,op)).rejects.toMatchObject({status:503});await vi.advanceTimersByTimeAsync(30000);await stalled;
});
it('enforces receipt and unchanged workspace byte bounds separately',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(new Response(new Uint8Array(MODEL_RECEIPT_BYTES+1),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}))
    .mockResolvedValueOnce(new Response(new Uint8Array(MODEL_WORKSPACE_BYTES+1),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}));vi.stubGlobal('fetch',fetcher);
  await expect(modelWorkApi.resolve(access,id,op)).rejects.toMatchObject({status:503});await expect(modelWorkApi.readWorkspace(access,id)).rejects.toMatchObject({status:503});
});
it('uses negotiated fresh workspace GET and accepts same-revision lifecycle changes',async()=>{
  const before=await pendingWorkspace(),after=await pendingWorkspace(undefined,'unknown');
  const fetcher=vi.fn().mockResolvedValueOnce(json(before)).mockResolvedValueOnce(json(after));vi.stubGlobal('fetch',fetcher);
  expect((await modelWorkApi.readWorkspace(access,id)).entries[0].model_request?.admission.state).toBe('reserved');
  expect((await modelWorkApi.readWorkspace(access,id)).entries[0].model_request?.admission.state).toBe('unknown');
  expect(fetcher.mock.calls.every(c=>new Headers(c[1].headers).get('X-Cosmas-Model-Contract')==='1')).toBe(true);
});
it.each([401,403,404,426])('withholds access on %s without consuming private error content',async status=>{
  vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response('private error must not appear',{status})));
  await expect(modelWorkApi.resolve(access,id,op)).rejects.toMatchObject({status});
});
it('transports and resolves the exact selected analysis on existing model paths and rejects an omitted-selection receipt',async()=>{
 const {analysisBody}=await import('./research-analysis-test-fixture');const selected={type:'ask' as const,body:analysisBody},receipt=await modelReceipt(analysisBody),fetcher=vi.fn().mockImplementation(()=>Promise.resolve(json(receipt)));vi.stubGlobal('fetch',fetcher);
 await modelWorkApi.submit(access,id,selected);await modelWorkApi.resolve(access,id,selected);expect(fetcher.mock.calls.map(c=>c[0])).toEqual([`http://127.0.0.1:8018/workspaces/${id}/conversation`,`http://127.0.0.1:8018/workspaces/${id}/conversation/resolve`]);expect(fetcher.mock.calls.every(c=>c[1].body===JSON.stringify(analysisBody))).toBe(true);
 const {research_analysis:_,...omitted}=analysisBody;fetcher.mockResolvedValueOnce(json(await modelReceipt(omitted)));await expect(modelWorkApi.resolve(access,id,selected)).rejects.toMatchObject({status:503});
});
it('retains a selected brief through the longer submit window and keeps resolve read-only and shorter',async()=>{
  const {default:actual}=await import('./__fixtures__/session-prep-chat.json');
  const selected={type:'ask' as const,body:actual.request as import('./workspace-api').ConversationInput};
  vi.useFakeTimers();const fetcher=vi.fn().mockImplementation(()=>new Promise(()=>{}));vi.stubGlobal('fetch',fetcher);
  let submitEnded=false;
  const submitted=expect(modelWorkApi.submit(access,id,selected).finally(()=>{submitEnded=true;})).rejects.toMatchObject({status:503});
  const resolved=expect(modelWorkApi.resolve(access,id,selected)).rejects.toMatchObject({status:503});
  await vi.advanceTimersByTimeAsync(30000);await resolved;expect(submitEnded).toBe(false);
  await vi.advanceTimersByTimeAsync(60000);await submitted;
  expect(fetcher).toHaveBeenCalledTimes(2);expect(fetcher.mock.calls.every(c=>c[1].body===JSON.stringify(selected.body))).toBe(true);
});

it('accepts a valid operational reply after 40s without dispatching another request',async()=>{
 const receipt=await modelReceipt();vi.useFakeTimers();let release!:(value:Response)=>void;
 const fetcher=vi.fn().mockImplementation(()=>new Promise<Response>(resolve=>{release=resolve;}));vi.stubGlobal('fetch',fetcher);
 const pending=modelWorkApi.submit(access,id,op);await vi.advanceTimersByTimeAsync(40000);
 expect((fetcher.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(false);
 release(json(receipt));await expect(pending).resolves.toMatchObject({outcome:'saved'});expect(fetcher).toHaveBeenCalledOnce();
});
it('bounds a stalled operational reply and rejects late completion',async()=>{
 const receipt=await modelReceipt();vi.useFakeTimers();let release!:(value:Response)=>void;
 const fetcher=vi.fn().mockImplementation(()=>new Promise<Response>(resolve=>{release=resolve;}));vi.stubGlobal('fetch',fetcher);
 const pending=modelWorkApi.submit(access,id,op),check=expect(pending).rejects.toMatchObject({status:503});
 await vi.advanceTimersByTimeAsync(75000);await check;expect((fetcher.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
 release(json(receipt));await vi.advanceTimersByTimeAsync(1);expect(fetcher).toHaveBeenCalledOnce();
});

it('retains an expired unstarted Chief request without replay, and submits only an explicit fresh request',async()=>{
  const chief={...conversationFixture,role:'chief' as const},original={type:'ask' as const,body:chief};
  const expired={...await modelReceipt(chief,id),outcome:'abandoned',saved_entry:null,admission:admissionFixture('abandoned'),reason:'reservation_expired'};
  const fresh={...chief,expected_revision:4,idempotency_key:'invented-expired-fresh-key'};
  const fetcher=vi.fn().mockResolvedValueOnce(json(expired)).mockResolvedValueOnce(json(await modelReceipt(fresh,id,5)));vi.stubGlobal('fetch',fetcher);
  await expect(modelWorkApi.resolve(access,id,original)).resolves.toMatchObject({outcome:'abandoned',reason:'reservation_expired',admission:{dispatch:'not_started'}});
  expect(fetcher).toHaveBeenCalledOnce();expect(fetcher.mock.calls[0][0]).toContain('/conversation/resolve');
  await modelWorkApi.submit(access,id,{type:'ask',body:fresh});expect(fetcher).toHaveBeenCalledTimes(2);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toMatchObject({idempotency_key:'invented-expired-fresh-key',expected_revision:4,role:'chief'});
});
