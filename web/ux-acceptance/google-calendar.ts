import type {GoogleRehearsalConnection} from './gmail';
import {googleCalendarEventHash,googleCalendarSourceContent,googleCalendarSourceHash,googleCalendarReviewHash,validGoogleCalendarObserveRequest,validGoogleCalendarReviewRequest,type GoogleCalendarReceipt,type GoogleCalendarReviewResponse} from '../src/google-calendar-api';
import {teamClosed,teamUuid,teamCanonical} from '../src/team-setup-request';
import {modelCanonical} from '../src/model-work-request';
import {vendorSha256} from '../src/vendor-contract';
import {WorkspaceApiError,type Workspace} from '../src/workspace-api';

type Scope={box_id:string;actor_id:string};
type Row={hash:string;grant:number;value:GoogleCalendarReceipt|GoogleCalendarReviewResponse};
type State={scope:Scope;grant:number;connected:boolean;permission:boolean;rows:[string,Row][];reserved:{key:string;id:string;grant:number}[]};
export type CalendarRehearsalStats={status:number;observes:number;inspects:number;reviews:number;resolves:number;externalCalls:number;requests:{action:string;key:string|null;body:unknown}[]};
const account={label:'Invented calendar account',email:'calendar@example.invalid'};
const hash=(v:unknown)=>vendorSha256(new TextEncoder().encode(modelCanonical(v)));
const response=(v:unknown,status=200)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
/** Invented tab-local ledger behind the real client validators; never contacts Google. */
export function googleCalendarRehearsal(read:()=>Workspace,write:(w:Workspace)=>void,storageKey:string,reset:boolean,scope:Scope,readConnection?:()=>GoogleRehearsalConnection){
 const key=storageKey+':google-calendar',scenario=()=>new URLSearchParams(location.search).get('scenario')??'';
 const stored=reset?null:sessionStorage.getItem(key),state:State=stored?JSON.parse(stored):{scope:structuredClone(scope),grant:1,connected:scenario()!=='google-calendar-disconnected',permission:scenario()!=='google-calendar-consent',rows:[],reserved:[]};
 const rows=new Map(state.rows),persist=()=>sessionStorage.setItem(key,JSON.stringify({...state,rows:[...rows]}));persist();
 // Named Calendar cases own their deliberate scenario state. The ordinary
 // Preview route shares Gmail's one synthetic Google account and grant.
 const connection=():GoogleRehearsalConnection=>scenario().startsWith('google-calendar')?{scope:state.scope,account,connected:state.connected,calendar_read:state.permission,grant:state.grant}:readConnection?.()??{scope:state.scope,account,connected:false,calendar_read:false,grant:state.grant};
 const currentGrant=()=>connection().grant;
 const stats:CalendarRehearsalStats={status:0,observes:0,inspects:0,reviews:0,resolves:0,externalCalls:0,requests:[]};
 const fail=(code:string,status=409):never=>{throw new WorkspaceApiError(status,code);};
 const grant=()=>{const value=connection();if(modelCanonical(scope)!==modelCanonical(state.scope)||modelCanonical(scope)!==modelCanonical(value.scope)||!value.connected)fail('google_calendar_grant_unavailable');if(!value.calendar_read)fail('google_calendar_consent_required');return structuredClone(value);};
 const checkLease=(admitted:GoogleRehearsalConnection)=>{const value=grant();if(modelCanonical(value)!==modelCanonical(admitted))fail('google_calendar_grant_changed');};
 const current=(row:Row|undefined)=>{if(!row)fail('google_calendar_not_observed');if(row!.grant!==currentGrant())fail('google_calendar_grant_changed');return row!;};
 const find=(id:string)=>[...rows.values()].find(row=>'observation_id'in row.value&&row.value.observation_id===id);
 const withhold=()=>write({...read(),entries:read().entries.map(e=>e.kind==='google_calendar'?{...e,content:'',source_label:'Unavailable calendar source',calendar_source_state:'unavailable'}:e)});
 Object.assign(window,{calendarRehearsalStats:stats,calendarRehearsalControls:{changeGrant:()=>{state.grant++;persist();withhold();},disconnect:()=>{state.connected=false;persist();withhold();}}});
 const retain=async(id:string,body:unknown,admitted:GoogleRehearsalConnection,work:()=>Promise<Row['value']>)=>{const digest=await hash(body);checkLease(admitted);const prior=rows.get(id);if(prior){if(prior.hash!==digest)fail('idempotency_conflict');return structuredClone(current(prior).value);}const value=await work();checkLease(admitted);if('workspace'in value){write(value.workspace);stats.reviews++;}rows.set(id,{hash:digest,grant:admitted.grant,value});persist();return structuredClone(value);};
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  const review=/^\/workspaces\/([a-f0-9-]{36})\/google-calendar\/review$/.exec(path),session=path==='/connections/google/session'&&scenario().startsWith('google-calendar');
  if(!session&&!review&&path!=='/connections/google/calendar-summaries')return null;
  try{
   const headers=new Headers(init?.headers);if(init?.method!=='POST'||typeof init.body!=='string'||headers.get(session?'X-Cosmas-Google-Connection':'X-Cosmas-Google-Calendar')!=='1')fail('invalid_google_calendar_request',422);
   let value:unknown;try{value=JSON.parse(init!.body as string);}catch{fail('invalid_google_calendar_request',422);}if(!value||typeof value!=='object'||Array.isArray(value))fail('invalid_google_calendar_request',422);const body=value as Record<string,unknown>;
   if(session){if(body.action==='status')return response({state:state.connected?'connected':'sign_in_required',account:state.connected?account:null,connected_at:state.connected?'2026-10-26T11:00:00Z':null,...(body.include_capabilities?{capabilities:{mail:state.connected,calendar:state.connected&&state.permission}}:{})});fail('google_calendar_grant_unavailable');}
   stats.requests.push({action:review?'review':String(body.action),key:typeof body.idempotency_key==='string'?body.idempotency_key:null,body:structuredClone(body)});
   if(body.action==='status'&&teamClosed(body,body.include_private_notebook===true?'action,include_private_notebook':'action')){stats.status++;const value=connection(),connected=value.connected&&modelCanonical(value.scope)===modelCanonical(scope)&&modelCanonical(state.scope)===modelCanonical(scope);return response({contract_version:1,state:connected?'connected':'sign_in_required',calendar_read:connected&&value.calendar_read,account:connected?value.account:null,...(body.include_private_notebook?{private_notebook_review:true}:{})});}
   const admitted=grant();
   if(review){
    if(!validGoogleCalendarReviewRequest(body)||review[1]!==read().id||(body.reviewed_private_notebook===true?(read().appointment_id!==null||read().private_draft?.state!=='unlinked'):!read().appointment_id))fail('invalid_google_calendar_review',422);
    const command=body as Parameters<typeof googleCalendarReviewHash>[1];
    return response(await retain(command.idempotency_key,{workspace_id:review[1],...command},admitted,async()=>{
     const anchor=current(find(command.observation_id)).value;if(!('observation'in anchor))fail('google_calendar_not_observed');const receipt=anchor as GoogleCalendarReceipt,event=receipt.observation.items.find(e=>e.id===command.event_id);
     if(!event||command.observation_sha256!==receipt.source_sha256||command.event_sha256!==await googleCalendarEventHash(event))fail('google_calendar_source_changed');const workspace=read();if(workspace.revision!==command.expected_revision)fail('workspace_revision_conflict');
     const content=googleCalendarSourceContent(receipt.observation,event!),entry_id=crypto.randomUUID(),revision=workspace.revision+1;
     const next:Workspace={...workspace,revision,model_observed_at:new Date().toISOString(),entries:[...workspace.entries,{id:entry_id,revision,kind:'google_calendar',content,source_label:('Google calendar: '+event!.subject).slice(0,160),calendar_source_state:'current',origin:'authenticated_human',created_at:new Date().toISOString(),ticket:null}]};
     return {entry_id,entry_revision:revision,request_sha256:await googleCalendarReviewHash(workspace.id,command),source_withheld:false,workspace:next,source:{entry_id,source_sha256:await googleCalendarSourceHash(receipt,event!),content_sha256:await vendorSha256(new TextEncoder().encode(content))}};
    }));
   }
   if(body.action==='inspect'&&teamClosed(body,'action,observation_id')&&teamUuid(body.observation_id)){stats.inspects++;return response(current(find(body.observation_id)).value);}
   if(body.action==='resolve'&&teamClosed(body,'action,idempotency_key')&&teamUuid(body.idempotency_key)){
    stats.resolves++;const reserved=state.reserved.find(r=>r.key===body.idempotency_key);if(reserved){if(reserved.grant!==currentGrant())fail('google_calendar_grant_changed');return response({status:'unconfirmed',observation_id:reserved.id,observation_key:reserved.key});}
    const row=rows.get(body.idempotency_key);return response(row?current(row).value:{status:'not_found',observation_id:null,observation_key:body.idempotency_key});
   }
   if(!validGoogleCalendarObserveRequest(body))fail('invalid_google_calendar_request',422);const command=body as {action:'observe';idempotency_key:string};
   if(scenario()==='google-calendar-unconfirmed'){
    if(!state.reserved.some(r=>r.key===command.idempotency_key)){stats.observes++;state.reserved.push({key:command.idempotency_key,id:crypto.randomUUID(),grant:state.grant});persist();}throw new Error('Invented unconfirmed calendar observation');
   }
   return response(await retain(command.idempotency_key,command,admitted,async()=>{
    const now=Date.now(),at=(hours:number)=>new Date(now+hours*3600000).toISOString();
    const observation={kind:'calendar' as const,account:admitted.account,observed_at:at(0),window:{starts_at:at(0),ends_at:at(168)},more:false,items:[{id:'invented-calendar-event',subject:'Invented follow-up for a very long clinic name — review the event summary',starts_at:at(2),ends_at:at(3),all_day:false,cancelled:false}]};
    stats.observes++;return {contract_version:1,observation_id:crypto.randomUUID(),observation_key:command.idempotency_key,source_sha256:await hash({scope,grant:admitted.grant,command,observation}),payload_sha256:await vendorSha256(new TextEncoder().encode(teamCanonical(observation))),observation};
   }));
  }catch(error){if(error instanceof WorkspaceApiError)return response({detail:error.code??'invalid_google_calendar_request'},error.status);throw error;}
 };
}
