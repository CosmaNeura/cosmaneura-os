import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {modelCanonical} from './model-work-request';
import {calendarBytesHash,calendarMatchesUpload,calendarReviewHash,calendarReviewMatches,calendarSelectedHash,calendarSourceContent,sameCalendarScope,validCalendarReceipt,validCalendarRevoke,validCalendarScope,validCalendarUploadIntent,validCalendarWindow,type CalendarImported,type CalendarImportReceipt,type CalendarImportScope,type CalendarImportWindow,type CalendarReportedSource,type CalendarReviewRequest,type CalendarRevokeRequest,type CalendarUploadIntent} from './calendar-import-api';

export type CalendarImportOwner={box_id:string;owner_id:string;workspace_id:string};
export type CalendarImportForm={reported_source:CalendarReportedSource;window:CalendarImportWindow};
export type CalendarSavedSource={workspace_id:string;entry_id:string;entry_revision:number;source_sha256:string;content_sha256:string;request_sha256:string;source_withheld:boolean};
export type CalendarPending={kind:'upload';request:CalendarUploadIntent}|{kind:'review';request:CalendarReviewRequest;anchor:CalendarImported}|{kind:'revoke';request:CalendarRevokeRequest;anchor:CalendarImportReceipt};
export type CalendarSupersededUpload={scope:CalendarImportScope;request:CalendarUploadIntent};
export type CalendarImportRecovery={version:1;reviewed_item_indices:number[];superseded_uploads:CalendarSupersededUpload[];owner:CalendarImportOwner;scope:CalendarImportScope|null;form:CalendarImportForm;import:CalendarImportReceipt|null;selected:number|null;pending:CalendarPending|null;saved:{source:CalendarSavedSource;request:CalendarReviewRequest;anchor:CalendarImported}|null};
export type CalendarRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(value:CalendarImportRecovery|null):Promise<void>;denied?(cause:unknown):void};
export const validCalendarOwner=(value:unknown):value is CalendarImportOwner=>teamClosed(value,'box_id,owner_id,workspace_id')&&teamUuid(value.box_id)&&teamUuid(value.owner_id)&&teamUuid(value.workspace_id);
export const validCalendarForm=(value:unknown):value is CalendarImportForm=>teamClosed(value,'reported_source,window')&&['atlas_md','other_calendar'].includes(String(value.reported_source))&&validCalendarWindow(value.window);
export const emptyCalendarRecovery=(owner:CalendarImportOwner,form:CalendarImportForm):CalendarImportRecovery=>({version:1,reviewed_item_indices:[],superseded_uploads:[],owner,scope:null,form,import:null,selected:null,pending:null,saved:null});
const fail=():never=>{throw new Error('Saved calendar import work could not be verified.');};
const same=(a:unknown,b:unknown)=>modelCanonical(a)===modelCanonical(b);
export async function validateCalendarRecovery(value:unknown,owner:CalendarImportOwner):Promise<CalendarImportRecovery>{
 if(!validCalendarOwner(owner)||!teamClosed(value,'version,reviewed_item_indices,superseded_uploads,owner,scope,form,import,selected,pending,saved')||value.version!==1||!validCalendarOwner(value.owner)||!same(value.owner,owner)||!validCalendarForm(value.form)||new TextEncoder().encode(modelCanonical(value)).length>131072)return fail();
 const r=value as CalendarImportRecovery,scope=r.scope;
 if(!Array.isArray(r.reviewed_item_indices)||r.reviewed_item_indices.length>25||r.reviewed_item_indices.some((n,i,a)=>!teamNatural(n)||n>=500||i>0&&n<=a[i-1])||r.reviewed_item_indices.length>0&&!r.import)return fail();
 if(r.import?.status==='imported'&&r.reviewed_item_indices.some(index=>!(r.import as CalendarImported).payload.items.some(item=>item.item_index===index&&!item.cancelled)))return fail();
 if(!Array.isArray(r.superseded_uploads)||r.superseded_uploads.length>3||new Set(r.superseded_uploads.map(old=>old?.request?.idempotency_key)).size!==r.superseded_uploads.length)return fail();
 for(const old of r.superseded_uploads)if(!teamClosed(old,'scope,request')||!validCalendarScope(old.scope)||!validCalendarUploadIntent(old.request)||!scope||!sameCalendarScope(old.scope,scope)||old.request.idempotency_key===r.pending?.request.idempotency_key)return fail();
 if(scope!==null&&(!validCalendarScope(scope)||scope.box_id!==owner.box_id||scope.owner_id!==owner.owner_id||scope.workspace_id!==owner.workspace_id))return fail();
 if(!scope&&(r.import||r.pending||r.saved||r.selected!==null))return fail();
 if(r.import&&(!await validCalendarReceipt(r.import)||!scope||!sameCalendarScope(r.import.scope,scope)||!await calendarMatchesUpload(r.import,scope,{action:'upload',idempotency_key:r.import.idempotency_key,byte_sha256:r.import.byte_sha256,...r.form})))return fail();
 if(r.selected!==null&&(!teamNatural(r.selected)||r.import?.status!=='imported'||!r.import.payload.items.some(item=>item.item_index===r.selected&&!item.cancelled)))return fail();
 if(r.pending){const p=r.pending;
  if(p.kind==='upload'){
   if(!teamClosed(p,'kind,request')||!validCalendarUploadIntent(p.request)||r.import||r.saved||r.selected!==null||!same(r.form,{window:p.request.window,reported_source:p.request.reported_source}))return fail();
  }else if(p.kind==='review'){
   if(!teamClosed(p,'kind,request,anchor')||r.import?.status!=='imported'||!same(p.anchor,r.import)||!await calendarReviewMatches(p.request,p.anchor)||r.selected!==p.request.item_index||r.reviewed_item_indices.includes(p.request.item_index)||r.saved)return fail();
  }else if(p.kind==='revoke'){
   if(!teamClosed(p,'kind,request,anchor')||!validCalendarRevoke(p.request)||!r.import||!same(p.anchor,r.import)||p.request.import_id!==r.import.import_id||p.request.source_sha256!==r.import.source_sha256)return fail();
  }else return fail();
 }
 if(r.saved){const saved=r.saved,s=saved.source,a=saved.anchor,body=saved.request;
  if(!teamClosed(saved,'source,request,anchor')||!await validCalendarReceipt(a)||a.status!=='imported'||!scope||!sameCalendarScope(a.scope,scope)||!r.import||a.import_id!==r.import.import_id||a.source_sha256!==r.import.source_sha256||!await calendarReviewMatches(body,a)||!teamClosed(s,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||s.workspace_id!==owner.workspace_id||!teamUuid(s.entry_id)||s.entry_revision!==body.expected_revision+1||!teamHash(s.content_sha256)||typeof s.source_withheld!=='boolean'||r.import.status==='withheld'&&!s.source_withheld||s.request_sha256!==await calendarReviewHash(owner.workspace_id,body))return fail();
  const item=a.payload.items.find(item=>item.item_index===body.item_index)!;
  if(s.source_sha256!==await calendarSelectedHash(a.source_sha256,item)||s.content_sha256!==await calendarBytesHash(new TextEncoder().encode(calendarSourceContent(a.payload,item))))return fail();
 }
 return structuredClone(r);
}
