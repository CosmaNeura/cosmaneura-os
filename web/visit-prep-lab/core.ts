import fixture from '../../tests/fixtures/visit-prep-ready.json';
import type {VisitPrepCommand,VisitPrepListCommand,VisitPrepReceipt,VisitPrepSelections} from '../src/visit-prep-contract';
import {validateVisitPrep,validateVisitPrepSelections} from '../src/visit-prep-contract';

const selections=[
  {preparation_ref:fixture.preparation_ref,recipient_first_name:'Rowan (invented)',recipient_role:'patient' as const,
    scheduled_at:'2026-10-09T14:00:00Z',timezone_name:'America/New_York',lifecycle_state:'completed' as const,
    chart_linked:false,available_to_open:true,created_at:'2026-10-01T15:00:00Z'},
  {preparation_ref:'visit_prep_00000000000000000000000002',recipient_first_name:'Ellis (invented)',recipient_role:'caregiver' as const,
    scheduled_at:'2026-10-09T15:00:00Z',timezone_name:'America/New_York',lifecycle_state:'in_progress' as const,
    chart_linked:false,available_to_open:true,created_at:'2026-10-01T14:00:00Z'},
];
export const coreConnectionApi={read:async()=>({connection_status:'connected',discovery:{connection:{connection_sha256:fixture.connection_sha256}}})};
export async function listVisitPrep(_identity:unknown,command:VisitPrepListCommand):Promise<VisitPrepSelections>{
  return validateVisitPrepSelections({contract_version:'1',connection_sha256:command.connection_sha256,workspace_id:command.workspace_id,
    request_nonce:command.request_nonce,checked_at:new Date().toISOString(),next_before_ref:null,preparations:selections},command);
}
export async function readVisitPrep(_identity:unknown,command:VisitPrepCommand):Promise<VisitPrepReceipt>{
  const value=structuredClone(fixture) as VisitPrepReceipt;
  Object.assign(value,{preparation_ref:command.preparation_ref,connection_sha256:command.connection_sha256,
    workspace_id:command.workspace_id,request_nonce:command.request_nonce,checked_at:new Date().toISOString()});
  value.package.sources.package_id=command.preparation_ref;
  value.package.sources.preparation.id=command.preparation_ref;
  value.package.sources.preparation.scheduled_at=selections.find(p=>p.preparation_ref===command.preparation_ref)!.scheduled_at;
  if(command.preparation_ref!==fixture.preparation_ref){
    value.package.status='missing';value.package.brief=null;value.package.version=null;
    Object.assign(value.package,{build_status:'not_requested',artifact_id:null,recorded_at:null,retry_at:null});
    value.package.sources.actor_role='caregiver';value.package.sources.current_answers_reviewed=false;
    value.package.sources.current_answers_complete=false;
    Object.assign(value.package.sources,{current_review_id:null,reviewed_at:null,missing_question_keys:[value.package.sources.topics[0].question_key]});
    const story=value.package.sources.topics.find(t=>t.kind==='story')!;story.answer='Invented caregiver report: walking has become harder this week.';
    value.package.sources.topics[0].response_kind=null;value.package.sources.topics[0].answer=null;
  }
  return validateVisitPrep(value,command);
}
