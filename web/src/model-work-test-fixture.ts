import type {ConversationInput,HandoffRetryInput,Workspace} from './workspace-api';
import {modelRequestHash,type AdmissionObservation,type HandoffRetryObservation,type ModelRequestObservation} from './model-work-request';
export const modelUuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export const modelTimestamp='2026-09-21T22:00:00Z';
export const conversationFixture:ConversationInput={expected_revision:1,team_revision:1,idempotency_key:'invented-model-key',role:'visit_prep',content:'Invented saved question'};
export const admissionFixture=(state:AdmissionObservation['state']='reserved'):AdmissionObservation=>({id:modelUuid(501),state,unit:1,admitted_at:modelTimestamp,
  dispatch:state==='reserved'||state==='abandoned'?'not_started':state==='unknown'?'unconfirmed':'started',usage:'unknown',input_tokens:null,output_tokens:null});
export async function modelReceipt(body:ConversationInput=conversationFixture,id=modelUuid(71),revision=2):Promise<ModelRequestObservation>{return {contract_version:1,workspace_id:id,
  idempotency_key:body.idempotency_key,request_sha256:await modelRequestHash(body),outcome:'saved',admission:null,saved_entry:{id:modelUuid(601),revision},reason:null};}
export async function retryReceipt(body:HandoffRetryInput,id:string,handoffId:string):Promise<HandoffRetryObservation>{return {contract_version:1,workspace_id:id,handoff_id:handoffId,previous_attempt_id:body.previous_attempt_id,
  idempotency_key:body.idempotency_key,request_sha256:await modelRequestHash(body),outcome:'recorded',recorded:{attempt_id:modelUuid(703),attempt_number:2,recorded_at:modelTimestamp,
    workspace_revision:body.expected_revision,status:'queued',result_entry:null,admission:admissionFixture(),coverage:'durable_admission',reason:null}};}
export async function pendingWorkspace(body:ConversationInput=conversationFixture,state:AdmissionObservation['state']='reserved'):Promise<Workspace&{appointment_id:string}>{return {id:modelUuid(71),appointment_id:modelUuid(72),label:'Invented model visit',revision:2,
  model_contract_version:1,model_observed_at:modelTimestamp,work_candidates:[],entries:[{id:modelUuid(601),revision:2,kind:'conversation',content:body.content,source_label:null,origin:'human',ticket:null,created_at:modelTimestamp,
    model_request:{contract_version:1,request_sha256:await modelRequestHash(body),request:{kind:'conversation',expected_revision:body.expected_revision,team_revision:body.team_revision,idempotency_key:body.idempotency_key,role:body.role},
      bot:{address:body.role,agent_id:modelUuid(102),role:'visit_prep',name:'Visit Prep',team_revision:body.team_revision},admission:admissionFixture(state),reason:state==='unknown'?'dispatch_interrupted':state==='abandoned'?'reservation_expired':null}}]};}
