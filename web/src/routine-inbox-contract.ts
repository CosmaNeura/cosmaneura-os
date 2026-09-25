import {WorkspaceApiError} from './workspace-api';

export type IncomingBriefItem={ticket_id:string;revision_id:string;payload_hash:string;version:number;
  state:'pending_approval'|'approved'|'closed'|'rejected'|'source_unavailable'|'work_changed';body:string|null;due_date:string|null;
  responsible:{id:string;name:string;available:boolean};originator_id:string;requires_owner_attention:boolean;
  pending_offer:boolean;ready_for_review:boolean;verified_current:boolean;publication_receipt_id:string|null;
  result_receipt_id:string|null;verification_receipt_id:string|null;changed_since_report:boolean};
export type IncomingBriefCounts={pending_approval:number;open:number;overdue:number;awaiting_acceptance:number;
  responsible_unavailable:number;awaiting_review:number;verified_complete:number;source_unavailable:number;work_changed:number};
export type IncomingBriefSection={coverage:'complete'|'partial'|'unavailable'|'not_included';
  reason:'source_unavailable'|'work_changed'|'collection_limit'|'legacy_report'|null;items:IncomingBriefItem[];
  matching_items:number;counts:IncomingBriefCounts|null;withheld_sources:boolean};
const closed=(v:unknown,keys:string):v is Record<string,any>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const id=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const n=(v:unknown,max=100):v is number=>Number.isSafeInteger(v)&&Number(v)>=0&&Number(v)<=max;
const text=(v:unknown,max:number):v is string=>typeof v==='string'&&v.length>0&&[...v].length<=max;
const date=(v:unknown):v is string=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number.isFinite(Date.parse(v))&&new Date(v).toISOString().slice(0,10)===v;
function invalid():never{throw new WorkspaceApiError(503);}
export function parseIncomingBrief(v:unknown,day:string,version:1|2):IncomingBriefSection{
  if(!closed(v,'coverage,reason,items,matching_items,counts,withheld_sources')||
    !['complete','partial','unavailable','not_included'].includes(v.coverage)||
    ![null,'source_unavailable','work_changed','collection_limit','legacy_report'].includes(v.reason)||typeof v.withheld_sources!=='boolean'||
    !n(v.matching_items)||!Array.isArray(v.items)||v.items.length>10||v.items.length>v.matching_items)invalid();
  if(version===1&&v.coverage!=='not_included'||version===2&&v.coverage==='not_included')invalid();
  if(v.coverage==='not_included'||v.coverage==='unavailable'){
    if(v.items.length||v.matching_items||v.counts!==null||v.reason===null||
      v.coverage==='not_included'&&(v.reason!=='legacy_report'||v.withheld_sources)||v.coverage==='unavailable'&&(!v.withheld_sources||!['source_unavailable','collection_limit'].includes(v.reason)))invalid();
    return v as IncomingBriefSection;
  }
  if(v.coverage==='complete'&&(v.withheld_sources||v.reason!==null)||v.coverage==='partial'&&(!v.withheld_sources||!['source_unavailable','work_changed'].includes(v.reason)))invalid();
  if(!closed(v.counts,'pending_approval,open,overdue,awaiting_acceptance,responsible_unavailable,awaiting_review,verified_complete,source_unavailable,work_changed')||
    !Object.values(v.counts).every(x=>n(x,v.matching_items))||
    [v.counts.overdue,v.counts.awaiting_acceptance,v.counts.awaiting_review].some(x=>x>v.counts.open)||
    v.counts.open+v.counts.pending_approval+v.counts.verified_complete+v.counts.source_unavailable+v.counts.work_changed>v.matching_items)invalid();
  const seen=new Set<string>();
  for(const item of v.items){
    if(!closed(item,'ticket_id,revision_id,payload_hash,version,state,body,due_date,responsible,originator_id,requires_owner_attention,pending_offer,ready_for_review,verified_current,publication_receipt_id,result_receipt_id,verification_receipt_id,changed_since_report')||
      !id(item.ticket_id)||seen.has(item.ticket_id)||!id(item.revision_id)||!id(item.originator_id)||
      typeof item.payload_hash!=='string'||!/^[a-f0-9]{64}$/.test(item.payload_hash)||!n(item.version,2147483647)||item.version===0||
      !['pending_approval','approved','closed','rejected','source_unavailable','work_changed'].includes(item.state)||
      !(item.body===null||text(item.body,180))||!(item.due_date===null||date(item.due_date))||
      !closed(item.responsible,'id,name,available')||!id(item.responsible.id)||!text(item.responsible.name,80)||typeof item.responsible.available!=='boolean'||
      !['requires_owner_attention','pending_offer','ready_for_review','verified_current','changed_since_report'].every(k=>typeof item[k]==='boolean')||
      !['publication_receipt_id','result_receipt_id','verification_receipt_id'].every(k=>item[k]===null||id(item[k])))invalid();
    if((item.pending_offer||item.ready_for_review)&&item.state!=='approved'||item.pending_offer&&item.ready_for_review||
      item.ready_for_review&&!item.result_receipt_id||item.verified_current&&(item.state!=='closed'||
      !item.publication_receipt_id||!item.result_receipt_id||!item.verification_receipt_id)||
      ['source_unavailable','work_changed'].includes(item.state)&&((item.state==='source_unavailable'&&!item.requires_owner_attention)||[item.body,item.due_date,item.pending_offer,item.ready_for_review,item.verified_current,item.publication_receipt_id,item.result_receipt_id,item.verification_receipt_id].some(Boolean)))invalid();
    if(v.coverage==='complete'&&['source_unavailable','work_changed'].includes(item.state))invalid();
    seen.add(item.ticket_id);
  }
  const items=v.items as IncomingBriefItem[],active=items.filter(x=>x.state==='approved');
  const visible:IncomingBriefCounts={pending_approval:items.filter(x=>x.state==='pending_approval').length,open:active.length,
    overdue:active.filter(x=>x.due_date!==null&&x.due_date<day).length,awaiting_acceptance:active.filter(x=>x.pending_offer).length,
    responsible_unavailable:items.filter(x=>!x.responsible.available).length,awaiting_review:active.filter(x=>x.ready_for_review).length,
    verified_complete:items.filter(x=>x.state==='closed'&&x.verified_current).length,source_unavailable:items.filter(x=>x.state==='source_unavailable').length,work_changed:items.filter(x=>x.state==='work_changed').length};
  const remaining=v.matching_items-items.length;
  if(Object.entries(visible).some(([key,value])=>v.counts[key]<value||v.counts[key]>value+remaining))invalid();
  return v as IncomingBriefSection;
}
