import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {coreDigest,validateCoreIdentity,type CoreConnection} from './core-connection-contract';

export type AthenaCommand={action:'athena_connection';request_nonce:string;connection_sha256:string}|{action:'athena_appointments';request_nonce:string;connection_sha256:string;account_sha256:string;start_date:string;end_date:string;offset:number};
export type AthenaAccount={account_ref:string;account_sha256:string;department_label:string;department_timezone:string;environment:'preview'|'production';state:'practice_enabled';access:'appointments_read_only'};
export type AthenaAppointment={appointment_ref:string;patient_ref:string;source_local_start:string;department_timezone:string;duration_minutes:number;source_status:'f'|'2'|'3'|'4'|'x';source_sha256:string};
export type AthenaResult={contract_version:1;action:AthenaCommand['action'];connection_status:'connected';athena_discovery:{action:'connection'|'appointments';request_nonce:string;checked_at:string;connection:CoreConnection;account:AthenaAccount|null;appointments:AthenaAppointment[];total_count:number|null;next_offset:number|null;complete:boolean;truncated:boolean}};
const fail=():never=>{throw new WorkspaceApiError(502);};
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const sha=(v:unknown):v is string=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const id=(v:unknown):v is string=>typeof v==='string'&&/^[1-9][0-9]{0,17}$/.test(v);
const integer=(v:unknown,min:number,max:number):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=min&&v<=max;
const day=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&v.slice(0,4)!=='0000'&&!Number.isNaN(Date.parse(v))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;
const local=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d$/.test(v)&&day(v.slice(0,10));
const label=(v:unknown):v is string=>typeof v==='string'&&Array.from(v).length>0&&Array.from(v).length<=200&&!v.includes('\0');
function timezone(v:unknown):v is string{if(typeof v!=='string'||v.length>100)return false;try{new Intl.DateTimeFormat(undefined,{timeZone:v});return true;}catch{return false;}}
export function isAthenaCommand(command:{action:string}):command is AthenaCommand{return ['athena_connection','athena_appointments'].includes(command.action);}

export function validateAthenaCommand(command:AthenaCommand){
  vendorCanonical(command);
  if(!vendorUuid(command.request_nonce)||!sha(command.connection_sha256))return fail();
  if(command.action==='athena_connection'){
    if(!closed(command,'action,request_nonce,connection_sha256'))return fail();
  }else if(command.action==='athena_appointments'){
    if(!closed(command,'action,request_nonce,connection_sha256,account_sha256,start_date,end_date,offset')||!sha(command.account_sha256)||!day(command.start_date)||!day(command.end_date)||!integer(command.offset,0,10000)||Date.parse(command.end_date)<Date.parse(command.start_date)||Date.parse(command.end_date)-Date.parse(command.start_date)>=31*86400000)return fail();
  }else return fail();
}

export async function validateAthenaResult(value:unknown,command:AthenaCommand):Promise<AthenaResult>{
  vendorCanonical(value);
  if(!closed(value,'contract_version,action,connection_status,athena_discovery')||value.contract_version!==1||value.action!==command.action||value.connection_status!=='connected')return fail();
  const d=value.athena_discovery;
  if(!closed(d,'action,request_nonce,checked_at,connection,account,appointments,total_count,next_offset,complete,truncated')||d.action!==(command.action==='athena_connection'?'connection':'appointments')||d.request_nonce!==command.request_nonce||typeof d.checked_at!=='string'||!/(?:Z|[+-]\d{2}:\d{2})$/.test(d.checked_at)||!Number.isFinite(Date.parse(d.checked_at))||Date.parse(d.checked_at)<Date.now()-30000||Date.parse(d.checked_at)>Date.now()+5000||typeof d.complete!=='boolean'||typeof d.truncated!=='boolean')return fail();
  await validateCoreIdentity(d.connection,command.connection_sha256);
  const a=d.account;
  if(a!==null&&(!closed(a,'account_ref,account_sha256,department_label,department_timezone,environment,state,access')||!vendorUuid(a.account_ref)||!sha(a.account_sha256)||!label(a.department_label)||!timezone(a.department_timezone)||!['preview','production'].includes(a.environment as string)||a.state!=='practice_enabled'||a.access!=='appointments_read_only'))return fail();
  if(!Array.isArray(d.appointments)||d.appointments.length>25)return fail();
  if(command.action==='athena_connection'){
    if(d.appointments.length||d.total_count!==null||d.next_offset!==null||d.complete||d.truncated)return fail();
  }else{
    if(!vendorObject(a)||a.account_sha256!==command.account_sha256||!integer(d.total_count,0,1000000))return fail();
    const seen=new Set<string>();
    for(const row of d.appointments){
      if(!closed(row,'appointment_ref,patient_ref,source_local_start,department_timezone,duration_minutes,source_status,source_sha256')||!id(row.appointment_ref)||!id(row.patient_ref)||!local(row.source_local_start)||row.department_timezone!==a.department_timezone||!integer(row.duration_minutes,1,1440)||!['f','2','3','4','x'].includes(row.source_status as string)||!sha(row.source_sha256)||row.source_local_start.slice(0,10)<command.start_date||row.source_local_start.slice(0,10)>command.end_date||seen.has(row.appointment_ref))return fail();
      seen.add(row.appointment_ref);
      const {source_sha256,...content}=row;
      if(await coreDigest({account_sha256:a.account_sha256,...content})!==source_sha256)return fail();
    }
    const after=command.offset+d.appointments.length,more=after<d.total_count,next=more&&after<=10000?after:null;
    if(d.appointments.length&&after>d.total_count||!d.appointments.length&&command.offset<d.total_count||d.next_offset!==next||d.complete!==!more||d.truncated!==(more&&next===null))return fail();
  }
  return value as AthenaResult;
}
