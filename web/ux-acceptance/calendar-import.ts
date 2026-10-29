import {calendarHash,calendarBytesHash,calendarMidnight,calendarUploadHash,calendarItemHash,calendarReviewHash,calendarRevokeHash,calendarSelectedHash,calendarSourceContent,validCalendarUploadIntent,validCalendarReview,validCalendarRevoke,type CalendarImported,type CalendarImportReceipt,type CalendarImportScope,type CalendarImportItem,type CalendarReviewRequest,type CalendarReviewResponse} from '../src/calendar-import-api';
import {WorkspaceApiError,type Workspace} from '../src/workspace-api';

export const CALENDAR_REHEARSAL_ICS=['BEGIN:VCALENDAR','VERSION:2.0','BEGIN:VEVENT','UID:invented-calendar-1','DTSTART:20261025T130000Z','DTEND:20261025T133000Z','SUMMARY:Invented calendar visit','END:VEVENT','END:VCALENDAR',''].join('\r\n');
/** This rehearsal accepts exactly one invented file; it is not a calendar parser. */
export function calendarImportRehearsal(read:()=>Workspace,write:(value:Workspace)=>void,key:string,reset:boolean,owner:{box_id:string;owner_id:string;account_id:string;patient_link_id:string}){
 const storeKey=key+':calendar-import',retained=reset?null:sessionStorage.getItem(storeKey),data=retained?JSON.parse(retained) as {imports:CalendarImported[];revoked:string[];reviews:{import_id:string;body:CalendarReviewRequest;receipt:CalendarReviewResponse}[];revocations:{key:string;hash:string;import_id:string}[]}:{imports:[],revoked:[],reviews:[],revocations:[]};
 const persist=()=>sessionStorage.setItem(storeKey,JSON.stringify(data));if(reset)sessionStorage.removeItem(storeKey);
 const stats={uploads:0,reviews:0,resolves:0,inspects:0,revokes:0,externalCalls:0};Object.assign(window,{calendarImportRehearsalStats:stats,calendarImportRehearsalFile:CALENDAR_REHEARSAL_ICS});let lostUpload=false,lostReview=false;
 const scope=():CalendarImportScope=>({...owner,workspace_id:read().id});
 const response=(value:unknown,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
 const stamp=()=>new Date().toISOString().replace(/\.\d{3}Z$/,'Z');
 const receipt=(item:CalendarImported):CalendarImportReceipt=>{if(!data.revoked.includes(item.import_id))return structuredClone(item);const {payload:_,payload_sha256:__,...rest}=item;return {...rest,status:'withheld'};};
 const find=(id:string)=>data.imports.find(row=>row.import_id===id&&row.scope.workspace_id===read().id);
 const lost=()=>new URLSearchParams(location.search).get('scenario')==='calendar-import-lost-replies';
 return async(path:string,init?:RequestInit):Promise<Response|null>=>{
  const route=/^\/workspaces\/([a-f0-9-]{36})\/calendar-imports(\/review)?$/.exec(path);if(!route)return null;
  try{
   if(route[1]!==read().id||init?.method!=='POST'||typeof init.body!=='string'||new Headers(init.headers).get('X-Cosmas-Calendar-Import')!=='1')throw new WorkspaceApiError(422,'invalid_calendar_import_request');
   const body=JSON.parse(init.body);
   if(route[2]){
    if(!validCalendarReview(body))throw new WorkspaceApiError(422,'invalid_calendar_import_review');stats.reviews++;const anchor=find(body.import_id);if(!anchor)throw new WorkspaceApiError(404,'calendar_import_unavailable');const hash=await calendarReviewHash(read().id,body),old=data.reviews.find(row=>row.body.idempotency_key===body.idempotency_key);
    if(old){if(old.receipt.request_sha256!==hash)throw new WorkspaceApiError(409,'idempotency_conflict');return response({...old.receipt,workspace:read(),source_withheld:data.revoked.includes(anchor.import_id)});}
    if(data.reviews.some(row=>row.import_id===anchor.import_id&&row.body.item_index===body.item_index))throw new WorkspaceApiError(409,'calendar_import_already_selected');
    if(data.revoked.includes(anchor.import_id))throw new WorkspaceApiError(409,'calendar_import_source_unavailable');const item=anchor.payload.items.find(row=>row.item_index===body.item_index);
    if(!item||item.cancelled||anchor.source_sha256!==body.source_sha256||await calendarItemHash(item)!==body.item_sha256)throw new WorkspaceApiError(409,'calendar_import_source_changed');if(body.expected_revision!==read().revision)throw new WorkspaceApiError(409,'workspace_revision_conflict');
    const content=calendarSourceContent(anchor.payload,item),entry_id=crypto.randomUUID(),revision=read().revision+1;
    const workspace:Workspace={...read(),revision,model_observed_at:stamp(),entries:[...read().entries,{id:entry_id,kind:'calendar_import_source',revision,source_label:'Imported calendar snapshot',content,origin:'authenticated_human',created_at:stamp(),ticket:null,calendar_import_source_state:'current'}]};write(workspace);
    const result:CalendarReviewResponse={entry_id,entry_revision:revision,workspace,source:{entry_id,source_sha256:await calendarSelectedHash(anchor.source_sha256,item),content_sha256:await calendarBytesHash(new TextEncoder().encode(content))},request_sha256:hash,source_withheld:false};data.reviews.push({import_id:anchor.import_id,body,receipt:result});persist();
    if(lost()&&!lostReview){lostReview=true;throw new Error('Invented lost calendar summary response');}return response(result);
   }
   if(body.action==='status')return response({status:'available',scope:scope(),file_limit_bytes:1048576,max_items:25,formats:['ics'],reported_sources:['atlas_md','other_calendar']});
   if(body.action==='list')return response({status:'listed',scope:scope(),more:false,imports:data.imports.filter(row=>row.scope.workspace_id===read().id).sort((a,b)=>(a.payload.imported_at+':'+a.import_id).localeCompare(b.payload.imported_at+':'+b.import_id)).map(row=>({reviewed_item_indices:[...new Set(data.reviews.filter(review=>review.import_id===row.import_id).map(review=>review.body.item_index))].sort((a,b)=>a-b),status:receipt(row).status,import_id:row.import_id,idempotency_key:row.idempotency_key,byte_sha256:row.byte_sha256,request_sha256:row.request_sha256,source_sha256:row.source_sha256,reported_source:row.payload.reported_source,window:row.payload.window,imported_at:row.payload.imported_at}))});
   if(body.action==='resolve'){stats.resolves++;const found=data.imports.find(row=>row.idempotency_key===body.idempotency_key&&row.scope.workspace_id===read().id);return response(found?receipt(found):{status:'not_found',scope:scope(),workspace_id:read().id,idempotency_key:body.idempotency_key});}
   if(body.action==='inspect'){stats.inspects++;const found=find(body.import_id);if(!found)throw new WorkspaceApiError(404,'calendar_import_unavailable');return response(receipt(found));}
   if(body.action==='revoke'){
    if(!validCalendarRevoke(body))throw new WorkspaceApiError(422,'invalid_calendar_import_request');stats.revokes++;const found=find(body.import_id);if(!found)throw new WorkspaceApiError(404,'calendar_import_unavailable');const hash=await calendarRevokeHash(read().id,body),old=data.revocations.find(row=>row.key===body.idempotency_key);if(old&&old.hash!==hash)throw new WorkspaceApiError(409,'idempotency_conflict');
    if(!old){if(body.expected_revision!==read().revision)throw new WorkspaceApiError(409,'workspace_revision_conflict');if(body.source_sha256!==found.source_sha256)throw new WorkspaceApiError(409,'calendar_import_source_changed');data.revoked.push(found.import_id);data.revocations.push({key:body.idempotency_key,hash,import_id:found.import_id});const ids=new Set(data.reviews.filter(row=>row.import_id===found.import_id).map(row=>row.receipt.entry_id));write({...read(),model_observed_at:stamp(),entries:read().entries.map(row=>ids.has(row.id)?{...row,content:'',source_label:'Unavailable calendar import',calendar_import_source_state:'unavailable'}:row)});persist();}
    return response({status:'revoked',scope:scope(),import_id:found.import_id,idempotency_key:body.idempotency_key,request_sha256:hash,source_sha256:found.source_sha256,workspace:read()});
   }
   const {file_base64,...intent}=body;if(!validCalendarUploadIntent(intent)||typeof file_base64!=='string')throw new WorkspaceApiError(422,'invalid_calendar_import_request');stats.uploads++;
   const hash=await calendarUploadHash(read().id,intent),old=data.imports.find(row=>row.idempotency_key===intent.idempotency_key&&row.scope.workspace_id===read().id);if(old){if(old.request_sha256!==hash)throw new WorkspaceApiError(409,'idempotency_conflict');return response(receipt(old));}
   const raw=Uint8Array.from(atob(file_base64),c=>c.charCodeAt(0));if(new TextDecoder().decode(raw)!==CALENDAR_REHEARSAL_ICS||await calendarBytesHash(raw)!==intent.byte_sha256)throw new WorkspaceApiError(422,'calendar_file_invalid');
   const item:CalendarImportItem={item_index:0,title:'Invented calendar visit',title_truncated:false,starts_at:'2026-10-25T13:00:00Z',ends_at:'2026-10-25T13:30:00Z',all_day:false,cancelled:false};const matching=Date.parse(item.starts_at)<calendarMidnight(intent.window.ends_on,intent.window.timezone)&&Date.parse(item.ends_at)>calendarMidnight(intent.window.starts_on,intent.window.timezone);
   const payload={imported_at:stamp(),reported_source:intent.reported_source,window:intent.window,items:matching?[item]:[],total_events:1,matching_events:matching?1:0,more:false,coverage:'file_window_only' as const},payload_sha256=await calendarHash(payload),import_id=crypto.randomUUID(),ownerScope=scope();
   const result:CalendarImported={status:'imported',scope:ownerScope,import_id,idempotency_key:intent.idempotency_key,request_sha256:hash,byte_sha256:intent.byte_sha256,payload_sha256,source_sha256:await calendarHash({kind:'calendar-import-snapshot-v1',import_id,...ownerScope,request_sha256:hash,payload_sha256}),payload};data.imports.push(result);persist();
   if(lost()&&!lostUpload){lostUpload=true;throw new Error('Invented lost calendar import response');}return response(result);
  }catch(error){if(error instanceof WorkspaceApiError)return response({detail:error.code??'invalid_calendar_import_request'},error.status);throw error;}
 };
}
