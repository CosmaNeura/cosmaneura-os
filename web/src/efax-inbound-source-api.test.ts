import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_API_BASE','http://127.0.0.1:8000');vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_EFAX_INBOUND_ENABLED','true');vi.stubEnv('VITE_EFAX_INBOUND_SOURCE_ENABLED','true');});
import {efaxSourceApi,efaxSourceRequestHash,validEFaxSourceReviewRequest,verifyEFaxSourceReceipt,verifyEFaxSourceWorkspace,EFAX_SOURCE_LABEL,
 type EFaxSourceScope,type EFaxSourceReviewRequest,type EFaxSourceReceipt} from './efax-inbound-source-api';
import {emptyEFaxSourceRecovery,validateEFaxSourceRecovery} from './efax-inbound-source-recovery';
import {vendorSha256} from './vendor-contract';
import type {Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
export const sourceUuid=(n:number)=>'00000000-0000-4000-8000-'+String(n).padStart(12,'0');
export const sourceScope:EFaxSourceScope={box_id:sourceUuid(1),owner_id:sourceUuid(2),workspace_id:sourceUuid(3)};
export const sourceRequest:EFaxSourceReviewRequest={expected_revision:5,idempotency_key:sourceUuid(6),operation_id:sourceUuid(4),document_sha256:'a'.repeat(64),passage:'Invented café fax. DOB and eligibility unknown. No referral sent.\nPatient asks about records.',page_numbers:[1,3],reviewed_patient:true,reviewed_exact_document:true,reviewed_exact_text:true,reviewed_untrusted_source:true};
export const sourceReceipt=async(request=sourceRequest):Promise<EFaxSourceReceipt>=>({contract_version:1,scope:sourceScope,idempotency_key:request.idempotency_key,request_sha256:await efaxSourceRequestHash(sourceScope,request),review_id:sourceUuid(7),entry_id:sourceUuid(8),entry_revision:request.expected_revision+1,operation_id:request.operation_id,source_sha256:'b'.repeat(64),content_sha256:await vendorSha256(new TextEncoder().encode(request.passage)),document_sha256:request.document_sha256,page_numbers:request.page_numbers,coverage:'human_selected_passage',extraction:'human_entered_no_ocr',source_withheld:false,state:'saved'});
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'};
const response=(value:unknown,status=200,extra:Record<string,string>={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store',...extra}});
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('fetch',vi.fn());});afterEach(()=>vi.unstubAllGlobals());
it('sends only the closed reviewed-passage command with scoped identity and byte checks',async()=>{
 vi.mocked(fetch).mockResolvedValueOnce(response(await sourceReceipt()));const r=await efaxSourceApi.review(identity,sourceScope,sourceRequest);expect(r.entry_revision).toBe(6);
 const [url,init]=vi.mocked(fetch).mock.calls[0];expect(url).toBe('http://127.0.0.1:8000/workspaces/'+sourceScope.workspace_id+'/efax-inbound-source');expect(init?.method).toBe('POST');
 expect(JSON.parse(init!.body as string)).toEqual(sourceRequest);expect(new Headers(init?.headers).get('X-Cosmas-EFax-Inbound')).toBe('1');expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer invented-token');
 expect(init).toMatchObject({cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer'});
 expect(fetch).toHaveBeenCalledOnce();
});
it('resolves exactly the original review key without another passage save',async()=>{
 vi.mocked(fetch).mockResolvedValueOnce(response(await sourceReceipt()));await efaxSourceApi.resolve(identity,sourceScope,sourceRequest);
 expect(vi.mocked(fetch).mock.calls[0][0]).toContain('/efax-inbound-source/resolve');expect(JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string)).toEqual({idempotency_key:sourceRequest.idempotency_key});
 vi.mocked(fetch).mockResolvedValueOnce(response({contract_version:1,scope:sourceScope,idempotency_key:sourceRequest.idempotency_key,state:'not_found'}));expect((await efaxSourceApi.resolve(identity,sourceScope,sourceRequest)).state).toBe('not_found');
 expect(fetch).toHaveBeenCalledTimes(2);
});
it('rejects wrong original scope/key/document/pages/content/request hash and added fields',async()=>{
 const r=await sourceReceipt();
 for(const value of [{...r,scope:{...sourceScope,owner_id:sourceUuid(99)}},{...r,idempotency_key:sourceUuid(98)},{...r,document_sha256:'c'.repeat(64)},{...r,page_numbers:[3,1]},{...r,content_sha256:'f'.repeat(64)},{...r,request_sha256:'f'.repeat(64)},{...r,entry_revision:7},{...r,ocr:true}]){
  await expect(verifyEFaxSourceReceipt(value,sourceScope,sourceRequest)).rejects.toThrow();
 }expect(fetch).not.toHaveBeenCalled();
});
it('requires bounded literal human passage, sorted pages and all four acknowledgments',()=>{
 for(const body of [{...sourceRequest,passage:' '},{...sourceRequest,passage:'x'.repeat(12001)},{...sourceRequest,passage:'bad\rtext'},{...sourceRequest,page_numbers:[1,1]},{...sourceRequest,page_numbers:[0]},{...sourceRequest,page_numbers:[51]},{...sourceRequest,reviewed_exact_text:false},{...sourceRequest,expected_revision:501},{...sourceRequest,extra:true}]){
  expect(validEFaxSourceReviewRequest(body)).toBe(false);
 }expect(validEFaxSourceReviewRequest(sourceRequest)).toBe(true);
});
it('withheld historical receipt never authorizes a current source even with exact hashes',async()=>{
 const r=await sourceReceipt(),entry={id:r.entry_id,revision:r.entry_revision,kind:'efax_inbound_source',content:sourceRequest.passage,source_label:EFAX_SOURCE_LABEL,fax_source_state:'current'};
 const workspace={id:sourceScope.workspace_id,revision:6,entries:[entry]} as unknown as Workspace;
 expect((await verifyEFaxSourceWorkspace(workspace,r,sourceRequest)).id).toBe(r.entry_id);
 await expect(verifyEFaxSourceWorkspace(workspace,{...r,source_withheld:true},sourceRequest)).rejects.toThrow();
 await expect(verifyEFaxSourceWorkspace({...workspace,entries:[{...entry,content:'',fax_source_state:'unavailable'}]} as unknown as Workspace,r,sourceRequest)).rejects.toThrow();
 await expect(verifyEFaxSourceWorkspace({...workspace,entries:[{...entry,content:'changed'}]} as unknown as Workspace,r,sourceRequest)).rejects.toThrow();
});
it('bounds response bytes, denies redirects/encoding/cache loss and duplicate keys without retry',async()=>{
 for(const raw of [response(await sourceReceipt(),200,{'Cache-Control':'max-age=60'}),response(await sourceReceipt(),200,{'Content-Encoding':'gzip'}),new Response('x'.repeat(16385),{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}}),new Response('{"state":"saved","state":"saved"}',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})]){
  vi.mocked(fetch).mockResolvedValueOnce(raw);await expect(efaxSourceApi.review(identity,sourceScope,sourceRequest)).rejects.toThrow();
 }expect(fetch).toHaveBeenCalledTimes(4);
});
it('decodes only closed private error code responses and preserves exact source refusal',async()=>{
 vi.mocked(fetch).mockResolvedValueOnce(response({error:{code:'efax_inbound_source_document_changed'}},409));
 await expect(efaxSourceApi.review(identity,sourceScope,sourceRequest)).rejects.toMatchObject({status:409,code:'efax_inbound_source_document_changed'});
 for(const body of [{detail:'efax_inbound_source_document_changed'},{error:{code:'invented_unknown'}},{error:{code:'efax_inbound_source_document_changed',message:'private fact'}}]){
  vi.mocked(fetch).mockResolvedValueOnce(response(body,409));await expect(efaxSourceApi.review(identity,sourceScope,sourceRequest)).rejects.toMatchObject({status:409,code:undefined});
 }expect(fetch).toHaveBeenCalledTimes(4);
});
it('fences a late fetch and asynchronous token when native session is no longer current',async()=>{
 let finish!:(r:Response)=>void;vi.mocked(fetch).mockReturnValueOnce(new Promise(r=>{finish=r;}));const c=new AbortController(),p=efaxSourceApi.review(identity,sourceScope,sourceRequest,c.signal);
 for(let i=0;i<20&&!vi.mocked(fetch).mock.calls.length;i++)await Promise.resolve();c.abort();await expect(p).rejects.toThrow();finish(response(await sourceReceipt()));
 let current=true,token!:(t:string)=>void;const native={mode:'clerk_jwt' as const,nativeSession:{revision:sourceUuid(90),isCurrent:()=>current},getToken:()=>new Promise<string>(r=>{token=r;})};
 const pending=efaxSourceApi.review(native,sourceScope,sourceRequest);for(let i=0;i<20&&!token;i++)await Promise.resolve();current=false;token('invented-token');await expect(pending).rejects.toThrow();expect(fetch).toHaveBeenCalledOnce();
});
it('verifies encrypted-recovery exact command commitment and refuses foreign scope/tampering',async()=>{
 const offered={operation_id:sourceRequest.operation_id,document_sha256:sourceRequest.document_sha256,pages:3},visit={id:sourceScope.workspace_id,label:'Invented walk-in · DOB optional',revision:5};
 const record={...emptyEFaxSourceRecovery(sourceScope,offered,visit),passage:sourceRequest.passage,page_numbers:[1,3],pending:{request:sourceRequest,request_sha256:await efaxSourceRequestHash(sourceScope,sourceRequest)}};
 expect((await validateEFaxSourceRecovery(record,sourceScope,offered)).pending!.request).toEqual(sourceRequest);
 await expect(validateEFaxSourceRecovery(record,{...sourceScope,owner_id:sourceUuid(99)},offered)).rejects.toThrow();
 await expect(validateEFaxSourceRecovery({...record,passage:'changed'},sourceScope,offered)).rejects.toThrow();
 await expect(validateEFaxSourceRecovery({...record,pending:{...record.pending,request_sha256:'f'.repeat(64)}},sourceScope,offered)).rejects.toThrow();
});
