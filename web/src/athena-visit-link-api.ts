import {WorkspaceApiError,WORKSPACE_BUILD,WORKSPACE_AUTHENTICATED_BUILD} from './workspace-api';
import {vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {coreDigest,validateCoreIdentity,validateCoreConnection,type CoreConnection,type CoreEncounter} from './core-connection-contract';
import {validateAthenaCommand,validateAthenaResult,type AthenaAccount,type AthenaAppointment} from './athena-connection-contract';

export const ATHENA_VISIT_LINK_BUILD=WORKSPACE_BUILD&&WORKSPACE_AUTHENTICATED_BUILD&&import.meta.env.VITE_ATHENA_CONNECTION_ENABLED==='true'&&import.meta.env.VITE_ATHENA_VISIT_LINK_ENABLED==='true';
export type AthenaSourceSelection={start_date:string;end_date:string;offset:number;appointment_ref:string;source_sha256:string};
type Action='lookup'|'preview'|'link'|'status'|'unlink_preview'|'unlink';
export type AthenaVisitLinkCommand={action:`athena_visit_${Action}`;request_nonce:string;connection_sha256:string;account_sha256:string;
 source?:AthenaSourceSelection;appointment_ref?:string;core_source_sha256?:string;link_ref?:string;plan_sha256?:string;command_key?:string;command_sha256?:string;confirmed?:true};
export type AthenaVisitLinkObservation={contract_version:'1';action:Action;request_nonce:string;checked_at:string;connection:CoreConnection;account:AthenaAccount;
 state:'not_linked'|'ready'|'linked'|'removed'|'review_required'|'not_found';source:AthenaAppointment|null;encounter:CoreEncounter|null;link_ref:string|null;
 plan_sha256:string|null;command_key:string|null;command_sha256:string|null;operation:'link'|'unlink'|null;applied:boolean};
export type AthenaVisitLinkResult={contract_version:1;action:AthenaVisitLinkCommand['action'];connection_status:'connected';athena_visit_link:AthenaVisitLinkObservation};
const fail=():never=>{throw new WorkspaceApiError(502);};
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>vendorObject(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',');
const sha=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const ref=(value:unknown,prefix:string):value is string=>typeof value==='string'&&new RegExp('^'+prefix+'_[0-7][0-9a-hjkmnp-tv-z]{25}$').test(value);
const actions=['lookup','preview','link','status','unlink_preview','unlink'];
const action=(command:AthenaVisitLinkCommand)=>command.action.slice('athena_visit_'.length) as Action;
export function isAthenaVisitLinkCommand(value:{action:string}):value is AthenaVisitLinkCommand{return value.action.startsWith('athena_visit_')&&actions.includes(value.action.slice('athena_visit_'.length));}
export function validateAthenaVisitLinkCommand(command:AthenaVisitLinkCommand){
 vendorCanonical(command);
 const fields:Record<Action,string[]>={lookup:['source'],preview:['source','appointment_ref','core_source_sha256','command_key'],link:['source','appointment_ref','core_source_sha256','command_key','plan_sha256','confirmed'],status:['command_key','command_sha256'],unlink_preview:['link_ref','command_key'],unlink:['link_ref','command_key','plan_sha256','confirmed']};
 const needed=fields[action(command)];
 if(!needed||!closed(command,['action','request_nonce','connection_sha256','account_sha256',...needed].join(','))||!vendorUuid(command.request_nonce)||!sha(command.connection_sha256)||!sha(command.account_sha256))return fail();
 if(command.command_key!==undefined&&!vendorUuid(command.command_key)||command.plan_sha256!==undefined&&!sha(command.plan_sha256)||command.command_sha256!==undefined&&!sha(command.command_sha256)||command.core_source_sha256!==undefined&&!sha(command.core_source_sha256)||command.confirmed!==undefined&&command.confirmed!==true||command.appointment_ref!==undefined&&!ref(command.appointment_ref,'appointment')||command.link_ref!==undefined&&!ref(command.link_ref,'athena_visit_link'))return fail();
 if(command.source){
  if(!closed(command.source,'start_date,end_date,offset,appointment_ref,source_sha256')||!sha(command.source.source_sha256)||!/^[1-9][0-9]{0,17}$/.test(command.source.appointment_ref))return fail();
  validateAthenaCommand({action:'athena_appointments',request_nonce:command.request_nonce,connection_sha256:command.connection_sha256,account_sha256:command.account_sha256,start_date:command.source.start_date,end_date:command.source.end_date,offset:command.source.offset});
 }
 if(new TextEncoder().encode(JSON.stringify(command)).length>2048)return fail();
}
async function digestCommand(command:AthenaVisitLinkCommand,c:CoreConnection,plan?:string){
 const {request_nonce:_nonce,action:original,...values}=command;
 return coreDigest({...values,expected_tenant_ref:c.tenant_ref,expected_actor_ref:c.actor_ref,
  action:original==='athena_visit_preview'?'link':original==='athena_visit_unlink_preview'?'unlink':action(command),
  ...(plan?{plan_sha256:plan,confirmed:true}:{})});
}

export async function validateAthenaVisitLinkResult(value:unknown,command:AthenaVisitLinkCommand):Promise<AthenaVisitLinkResult>{
 vendorCanonical(value);
 if(!closed(value,'contract_version,action,connection_status,athena_visit_link')||value.contract_version!==1||value.action!==command.action||value.connection_status!=='connected')return fail();
 const d=value.athena_visit_link;
 if(!closed(d,'contract_version,action,request_nonce,checked_at,connection,account,state,source,encounter,link_ref,plan_sha256,command_key,command_sha256,operation,applied')||d.contract_version!=='1'||d.action!==action(command)||d.request_nonce!==command.request_nonce||typeof d.applied!=='boolean'||!['not_linked','ready','linked','removed','review_required','not_found'].includes(String(d.state))||d.command_key!==(command.command_key??null)||d.plan_sha256!==null&&!sha(d.plan_sha256)||d.command_sha256!==null&&!sha(d.command_sha256)||d.link_ref!==null&&!ref(d.link_ref,'athena_visit_link')||d.operation!==null&&!['link','unlink'].includes(String(d.operation)))return fail();
 await validateCoreIdentity(d.connection,command.connection_sha256);
 const c=d.connection as CoreConnection;
 // Reuse the established account and encounter validators for these nested views.
 const wrapper={contract_version:1,action:'athena_connection',connection_status:'connected',athena_discovery:{action:'connection',request_nonce:d.request_nonce,checked_at:d.checked_at,connection:c,account:d.account,appointments:[],total_count:null,next_offset:null,complete:false,truncated:false}};
 await validateAthenaResult(wrapper,{action:'athena_connection',request_nonce:command.request_nonce,connection_sha256:command.connection_sha256});
 if(!vendorObject(d.account)||d.account.account_sha256!==command.account_sha256)return fail();
 if(d.source!==null){
  if(!command.source||!vendorObject(d.source)||d.source.appointment_ref!==command.source.appointment_ref||d.source.source_sha256!==command.source.source_sha256)return fail();
  await validateAthenaResult({...wrapper,action:'athena_appointments',athena_discovery:{...wrapper.athena_discovery,action:'appointments',appointments:[d.source],total_count:command.source.offset+1,complete:true}},
   {action:'athena_appointments',request_nonce:command.request_nonce,connection_sha256:command.connection_sha256,account_sha256:command.account_sha256,start_date:command.source.start_date,end_date:command.source.end_date,offset:command.source.offset});
 }
 if(d.encounter!==null){
  const e=d.encounter;
  if(!vendorObject(e)||!vendorObject(e.appointment)||typeof e.appointment.appointment_ref!=='string'||typeof e.source_sha256!=='string')return fail();
  await validateCoreConnection({contract_version:1,action:'encounter',connection_status:'connected',discovery:{contract_version:'1',action:'encounter',request_nonce:d.request_nonce,checked_at:d.checked_at,connection:c,encounters:[e],next_cursor:null}},
   {action:'encounter',request_nonce:command.request_nonce,connection_sha256:command.connection_sha256,appointment_ref:e.appointment.appointment_ref,source_sha256:e.source_sha256});
 }
 const result=d as unknown as AthenaVisitLinkObservation,a=action(command);
 if(a==='link'||a==='unlink'||a==='status'){
  const expected=a==='status'?command.command_sha256:await digestCommand(command,c);
  if(result.command_sha256!==expected)return fail();
  if(result.applied){if(!result.link_ref||!result.operation||!['linked','removed','review_required'].includes(result.state)||a!=='status'&&result.operation!==a)return fail();}
  else if(a!=='status'||result.state!=='not_found'||result.operation!==null||result.link_ref!==null||result.encounter!==null)return fail();
  if(a==='unlink'&&(result.state!=='removed'||result.link_ref!==command.link_ref))return fail();
  // A direct save must return the exact visit reviewed, not just its command receipt.
  if(a==='link'&&result.state==='linked'&&(!result.encounter||result.encounter.appointment.appointment_ref!==command.appointment_ref||result.encounter.source_sha256!==command.core_source_sha256))return fail();
 }else{
  if(result.applied)return fail();
  if(a==='lookup'){
   if(!['linked','not_linked','review_required'].includes(result.state)||result.source===null||result.plan_sha256!==null||result.command_sha256!==null||result.operation!==null)return fail();
  }else if(result.state==='ready'||result.state==='removed'){
   if(!result.plan_sha256||result.command_sha256!==await digestCommand(command,c,result.plan_sha256)||result.operation!==(a==='preview'?'link':'unlink'))return fail();
   if(a==='preview'&&(result.source===null||!result.encounter||result.encounter.appointment.appointment_ref!==command.appointment_ref||result.encounter.source_sha256!==command.core_source_sha256))return fail();
   if(a==='unlink_preview'&&result.link_ref!==command.link_ref)return fail();
  }else if(a!=='preview'||result.state!=='review_required'||result.plan_sha256!==null||result.command_sha256!==null)return fail();
 }
 if(result.state==='linked'&&(!result.link_ref||!result.encounter))return fail();
 return value as AthenaVisitLinkResult;
}
