// Scripted service boundaries for usability walkthroughs; no live STT claim.
import type {CaptureDraft,CaptureNoteTemplate} from '../src/capture-notes-api';
import type {CreatorReviewView} from '../../clients/scribe-review/creator-review-api';
export const id=(n:number)=>`10000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export const sessionId=id(20),sourceId=id(21);
let note:CaptureDraft|null=null,uploaded=false;
const ref=(kind:string,n:number)=>kind+'_'+String(n).padStart(26,'0');
export function resetServices(){note=null;uploaded=false;}
export function creatorReviewApi(){return {read:async()=>{await new Promise(r=>setTimeout(r,100));return {
  schema_version:'1.0',session_id:sessionId,status:'transcript_ready',translation_progress:[],
  source:{source_transcript_version:1,segments:[{source_segment_id:id(22),source_segment_version:1,source_locale:'en-US',speaker_role:'clinician',start_ms:0,end_ms:19000,content:'This is a synthetic Scribe test. No patient information. The provider will review the draft before saving.'}]},
  working:{source_transcript_version:1,working_transcript_id:sourceId,working_transcript_version:1,note_ready:true,blockers:[],segments:[{source_segment_id:id(22),source_segment_version:1,resolution:'english_source',content:'This is a synthetic Scribe test. No patient information. The provider will review the draft before saving.'}]},
  review_queue:{schema_version:'1.0',session_id:sessionId,source_transcript_version:1,working_transcript_id:sourceId,working_transcript_version:1,status:'complete',items:[]},
} as unknown as CreatorReviewView;},decide:async()=>{throw Error('No translation decisions in English example');}};}
export async function captureNoteTemplates():Promise<CaptureNoteTemplate[]>{return [{schema_ref:ref('doctor_note_schema',1),note_type:'SOAP note',field_names:['Subjective','Objective','Assessment','Plan']}];}
function blank():CaptureDraft{return {session_id:sessionId,scribe_source_id:sourceId,source_sha256:'b'.repeat(64),schema_ref:ref('doctor_note_schema',1),transcript_ref:null,note_ref:null,status:'not_prepared',note_type:'SOAP note',fields:null,field_order:null,note_sha256:null,created_at:null,review_required:true};}
export async function captureDraft(_workspace:string,_session:string,_source:string,_identity:unknown,_schema:string,action:string){
  if(action==='prepare'&&!note)note={...blank(),status:'draft',transcript_ref:ref('ai_visit_transcript',1),note_ref:ref('visit_note',1),fields:{Subjective:'Synthetic recording; no patient information.',Objective:'No examination findings stated.',Assessment:'Synthetic Scribe workflow.',Plan:'Provider to review and save this draft.'},field_order:['Subjective','Objective','Assessment','Plan'],note_sha256:'c'.repeat(64),created_at:new Date().toISOString()};
  return structuredClone(note??blank());
}
export async function saveCaptureDraft(_workspace:string,_identity:unknown,base:CaptureDraft,fields:Record<string,string>){note={...base,fields:structuredClone(fields),note_ref:ref('visit_note',2),note_sha256:'d'.repeat(64)};return structuredClone(note);}
export async function validateDraft(v:CaptureDraft){return v;}
export async function resolveCaptureSave(){throw Error('No uncertain saves in this example');}
export async function openSavedRecordingRuntime(options:{admitted:{session_id:string};chunks:number}){
  let state=uploaded?'processing':'ready',count=uploaded?options.chunks:0;const listeners=new Set<(v:unknown)=>void>();
  const snapshot=()=>({state,sessionId:options.admitted.session_id,statusCode:'saved_import',recordedChunks:count,queuedChunks:0,elapsedSeconds:19,remainingBudgetSeconds:null,remainingAuthoritySeconds:null,transcriptionStatus:null,transcript:null});
  const publish=()=>{for(const f of listeners)f(snapshot());};
  return {controller:{get snapshot(){return snapshot();},subscribe:(f:(v:unknown)=>void)=>{listeners.add(f);f(snapshot());return()=>listeners.delete(f);}},reviewOnly:uploaded,
    transcribe:async()=>{state='uploading';publish();for(let i=0;i<options.chunks;i++){await new Promise(r=>setTimeout(r,200));count++;publish();}uploaded=true;state='processing';publish();},
    releaseUploadedCapture:async()=>{},close:async()=>{listeners.clear();}};
}
