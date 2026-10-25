import fixture from '../src/__fixtures__/athena-visit-links.json';
import {coreDigest,validateCoreCommand} from '../src/core-connection-contract';
import {validateAthenaCommand} from '../src/athena-connection-contract';
import {validateAthenaVisitLinkCommand,type AthenaVisitLinkCommand} from '../src/athena-visit-link-api';

/** Invented, tab-local Core receiver. No request leaves this fixture. */
export async function athenaRehearsal(storageKey:string,reset=false,openWorkspace?:()=>{workspace_id:string;appointment_id:string}){
 const key=storageKey+':athena';
 type Entry={hash:string;operation:'link'|'unlink'};
 const saved: {linked:boolean;lost:string[];commands:[string,Entry][]}=reset?{linked:false,lost:[],commands:[]}:JSON.parse(sessionStorage.getItem(key)??'{"linked":false,"lost":[],"commands":[]}');
 const ledger=new Map(saved.commands),persist=()=>sessionStorage.setItem(key,JSON.stringify({...saved,commands:[...ledger]}));persist();
 const connection=structuredClone(fixture.lookup.response.athena_visit_link.connection);connection.practice_label='Local example — invented Athena practice';
 const {connection_sha256:_oldConnection,...c}=connection;connection.connection_sha256=await coreDigest(c);
 const account=structuredClone(fixture.lookup.response.athena_visit_link.account);account.department_label='Invented Athena office';
 const stats={actions:[] as {action:string;key:string|null;hash:string|null;nonce:string}[],externalCalls:0};Object.assign(window,{athenaRehearsalStats:stats});
 const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 async function projection(day:string){
  const source={...fixture.lookup.response.athena_visit_link.source,source_local_start:day+'T09:00:00'};
  const {source_sha256:_old,...fields}=source;source.source_sha256=await coreDigest({account_sha256:account.account_sha256,...fields});
  const encounter=structuredClone(fixture.preview.response.athena_visit_link.encounter);encounter.connection_sha256=connection.connection_sha256;
  encounter.patient.display_name='Jordan Cypress — invented patient';encounter.appointment.appointment_date=day+'T13:00:00+00:00';encounter.appointment.timezone_known=true;
  const {source_sha256:_oldEncounter,...body}=encounter;encounter.source_sha256=await coreDigest(body);return {source,encounter};
 }
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  if(path!=='/connections/cosmaneura/read')return null;
  if(init?.method!=='POST'||typeof init.body!=='string')return response({detail:'invalid_core_connection_request'},422);
  const command=JSON.parse(init.body),action=command.action as string;
  stats.actions.push({action,key:command.command_key??null,hash:command.command_sha256??null,nonce:command.request_nonce});
  const checked_at=new Date().toISOString(),day=command.source?.start_date??command.start_date??command.window?.start_date??new Date().toISOString().slice(0,10),{source,encounter}=await projection(day);
  if(action==='open'&&openWorkspace){
   validateCoreCommand(command);
   if(!saved.linked||command.connection_sha256!==connection.connection_sha256||command.appointment_ref!==encounter.appointment.appointment_ref||command.source_sha256!==encounter.source_sha256)return response({detail:'core_connection_changed'},409);
   return response({contract_version:1,action,connection_status:'connected',workspace:openWorkspace(),discovery:{contract_version:'1',action:'encounter',request_nonce:command.request_nonce,checked_at,connection,encounters:[encounter],next_cursor:null}});
  }
  if(action==='connection'||action==='encounters'){
   validateCoreCommand(command);
   return response({contract_version:1,action,connection_status:'connected',discovery:{contract_version:'1',action,request_nonce:command.request_nonce,checked_at,connection,encounters:action==='encounters'?[encounter]:[],next_cursor:null}});
  }
  if(action==='athena_connection'||action==='athena_appointments'){
   validateAthenaCommand(command);
   return response({contract_version:1,action,connection_status:'connected',athena_discovery:{action:action==='athena_connection'?'connection':'appointments',request_nonce:command.request_nonce,checked_at,connection,account,appointments:action==='athena_appointments'?[source]:[],total_count:action==='athena_appointments'?command.offset+1:null,next_offset:null,complete:action==='athena_appointments',truncated:false}});
  }
  if(!action.startsWith('athena_visit_'))return response({detail:'core_connection_unavailable'},404);
  validateAthenaVisitLinkCommand(command);
  const request=command as AthenaVisitLinkCommand,operation=action==='athena_visit_unlink'||action==='athena_visit_unlink_preview'?'unlink':'link';
  const {request_nonce:_nonce,action:_action,...fields}=request;
  const preview=action.endsWith('preview'),plan=preview?'d'.repeat(64):request.plan_sha256??null;
  const digest=await coreDigest({...fields,action:operation,expected_actor_ref:connection.actor_ref,expected_tenant_ref:connection.tenant_ref,...(preview?{plan_sha256:plan,confirmed:true}:{})});
  const base={contract_version:'1',action:action.slice('athena_visit_'.length),request_nonce:request.request_nonce,checked_at,connection,account,
   state:'not_linked',source:request.source?source:null,encounter:null as typeof encounter|null,link_ref:null as string|null,plan_sha256:null as string|null,command_key:request.command_key??null,command_sha256:null as string|null,operation:null as 'link'|'unlink'|null,applied:false};
  if(action==='athena_visit_lookup'){if(saved.linked)Object.assign(base,{state:'linked',encounter,link_ref:fixture.link.response.athena_visit_link.link_ref});}
  else if(preview)Object.assign(base,{state:'ready',encounter,link_ref:operation==='unlink'?request.link_ref:null,plan_sha256:plan,command_sha256:digest,operation});
  else if(action==='athena_visit_status'){
   const prior=ledger.get(request.command_key!);
   if(prior&&prior.hash!==request.command_sha256)return response({detail:'core_connection_changed'},409);
   Object.assign(base,{state:prior?(prior.operation==='unlink'?'removed':'linked'):'not_found',encounter:prior?.operation==='link'?encounter:null,
    link_ref:prior?fixture.link.response.athena_visit_link.link_ref:null,command_sha256:request.command_sha256,operation:prior?.operation??null,applied:!!prior});
  }else{
   const prior=ledger.get(request.command_key!);if(prior&&prior.hash!==digest)return response({detail:'core_connection_changed'},409);
   ledger.set(request.command_key!,{hash:digest,operation});saved.linked=operation==='link';persist();
   Object.assign(base,{state:operation==='link'?'linked':'removed',encounter:operation==='link'?encounter:null,link_ref:fixture.link.response.athena_visit_link.link_ref,plan_sha256:plan,command_sha256:digest,operation,applied:true});
   const scenario=new URLSearchParams(location.search).get('scenario');if(scenario===`athena-lost-${operation}`&&!saved.lost.includes(operation)){saved.lost.push(operation);persist();throw new Error('Invented lost Athena mutation response');}
  }
  return response({contract_version:1,action,connection_status:'connected',athena_visit_link:base});
 };
}
