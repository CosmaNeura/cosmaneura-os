import {modelCanonical} from './model-work-request';
import {teamClosed,teamNatural,teamUuid,teamHash} from './team-setup-request';
import {validMicrosoftCalendarReceipt,validMicrosoftCalendarObserveRequest,validMicrosoftCalendarReviewRequest,microsoftCalendarEventHash,microsoftCalendarSourceHash,microsoftCalendarSourceContent,
 type MicrosoftCalendarReceipt,type MicrosoftCalendarObserveRequest,type MicrosoftCalendarReviewRequest} from './microsoft-calendar-api';
import {vendorSha256} from './vendor-contract';
export type MicrosoftCalendarRecoveryScope={box_id:string;actor_id:string};
// Calendar review is restricted to an existing linked visit.
export type MicrosoftCalendarVisit={id:string;label:string;revision:number};
export type MicrosoftCalendarPending=({kind:'observe';request:MicrosoftCalendarObserveRequest}|{kind:'review';request:MicrosoftCalendarReviewRequest})&{workspace:MicrosoftCalendarVisit|null;observation_anchor:MicrosoftCalendarReceipt|null};
export type MicrosoftCalendarSaved={workspace_id:string;entry_id:string;entry_revision:number;source_sha256:string;content_sha256:string;request_sha256:string;source_withheld:boolean};
export type MicrosoftCalendarRecoveryRecord={version:1;scope:MicrosoftCalendarRecoveryScope;pending:MicrosoftCalendarPending|null;observation:MicrosoftCalendarReceipt|null;selected_event_id:string|null;selected_visit:MicrosoftCalendarVisit|null;saved:MicrosoftCalendarSaved|null};
export type MicrosoftCalendarRecoveryAccess={load():Promise<unknown>;persist(value:MicrosoftCalendarRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const validMicrosoftCalendarScope=(v:unknown):v is MicrosoftCalendarRecoveryScope=>teamClosed(v,'box_id,actor_id')&&teamUuid(v.box_id)&&teamUuid(v.actor_id);
export const validMicrosoftCalendarVisit=(v:unknown):v is MicrosoftCalendarVisit=>teamClosed(v,'id,label,revision')&&teamUuid(v.id)&&typeof v.label==='string'&&v.label.length<=320&&!!v.label.trim()&&!/[\u0000-\u001f\u007f]/.test(v.label)&&teamNatural(v.revision)&&v.revision>0;
export const emptyMicrosoftCalendarRecovery=(scope:MicrosoftCalendarRecoveryScope):MicrosoftCalendarRecoveryRecord=>({version:1,scope:structuredClone(scope),pending:null,observation:null,selected_event_id:null,selected_visit:null,saved:null});
const invalid=():never=>{throw new Error('Private calendar recovery is invalid.');};
export async function validateMicrosoftCalendarRecovery(value:unknown,scope:MicrosoftCalendarRecoveryScope):Promise<MicrosoftCalendarRecoveryRecord>{
 if(!validMicrosoftCalendarScope(scope)||!teamClosed(value,'version,scope,pending,observation,selected_event_id,selected_visit,saved')||value.version!==1||!validMicrosoftCalendarScope(value.scope)||modelCanonical(value.scope)!==modelCanonical(scope)||new TextEncoder().encode(JSON.stringify(value)).length>131072)return invalid();
 const v=value as MicrosoftCalendarRecoveryRecord;
 if(v.selected_visit!==null&&!validMicrosoftCalendarVisit(v.selected_visit)||v.observation!==null&&!await validMicrosoftCalendarReceipt(v.observation))return invalid();
 const event=v.observation?.observation.items.find(i=>i.id===v.selected_event_id);
 if(v.selected_event_id!==null&&!event||v.selected_visit!==null&&!event)return invalid();
 if(v.saved!==null){const s=v.saved;if(!teamClosed(s,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||!teamUuid(s.workspace_id)||!teamUuid(s.entry_id)||!teamNatural(s.entry_revision)||s.entry_revision<1||!teamHash(s.source_sha256)||!teamHash(s.content_sha256)||!teamHash(s.request_sha256)||typeof s.source_withheld!=='boolean'||!event||!v.observation||!v.selected_visit||s.workspace_id!==v.selected_visit.id||s.source_sha256!==await microsoftCalendarSourceHash(v.observation,event)||s.content_sha256!==await vendorSha256(new TextEncoder().encode(microsoftCalendarSourceContent(v.observation.observation,event))))return invalid();}
 const q=v.pending;
 if(q!==null){
  if(!teamClosed(q,'kind,request,workspace,observation_anchor')||q.workspace!==null&&!validMicrosoftCalendarVisit(q.workspace)||q.observation_anchor!==null&&!await validMicrosoftCalendarReceipt(q.observation_anchor))return invalid();
  if(q.kind==='observe'){if(!validMicrosoftCalendarObserveRequest(q.request)||q.workspace!==null||q.observation_anchor!==null)return invalid();}
  else if(q.kind==='review'){
   const selected=q.observation_anchor?.observation.items.find(i=>i.id===q.request.event_id);
   if(!validMicrosoftCalendarReviewRequest(q.request)||!q.workspace||!q.observation_anchor||!selected||q.request.expected_revision!==q.workspace.revision||q.request.observation_id!==q.observation_anchor.observation_id||q.request.observation_sha256!==q.observation_anchor.source_sha256||q.request.event_sha256!==await microsoftCalendarEventHash(selected)||!v.observation||modelCanonical(v.observation)!==modelCanonical(q.observation_anchor)||v.selected_event_id!==q.request.event_id||!v.selected_visit||modelCanonical(v.selected_visit)!==modelCanonical(q.workspace))return invalid();
  }else return invalid();
 }
 return structuredClone(v);
}
