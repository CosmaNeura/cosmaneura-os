import {teamCanonical} from './team-setup-request';
import {googleCalendarEventHash,googleCalendarSourceHash,googleCalendarSourceContent,googleCalendarReviewHash,type GoogleCalendarReceipt,type GoogleCalendarReviewRequest} from './google-calendar-api';
import type {Workspace} from './workspace-api';
export const calendarUuid=(n:number)=>`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`;
export const calendarSha=async(s:string)=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(s)))].map(n=>n.toString(16).padStart(2,'0')).join('');
export const calendarScope={box_id:calendarUuid(101),actor_id:calendarUuid(102)};
export const calendarVisit={id:calendarUuid(103),label:'Invented Shawn visit · DOB not provided',revision:5};
export async function calendarReceipt():Promise<GoogleCalendarReceipt>{
 const observation={kind:'calendar' as const,account:{label:'Invented clinician café',email:'clinician@example.invalid'},items:[
  {id:'invented-timed',subject:'Invented café follow-up 😀 <img src="https://example.invalid">',starts_at:'2026-10-02T13:00:00Z',ends_at:'2026-10-02T15:00:00Z',all_day:false,cancelled:false},
  {id:'invented-allday',subject:'Invented all-day visit',starts_at:'2026-10-05',ends_at:'2026-10-06',all_day:true,cancelled:false},
  {id:'invented-cancelled',subject:'Invented cancelled visit',starts_at:'2026-10-02T16:00:00Z',ends_at:'2026-10-02T17:00:00Z',all_day:false,cancelled:true}
 ],more:true,observed_at:'2026-10-02T12:00:00Z',window:{starts_at:'2026-10-02T12:00:00Z',ends_at:'2026-10-09T12:00:00Z'}};
 return {contract_version:1,observation_id:calendarUuid(1),observation_key:calendarUuid(2),source_sha256:'a'.repeat(64),payload_sha256:await calendarSha(teamCanonical(observation)),observation};
}
export async function calendarReview(receipt:GoogleCalendarReceipt,body:GoogleCalendarReviewRequest){
 const event=receipt.observation.items.find(e=>e.id===body.event_id)!,content=googleCalendarSourceContent(receipt.observation,event);
 const workspace={id:calendarVisit.id,label:calendarVisit.label,appointment_id:calendarUuid(104),revision:6,entries:[{id:calendarUuid(5),revision:6,kind:'google_calendar',content,origin:'authenticated_human',source_label:'Google calendar: '+event.subject,calendar_source_state:'current',created_at:'2026-10-02T12:00:00Z',ticket:null}],work_candidates:[],model_contract_version:1,model_observed_at:'2026-10-02T12:00:00Z'} as unknown as Workspace;
 return {entry_id:calendarUuid(5),entry_revision:6,request_sha256:await googleCalendarReviewHash(calendarVisit.id,body),source_withheld:false,workspace,source:{entry_id:calendarUuid(5),source_sha256:await googleCalendarSourceHash(receipt,event),content_sha256:await calendarSha(content)}};
}
export async function calendarBody(receipt:GoogleCalendarReceipt,eventId='invented-timed'):Promise<GoogleCalendarReviewRequest>{return {expected_revision:5,idempotency_key:calendarUuid(8),observation_id:receipt.observation_id,observation_sha256:receipt.source_sha256,event_id:eventId,event_sha256:await googleCalendarEventHash(receipt.observation.items.find(e=>e.id===eventId)!),reviewed_visit:true,reviewed_exact_summary:true,reviewed_untrusted_source:true};}
