import {WorkspaceApiError} from './workspace-api';
import {vendorObject,vendorUuid} from './vendor-contract';
import {validModelUsage} from './team-setup-validators';
import {teamAddress,teamText,type ModelUsage} from './team-setup-request';
import {modelTime,validAdmission,type AdmissionObservation} from './model-work-request';

export type ActivityView='attention'|'recent';
export type AiActivityContext={box_id:string;owner_id:string;recovery_scope:string};
export type AiActivitySelection={workspace_id:string;appointment_id:string;entry_id:string};
export type ActivityRow={kind:'conversation'|'private_handoff';bot:{address:string;agent_id:string;role:'scribe'|'visit_prep'|'follow_up'|'chief'|'custom'|'research';name:string;team_revision:number};encounter:AiActivitySelection&{label:string;starts_at:string|null;source_local_start?:string|null};admission:AdmissionObservation};
export type ModelActivityPage=AiActivityContext&{contract_version:1|2;view:ActivityView;as_of:string;
  page:{limit:20;cursor:string|null;next_cursor:string|null;has_more:boolean};
  coverage:{rows:'durable_admissions_only';paging:'live_current_access';attention_total:number;recent_total:number;withheld_total:number;legacy_rows_included:false};
  usage:ModelUsage;rows:ActivityRow[]};
export const ACTIVITY_RESPONSE_BYTES=65536,ACTIVITY_ERROR_BYTES=1024,ACTIVITY_DEADLINE_MS=15000;
export const validActivityCursor=(value:unknown):value is string=>typeof value==='string'&&/^a1[0-9a-f]{128}$/.test(value);
const invalid=():never=>{throw new WorkspaceApiError(502);};
export function activityClosed(value:unknown,keys:string):value is Record<string,any>{
  return vendorObject(value)&&Object.keys(value).sort().join(',')===keys.split(',').sort().join(',')&&
    Reflect.ownKeys(value).length===Object.keys(value).length&&Object.values(Object.getOwnPropertyDescriptors(value)).every(p=>'value'in p&&p.enumerable);
}
export function validActivityContext(value:unknown):value is AiActivityContext{
  return activityClosed(value,'box_id,owner_id,recovery_scope')&&vendorUuid(value.box_id)&&vendorUuid(value.owner_id)&&typeof value.recovery_scope==='string'&&/^[a-f0-9]{64}$/.test(value.recovery_scope);
}
const localTime=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?$/.test(v)&&modelTime(v+'Z');
const count=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>=0&&Number(v)<=999999999999;
const positive=(v:unknown):v is number=>Number.isSafeInteger(v)&&Number(v)>=1;
// PostgreSQL timestamps include microseconds. Date.parse alone loses their order.
const instant=(value:string):bigint=>{
  const fraction=value.match(/\.(\d+)(?=Z|[+-]\d\d:\d\d$)/)?.[1]??'';
  if(fraction.length>9)throw new Error('Invalid precision');
  const whole=value.replace(/\.\d+(?=Z|[+-]\d\d:\d\d$)/,'');
  return BigInt(Date.parse(whole))*1000000n+BigInt(fraction.padEnd(9,'0'));
};
const usageKeys='contract_version,policy,team_revision,as_of,window_start,admitted_units,occupied_units,remaining_units,pending_units,unknown_units,verified_input_tokens,verified_output_tokens,usage_complete,coverage';
const admissionKeys='id,state,unit,admitted_at,dispatch,usage,input_tokens,output_tokens';
export function validateModelActivity(value:unknown,context:AiActivityContext,view:ActivityView,cursor:string|null=null):ModelActivityPage{
  try{
    if(!validActivityContext(context)||!['attention','recent'].includes(view)||cursor!==null&&!validActivityCursor(cursor)||
      !activityClosed(value,'contract_version,box_id,owner_id,recovery_scope,view,as_of,page,coverage,usage,rows')||![1,2].includes(value.contract_version)||value.view!==view||
      value.box_id!==context.box_id||value.owner_id!==context.owner_id||value.recovery_scope!==context.recovery_scope||!modelTime(value.as_of))return invalid();
    const p=value.page,c=value.coverage,u=value.usage;
    if(!activityClosed(p,'limit,cursor,next_cursor,has_more')||p.limit!==20||p.cursor!==cursor||typeof p.has_more!=='boolean'||p.next_cursor!==null&&!validActivityCursor(p.next_cursor)||
      p.has_more!==(p.next_cursor!==null)||p.next_cursor!==null&&p.next_cursor===cursor||
      !activityClosed(c,'rows,paging,attention_total,recent_total,withheld_total,legacy_rows_included')||c.rows!=='durable_admissions_only'||c.paging!=='live_current_access'||c.legacy_rows_included!==false||
      ![c.attention_total,c.recent_total,c.withheld_total].every(count)||!activityClosed(u,usageKeys)||u.policy!==null&&!activityClosed(u.policy,'version,max_attempts_per_24h')||!validModelUsage(u)||instant(u.as_of)!==instant(value.as_of))return invalid();
    for(const key of ['team_revision','admitted_units','occupied_units','pending_units','unknown_units'] as const)if(!count(u[key]))return invalid();
    for(const key of ['remaining_units','verified_input_tokens','verified_output_tokens'] as const)if(u[key]!==null&&!count(u[key]))return invalid();
    if(!Array.isArray(value.rows)||value.rows.length>20||p.has_more&&value.rows.length!==20||value.rows.length>c[view==='attention'?'attention_total':'recent_total'])return invalid();
    if(Reflect.ownKeys(value.rows).length!==value.rows.length+1||Object.values(Object.getOwnPropertyDescriptors(value.rows)).some(p=>!('value'in p)))return invalid();
    const ids=new Set<string>();let previous:{time:bigint;id:string}|undefined;
    for(const row of value.rows){
      if(!activityClosed(row,'kind,bot,encounter,admission')||!['conversation','private_handoff'].includes(row.kind)||!activityClosed(row.admission,admissionKeys)||!validAdmission(row.admission)||
        ids.has(row.admission.id)||instant(row.admission.admitted_at)>instant(value.as_of)||(['reserved','running','unknown'].includes(row.admission.state))!==(view==='attention'))return invalid();
      ids.add(row.admission.id);
      const current={time:instant(row.admission.admitted_at),id:row.admission.id};
      if(previous){const direction=current.time<previous.time?-1:current.time>previous.time?1:current.id<previous.id?-1:current.id>previous.id?1:0;
        if(view==='attention'?direction<0:direction>0)return invalid();}
      previous=current;
      const b=row.bot,e=row.encounter;
      if(!activityClosed(b,'address,agent_id,role,name,team_revision')||!teamAddress(b.address)||!vendorUuid(b.agent_id)||!['scribe','visit_prep','follow_up','chief','custom','research'].includes(b.role)||!teamText(b.name,40,1)||!positive(b.team_revision)||
        !activityClosed(e,'workspace_id,appointment_id,label,starts_at,entry_id'+(value.contract_version===2?',source_local_start':''))||!vendorUuid(e.workspace_id)||!vendorUuid(e.appointment_id)||!vendorUuid(e.entry_id)||!teamText(e.label,200,1)||!(modelTime(e.starts_at)&&(value.contract_version===1||e.source_local_start===null)||value.contract_version===2&&e.starts_at===null&&localTime(e.source_local_start)))return invalid();
    }
    return structuredClone(value) as ModelActivityPage;
  }catch{return invalid();}
}
