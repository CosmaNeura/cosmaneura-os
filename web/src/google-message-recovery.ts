import {modelCanonical} from './model-work-request';
import {teamClosed,teamNatural,teamUuid,teamHash} from './team-setup-request';
import {validGoogleMessageReceipt,validGoogleMessageListRequest,validGoogleMessageReadRequest,validGoogleMessageReviewRequest,
  type GoogleMessageReceipt,type GoogleMessageListRequest,type GoogleMessageReadRequest,type GoogleMessageReviewRequest} from './google-message-api';

export type GoogleMessageRecoveryScope={box_id:string;actor_id:string};
export type GoogleMessageVisit={id:string;label:string;revision:number};
export type GoogleMessagePending=({kind:'list';request:GoogleMessageListRequest}|{kind:'message';request:GoogleMessageReadRequest}|{kind:'review';request:GoogleMessageReviewRequest})&{
  workspace:GoogleMessageVisit|null;list_anchor:GoogleMessageReceipt|null;message_anchor:GoogleMessageReceipt|null};
export type GoogleMessageSaved={workspace_id:string;entry_id:string;entry_revision:number;source_sha256:string;content_sha256:string;request_sha256:string;source_withheld:boolean};
export type GoogleMessageRecoveryRecord={version:1;scope:GoogleMessageRecoveryScope;pending:GoogleMessagePending|null;list:GoogleMessageReceipt|null;
  message:GoogleMessageReceipt|null;selected_message_id:string|null;selected_visit:GoogleMessageVisit|null;saved:GoogleMessageSaved|null};
export type GoogleMessageRecoveryAccess={load():Promise<unknown>;persist(value:GoogleMessageRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const validGoogleMessageScope=(v:unknown):v is GoogleMessageRecoveryScope=>teamClosed(v,'box_id,actor_id')&&teamUuid(v.box_id)&&teamUuid(v.actor_id);
export const validGoogleMessageVisit=(v:unknown):v is GoogleMessageVisit=>teamClosed(v,'id,label,revision')&&teamUuid(v.id)&&typeof v.label==='string'&&v.label.length<=320&&
  !!v.label.trim()&&!/[\u0000-\u001f\u007f]/.test(v.label)&&teamNatural(v.revision)&&v.revision>0;
export const emptyGoogleMessageRecovery=(scope:GoogleMessageRecoveryScope):GoogleMessageRecoveryRecord=>({version:1,scope:structuredClone(scope),pending:null,list:null,message:null,selected_message_id:null,selected_visit:null,saved:null});
const invalid=():never=>{throw new Error('Private email recovery is invalid.');};
const messageId=(v:unknown):v is string=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(v);
export async function validateGoogleMessageRecovery(value:unknown,scope:GoogleMessageRecoveryScope):Promise<GoogleMessageRecoveryRecord> {
  if(!validGoogleMessageScope(scope)||!teamClosed(value,'version,scope,pending,list,message,selected_message_id,selected_visit,saved')||value.version!==1||
    !validGoogleMessageScope(value.scope)||modelCanonical(value.scope)!==modelCanonical(scope)||new TextEncoder().encode(JSON.stringify(value)).length>131072)return invalid();
  const v=value as GoogleMessageRecoveryRecord;
  if(v.selected_visit!==null&&!validGoogleMessageVisit(v.selected_visit)||v.selected_message_id!==null&&!messageId(v.selected_message_id))return invalid();
  if(v.list!==null&&(!await validGoogleMessageReceipt(v.list)||v.list.kind!=='list')||v.message!==null&&(!await validGoogleMessageReceipt(v.message)||v.message.kind!=='message'))return invalid();
  if(v.message&&(!v.list||v.message.observation_id!==v.list.read_id||!v.list.observation!.items.some(i=>i.id===v.message!.message!.message_id)))return invalid();
  if(v.selected_message_id&&(!v.list||!v.list.observation!.items.some(i=>i.id===v.selected_message_id)))return invalid();
  if(v.saved!==null&&(!teamClosed(v.saved,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||!teamUuid(v.saved.workspace_id)||!teamUuid(v.saved.entry_id)||
    !teamHash(v.saved.request_sha256)||typeof v.saved.source_withheld!=='boolean'||
    !teamNatural(v.saved.entry_revision)||v.saved.entry_revision<1||!teamHash(v.saved.source_sha256)||!teamHash(v.saved.content_sha256)||!v.message||v.message.status!=='complete'||
    v.saved.source_sha256!==v.message.source_sha256||v.saved.content_sha256!==v.message.message!.content_sha256))return invalid();
  const p=v.pending;
  if(p!==null){
    if(!teamClosed(p,'kind,request,workspace,list_anchor,message_anchor')||p.workspace!==null&&!validGoogleMessageVisit(p.workspace)||
      p.list_anchor!==null&&(!await validGoogleMessageReceipt(p.list_anchor)||p.list_anchor.kind!=='list')||
      p.message_anchor!==null&&(!await validGoogleMessageReceipt(p.message_anchor)||p.message_anchor.kind!=='message'))return invalid();
    if(p.kind==='list'){if(!validGoogleMessageListRequest(p.request)||p.workspace!==null||p.list_anchor!==null||p.message_anchor!==null)return invalid();}
    else if(p.kind==='message'){
      if(!validGoogleMessageReadRequest(p.request)||p.workspace!==null||p.message_anchor!==null||!p.list_anchor||
        p.request.observation_id!==p.list_anchor.read_id||p.request.observation_sha256!==p.list_anchor.source_sha256||
        !p.list_anchor.observation!.items.some(i=>i.id===p.request.message_id&&(!p.request.thread_id||i.thread_id===p.request.thread_id)))return invalid();
    }else if(p.kind==='review'){
      if(!validGoogleMessageReviewRequest(p.request)||!p.workspace||!p.message_anchor||p.message_anchor.status!=='complete'||
        p.request.expected_revision!==p.workspace.revision||p.request.read_id!==p.message_anchor.read_id||p.request.source_sha256!==p.message_anchor.source_sha256||
        !p.list_anchor||p.message_anchor.observation_id!==p.list_anchor.read_id)return invalid();
    }else return invalid();
  }
  return structuredClone(v);
}
