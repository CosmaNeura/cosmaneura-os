import {DraftStoreError} from './draft-store';
import {teamClosed,teamText,teamUuid} from './team-setup-request';
import {schedulingPatientRequestHash,validSchedulingPatientCommand,validSchedulingPatientDate,validateSchedulingPatientReceipt,
 type SchedulingPatientCommand,type SchedulingPatientReceipt,type SchedulingPatientChoice} from './scheduling-patient-api';
export type SchedulingPatientRecovery={version:1;workspace_id:string;appointment_id:string;query:string;birth_date:string|null;selected_choice_ref:string|null;
  pending:SchedulingPatientCommand|null;preview:SchedulingPatientReceipt|null;saved:SchedulingPatientReceipt|null};
export const emptySchedulingPatientRecovery=(workspaceId:string,appointmentId:string):SchedulingPatientRecovery=>({version:1,workspace_id:workspaceId,appointment_id:appointmentId,
 query:'',birth_date:null,selected_choice_ref:null,pending:null,preview:null,saved:null});
const invalid=():never=>{throw new DraftStoreError('integrity');};
export async function validateSchedulingPatientRecovery(value:unknown,workspaceId:string):Promise<SchedulingPatientRecovery>{
 if(!teamClosed(value,'version,workspace_id,appointment_id,query,birth_date,selected_choice_ref,pending,preview,saved')||value.version!==1||value.workspace_id!==workspaceId||
  !teamUuid(value.workspace_id)||!teamUuid(value.appointment_id)||!teamText(value.query,120)||/[\u0000-\u001f\u007f]/.test(value.query)||!validSchedulingPatientDate(value.birth_date)||
  value.selected_choice_ref!==null&&!teamUuid(value.selected_choice_ref)||new TextEncoder().encode(JSON.stringify(value)).byteLength>32768)return invalid();
 const v=structuredClone(value) as SchedulingPatientRecovery;
 if(v.preview!==null){v.preview=await validateSchedulingPatientReceipt(v.preview);if(v.preview.kind!=='preview'||v.preview.status==='not_found')return invalid();}
 if(v.saved!==null){v.saved=await validateSchedulingPatientReceipt(v.saved);if(v.saved.kind!=='confirm'||v.saved.status!=='saved')return invalid();}
 if(v.selected_choice_ref!==null&&!v.preview?.preview?.choices.some(c=>c.choice_ref===v.selected_choice_ref))return invalid();
 if(v.pending!==null){
  if(!validSchedulingPatientCommand(v.pending))return invalid();
  if(v.pending.action==='preview'&&(v.pending.search.query!==v.query.trim()||v.pending.search.birth_date!==v.birth_date))return invalid();
  if(v.pending.action==='confirm'){
   const p=v.preview;
   const command=v.pending,selected=p?.preview?.choices.find(c=>c.choice_ref===command.choice_ref);
   if(!p||p.request_id!==v.pending.preview_id||p.source_sha256!==v.pending.preview_sha256||!selected||selected.identity_sha256!==v.pending.identity_sha256||v.selected_choice_ref!==selected.choice_ref)return invalid();
  }
 }
 if(v.saved&&!v.saved.source_withheld){
  const choice=v.preview?.preview?.choices.find(c=>c.choice_ref===v.selected_choice_ref);
  if(!choice||!v.saved.mapping||v.saved.mapping.identity_sha256!==choice.identity_sha256||v.saved.mapping.subject_revision!==choice.subject_revision)return invalid();
 }
 return v;
}
export async function schedulingPatientReceiptMatches(receipt:SchedulingPatientReceipt,workspaceId:string,command:SchedulingPatientCommand):Promise<boolean>{
 return receipt.kind===command.action&&receipt.request_key===command.idempotency_key&&receipt.status!=='not_found'&&receipt.request_sha256===await schedulingPatientRequestHash(workspaceId,command);
}
export function schedulingPatientSelected(record:SchedulingPatientRecovery):SchedulingPatientChoice|null{
 return record.preview?.preview?.choices.find(c=>c.choice_ref===record.selected_choice_ref)??null;
}
