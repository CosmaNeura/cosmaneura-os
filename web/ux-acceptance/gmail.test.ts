import {afterEach,beforeEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{for(const [key,value] of Object.entries({VITE_COSMAS_ENV:'synth_os',VITE_WORKSPACE_ENABLED:'true',VITE_WORKSPACE_AUTHENTICATED_ENABLED:'true',VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED:'true',VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED:'true'}))vi.stubEnv(key,value);});
import {googleMessageApi,type GoogleMessageReadRequest,type GoogleMessageReceipt} from '../src/google-message-api';
import {googleConnectionRequest} from '../src/google-connection-api';
import type {Workspace} from '../src/workspace-api';
import {gmailRehearsal,GMAIL_REHEARSAL_HEADER,GMAIL_REHEARSAL_TEXT,type GmailRehearsalStats} from './gmail';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const scope={box_id:uuid(1),actor_id:uuid(2)},identity={mode:'clerk_jwt' as const,getToken:async()=>'invented-fixture-token'};
let workspace:Workspace,port:ReturnType<typeof gmailRehearsal>;
const stats=()=> (window as unknown as {gmailRehearsalStats:GmailRehearsalStats}).gmailRehearsalStats;
const controls=()=> (window as unknown as {gmailRehearsalControls:{changeGrant():void;disconnect():void}}).gmailRehearsalControls;
function open(owner=scope){port=gmailRehearsal(()=>workspace,value=>{workspace=value;},'invented-gmail-test',false,owner);vi.stubGlobal('fetch',async(input:string|URL|Request,init?:RequestInit)=>{const path=new URL(typeof input==='string'?input:input instanceof URL?input.href:input.url,location.href).pathname;const result=await port(path,init);if(!result)throw new Error('No external fixture passthrough');return result;});}
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);sessionStorage.clear();history.replaceState(null,'','/');workspace={id:uuid(71),appointment_id:uuid(72),label:'Invented visit',revision:5,entries:[],work_candidates:[],follow_ups:[],model_contract_version:1,model_observed_at:'2026-10-26T12:05:00Z'};open();});
afterEach(()=>{vi.unstubAllGlobals();history.replaceState(null,'','/');});
async function selected(){const list=await googleMessageApi.list(identity,{action:'list',idempotency_key:crypto.randomUUID()});const request:GoogleMessageReadRequest={action:'read',idempotency_key:crypto.randomUUID(),observation_id:list.read_id,observation_sha256:list.source_sha256,message_id:GMAIL_REHEARSAL_HEADER.id,thread_id:GMAIL_REHEARSAL_HEADER.thread_id};return {list,request};}
const reviewRequest=(message:GoogleMessageReceipt)=>({expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),read_id:message.read_id,source_sha256:message.source_sha256,reviewed_patient:true as const,reviewed_exact_message:true as const,reviewed_untrusted_source:true as const});
it('passes the actual status, full-message and exact source-save validators, without changing clinical notes or sending',async()=>{
 expect(await googleConnectionRequest(identity,'status')).toMatchObject({state:'connected',capabilities:{mail:true,calendar:false}});
 expect(await googleMessageApi.status(identity)).toMatchObject({full_mail_read:true,account:{email:'owner@example.invalid'}});
 const {request}=await selected(),message=await googleMessageApi.read(identity,request);
 expect(message.message?.content).toBe(GMAIL_REHEARSAL_TEXT);expect(message.message?.is_read).toBe(false);
 const saved=await googleMessageApi.review(identity,workspace.id,reviewRequest(message),message);
 expect(workspace.entries).toHaveLength(1);expect(workspace.entries[0]).toMatchObject({id:saved.entry_id,kind:'google_message',content:GMAIL_REHEARSAL_TEXT,google_source_state:'current',source_label:'Google message: Invented visit follow-up'});
 expect(stats()).toMatchObject({lists:1,reads:1,reviews:1,resolves:0,externalCalls:0});
 expect(stats().requests.at(-1)?.body).toMatchObject({reviewed_patient:true,reviewed_exact_message:true,reviewed_untrusted_source:true});
});
it('restores a lost successful read by its same key after reload without rereading the list or body',async()=>{
 history.replaceState(null,'','/?scenario=gmail-lost-read');const {request}=await selected();await expect(googleMessageApi.read(identity,request)).rejects.toMatchObject({status:503});
 expect(stats()).toMatchObject({lists:1,reads:1,reviews:0});open();
 const result=await googleMessageApi.resolve(identity,request.idempotency_key,'message');expect(result).toMatchObject({read_key:request.idempotency_key,message:{content:GMAIL_REHEARSAL_TEXT}});
 expect(stats()).toMatchObject({lists:0,reads:0,reviews:0,resolves:1,externalCalls:0});
 await expect(googleMessageApi.resolve(identity,request.idempotency_key,'list')).rejects.toMatchObject({code:'idempotency_conflict'});
 await expect(googleMessageApi.read(identity,{...request,message_id:'different-invented-message'})).rejects.toMatchObject({code:'idempotency_conflict'});
 expect(stats().reads).toBe(0);
});
it('retries an exact lost source save after reload without adding a second source or changing its request',async()=>{
 const {request}=await selected(),message=await googleMessageApi.read(identity,request),body=reviewRequest(message);history.replaceState(null,'','/?scenario=gmail-lost-review');
 await expect(googleMessageApi.review(identity,workspace.id,body,message)).rejects.toMatchObject({status:503});const prior=structuredClone(workspace);expect(prior.entries).toHaveLength(1);open();
 const saved=await googleMessageApi.review(identity,workspace.id,body,message);expect(saved.workspace).toEqual(prior);expect(workspace).toEqual(prior);expect(stats()).toMatchObject({lists:0,reads:0,reviews:0,externalCalls:0});
 expect(stats().requests[0].body).toEqual(body);await expect(googleMessageApi.review(identity,workspace.id,{...body,expected_revision:body.expected_revision+1},message)).rejects.toMatchObject({code:'idempotency_conflict'});
});
it('refuses the saved source after a simulated grant change, withholding workspace content without a provider reread',async()=>{
 const {request}=await selected(),message=await googleMessageApi.read(identity,request);await googleMessageApi.review(identity,workspace.id,reviewRequest(message),message);controls().changeGrant();
 expect(await googleMessageApi.status(identity)).toMatchObject({state:'connected'});await expect(googleMessageApi.inspect(identity,message)).rejects.toMatchObject({status:409,code:'google_message_grant_changed'});
 expect(workspace.entries[0]).toMatchObject({content:'',source_label:'Unavailable email source',google_source_state:'unavailable'});expect(stats()).toMatchObject({lists:1,reads:1,reviews:1,inspects:1,externalCalls:0});
});
it('rejects a different owner without exposing or replacing the retained ledger',async()=>{
 const {request}=await selected();await googleMessageApi.read(identity,request);const before=sessionStorage.getItem('invented-gmail-test:gmail');open({...scope,actor_id:uuid(3)});
 await expect(googleMessageApi.resolve(identity,request.idempotency_key,'message')).rejects.toMatchObject({code:'google_message_grant_unavailable'});expect(sessionStorage.getItem('invented-gmail-test:gmail')).toBe(before);expect(stats()).toMatchObject({lists:0,reads:0,reviews:0,externalCalls:0});
});
it('keeps a reserved read unconfirmed across repeated saved-result checks, with no duplicate read',async()=>{
 history.replaceState(null,'','/?scenario=gmail-unconfirmed-read');const {request}=await selected();await expect(googleMessageApi.read(identity,request)).rejects.toMatchObject({status:503});open();
 const first=await googleMessageApi.resolve(identity,request.idempotency_key,'message'),second=await googleMessageApi.resolve(identity,request.idempotency_key,'message');expect(first).toMatchObject({status:'unconfirmed',read_key:request.idempotency_key,kind:'message'});expect(second).toEqual(first);expect(stats()).toMatchObject({lists:0,reads:0,resolves:2,reviews:0});
});
it('keeps empty, incomplete and missing-permission outcomes distinct with no usable partial source',async()=>{
 history.replaceState(null,'','/?scenario=gmail-empty');const empty=await googleMessageApi.list(identity,{action:'list',idempotency_key:crypto.randomUUID()});expect(empty.observation?.items).toEqual([]);
 history.replaceState(null,'','/?scenario=gmail-needs-human');const {request}=await selected(),message=await googleMessageApi.read(identity,request);expect(message).toMatchObject({status:'needs_human',message:{content:null,content_sha256:null,reason:'attachment'}});expect(workspace.entries).toEqual([]);
 sessionStorage.clear();history.replaceState(null,'','/?scenario=gmail-consent');open();expect(await googleMessageApi.status(identity)).toMatchObject({state:'connected',full_mail_read:false});const next=await selected();await expect(googleMessageApi.read(identity,next.request)).rejects.toMatchObject({code:'google_mail_consent_required'});expect(stats().reads).toBe(0);
});
it('does not offer OAuth navigation, external fallback, or unsupported command shapes',async()=>{
 expect(await port('/other-service',{method:'POST'})).toBeNull();
 const headers={'Content-Type':'application/json','X-Cosmas-Google-Messages':'1'};
 const refused=await port('/connections/google/messages',{method:'POST',headers,body:JSON.stringify({action:'list',idempotency_key:crypto.randomUUID(),send:true})});expect(refused?.status).toBe(422);
 const oauth=await port('/connections/google/session',{method:'POST',headers:{'X-Cosmas-Google-Connection':'1'},body:'{"action":"start_full_mail"}'});expect(oauth?.status).toBe(409);expect(await oauth?.json()).not.toHaveProperty('authorization_url');expect(stats()).toMatchObject({lists:0,reads:0,reviews:0,externalCalls:0});
});
