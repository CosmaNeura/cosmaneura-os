import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','true');});
vi.mock('./workspace-auth-headers',()=>({assertCurrentDesktopSession:()=>{},workspaceAuthHeaders:async()=>new Headers({'Content-Type':'application/json','Authorization':'Bearer invented'})}));
import {googleMessageApi,googleMessageReviewHash,validGoogleMessageReceipt,googleReviewProvesNoCommit,GoogleMessageRefusal,type GoogleMessageReceipt} from './google-message-api';
import {teamCanonical} from './team-setup-request';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const sha=async(value:string)=>[...new Uint8Array(await webcrypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(n=>n.toString(16).padStart(2,'0')).join('');
const uuid=(n:number)=>`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
let list:GoogleMessageReceipt,message:GoogleMessageReceipt;
beforeEach(async()=>{
 vi.stubGlobal('crypto',webcrypto);
 const observation={kind:'mail' as const,account:{label:'Invented clinician',email:'clinician@example.invalid'},items:[{id:'email_1',thread_id:'thread_1',subject:'Invented follow-up — résumé',sender:'sender@example.invalid',received_at:'2026-10-02T12:00:00Z',is_read:false}],more:false,observed_at:'2026-10-02T12:05:00Z'};
 list={read_id:uuid(1),read_key:uuid(2),kind:'list',observation_id:uuid(1),source_sha256:'a'.repeat(64),payload_sha256:await sha(teamCanonical(observation)),status:'observed',message:null,observation};
 const content='Invented follow-up. <script>do not execute</script> https://example.invalid';
 message={read_id:uuid(3),read_key:uuid(4),kind:'message',observation_id:list.read_id,source_sha256:'b'.repeat(64),payload_sha256:'c'.repeat(64),status:'complete',observation:null,
  message:{message_id:'email_1',thread_id:'thread_1',history_id:'42',subject:'Invented follow-up',sender:'sender@example.invalid',received_at:'2026-10-02T12:00:00Z',is_read:false,observed_at:'2026-10-02T12:06:00Z',status:'complete',content,reason:null,raw_sha256:'d'.repeat(64),content_sha256:await sha(content)}};
});
afterEach(()=>{vi.unstubAllGlobals();vi.useRealTimers();});
const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
it('verifies UTF8 list commitment and exact message text while keeping sealed custody out of the public schema',async()=>{
 expect(await validGoogleMessageReceipt(list)).toBe(true);expect(await validGoogleMessageReceipt(message)).toBe(true);
 expect(await validGoogleMessageReceipt({...list,payload_sha256:'e'.repeat(64)})).toBe(false);
 expect(await validGoogleMessageReceipt({...message,message:{...message.message,content:'Changed text'}})).toBe(false);
 expect(await validGoogleMessageReceipt({...message,message:{...message.message,custody:{grant:'never expose'}}})).toBe(false);
 expect(await validGoogleMessageReceipt({...list,observation:{...list.observation,items:[...list.observation!.items,...list.observation!.items]}})).toBe(false);
});
it('accepts needs-human receipts only with no usable body or content hash',async()=>{
 const limited={...message,status:'needs_human',message:{...message.message,status:'needs_human',content:null,content_sha256:null,reason:'attachment'}};
 expect(await validGoogleMessageReceipt(limited)).toBe(true);
 expect(await validGoogleMessageReceipt({...limited,message:{...limited.message,content:'Incomplete excerpt'}})).toBe(false);
 expect(await validGoogleMessageReceipt({...limited,message:{...limited.message,reason:'made_up'}})).toBe(false);
});
it('dispatches a single closed read with the observed source binding and no model header',async()=>{
 const fetcher=vi.fn().mockResolvedValue(response(message));vi.stubGlobal('fetch',fetcher);
 const body={action:'read' as const,idempotency_key:message.read_key,observation_id:list.read_id,observation_sha256:list.source_sha256,message_id:'email_1',thread_id:'thread_1'};
 expect(await googleMessageApi.read(identity,body)).toEqual(message);
 expect(fetcher).toHaveBeenCalledTimes(1);const [,init]=fetcher.mock.calls[0];expect(init).toMatchObject({body:JSON.stringify(body),method:'POST',credentials:'omit',redirect:'error',cache:'no-store'});
 expect(init.headers.get('X-Cosmas-Google-Messages')).toBe('1');expect(init.headers.has('X-Cosmas-Model-Contract')).toBe(false);
});
it('rejects a mismatched source, unobserved message, extra fields and shortened content without retry',async()=>{
 for(const value of [{...message,observation_id:uuid(99)},{...message,message:{...message.message,message_id:'other'}},{...message,token:'never'},
  {...message,message:{...message.message,content:message.message!.content!.slice(0,8)}}]){
  const fetcher=vi.fn().mockResolvedValue(response(value));vi.stubGlobal('fetch',fetcher);
  await expect(googleMessageApi.read(identity,{action:'read',idempotency_key:message.read_key,observation_id:list.read_id,observation_sha256:list.source_sha256,message_id:'email_1'})).rejects.toMatchObject({status:502});
  expect(fetcher).toHaveBeenCalledTimes(1);
 }
});
it('resolves original keys without a provider read and requires the exact returned key',async()=>{
 const fetcher=vi.fn().mockResolvedValueOnce(response({status:'unconfirmed',kind:'message',read_key:message.read_key,read_id:message.read_id})).mockResolvedValueOnce(response(message));vi.stubGlobal('fetch',fetcher);
 expect(await googleMessageApi.resolve(identity,message.read_key,'message')).toMatchObject({status:'unconfirmed'});
 expect(await googleMessageApi.resolve(identity,message.read_key,'message')).toEqual(message);
 expect(fetcher.mock.calls.every(call=>JSON.parse(call[1].body).action==='resolve')).toBe(true);
 fetcher.mockResolvedValueOnce(response({...message,read_key:uuid(98)}));await expect(googleMessageApi.resolve(identity,message.read_key,'message')).rejects.toThrow();
});
it('saves an independent exact source and validates immutable entry revision against a later workspace projection',async()=>{
 const body={expected_revision:5,idempotency_key:uuid(5),read_id:message.read_id,source_sha256:message.source_sha256,reviewed_patient:true as const,reviewed_exact_message:true as const,reviewed_untrusted_source:true as const};
 const workspace={id:uuid(6),label:'Invented visit',appointment_id:uuid(7),revision:8,entries:[{id:uuid(8),kind:'google_message',revision:6,content:message.message!.content,source_label:'Email',origin:'authenticated_human',ticket:null,created_at:'2026-10-02T12:00:00Z'}],work_candidates:[],model_contract_version:1,model_observed_at:'2026-10-02T12:00:00Z'} as unknown as Workspace;
 const value={entry_id:uuid(8),entry_revision:6,request_sha256:await googleMessageReviewHash(workspace.id,body,message.message!.content_sha256!),source_withheld:false,workspace,source:{entry_id:uuid(8),source_sha256:message.source_sha256,content_sha256:message.message!.content_sha256}};
 const fetcher=vi.fn().mockResolvedValueOnce(response(value));vi.stubGlobal('fetch',fetcher);
 expect(await googleMessageApi.review(identity,workspace.id,body,message)).toEqual(value);
 fetcher.mockResolvedValueOnce(response({...value,workspace:{...workspace,entries:[{...workspace.entries[0],content:'Changed'}]}}));
 await expect(googleMessageApi.review(identity,workspace.id,body,message)).rejects.toThrow();
});
it('confirms an exact historical source save without returning or reauthorizing unavailable message contents',async()=>{
 const body={expected_revision:5,idempotency_key:uuid(5),read_id:message.read_id,source_sha256:message.source_sha256,reviewed_patient:true as const,reviewed_exact_message:true as const,reviewed_untrusted_source:true as const};
 const workspace={id:uuid(6),label:'Invented visit',appointment_id:uuid(7),revision:9,entries:[{id:uuid(8),kind:'google_message',revision:6,content:'',source_label:'Unavailable email source',google_source_state:'unavailable',origin:'authenticated_human',ticket:null,created_at:'2026-10-02T12:00:00Z'}],work_candidates:[],model_contract_version:1,model_observed_at:'2026-10-02T12:00:00Z'} as unknown as Workspace;
 const value={entry_id:uuid(8),entry_revision:6,request_sha256:await googleMessageReviewHash(workspace.id,body,message.message!.content_sha256!),source_withheld:true,workspace,source:{entry_id:uuid(8),source_sha256:message.source_sha256,content_sha256:message.message!.content_sha256}};
 const fetcher=vi.fn().mockResolvedValueOnce(response(value));vi.stubGlobal('fetch',fetcher);await expect(googleMessageApi.review(identity,workspace.id,body,message)).resolves.toMatchObject({source_withheld:true});
 for(const bad of [{...value,request_sha256:'f'.repeat(64)},{...value,workspace:{...workspace,entries:[{...workspace.entries[0],content:message.message!.content}]}},{...value,workspace:{...workspace,entries:[{...workspace.entries[0],google_source_state:'current'}]}},{...value,source_withheld:false}]){
  fetcher.mockResolvedValueOnce(response(bad));await expect(googleMessageApi.review(identity,workspace.id,body,message)).rejects.toMatchObject({status:502});
 }
});
it('keeps unknown errors opaque and distinguishes only structured definite review refusals',async()=>{
 const fetcher=vi.fn().mockResolvedValueOnce(response({detail:'workspace_revision_conflict'},409)).mockResolvedValueOnce(response({detail:'secret unsafe error'},409));vi.stubGlobal('fetch',fetcher);
 await expect(googleMessageApi.status(identity)).rejects.toBeInstanceOf(GoogleMessageRefusal);
 await expect(googleMessageApi.status(identity)).rejects.toMatchObject({status:409,code:undefined});
 expect(googleReviewProvesNoCommit(new GoogleMessageRefusal(409,'workspace_revision_conflict'))).toBe(true);
 expect(googleReviewProvesNoCommit(new WorkspaceApiError(503))).toBe(false);
 expect(googleReviewProvesNoCommit(new GoogleMessageRefusal(409,'google_message_source_changed'))).toBe(false);
});
it('bounds stalled headers and never automatically repeats the message call',async()=>{
 vi.useFakeTimers();const fetcher=vi.fn().mockImplementation(()=>new Promise(()=>{}));vi.stubGlobal('fetch',fetcher);
 const pending=googleMessageApi.status(identity);const rejected=expect(pending).rejects.toMatchObject({status:503});
 await vi.advanceTimersByTimeAsync(50001);await rejected;expect(fetcher).toHaveBeenCalledTimes(1);
});
