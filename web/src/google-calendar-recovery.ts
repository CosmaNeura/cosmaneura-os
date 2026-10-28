import {modelCanonical} from './model-work-request';
import {teamClosed,teamNatural,teamUuid,teamHash} from './team-setup-request';
import {validGoogleCalendarReceipt,validGoogleCalendarObserveRequest,validGoogleCalendarReviewRequest,googleCalendarEventHash,googleCalendarSourceHash,googleCalendarSourceContent,
 type GoogleCalendarReceipt,type GoogleCalendarObserveRequest,type GoogleCalendarReviewRequest} from './google-calendar-api';
import {vendorSha256} from './vendor-contract';
export type GoogleCalendarRecoveryScope={box_id:string;actor_id:string};
// Missing kind is the existing linked-visit journal contract.
export type GoogleCalendarVisit={id:string;label:string;revision:number;kind?:'private_notebook'};
export type GoogleCalendarPending=({kind:'observe';request:GoogleCalendarObserveRequest}|{kind:'review';request:GoogleCalendarReviewRequest})&{workspace:GoogleCalendarVisit|null;observation_anchor:GoogleCalendarReceipt|null};
export type GoogleCalendarSaved={workspace_id:string;entry_id:string;entry_revision:number;source_sha256:string;content_sha256:string;request_sha256:string;source_withheld:boolean};
export type GoogleCalendarRecoveryRecord={version:1;scope:GoogleCalendarRecoveryScope;pending:GoogleCalendarPending|null;observation:GoogleCalendarReceipt|null;selected_event_id:string|null;selected_visit:GoogleCalendarVisit|null;saved:GoogleCalendarSaved|null};
export type GoogleCalendarRecoveryAccess={load():Promise<unknown>;persist(value:GoogleCalendarRecoveryRecord|null):Promise<void>;authorize():Promise<void>;denied?(error:unknown):void};
export const validGoogleCalendarScope=(v:unknown):v is GoogleCalendarRecoveryScope=>teamClosed(v,'box_id,actor_id')&&teamUuid(v.box_id)&&teamUuid(v.actor_id);
export const validGoogleCalendarVisit=(v:unknown):v is GoogleCalendarVisit=>(teamClosed(v,'id,label,revision')||teamClosed(v,'id,label,revision,kind')&&v.kind==='private_notebook')&&teamUuid(v.id)&&typeof v.label==='string'&&v.label.length<=320&&!!v.label.trim()&&!/[\u0000-\u001f\u007f]/.test(v.label)&&teamNatural(v.revision)&&v.revision>0;
export const emptyGoogleCalendarRecovery=(scope:GoogleCalendarRecoveryScope):GoogleCalendarRecoveryRecord=>({version:1,scope:structuredClone(scope),pending:null,observation:null,selected_event_id:null,selected_visit:null,saved:null});
const invalid=():never=>{throw new Error('Private calendar recovery is invalid.');};
export async function validateGoogleCalendarRecovery(value:unknown,scope:GoogleCalendarRecoveryScope):Promise<GoogleCalendarRecoveryRecord>{
 if(!validGoogleCalendarScope(scope)||!teamClosed(value,'version,scope,pending,observation,selected_event_id,selected_visit,saved')||value.version!==1||!validGoogleCalendarScope(value.scope)||modelCanonical(value.scope)!==modelCanonical(scope)||new TextEncoder().encode(JSON.stringify(value)).length>131072)return invalid();
 const v=value as GoogleCalendarRecoveryRecord;
 if(v.selected_visit!==null&&!validGoogleCalendarVisit(v.selected_visit)||v.observation!==null&&!await validGoogleCalendarReceipt(v.observation))return invalid();
 const event=v.observation?.observation.items.find(i=>i.id===v.selected_event_id);
 if(v.selected_event_id!==null&&!event||v.selected_visit!==null&&!event)return invalid();
 if(v.saved!==null){const s=v.saved;if(!teamClosed(s,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||!teamUuid(s.workspace_id)||!teamUuid(s.entry_id)||!teamNatural(s.entry_revision)||s.entry_revision<1||!teamHash(s.source_sha256)||!teamHash(s.content_sha256)||!teamHash(s.request_sha256)||typeof s.source_withheld!=='boolean'||!event||!v.observation||!v.selected_visit||s.workspace_id!==v.selected_visit.id||s.source_sha256!==await googleCalendarSourceHash(v.observation,event)||s.content_sha256!==await vendorSha256(new TextEncoder().encode(googleCalendarSourceContent(v.observation.observation,event))))return invalid();}
 const q=v.pending;
 if(q!==null){
  if(!teamClosed(q,'kind,request,workspace,observation_anchor')||q.workspace!==null&&!validGoogleCalendarVisit(q.workspace)||q.observation_anchor!==null&&!await validGoogleCalendarReceipt(q.observation_anchor))return invalid();
  if(q.kind==='observe'){if(!validGoogleCalendarObserveRequest(q.request)||q.workspace!==null||q.observation_anchor!==null)return invalid();}
  else if(q.kind==='review'){
   const selected=q.observation_anchor?.observation.items.find(i=>i.id===q.request.event_id);
   if(!validGoogleCalendarReviewRequest(q.request)||!q.workspace||(q.workspace.kind==='private_notebook')!==(q.request.reviewed_private_notebook===true)||!q.observation_anchor||!selected||q.request.expected_revision!==q.workspace.revision||q.request.observation_id!==q.observation_anchor.observation_id||q.request.observation_sha256!==q.observation_anchor.source_sha256||q.request.event_sha256!==await googleCalendarEventHash(selected)||!v.observation||modelCanonical(v.observation)!==modelCanonical(q.observation_anchor)||v.selected_event_id!==q.request.event_id||!v.selected_visit||modelCanonical(v.selected_visit)!==modelCanonical(q.workspace))return invalid();
  }else return invalid();
 }
 return structuredClone(v);
}
