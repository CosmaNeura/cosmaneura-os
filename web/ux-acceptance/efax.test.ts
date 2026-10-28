import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const [key,value] of Object.entries({VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_ENABLED:'true',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_EFAX_INBOUND_ENABLED:'true',VITE_EFAX_INBOUND_SOURCE_ENABLED:'true'}))vi.stubEnv(key,value);});
import {efaxInboundApi,efaxFaxHash,type EFaxPending,type EFaxReceipt} from '../src/efax-inbound-api';
import {efaxSourceApi,verifyEFaxSourceWorkspace,type EFaxSourceReviewRequest} from '../src/efax-inbound-source-api';
import {readConnectionCatalog} from '../src/connection-catalog-api';
import {readFaxReadiness} from '../src/fax-readiness-api';
import {vendorSha256} from '../src/vendor-contract';
import type {Workspace} from '../src/workspace-api';
import {receivedFaxRehearsal,receivedFaxPdf,RECEIVED_FAX_PASSAGE,type ReceivedFaxStats} from './efax';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const scope={box_id:uuid(1),owner_id:uuid(2)},identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-fixture-token'};
let workspace:Workspace,port:ReturnType<typeof receivedFaxRehearsal>;
const stats=()=> (window as unknown as {receivedFaxStats:ReceivedFaxStats}).receivedFaxStats;
const withdraw=()=> (window as unknown as {receivedFaxControls:{withdraw():void}}).receivedFaxControls.withdraw();
function open(owner=scope){port=receivedFaxRehearsal(()=>workspace,value=>{workspace=value;},'invented-fax-test',false,owner);vi.stubGlobal('fetch',async(input:string|URL|Request,init?:RequestInit)=>{const path=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname;const result=await port(path,init);if(!result)throw new Error('No external fixture passthrough');return result;});}
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);sessionStorage.clear();history.replaceState(null,'','/?scenario=received-fax-happy');workspace={id:uuid(71),appointment_id:uuid(72),label:'Invented visit',revision:5,entries:[],work_candidates:[],follow_ups:[],model_contract_version:1,model_observed_at:'2026-10-26T12:05:00Z'};open();});
afterEach(()=>{vi.unstubAllGlobals();history.replaceState(null,'','/');});
async function approved(){
 const status=await efaxInboundApi.status(identity,scope),grant=status.grants[0].grant_id;
 const end=new Date('2026-10-26T17:00:00Z'),start=new Date(end.getTime()-7*86400000);
 const observed=await efaxInboundApi.command(identity,scope,{kind:'observe',request:{idempotency_key:crypto.randomUUID(),grant_id:grant,starts_at:start.toISOString().replace('.000',''),ends_at:end.toISOString().replace('.000',''),limit:25,offset:0}});
 const fax=observed.snapshot!.items[0],proposed=await efaxInboundApi.command(identity,scope,{kind:'propose',request:{idempotency_key:crypto.randomUUID(),grant_id:grant,observation_id:observed.observation_id!,observation_sha256:observed.source_sha256!,fax_id:fax.fax_id,fax_sha256:await efaxFaxHash(fax)}});
 const proposal=await efaxInboundApi.proposal(identity,scope,proposed.ticket_id!);expect(proposal.fax).toEqual(fax);
 const decision=await efaxInboundApi.command(identity,scope,{kind:'decide',request:{idempotency_key:crypto.randomUUID(),ticket_id:proposal.ticket_id,revision_id:proposal.revision_id,expected_version:proposal.version,choice:'approve',reviewed_mark_read:true}});
 const request:Extract<EFaxPending,{kind:'acquire'}>={kind:'acquire',request:{idempotency_key:crypto.randomUUID(),ticket_id:proposal.ticket_id,revision_id:proposal.revision_id,expected_version:decision.version!,approval_sha256:decision.approval_sha256!}};
 return request;
}
const sourceScope=()=>({...scope,workspace_id:workspace.id});
function review(image:EFaxReceipt):EFaxSourceReviewRequest{return {expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),operation_id:image.operation_id!,document_sha256:image.document!.sha256,passage:RECEIVED_FAX_PASSAGE,page_numbers:[1],reviewed_patient:true,reviewed_exact_document:true,reviewed_exact_text:true,reviewed_untrusted_source:true};}
it('passes actual acquisition, exact-PDF and reviewed passage validators with explicit approval and no sends',async()=>{
 const catalog=await readConnectionCatalog(identity,new AbortController().signal);expect(catalog.messaging).toBe(true);expect(catalog.readiness?.messaging.installed_account).toBe('installed');
 expect(catalog.readiness?.google.actions.find(action=>action.id==='reviewed_email_source')).toMatchObject({supported:true,runtime_available:true});expect(catalog.readiness?.microsoft.actions.find(action=>action.id==='full_email_source')).toMatchObject({supported:true,runtime_available:true});
 expect(await readFaxReadiness(identity,new AbortController().signal)).toMatchObject({enabled:true,work_enabled:false,delivery_enabled:false});
 const request=await approved(),image=await efaxInboundApi.command(identity,scope,request),bytes=await efaxInboundApi.document(identity,image);
 expect(Array.from(bytes)).toEqual(Array.from(receivedFaxPdf()));expect(await vendorSha256(bytes)).toBe(image.document?.sha256);expect(image.document?.pages).toBe(1);
 const command=review(image),saved=await efaxSourceApi.review(identity,sourceScope(),command);expect(await verifyEFaxSourceWorkspace(workspace,saved,command)).toMatchObject({kind:'efax_inbound_source',content:RECEIVED_FAX_PASSAGE});
 expect(stats()).toMatchObject({observations:1,proposals:1,decisions:1,acquisitions:1,documents:1,reviews:1,externalCalls:0});expect(workspace.entries).toHaveLength(1);
});
it('recovers a lost acquisition by its original key after reload and reopens saved bytes without another acquisition',async()=>{
 const request=await approved();history.replaceState(null,'','/?scenario=received-fax-lost-acquire');await expect(efaxInboundApi.command(identity,scope,request)).rejects.toMatchObject({status:503});expect(stats().acquisitions).toBe(1);open();
 const result=await efaxInboundApi.resolve(identity,scope,request);expect(result.state).toBe('acquired');const image=result as EFaxReceipt;
 expect(Array.from(await efaxInboundApi.document(identity,image))).toEqual(Array.from(receivedFaxPdf()));expect(Array.from(await efaxInboundApi.document(identity,image))).toEqual(Array.from(receivedFaxPdf()));
 expect(stats()).toMatchObject({observations:0,proposals:0,decisions:0,acquisitions:0,documents:2,resolves:1,reviews:0});
 await expect(efaxInboundApi.command(identity,scope,{...request,request:{...request.request,approval_sha256:'f'.repeat(64)}})).rejects.toMatchObject({code:'efax_inbound_idempotency_conflict'});expect(stats().acquisitions).toBe(0);
});
it('recovers a lost review result without another save and keeps its exact passage, pages and source',async()=>{
 const image=await efaxInboundApi.command(identity,scope,await approved()),request=review(image);history.replaceState(null,'','/?scenario=received-fax-lost-review');
 await expect(efaxSourceApi.review(identity,sourceScope(),request)).rejects.toMatchObject({status:503});const before=structuredClone(workspace);open();
 const saved=await efaxSourceApi.resolve(identity,sourceScope(),request);expect(saved.state).toBe('saved');if(saved.state!=='saved')throw new Error('Expected saved fixture');expect(await verifyEFaxSourceWorkspace(workspace,saved,request)).toMatchObject({content:RECEIVED_FAX_PASSAGE});expect(workspace).toEqual(before);expect(stats()).toMatchObject({reviews:0,acquisitions:0,documents:0,resolves:1});
});
it('withdraws saved PDF and passage access without repeating an acquisition or changing source identity',async()=>{
 const acquire=await approved(),image=await efaxInboundApi.command(identity,scope,acquire),request=review(image),saved=await efaxSourceApi.review(identity,sourceScope(),request);withdraw();
 expect(await efaxInboundApi.resolve(identity,scope,acquire)).toMatchObject({state:'acquired',content_available:false,source_withheld:true,document:null});
 await expect(efaxInboundApi.command(identity,scope,acquire)).rejects.toMatchObject({code:'efax_inbound_grant_unavailable'});
 await expect(efaxInboundApi.document(identity,image)).rejects.toMatchObject({code:'efax_inbound_grant_unavailable'});
 expect(await efaxSourceApi.resolve(identity,sourceScope(),request)).toMatchObject({state:'saved',entry_id:saved.entry_id,source_withheld:true});expect(workspace.entries[0]).toMatchObject({id:saved.entry_id,content:'',source_label:'Unavailable fax source',fax_source_state:'unavailable'});
 expect(stats()).toMatchObject({acquisitions:1,documents:0,reviews:1});
});
it('keeps metadata-only access from authorizing, replaying or reopening an image',async()=>{
 const request=await approved(),image=await efaxInboundApi.command(identity,scope,request),status=await efaxInboundApi.status(identity,scope);
 await efaxInboundApi.command(identity,scope,{kind:'grant',request:{idempotency_key:crypto.randomUUID(),installation_id:status.installations[0].installation_id,reviewed_account:true,reviewed_mark_read:false,image_enabled:false,expires_at:new Date(Date.now()+86400000).toISOString().replace(/\.\d{3}Z$/,'Z')}});
 expect((await efaxInboundApi.status(identity,scope)).grants[0].image_enabled).toBe(false);
 await expect(efaxInboundApi.command(identity,scope,request)).rejects.toMatchObject({code:'efax_inbound_grant_unavailable'});
 await expect(efaxInboundApi.document(identity,image)).rejects.toMatchObject({code:'efax_inbound_grant_unavailable'});
 expect(await efaxInboundApi.resolve(identity,scope,request)).toMatchObject({content_available:false,source_withheld:true,document:null});expect(stats()).toMatchObject({acquisitions:1,documents:0,reviews:0});
});
it('refuses altered PDF digests, wrong pages and unapproved acquisition before source review',async()=>{
 const request=await approved();await expect(efaxInboundApi.command(identity,scope,{...request,request:{...request.request,approval_sha256:'f'.repeat(64)}})).rejects.toMatchObject({code:'efax_inbound_approval_unavailable'});
 const image=await efaxInboundApi.command(identity,scope,request);await expect(efaxInboundApi.document(identity,{...image,document:{...image.document!,sha256:'f'.repeat(64)}})).rejects.toMatchObject({code:'efax_inbound_response_invalid'});
 await expect(efaxSourceApi.review(identity,sourceScope(),{...review(image),page_numbers:[2]})).rejects.toMatchObject({code:'efax_inbound_source_document_changed'});expect(workspace.entries).toEqual([]);expect(stats()).toMatchObject({acquisitions:1,reviews:0});
});
it('keeps a different owner from reading or replacing the tab ledger',async()=>{
 const request=await approved();await efaxInboundApi.command(identity,scope,request);const before=sessionStorage.getItem('invented-fax-test:received-fax');open({...scope,owner_id:uuid(3)});
 await expect(efaxInboundApi.resolve(identity,scope,request)).rejects.toMatchObject({code:'efax_inbound_grant_unavailable'});expect(sessionStorage.getItem('invented-fax-test:received-fax')).toBe(before);expect(stats()).toMatchObject({acquisitions:0,documents:0,reviews:0});
});
it('does not offer external fallback, sending, OCR or automatic acquisition',async()=>{
 expect(await port('/other-service',{method:'POST'})).toBeNull();const refused=await port('/efax-inbound/send',{method:'POST',headers:{'X-Cosmas-EFax-Inbound':'1'},body:'{"idempotency_key":"invented-request"}'});expect(refused?.status).toBe(502);expect(stats()).toMatchObject({observations:0,acquisitions:0,documents:0,reviews:0,externalCalls:0});
});
