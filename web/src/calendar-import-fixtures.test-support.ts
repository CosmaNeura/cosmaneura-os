import {calendarHash,calendarBytesHash,calendarUploadHash,calendarItemHash,calendarReviewHash,calendarSelectedHash,calendarSourceContent,type CalendarImported,type CalendarUploadIntent,type CalendarReviewRequest,type CalendarReviewResponse} from './calendar-import-api';
import {CALENDAR_REHEARSAL_ICS} from '../ux-acceptance/calendar-import';
export const calUuid=(n:number)=>`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`;
export const calOwner={box_id:calUuid(4001),owner_id:calUuid(4002),workspace_id:calUuid(4003)};
export const calScope={...calOwner,account_id:calUuid(4004),patient_link_id:calUuid(4005)};
export const calVisit={id:calOwner.workspace_id,label:'Invented calendar visit',revision:5};
export const calForm={reported_source:'atlas_md' as const,window:{starts_on:'2026-10-25',ends_on:'2026-11-01',timezone:'America/New_York'}};
export const calBytes=()=>new TextEncoder().encode(CALENDAR_REHEARSAL_ICS);
export const calIntent=async(key=calUuid(4010)):Promise<CalendarUploadIntent>=>({action:'upload',idempotency_key:key,byte_sha256:await calendarBytesHash(calBytes()),...calForm});
export async function calImported(input?:CalendarUploadIntent,id=calUuid(4011)):Promise<CalendarImported>{
 const intent=input??await calIntent();
 const payload={imported_at:'2026-10-25T12:00:00Z',reported_source:intent.reported_source,window:intent.window,items:[{item_index:0,title:'Invented calendar visit',title_truncated:false,starts_at:'2026-10-25T13:00:00Z',ends_at:'2026-10-25T13:30:00Z',all_day:false,cancelled:false}],total_events:1,matching_events:1,more:false,coverage:'file_window_only' as const},payload_sha256=await calendarHash(payload),request_sha256=await calendarUploadHash(calVisit.id,intent);
 return {status:'imported',scope:calScope,import_id:id,idempotency_key:intent.idempotency_key,byte_sha256:intent.byte_sha256,request_sha256,payload_sha256,payload,source_sha256:await calendarHash({kind:'calendar-import-snapshot-v1',import_id:id,...calScope,request_sha256,payload_sha256})};
}
export async function calReviewBody(anchor:CalendarImported):Promise<CalendarReviewRequest>{return {expected_revision:calVisit.revision,idempotency_key:calUuid(4012),import_id:anchor.import_id,source_sha256:anchor.source_sha256,item_index:0,item_sha256:await calendarItemHash(anchor.payload.items[0]),reviewed_visit:true,reviewed_exact_summary:true,reviewed_untrusted_source:true};}
export async function calReviewResult(anchor:CalendarImported,body:CalendarReviewRequest):Promise<CalendarReviewResponse>{
 const content=calendarSourceContent(anchor.payload,anchor.payload.items[0]),entry_id=calUuid(4013);return {entry_id,entry_revision:body.expected_revision+1,request_sha256:await calendarReviewHash(calVisit.id,body),source_withheld:false,source:{entry_id,source_sha256:await calendarSelectedHash(anchor.source_sha256,anchor.payload.items[0]),content_sha256:await calendarBytesHash(new TextEncoder().encode(content))},workspace:{...calVisit,appointment_id:calUuid(4014),revision:body.expected_revision+1,entries:[{id:entry_id,kind:'calendar_import_source',revision:body.expected_revision+1,content,source_label:'Imported calendar snapshot',origin:'authenticated_human',created_at:'2026-10-25T12:00:00Z',ticket:null,calendar_import_source_state:'current'}],work_candidates:[],model_contract_version:1,model_observed_at:'2026-10-25T12:00:00Z'}};
}
