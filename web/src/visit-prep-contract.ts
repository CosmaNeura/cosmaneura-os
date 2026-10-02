import schema from './visit-prep-result.schema.json';
import {vendorObject,vendorUuid} from './vendor-contract';
import {WorkspaceApiError} from './workspace-api';

export type Topic={question_key:string;prompt:string;kind:'story'|'list'|'choice';position:number;choices:{value:string;label:string}[];
  response_kind:'answered'|'skipped'|null;answer:string|null;initial_response_kind:'answered'|'skipped'|null;initial_answer:string|null;
  changed:boolean;original_response_id:string|null;additional_answer_source_id:string|null;current_revision_id:string|null;
  recorded_at:string|null;initial_recorded_at:string|null;explanation_words:string|null;explanation_source_id:string|null;explanation_recorded_at:string|null};
export type BriefItem={text:string;evidence:{source_ref:string;quote:string}[]};
export type VisitPrepReceipt={contract_version:'1';preparation_ref:string;connection_sha256:string;workspace_id:string;request_nonce:string;checked_at:string;
  package:{contract:'visit_prep.patient_synthesis.v1';status:'ready'|'missing'|'stale';build_status:string;version:number|null;recorded_at:string|null;
    sources:{package_id:string;source_version:string;actor_role:'patient'|'caregiver';current_answers_complete:boolean;current_answers_reviewed:boolean;
      missing_question_keys:string[];skipped_question_keys:string[];topics:Topic[];preparation:{id:string;patient_id:string|null;appointment_id:string|null;
        physician_display_name:string;practice_display_name:string;scheduled_at:string;timezone_name:string}};
    brief:({headline:BriefItem|null}&Record<'summary'|'visit_priorities'|'medication_and_adherence'|'barriers'|'uncertainties',BriefItem[]>)|null}};
export type VisitPrepCommand={preparation_ref:string;connection_sha256:string;workspace_id:string;request_nonce:string;bot:{address:string;team_revision:number}};
type Rule={$ref?:string;type?:string|string[];const?:unknown;enum?:unknown[];anyOf?:Rule[];allOf?:Rule[];if?:Rule;then?:Rule;else?:Rule;
  properties?:Record<string,Rule>;required?:string[];additionalProperties?:boolean;items?:Rule;minItems?:number;maxItems?:number;uniqueItems?:boolean;
  minLength?:number;maxLength?:number;minimum?:number;maximum?:number;pattern?:string;format?:string};
const fail=():never=>{throw new WorkspaceApiError(502);};
function valid(r:Rule,v:unknown,depth=0):boolean {
  if(!r||depth>30)return false;
  if(r.$ref)return valid((schema.$defs as Record<string,Rule>)[r.$ref.split('/').at(-1)!],v,depth+1);
  if(r.anyOf&&!r.anyOf.some(branch=>valid(branch,v,depth+1))||r.allOf&&!r.allOf.every(branch=>valid(branch,v,depth+1)))return false;
  if(r.if&&!valid(valid(r.if,v,depth+1)?r.then??{}:r.else??{},v,depth+1))return false;
  if(Object.hasOwn(r,'const')&&v!==r.const||r.enum&&!r.enum.includes(v))return false;
  const types=r.type===undefined?[]:Array.isArray(r.type)?r.type:[r.type];
  const type=v===null?'null':Array.isArray(v)?'array':typeof v==='number'?'integer':typeof v;
  if(types.length&&!types.includes(type))return false;
  if(typeof v==='number'&&(!Number.isSafeInteger(v)||v<(r.minimum??0)||v>(r.maximum??Number.MAX_SAFE_INTEGER)))return false;
  if(typeof v==='string'){
    const n=[...v].length;
    if(n<(r.minLength??0)||n>(r.maxLength??Infinity)||v.includes('\0')||/[\uD800-\uDFFF]/u.test(v)||
      r.pattern&&!new RegExp(r.pattern,'u').test(v)||r.format==='uuid'&&!vendorUuid(v)||
      r.format==='date-time'&&(!/(?:Z|[+-]\d\d:\d\d)$/.test(v)||!Number.isFinite(Date.parse(v))))return false;
  }
  if(Array.isArray(v)&&(v.length<(r.minItems??0)||v.length>(r.maxItems??Infinity)||
    r.uniqueItems&&new Set(v.map(item=>JSON.stringify(item))).size!==v.length||r.items&&!v.every(item=>valid(r.items!,item,depth+1))))return false;
  if(vendorObject(v)&&(r.required?.some(key=>!Object.hasOwn(v,key))||
    r.additionalProperties===false&&Object.keys(v).some(key=>!Object.hasOwn(r.properties??{},key))||
    Object.entries(v).some(([key,item])=>r.properties?.[key]&&!valid(r.properties[key],item,depth+1))))return false;
  return true;
}
export function validateVisitPrep(value:unknown,command:VisitPrepCommand):VisitPrepReceipt {
  if(!valid(schema as Rule,value))return fail();
  const v=value as VisitPrepReceipt,p=v.package,s=p.sources;
  if(v.preparation_ref!==command.preparation_ref||v.connection_sha256!==command.connection_sha256||
    v.workspace_id!==command.workspace_id||v.request_nonce!==command.request_nonce||s.package_id!==v.preparation_ref||s.preparation.id!==s.package_id||
    Date.parse(v.checked_at)<Date.now()-30000||Date.parse(v.checked_at)>Date.now()+5000)return fail();
  const keys=s.topics.map(t=>t.question_key),positions=s.topics.map(t=>t.position);
  if(new Set(keys).size!==keys.length||positions.some((pos,i)=>i>0&&pos<=positions[i-1])||
    JSON.stringify(s.missing_question_keys)!==JSON.stringify(s.topics.filter(t=>t.response_kind===null).map(t=>t.question_key))||
    JSON.stringify(s.skipped_question_keys)!==JSON.stringify(s.topics.filter(t=>t.response_kind==='skipped').map(t=>t.question_key)))return fail();
  const evidence=new Map<string,string>();
  for(const t of s.topics){
    if((t.response_kind==='answered')!==(t.answer!==null))return fail();
    if(t.response_kind==='answered'){
      const ref=t.current_revision_id??t.additional_answer_source_id??t.original_response_id;
      const labels=t.choices.filter(c=>c.value===t.answer),words=t.kind==='choice'?labels[0]?.label:t.answer;
      if(!ref||!words||t.kind==='choice'&&labels.length!==1)return fail();
      evidence.set(ref,words);
    }
    if(t.explanation_source_id&&t.explanation_words)evidence.set(t.explanation_source_id,t.explanation_words);
  }
  if(p.brief)for(const item of [...(p.brief.headline?[p.brief.headline]:[]),...p.brief.summary,...p.brief.visit_priorities,
    ...p.brief.medication_and_adherence,...p.brief.barriers,...p.brief.uncertainties]){
    if(item.evidence.some(e=>!evidence.get(e.source_ref)?.includes(e.quote)))return fail();
  }
  return v;
}
