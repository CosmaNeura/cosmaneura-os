import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical,vendorObject,vendorSha256,vendorUuid} from './vendor-contract';

export type CoreConnection={actor_ref:string;tenant_ref:string;provider_link_ref:string;practice_ref:string;practice_label:string;review_sha256:string;connection_sha256:string};
export type CoreEncounter={connection_sha256:string;patient:{patient_ref:string;display_name:string};appointment:{appointment_ref:string;patient_ref:string;appointment_date:string;timezone_known:boolean};source_sha256:string};
export type CoreWindow={start_date:string;end_date:string};
export type CoreCursor={window_sha256:string;connection_sha256:string;appointment_date:string;appointment_ref:string};
export type CoreConnectionCommand={action:'connection'|'connect'|'encounters'|'encounter'|'open';request_nonce:string;connection_sha256?:string;window?:CoreWindow;cursor?:CoreCursor;appointment_ref?:string;source_sha256?:string};
export type CoreConnectionResult={contract_version:1;action:CoreConnectionCommand['action'];connection_status:'connected'|'ready_to_connect'|'review_required';workspace?:{workspace_id:string;appointment_id:string};discovery:{contract_version:'1';action:'connection'|'encounters'|'encounter';request_nonce:string;checked_at:string;connection:CoreConnection;encounters:CoreEncounter[];next_cursor:CoreCursor|null}};
const fail=():never=>{throw new WorkspaceApiError(502);};
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const ref=(v:unknown,prefix:string)=>typeof v==='string'&&new RegExp('^'+prefix+'_[0-7][0-9a-hjkmnp-tv-z]{25}$').test(v);
const sha=(v:unknown)=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const label=(v:unknown)=>typeof v==='string'&&Array.from(v).length>0&&Array.from(v).length<=200&&!v.includes('\0');
export const coreDigest=(v:unknown)=>vendorSha256(new TextEncoder().encode(vendorCanonical(v)));
const without=(v:Record<string,unknown>,key:string)=>Object.fromEntries(Object.entries(v).filter(([k])=>k!==key));
const day=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&v.slice(0,4)!=='0000'&&!Number.isNaN(Date.parse(v))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
const stamp=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$/.test(v)&&day(v.slice(0,10))&&!Number.isNaN(Date.parse(v));
const aware=(v:string)=>/(?:Z|[+-]\d{2}:\d{2})$/.test(v);

export function validateCoreCommand(command:CoreConnectionCommand){
  vendorCanonical(command);
  if(!vendorUuid(command.request_nonce))return fail();
  const required={connection:['action','request_nonce'],connect:['action','request_nonce','connection_sha256'],encounters:['action','request_nonce','connection_sha256','window'],encounter:['action','request_nonce','connection_sha256','appointment_ref','source_sha256'],open:['action','request_nonce','connection_sha256','appointment_ref','source_sha256']}[command.action];
  if(!required||!closed(command,[...required,...(command.action==='encounters'&&command.cursor?['cursor']:[])].join(',')))return fail();
  if(command.action!=='connection'&&!sha(command.connection_sha256))return fail();
  if(['encounter','open'].includes(command.action)&&(!ref(command.appointment_ref,'appointment')||!sha(command.source_sha256)))return fail();
  if(command.window&&(!closed(command.window,'start_date,end_date')||!day(command.window.start_date)||!day(command.window.end_date)||Date.parse(command.window.end_date)-Date.parse(command.window.start_date)<86400000||Date.parse(command.window.end_date)-Date.parse(command.window.start_date)>31*86400000))return fail();
  if(command.cursor)validateCursor(command.cursor);
  if(new TextEncoder().encode(JSON.stringify(command)).length>2048)return fail();
}
function validateCursor(v:unknown):asserts v is CoreCursor{
  if(!closed(v,'window_sha256,connection_sha256,appointment_date,appointment_ref')||!sha(v.window_sha256)||!sha(v.connection_sha256)||!stamp(v.appointment_date)||!ref(v.appointment_ref,'appointment'))return fail();
}
export async function validateCoreIdentity(c:unknown,expected?:string):Promise<void>{
  if(!closed(c,'actor_ref,tenant_ref,provider_link_ref,practice_ref,practice_label,review_sha256,connection_sha256')||!ref(c.actor_ref,'authority_actor')||!ref(c.tenant_ref,'authority_tenant')||!ref(c.provider_link_ref,'scribe_provider_link')||!ref(c.practice_ref,'practice')||!label(c.practice_label)||!sha(c.review_sha256)||!sha(c.connection_sha256)||await coreDigest(without(c,'connection_sha256'))!==c.connection_sha256||expected!==undefined&&expected!==c.connection_sha256)return fail();
}
export async function validateCoreConnection(value:unknown,command:CoreConnectionCommand):Promise<CoreConnectionResult>{
  vendorCanonical(value);
  if(!closed(value,'contract_version,action,connection_status,discovery'+(command.action==='open'?',workspace':''))||value.contract_version!==1||value.action!==command.action||!['connected','ready_to_connect','review_required'].includes(value.connection_status as string))return fail();
  if(command.action==='open'&&(!closed(value.workspace,'workspace_id,appointment_id')||!vendorUuid(value.workspace.workspace_id)||!vendorUuid(value.workspace.appointment_id)))return fail();
  const d=value.discovery;
  if(!closed(d,'contract_version,action,request_nonce,checked_at,connection,encounters,next_cursor')||d.contract_version!=='1'||d.action!==(command.action==='connect'?'connection':command.action==='open'?'encounter':command.action)||d.request_nonce!==command.request_nonce||!stamp(d.checked_at)||!aware(d.checked_at)||Date.parse(d.checked_at)<Date.now()-30000||Date.parse(d.checked_at)>Date.now()+5000)return fail();
  const c=d.connection;
  await validateCoreIdentity(c,command.connection_sha256);
  if(!vendorObject(c))return fail();
  if(!Array.isArray(d.encounters)||d.encounters.length>25||d.action==='connection'&&d.encounters.length||d.action==='encounter'&&d.encounters.length!==1)return fail();
  const refs=new Set<string>();
  for(const entry of d.encounters){
    if(!closed(entry,'connection_sha256,patient,appointment,source_sha256')||entry.connection_sha256!==c.connection_sha256||!sha(entry.source_sha256))return fail();
    const p=entry.patient,a=entry.appointment;
    if(!closed(p,'patient_ref,display_name')||!ref(p.patient_ref,'patient')||!label(p.display_name)||!closed(a,'appointment_ref,patient_ref,appointment_date,timezone_known')||!ref(a.appointment_ref,'appointment')||a.patient_ref!==p.patient_ref||!stamp(a.appointment_date)||typeof a.timezone_known!=='boolean'||a.timezone_known!==aware(a.appointment_date))return fail();
    if(refs.has(a.appointment_ref as string)||command.window&&(a.appointment_date.slice(0,10)<command.window.start_date||a.appointment_date.slice(0,10)>=command.window.end_date))return fail();
    refs.add(a.appointment_ref as string);
    if(await coreDigest(without(entry,'source_sha256'))!==entry.source_sha256)return fail();
    if(['encounter','open'].includes(command.action)&&(a.appointment_ref!==command.appointment_ref||entry.source_sha256!==command.source_sha256))return fail();
  }
  if(d.next_cursor!==null){
    validateCursor(d.next_cursor);
    if(command.action!=='encounters'||!command.window||d.next_cursor.connection_sha256!==c.connection_sha256||d.next_cursor.window_sha256!==await coreDigest(command.window))return fail();
  }
  if(command.action!=='connection'&&value.connection_status!=='connected')return fail();
  return value as CoreConnectionResult;
}
