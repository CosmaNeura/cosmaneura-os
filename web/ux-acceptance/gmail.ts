import {googleMessageReviewHash,validGoogleMessageListRequest,validGoogleMessageReadRequest,validGoogleMessageReviewRequest,type GoogleMessageReceipt,type GoogleMessageReviewResponse} from '../src/google-message-api';
import {modelCanonical} from '../src/model-work-request';
import {teamCanonical,teamClosed,teamUuid} from '../src/team-setup-request';
import {vendorSha256} from '../src/vendor-contract';
import {CONNECTION_IDS} from '../src/connection-catalog-api';
import {readinessFixture} from '../src/connection-readiness-fixture';
import {WorkspaceApiError,type Workspace} from '../src/workspace-api';

// Invented content from the existing signed GoogleMessage UI lab. No real mail,
// OAuth grant, provider read, send, or model call is performed by this fixture.
export const GMAIL_REHEARSAL_TEXT='Subject: Invented visit follow-up\nFrom: sender@example.invalid\n\nInvented administrative request: please prepare follow-up work. Heart history and trial eligibility are unconfirmed. DOB unavailable. No sending or clinical decision requested.';
export const GMAIL_REHEARSAL_HEADER={id:'invented-ui-message',thread_id:'invented-thread',subject:'Invented visit follow-up',sender:'sender@example.invalid',received_at:'2026-10-26T12:00:00Z',is_read:false};
const account={label:'Invented UI account',email:'owner@example.invalid'};
type Scope={box_id:string;actor_id:string};
type Value=GoogleMessageReceipt|GoogleMessageReviewResponse;
type Row={hash:string;grant:number;value:Value};
type Reservation={key:string;hash:string;kind:'message';read_id:string;grant:number};
type State={scope:Scope;connected:boolean;full_mail_read:boolean;connected_at:string;grant:number;lost:string[];ledger:[string,Row][];reservations:Reservation[]};
export type GmailRehearsalStats={lists:number;reads:number;reviews:number;resolves:number;inspects:number;status:number;externalCalls:number;requests:{action:string;key:string|null;body:unknown}[]};

/** Tab-local saved-result ledger. All requests still pass the real API validators. */
export function gmailRehearsal(read:()=>Workspace,write:(value:Workspace)=>void,storageKey:string,reset:boolean,scope:Scope){
 const key=storageKey+':gmail',scenario=()=>new URLSearchParams(location.search).get('scenario')??'gmail-happy';
 const stored=reset?null:sessionStorage.getItem(key);
 const state:State=stored?JSON.parse(stored):{scope:structuredClone(scope),connected:scenario()!=='gmail-disconnected',full_mail_read:scenario()!=='gmail-consent',connected_at:'2026-10-26T11:00:00Z',grant:1,lost:[],ledger:[],reservations:[]};
 const scopeCurrent=()=>modelCanonical(state.scope)===modelCanonical(scope);
 const ledger=new Map(state.ledger),persist=()=>sessionStorage.setItem(key,JSON.stringify({...state,ledger:[...ledger]}));
 if(scopeCurrent())persist();
 const stats:GmailRehearsalStats={lists:0,reads:0,reviews:0,resolves:0,inspects:0,status:0,externalCalls:0,requests:[]};
 Object.assign(window,{gmailRehearsalStats:stats});
 const digest=(value:unknown)=>vendorSha256(new TextEncoder().encode(modelCanonical(value)));
 const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 function fail(code:string,status=409):never{throw new WorkspaceApiError(status,code);}
 const closed=(value:unknown,keys:string):boolean=>teamClosed(value,keys);
 const requireGrant=(full=false)=>{if(!scopeCurrent())fail('google_message_grant_unavailable');if(!state.connected)fail('google_message_grant_unavailable');if(full&&!state.full_mail_read)fail('google_mail_consent_required');};
 const find=(id:string)=>[...ledger.values()].find((row):row is Row&{value:GoogleMessageReceipt}=>'read_id'in row.value&&row.value.read_id===id);
 const current=(row:Row|undefined)=>{if(!row)fail('google_message_not_observed');if(row.grant!==state.grant)fail('google_message_grant_changed');return row;};
 const retain=async(id:string,body:unknown,work:()=>Promise<Value>)=>{const hash=await digest(body),prior=ledger.get(id);if(prior){if(prior.hash!==hash)fail('idempotency_conflict');current(prior);return structuredClone(prior.value);}const value=await work();ledger.set(id,{hash,grant:state.grant,value});persist();return structuredClone(value);};
 const withhold=()=>{const workspace=read();write({...workspace,entries:workspace.entries.map(entry=>entry.kind==='google_message'?{...entry,content:'',source_label:'Unavailable email source',google_source_state:'unavailable'}:entry)});};
 const changeGrant=()=>{state.grant++;persist();withhold();};
 const disconnect=()=>{state.connected=false;persist();withhold();};
 Object.assign(window,{gmailRehearsalControls:{changeGrant,disconnect}});
 const lose=(kind:'read'|'review')=>{if(scenario()===`gmail-lost-${kind}`&&!state.lost.includes(kind)){state.lost.push(kind);persist();throw new Error(`Invented lost Gmail ${kind} success response`);}};
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  if(path==='/connections/catalog'&&init?.method==='GET'){
   const catalog=readinessFixture();catalog.google=true;catalog.microsoft=true;
   for(const [vendor,actionId] of [['google','reviewed_email_source'],['microsoft','full_email_source']] as const)
    catalog.readiness![vendor].actions=catalog.readiness![vendor].actions.map(action=>action.id===actionId?{...action,supported:true,runtime_available:true}:action);
   return response({version:2,services:CONNECTION_IDS.map(id=>({id,setup_available:catalog[id],...catalog.readiness![id]}))});
  }
  const review=/^\/workspaces\/([a-f0-9-]{36})\/google-messages\/review$/.exec(path);
  if(path!=='/connections/google/session'&&path!=='/connections/google/messages'&&!review)return null;
  try{
   const headers=new Headers(init?.headers),session=path.endsWith('/session');
   if(init?.method!=='POST'||typeof init.body!=='string'||headers.get(session?'X-Cosmas-Google-Connection':'X-Cosmas-Google-Messages')!=='1')fail('invalid_google_message_request',422);
   let body:unknown;try{body=JSON.parse(init.body as string);}catch{return response({detail:'invalid_google_message_request'},422);}
   if(!body||typeof body!=='object'||Array.isArray(body))fail('invalid_google_message_request',422);
   const b=body as Record<string,unknown>;
   if(!scopeCurrent())fail('google_message_grant_unavailable');
   if(session){
    if(b.action==='status'&&(closed(b,'action')||closed(b,'action,include_capabilities')&&b.include_capabilities===true))return response({state:state.connected?'connected':'sign_in_required',account:state.connected?account:null,connected_at:state.connected?state.connected_at:null,...(b.include_capabilities?{capabilities:{mail:state.connected,calendar:false}}:{})});
    if(b.action==='disconnect'&&teamClosed(b,'action')){disconnect();return response({state:'disconnected'});}
    // Real OAuth navigation is deliberately unavailable in an invented fixture.
    fail('google_message_grant_unavailable');
   }
   stats.requests.push({action:review?'review':String(b.action),key:typeof b.idempotency_key==='string'?b.idempotency_key:null,body:structuredClone(b)});
   if(b.action==='status'&&teamClosed(b,'action')){stats.status++;return response({contract_version:1,state:state.connected?'connected':'sign_in_required',full_mail_read:state.connected&&state.full_mail_read,account:state.connected?account:null});}
   requireGrant(!!review||b.action==='read');
   if(review){
    if(!validGoogleMessageReviewRequest(b)||review[1]!==read().id)fail('invalid_google_message_request',422);
    const command=b as Parameters<typeof googleMessageReviewHash>[1];
    const result=await retain(command.idempotency_key,{workspace_id:review[1],...command},async()=>{
     const workspace=read(),row=find(command.read_id);current(row);const anchor=row!.value;
     if(workspace.revision!==command.expected_revision)fail('workspace_revision_conflict');
     if(anchor.kind!=='message'||anchor.status!=='complete'||anchor.source_sha256!==command.source_sha256)fail('google_message_source_changed');
     const message=anchor.message!,entry_id=crypto.randomUUID(),revision=workspace.revision+1;
     const next:Workspace={...workspace,revision,model_observed_at:new Date().toISOString(),entries:[...workspace.entries,{id:entry_id,revision,kind:'google_message',content:message.content!,source_label:('Google message: '+message.subject).slice(0,160),origin:'authenticated_human',created_at:new Date().toISOString(),ticket:null,google_source_state:'current'}]};
     const value:GoogleMessageReviewResponse={entry_id,entry_revision:revision,request_sha256:await googleMessageReviewHash(workspace.id,command,message.content_sha256!),source_withheld:false,workspace:next,source:{entry_id,source_sha256:anchor.source_sha256,content_sha256:message.content_sha256!}};
     stats.reviews++;write(next);return value;
    });lose('review');return response(result);
   }
   if(b.action==='resolve'&&teamClosed(b,'action,idempotency_key,kind')&&teamUuid(b.idempotency_key)&&(b.kind==='list'||b.kind==='message')){
    stats.resolves++;const reserved=state.reservations.find(item=>item.key===b.idempotency_key);
    if(reserved){if(reserved.kind!==b.kind)fail('idempotency_conflict');if(reserved.grant!==state.grant)fail('google_message_grant_changed');return response({status:'unconfirmed',kind:reserved.kind,read_key:reserved.key,read_id:reserved.read_id});}
    const row=ledger.get(b.idempotency_key);if(row){current(row);if(!('kind'in row.value)||row.value.kind!==b.kind)fail('idempotency_conflict');}
    return response(row?.value??{status:'not_found',kind:b.kind,read_key:b.idempotency_key,read_id:null});
   }
   if(b.action==='inspect'&&teamClosed(b,'action,read_id')&&teamUuid(b.read_id)){stats.inspects++;const row=find(b.read_id);current(row);return response(row!.value);}
   if(!validGoogleMessageListRequest(b)&&!validGoogleMessageReadRequest(b))fail('invalid_google_message_request',422);
   const command=b as Parameters<typeof validGoogleMessageReadRequest>[0]&({action:'list';idempotency_key:string}|{action:'read';idempotency_key:string;observation_id:string;observation_sha256:string;message_id:string;thread_id?:string});
   const selected=()=>{if(command.action!=='read')fail('invalid_google_message_request',422);const row=find(command.observation_id);current(row);const anchor=row!.value;
    if(anchor.kind!=='list'||anchor.source_sha256!==command.observation_sha256||!anchor.observation!.items.some(item=>item.id===command.message_id&&(!command.thread_id||command.thread_id===item.thread_id)))fail('google_message_not_observed');return anchor;};
   if(command.action==='read'&&scenario()==='gmail-unconfirmed-read'){
    selected();const hash=await digest(command),prior=state.reservations.find(item=>item.key===command.idempotency_key);
    if(prior&&prior.hash!==hash)fail('idempotency_conflict');
    if(!prior){stats.reads++;state.reservations.push({key:command.idempotency_key,hash,kind:'message',read_id:crypto.randomUUID(),grant:state.grant});persist();}
    throw new Error('Invented reserved Gmail read without a confirmed response');
   }
   const result=await retain(command.idempotency_key,command,async()=>{
    const read_id=crypto.randomUUID(),observed_at='2026-10-26T12:05:00Z';
    if(command.action==='list'){
     const observation={kind:'mail' as const,account,items:scenario()==='gmail-empty'?[]:[GMAIL_REHEARSAL_HEADER],more:false,observed_at};
     const payload_sha256=await vendorSha256(new TextEncoder().encode(teamCanonical(observation)));stats.lists++;
     return {read_id,read_key:command.idempotency_key,kind:'list',observation_id:read_id,source_sha256:await digest({contract:'invented.gmail.list.v1',scope,grant:state.grant,command,payload_sha256}),payload_sha256,status:'observed',message:null,observation};
    }
    const list=selected(),incomplete=scenario()==='gmail-needs-human',status=incomplete?'needs_human' as const:'complete' as const;
    const message={message_id:GMAIL_REHEARSAL_HEADER.id,thread_id:GMAIL_REHEARSAL_HEADER.thread_id,history_id:'123',subject:GMAIL_REHEARSAL_HEADER.subject,sender:GMAIL_REHEARSAL_HEADER.sender,received_at:GMAIL_REHEARSAL_HEADER.received_at,is_read:false,observed_at,status,content:incomplete?null:GMAIL_REHEARSAL_TEXT,reason:incomplete?'attachment' as const:null,raw_sha256:await digest({invented:GMAIL_REHEARSAL_TEXT}),content_sha256:incomplete?null:await vendorSha256(new TextEncoder().encode(GMAIL_REHEARSAL_TEXT))};
    const payload_sha256=await digest({scope,grant:state.grant,message});stats.reads++;
    return {read_id,read_key:command.idempotency_key,kind:'message',observation_id:list.read_id,source_sha256:await digest({contract:'invented.gmail.message.v1',scope,grant:state.grant,command,payload_sha256}),payload_sha256,status,message,observation:null};
   });if(command.action==='read')lose('read');return response(result);
  }catch(error){if(error instanceof WorkspaceApiError)return response({detail:error.code??'invalid_google_message_request'},error.status);throw error;}
 };
}
