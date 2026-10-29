import {outlookMessageReviewHash,validOutlookMessageListRequest,validOutlookMessageReadRequest,validOutlookMessageReviewRequest,type OutlookMessageReceipt,type OutlookMessageReviewResponse} from '../src/outlook-message-api';
import {modelCanonical} from '../src/model-work-request';
import {teamCanonical} from '../src/team-setup-request';
import {vendorSha256} from '../src/vendor-contract';
import {CONNECTION_IDS} from '../src/connection-catalog-api';
import {readinessFixture} from '../src/connection-readiness-fixture';
import {WorkspaceApiError,type Workspace} from '../src/workspace-api';

/** Invented, tab-local Outlook service. This fixture never reaches Microsoft. */
export function outlookRehearsal(read:()=>Workspace,write:(value:Workspace)=>void,storageKey:string,reset:boolean,scope:{box_id:string;actor_id:string}){
 const key=storageKey+':outlook',stored=reset?null:sessionStorage.getItem(key);
 type Row={hash:string;value:OutlookMessageReceipt|OutlookMessageReviewResponse};
 const state:{connected:boolean;connected_at:string;lost:string[];ledger:[string,Row][];reservations:{key:string;hash:string;read_id:string}[]}=stored?JSON.parse(stored):{connected:true,connected_at:new Date().toISOString(),lost:[],ledger:[],reservations:[]};state.reservations??=[];
 const ledger=new Map(state.ledger),persist=()=>sessionStorage.setItem(key,JSON.stringify({...state,ledger:[...ledger]}));persist();
 const stats={reads:0,reviews:0,resolves:0,inspects:0,status:0,externalCalls:0,requests:[] as {action:string;key:string|null}[]};Object.assign(window,{outlookRehearsalStats:stats});
 const account={label:'Local example — invented Outlook account',email:'doctor@example.invalid'};
 const header={id:'AAMk+invented/email=',thread_id:'AAQk+invented/thread=',subject:'Invented sleep diary follow-up',sender:'jordan@example.invalid',received_at:'2026-10-25T12:00:00Z',is_read:false};
 const text='Invented message for Jordan Cypress: I can bring the sleep diary to the next visit. Please ask the practice about the preferred contact time. This invented message does not establish consent or a medication list.';
 const digest=(value:unknown)=>vendorSha256(new TextEncoder().encode(modelCanonical(value)));
 const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const requireGrant=()=>{if(!state.connected)throw new WorkspaceApiError(409,'microsoft_message_grant_unavailable');};
 const find=(id:string)=>[...ledger.values()].map(row=>row.value).find((value):value is OutlookMessageReceipt=>'read_id'in value&&value.read_id===id);
 const retain=async(id:string,body:unknown,work:()=>Promise<Row['value']>)=>{const hash=await digest(body),prior=ledger.get(id);if(prior){if(prior.hash!==hash)throw new WorkspaceApiError(409,'idempotency_conflict');return structuredClone(prior.value);}const value=await work();ledger.set(id,{hash,value});persist();return structuredClone(value);};
 const disconnect=()=>{state.connected=false;persist();const current=read();write({...current,entries:current.entries.map(entry=>entry.kind==='microsoft_message'?{...entry,content:'',source_label:'Unavailable email source',microsoft_source_state:'unavailable'}:entry)});};
 Object.assign(window,{outlookRehearsalControls:{disconnect}});
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  if(path==='/connections/catalog'&&init?.method==='GET'){
   const catalog=readinessFixture();catalog.microsoft=true;
   catalog.readiness!.microsoft.actions=catalog.readiness!.microsoft.actions.map(action=>action.id==='full_email_source'?{...action,supported:true,runtime_available:true}:action);
   return response({version:2,services:CONNECTION_IDS.map(id=>({id,setup_available:catalog[id],...catalog.readiness![id]}))});
  }
  const review=/^\/workspaces\/([a-f0-9-]{36})\/microsoft-messages\/review$/.exec(path);
  if(path!=='/connections/microsoft/session'&&path!=='/connections/microsoft/messages'&&!review)return null;
  try{
   const headers=new Headers(init?.headers);
   if(init?.method!=='POST'||typeof init.body!=='string'||headers.get(path.endsWith('/session')?'X-Cosmas-Microsoft-Connection':'X-Cosmas-Microsoft-Messages')!=='1')throw new WorkspaceApiError(422,'invalid_microsoft_message_request');
   const body=JSON.parse(init.body);
   if(path==='/connections/microsoft/session'){
    if(body.action==='disconnect'){disconnect();return response({state:'disconnected'});}
    if(body.action==='status')return response({state:state.connected?'connected':'sign_in_required',account:state.connected?account:null,connected_at:state.connected?state.connected_at:null});
    requireGrant();if(body.action==='mail')return response({kind:'mail',account,items:[{id:header.id,subject:header.subject,sender:header.sender,received_at:header.received_at,is_read:false}],more:false,observed_at:new Date().toISOString()});
    if(body.action==='calendar')return response({kind:'calendar',account,items:[],more:false,observed_at:new Date().toISOString()});
    throw new WorkspaceApiError(409,'microsoft_message_grant_unavailable');
   }
   stats.requests.push({action:review?'review':body.action,key:body.idempotency_key??null});
   if(body.action==='status'){stats.status++;return response({contract_version:1,state:state.connected?'connected':'sign_in_required',full_mail_read:state.connected,account:state.connected?account:null});}
   requireGrant();
   if(review){
    if(!validOutlookMessageReviewRequest(body)||review[1]!==read().id)throw new WorkspaceApiError(422,'invalid_microsoft_message_request');stats.reviews++;
    const result=await retain(body.idempotency_key,{workspace_id:review[1],...body},async()=>{
     const current=read(),anchor=find(body.read_id);if(current.revision!==body.expected_revision)throw new WorkspaceApiError(409,'workspace_revision_conflict');
     if(!anchor||anchor.kind!=='message'||anchor.status!=='complete'||anchor.source_sha256!==body.source_sha256)throw new WorkspaceApiError(409,'microsoft_message_source_changed');
     const entry_id=crypto.randomUUID(),revision=current.revision+1,workspace:Workspace={...current,revision,model_observed_at:new Date().toISOString(),entries:[...current.entries,{id:entry_id,revision,kind:'microsoft_message',content:anchor.message!.content!,source_label:'Outlook: '+header.subject,origin:'authenticated_human',created_at:new Date().toISOString(),ticket:null,microsoft_source_state:'current'}]};write(workspace);
     return {entry_id,entry_revision:revision,request_sha256:await outlookMessageReviewHash(current.id,body,anchor.message!.content_sha256!),source_withheld:false,workspace,source:{entry_id,source_sha256:anchor.source_sha256,content_sha256:anchor.message!.content_sha256!}};
    });
    if(new URLSearchParams(location.search).get('scenario')==='outlook-lost-review'&&!state.lost.includes('review')){state.lost.push('review');persist();throw new Error('Invented lost Outlook source-save response');}return response(result);
   }
   if(body.action==='resolve'){stats.resolves++;const reserved=state.reservations.find(item=>item.key===body.idempotency_key);if(reserved){if(body.kind!=='message')throw new WorkspaceApiError(409,'idempotency_conflict');return response({status:'unconfirmed',kind:'message',read_key:reserved.key,read_id:reserved.read_id});}const result=ledger.get(body.idempotency_key)?.value;if(result&&(!('kind'in result)||result.kind!==body.kind))throw new WorkspaceApiError(409,'idempotency_conflict');return response(result??{status:'not_found',kind:body.kind,read_key:body.idempotency_key,read_id:null});}
   if(body.action==='inspect'){stats.inspects++;const result=find(body.read_id);if(!result)throw new WorkspaceApiError(409,'microsoft_message_not_observed');return response(result);}
   if(!validOutlookMessageListRequest(body)&&!validOutlookMessageReadRequest(body))throw new WorkspaceApiError(422,'invalid_microsoft_message_request');
   if(body.action==='read'&&new URLSearchParams(location.search).get('scenario')==='outlook-unconfirmed-read'){
    const hash=await digest(body),prior=state.reservations.find(item=>item.key===body.idempotency_key);if(prior&&prior.hash!==hash)throw new WorkspaceApiError(409,'idempotency_conflict');
    if(!prior){stats.reads++;state.reservations.push({key:body.idempotency_key,hash,read_id:crypto.randomUUID()});persist();}throw new Error('Invented unconfirmed Outlook read');
   }
   const result=await retain(body.idempotency_key,body,async()=>{
    stats.reads++;const read_id=crypto.randomUUID(),observed_at=new Date().toISOString();
    if(body.action==='list'){
     const observation={kind:'mail' as const,account,items:[header],more:false,observed_at},payload_sha256=await vendorSha256(new TextEncoder().encode(teamCanonical(observation)));
     return {read_id,read_key:body.idempotency_key,kind:'list',observation_id:read_id,source_sha256:await digest({kind:'outlook-rehearsal-list-v1',scope,body,payload_sha256}),payload_sha256,status:'observed',message:null,observation};
    }
    const list=find(body.observation_id);if(!list||list.kind!=='list'||list.source_sha256!==body.observation_sha256||body.message_id!==header.id||body.thread_id!==undefined&&body.thread_id!==header.thread_id)throw new WorkspaceApiError(409,'microsoft_message_not_observed');
    const message={message_id:header.id,thread_id:header.thread_id,change_key:'CQAA+invented/change=',subject:header.subject,sender:header.sender,received_at:header.received_at,is_read:false,observed_at,status:'complete' as const,content:text,reason:null,raw_sha256:await digest({invented:text}),content_sha256:await vendorSha256(new TextEncoder().encode(text))},payload_sha256=await digest({scope,message});
    return {read_id,read_key:body.idempotency_key,kind:'message',observation_id:list.read_id,source_sha256:await digest({kind:'outlook-rehearsal-message-v1',scope,body,payload_sha256}),payload_sha256,status:'complete',message,observation:null};
   });
   if(body.action==='read'&&new URLSearchParams(location.search).get('scenario')==='outlook-lost-read'&&!state.lost.includes('read')){state.lost.push('read');persist();throw new Error('Invented lost Outlook body response');}return response(result);
  }catch(error){if(error instanceof WorkspaceApiError)return response({detail:error.code??'invalid_microsoft_message_request'},error.status);throw error;}
 };
}
