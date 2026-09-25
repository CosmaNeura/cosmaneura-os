import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {SCHEDULING_LOGIN_BUILD,requestSchedulingSession,validGoogleSchedulingUrl,type SchedulingLoginStart} from './scheduling-login-api';
import {vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {coreDigest} from './core-connection-contract';
export const SCHEDULING_ENROLLMENT_BUILD=SCHEDULING_LOGIN_BUILD&&import.meta.env.VITE_WORKSPACE_SCHEDULING_ENROLLMENT_ENABLED==='true';
type Choice={id:string;label:string};type ZonedChoice=Choice&{timezone:string};type VisitChoice=Choice&{duration_minutes:number};
export type SchedulingCatalog={contract_version:'1';practice:Choice;actor_id:string;role:'owner'|'admin'|'staff';practitioner:ZonedChoice|null;locations:ZonedChoice[];appointment_types:VisitChoice[];observed_at:string;catalog_sha256:string};
export type EnrollmentCommand={action:'enrollment_status'|'enrollment_start'|'enrollment_cancel'|'enrollment_review'|'enrollment_confirm'|'enrollment_result';attempt_ref?:string;catalog_sha256?:string;location_id?:string;appointment_type_id?:string;command_key?:string;command_sha256?:string;plan_sha256?:string;confirmed?:true};
export type EnrollmentStatus={state:'not_connected'|'sign_in_pending'|'completing_sign_in'|'choose_schedule'|'setup_required'|'connected'|'review_required';label:string|null;attempt_ref:string|null;catalog:SchedulingCatalog|null;expires_at:string|null};
export type EnrollmentReview={state:'ready';attempt_ref:string;catalog:SchedulingCatalog;location_id:string;appointment_type_id:string;plan_sha256:string;command_key:string;command_sha256:string;expires_at:string};
export type EnrollmentReceipt={state:'connected'|'review_required'|'not_found';attempt_ref:string;command_key:string;command_sha256:string;applied:boolean;label:string|null};
export type EnrollmentResponse=EnrollmentStatus|EnrollmentReview|EnrollmentReceipt|SchedulingLoginStart|{state:'cancelled'};
const fail=():never=>{throw new WorkspaceApiError(502);};
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const sha=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const label=(v:unknown):v is string=>typeof v==='string'&&Array.from(v).length>0&&Array.from(v).length<=120&&!v.includes('\0');
const expiry=(v:unknown):v is string=>typeof v==='string'&&Number.isFinite(Date.parse(v))&&Date.parse(v)>Date.now()&&Date.parse(v)<=Date.now()+610000;
function choice(v:unknown,kind:'plain'|'zoned'|'visit'){
 if(!closed(v,'id,label'+(kind==='zoned'?',timezone':kind==='visit'?',duration_minutes':''))||!vendorUuid(v.id)||!label(v.label))return fail();
 if(kind==='zoned'){if(typeof v.timezone!=='string'||v.timezone.length>64)return fail();try{new Intl.DateTimeFormat(undefined,{timeZone:v.timezone});}catch{return fail();}}
 if(kind==='visit'&&(!Number.isInteger(v.duration_minutes)||(v.duration_minutes as number)<5||(v.duration_minutes as number)>480))return fail();
}
export async function validateSchedulingCatalog(v:unknown):Promise<SchedulingCatalog>{
 vendorCanonical(v);
 if(!closed(v,'contract_version,practice,actor_id,role,practitioner,locations,appointment_types,observed_at,catalog_sha256')||v.contract_version!=='1'||!vendorUuid(v.actor_id)||!['owner','admin','staff'].includes(String(v.role))||typeof v.observed_at!=='string'||!Number.isFinite(Date.parse(v.observed_at))||Date.parse(v.observed_at)<Date.now()-30000||Date.parse(v.observed_at)>Date.now()+5000||!sha(v.catalog_sha256))return fail();
 choice(v.practice,'plain');if(v.practitioner!==null)choice(v.practitioner,'zoned');
 for(const [items,kind] of [[v.locations,'zoned'],[v.appointment_types,'visit']] as const){
  if(!Array.isArray(items)||items.length>50)return fail();const ids=new Set<string>();
  for(const item of items){choice(item,kind);if(ids.has(item.id))return fail();ids.add(item.id);}
 }
 const {catalog_sha256,observed_at:_at,...content}=v;if(await coreDigest(content)!==catalog_sha256)return fail();
 return v as SchedulingCatalog;
}
export function validateEnrollmentCommand(command:EnrollmentCommand){
 const fields:Record<EnrollmentCommand['action'],string[]>={enrollment_status:[],enrollment_start:[],enrollment_cancel:[],enrollment_review:['attempt_ref','catalog_sha256','location_id','appointment_type_id','command_key'],enrollment_confirm:['attempt_ref','catalog_sha256','location_id','appointment_type_id','command_key','plan_sha256','confirmed'],enrollment_result:['attempt_ref','command_key','command_sha256']};
 if(!fields[command.action]||!closed(command,['action',...fields[command.action]].join(',')))return fail();
 for(const name of ['attempt_ref','location_id','appointment_type_id','command_key'] as const)if(command[name]!==undefined&&!vendorUuid(command[name]))return fail();
 for(const name of ['catalog_sha256','command_sha256','plan_sha256'] as const)if(command[name]!==undefined&&!sha(command[name]))return fail();
 if(command.confirmed!==undefined&&command.confirmed!==true)return fail();
}
export async function validateEnrollmentResponse(value:unknown,command:EnrollmentCommand):Promise<EnrollmentResponse>{
 vendorCanonical(value);
 if(command.action==='enrollment_start'){
  if(!closed(value,'authorization_url,expires_at')||!validGoogleSchedulingUrl(value.authorization_url)||!expiry(value.expires_at))return fail();return value as SchedulingLoginStart;
 }
 if(command.action==='enrollment_cancel'){if(!closed(value,'state')||value.state!=='cancelled')return fail();return {state:'cancelled'};}
 if(command.action==='enrollment_status'){
  if(!closed(value,'state,label,attempt_ref,catalog,expires_at')||!['not_connected','sign_in_pending','completing_sign_in','choose_schedule','setup_required','connected','review_required'].includes(String(value.state))||value.attempt_ref!==null&&!vendorUuid(value.attempt_ref)||value.label!==null&&!label(value.label))return fail();
  const active=['sign_in_pending','completing_sign_in','choose_schedule','setup_required'].includes(String(value.state));
  if(active&&(!value.attempt_ref||!expiry(value.expires_at))||!active&&value.expires_at!==null)return fail();
  if(['choose_schedule','setup_required'].includes(String(value.state))){
   const catalog=await validateSchedulingCatalog(value.catalog);const ready=!!catalog.practitioner&&!!catalog.locations.length&&!!catalog.appointment_types.length;
   if((value.state==='choose_schedule')!==ready)return fail();
  }else if(value.catalog!==null)return fail();
  if(value.state==='connected'&&!label(value.label)||value.state!=='connected'&&value.label!==null)return fail();
  return value as EnrollmentStatus;
 }
 if(command.action==='enrollment_review'){
  if(!closed(value,'state,attempt_ref,catalog,location_id,appointment_type_id,plan_sha256,command_key,command_sha256,expires_at')||value.state!=='ready'||value.attempt_ref!==command.attempt_ref||value.location_id!==command.location_id||value.appointment_type_id!==command.appointment_type_id||value.command_key!==command.command_key||!sha(value.plan_sha256)||!sha(value.command_sha256)||!expiry(value.expires_at))return fail();
  const catalog=await validateSchedulingCatalog(value.catalog);
  if(catalog.catalog_sha256!==command.catalog_sha256||!catalog.practitioner||!catalog.locations.some(v=>v.id===command.location_id)||!catalog.appointment_types.some(v=>v.id===command.appointment_type_id)||await coreDigest({...command,action:'enrollment_confirm',plan_sha256:value.plan_sha256,confirmed:true})!==value.command_sha256)return fail();
  return value as EnrollmentReview;
 }
 if(!closed(value,'state,attempt_ref,command_key,command_sha256,applied,label')||!['connected','review_required','not_found'].includes(String(value.state))||value.attempt_ref!==command.attempt_ref||value.command_key!==command.command_key||typeof value.applied!=='boolean'||value.command_sha256!==(command.action==='enrollment_confirm'?await coreDigest(command):command.command_sha256)||value.applied!==(value.state!=='not_found')||value.state==='connected'&&!label(value.label)||value.state!=='connected'&&value.label!==null)return fail();
 return value as EnrollmentReceipt;
}
export async function schedulingEnrollmentRequest(identity:AuthenticatedWorkspaceIdentity,command:EnrollmentCommand,signal?:AbortSignal){
 if(!SCHEDULING_ENROLLMENT_BUILD)throw new WorkspaceApiError(404);validateEnrollmentCommand(command);
 return requestSchedulingSession(identity,command,value=>validateEnrollmentResponse(value,command),signal);
}
