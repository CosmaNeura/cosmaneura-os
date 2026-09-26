import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical,vendorObject} from './vendor-contract';
import {coreDigest,validateCoreCommand,validateCoreIdentity,type CoreConnection,type CoreCursor,type CoreWindow} from './core-connection-contract';

export type AppointmentSetupCommand={action:'appointment_setup_preview'|'appointment_setup_connect';request_nonce:string;connection_sha256:string;window:CoreWindow;cursor?:CoreCursor;plan_sha256?:string};
export type AppointmentSetupResult={contract_version:1;action:AppointmentSetupCommand['action'];connection_status:'connected';appointment_setup:{contract_version:'1';action:'preview'|'connect';request_nonce:string;checked_at:string;connection:CoreConnection;window:CoreWindow;plan_sha256:string;scanned_count:number;eligible_count:number;already_connected_count:number;review_required_count:number;connected_now_count:number;next_cursor:CoreCursor|null}};
const fail=():never=>{throw new WorkspaceApiError(502);};
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const sha=(v:unknown)=>typeof v==='string'&&/^[0-9a-f]{64}$/.test(v);
const count=(v:unknown):v is number=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0&&v<=25;
const local=(v:string)=>/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?$/.test(v);
export const isAppointmentSetupCommand=(c:{action:string}):c is AppointmentSetupCommand=>['appointment_setup_preview','appointment_setup_connect'].includes(c.action);

export async function validateAppointmentSetupCommand(command:AppointmentSetupCommand){
  vendorCanonical(command);
  const connect=command.action==='appointment_setup_connect';
  if(!isAppointmentSetupCommand(command)||!closed(command,'action,request_nonce,connection_sha256,window'+(command.cursor?',cursor':'')+(connect?',plan_sha256':''))||connect&&!sha(command.plan_sha256))return fail();
  validateCoreCommand({action:'encounters',request_nonce:command.request_nonce,connection_sha256:command.connection_sha256,window:command.window,...(command.cursor?{cursor:command.cursor}:{})});
  if(command.cursor&&(command.cursor.connection_sha256!==command.connection_sha256||command.cursor.window_sha256!==await coreDigest(command.window)||!local(command.cursor.appointment_date)||command.cursor.appointment_date.slice(0,10)<command.window.start_date||command.cursor.appointment_date.slice(0,10)>=command.window.end_date))return fail();
  if(new TextEncoder().encode(JSON.stringify(command)).length>2048)return fail();
}

export async function validateAppointmentSetupResult(value:unknown,command:AppointmentSetupCommand):Promise<AppointmentSetupResult>{
  vendorCanonical(value);
  if(!closed(value,'contract_version,action,connection_status,appointment_setup')||value.contract_version!==1||value.action!==command.action||value.connection_status!=='connected')return fail();
  const d=value.appointment_setup,connect=command.action==='appointment_setup_connect';
  if(!closed(d,'contract_version,action,request_nonce,checked_at,connection,window,plan_sha256,scanned_count,eligible_count,already_connected_count,review_required_count,connected_now_count,next_cursor')||d.contract_version!=='1'||d.action!==(connect?'connect':'preview')||d.request_nonce!==command.request_nonce||!sha(d.plan_sha256)||connect&&d.plan_sha256!==command.plan_sha256||typeof d.checked_at!=='string'||!/(?:Z|[+-]\d{2}:\d{2})$/.test(d.checked_at)||!Number.isFinite(Date.parse(d.checked_at))||Date.parse(d.checked_at)<Date.now()-30000||Date.parse(d.checked_at)>Date.now()+5000)return fail();
  await validateCoreIdentity(d.connection,command.connection_sha256);
  if(!closed(d.window,'start_date,end_date')||d.window.start_date!==command.window.start_date||d.window.end_date!==command.window.end_date||![d.scanned_count,d.eligible_count,d.already_connected_count,d.review_required_count,d.connected_now_count].every(count))return fail();
  const result=value as AppointmentSetupResult,s=result.appointment_setup;
  if(s.scanned_count!==s.eligible_count+s.already_connected_count+s.review_required_count||s.connected_now_count!==(connect?s.eligible_count:0))return fail();
  if(s.next_cursor!==null){
    await validateAppointmentSetupCommand({action:'appointment_setup_preview',request_nonce:command.request_nonce,connection_sha256:command.connection_sha256,window:command.window,cursor:s.next_cursor});
    const key=(c:CoreCursor)=>c.appointment_date.slice(0,19)+'.'+(c.appointment_date.split('.')[1]??'').padEnd(6,'0')+'|'+c.appointment_ref;
    if(s.scanned_count!==25||command.cursor&&key(s.next_cursor)<=key(command.cursor))return fail();
  }
  if(new TextEncoder().encode(JSON.stringify(d)).length>4096)return fail();
  return result;
}
