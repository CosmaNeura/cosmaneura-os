import {modelCanonical} from './model-work-request';
import {teamClosed,teamNatural,teamUuid,teamHash} from './team-setup-request';
import {validOutlookMessageReceipt,validOutlookMessageListRequest,validOutlookMessageReadRequest,validOutlookMessageReviewRequest,
  type OutlookMessageReceipt,type OutlookMessageListRequest,type OutlookMessageReadRequest,type OutlookMessageReviewRequest} from './outlook-message-api';

export type OutlookMessageRecoveryScope={box_id:string;actor_id:string};
export type OutlookMessageVisit={id:string;label:string;revision:number};
export type OutlookMessagePending=({kind:'list';request:OutlookMessageListRequest}|{kind:'message';request:OutlookMessageReadRequest}|{kind:'review';request:OutlookMessageReviewRequest})&{
  workspace:OutlookMessageVisit|null;list_anchor:OutlookMessageReceipt|null;message_anchor:OutlookMessageReceipt|null};
export type OutlookMessageSaved={workspace_id:string;entry_id:string;entry_revision:number;source_sha256:string;content_sha256:string;request_sha256:string;source_withheld:boolean};
export type OutlookEarlierRead={kind:'list';request:OutlookMessageListRequest}|{kind:'message';request:OutlookMessageReadRequest};
export type OutlookMessageRecoveryRecord={version:1;scope:OutlookMessageRecoveryScope;pending:OutlookMessagePending|null;list:OutlookMessageReceipt|null;
  message:OutlookMessageReceipt|null;selected_message_id:string|null;selected_visit:OutlookMessageVisit|null;saved:OutlookMessageSaved|null;earlier_reads:OutlookEarlierRead[]};
export type OutlookMessageRecoveryAccess={load():Promise<unknown>;persist(value:OutlookMessageRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const validOutlookMessageScope=(v:unknown):v is OutlookMessageRecoveryScope=>teamClosed(v,'box_id,actor_id')&&teamUuid(v.box_id)&&teamUuid(v.actor_id);
export const validOutlookMessageVisit=(v:unknown):v is OutlookMessageVisit=>teamClosed(v,'id,label,revision')&&teamUuid(v.id)&&typeof v.label==='string'&&v.label.length<=320&&
  !!v.label.trim()&&!/[\u0000-\u001f\u007f]/.test(v.label)&&teamNatural(v.revision)&&v.revision>0;
export const emptyOutlookMessageRecovery=(scope:OutlookMessageRecoveryScope):OutlookMessageRecoveryRecord=>({version:1,scope:structuredClone(scope),pending:null,list:null,message:null,selected_message_id:null,selected_visit:null,saved:null,earlier_reads:[]});
const invalid=():never=>{throw new Error('Private email recovery is invalid.');};
const messageId=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9_+/=-]{1,2048}$/.test(v);
export async function validateOutlookMessageRecovery(value:unknown,scope:OutlookMessageRecoveryScope):Promise<OutlookMessageRecoveryRecord> {
  if(!validOutlookMessageScope(scope)||!teamClosed(value,'version,scope,pending,list,message,selected_message_id,selected_visit,saved,earlier_reads')||value.version!==1||
    !validOutlookMessageScope(value.scope)||modelCanonical(value.scope)!==modelCanonical(scope)||new TextEncoder().encode(JSON.stringify(value)).length>131072)return invalid();
  const v=value as OutlookMessageRecoveryRecord;
  if(!Array.isArray(v.earlier_reads)||v.earlier_reads.length>8||v.earlier_reads.some(r=>!teamClosed(r,'kind,request')||
    !(r.kind==='list'?validOutlookMessageListRequest(r.request):r.kind==='message'&&validOutlookMessageReadRequest(r.request)))||
    new Set(v.earlier_reads.map(r=>r.request.idempotency_key)).size!==v.earlier_reads.length||
    v.pending&&v.earlier_reads.some(r=>r.request.idempotency_key===v.pending!.request.idempotency_key))return invalid();
  if(v.selected_visit!==null&&!validOutlookMessageVisit(v.selected_visit)||v.selected_message_id!==null&&!messageId(v.selected_message_id))return invalid();
  if(v.list!==null&&(!await validOutlookMessageReceipt(v.list)||v.list.kind!=='list')||v.message!==null&&(!await validOutlookMessageReceipt(v.message)||v.message.kind!=='message'))return invalid();
  if(v.message&&(!v.list||v.message.observation_id!==v.list.read_id||!v.list.observation!.items.some(i=>i.id===v.message!.message!.message_id)))return invalid();
  if(v.selected_message_id&&(!v.list||!v.list.observation!.items.some(i=>i.id===v.selected_message_id)))return invalid();
  if(v.saved!==null&&(!teamClosed(v.saved,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||!teamUuid(v.saved.workspace_id)||!teamUuid(v.saved.entry_id)||
    !teamHash(v.saved.request_sha256)||typeof v.saved.source_withheld!=='boolean'||
    !teamNatural(v.saved.entry_revision)||v.saved.entry_revision<1||!teamHash(v.saved.source_sha256)||!teamHash(v.saved.content_sha256)||!v.message||v.message.status!=='complete'||
    v.saved.source_sha256!==v.message.source_sha256||v.saved.content_sha256!==v.message.message!.content_sha256))return invalid();
  const p=v.pending;
  if(p!==null){
    if(!teamClosed(p,'kind,request,workspace,list_anchor,message_anchor')||p.workspace!==null&&!validOutlookMessageVisit(p.workspace)||
      p.list_anchor!==null&&(!await validOutlookMessageReceipt(p.list_anchor)||p.list_anchor.kind!=='list')||
      p.message_anchor!==null&&(!await validOutlookMessageReceipt(p.message_anchor)||p.message_anchor.kind!=='message'))return invalid();
    if(p.kind==='list'){if(!validOutlookMessageListRequest(p.request)||p.workspace!==null||p.list_anchor!==null||p.message_anchor!==null)return invalid();}
    else if(p.kind==='message'){
      if(!validOutlookMessageReadRequest(p.request)||p.workspace!==null||p.message_anchor!==null||!p.list_anchor||
        p.request.observation_id!==p.list_anchor.read_id||p.request.observation_sha256!==p.list_anchor.source_sha256||
        !p.list_anchor.observation!.items.some(i=>i.id===p.request.message_id&&(!p.request.thread_id||i.thread_id===p.request.thread_id)))return invalid();
    }else if(p.kind==='review'){
      if(!validOutlookMessageReviewRequest(p.request)||!p.workspace||!p.message_anchor||p.message_anchor.status!=='complete'||
        p.request.expected_revision!==p.workspace.revision||p.request.read_id!==p.message_anchor.read_id||p.request.source_sha256!==p.message_anchor.source_sha256||
        !p.list_anchor||p.message_anchor.observation_id!==p.list_anchor.read_id)return invalid();
    }else return invalid();
  }
  return structuredClone(v);
}
