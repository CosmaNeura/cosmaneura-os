import {ehrHash,ehrProvider,ehrProviderFields,ehrSourceLabel,ehrItemHash,ehrSourceHash,ehrSourceContent,ehrContentHash,ehrReviewHash,type EhrReceipt,type EhrReviewRequest,type EhrReviewResponse,type EhrWindowItem,type EhrVerifiedItem,type EhrCommand,type EhrProblemsRequest,type EhrProblemList,type EhrMedicationsRequest,type EhrMedicationList,type EhrMedication} from './ehr-read-api';
export const ehrUuid=(n:number)=>`00000000-0000-4000-8000-${n.toString().padStart(12,'0')}`;
export const ehrScope={box_id:ehrUuid(101),owner_id:ehrUuid(102),workspace_id:ehrUuid(103)};
export const ehrVisit={id:ehrScope.workspace_id,label:'Invented Mira visit',revision:5};
export const ehrBinding={connection_id:ehrUuid(104),binding_sha256:'b'.repeat(64)};
export const ehrPractice={label:'Invented Maple practice',timezone:'America/Los_Angeles'};
export async function ehrWindowReceipt(command?:EhrCommand):Promise<EhrReceipt>{
 const item:EhrWindowItem={handle:ehrUuid(201),sha256:'',starts_at:'2026-10-25T13:00:00Z',ends_at:'2026-10-25T13:30:00Z',status:'Scheduled',selectable:true};item.sha256=await ehrItemHash(item);
 const observation={kind:'window' as const,provider:ehrProvider(command??{}),mode:'synthetic' as const,practice:ehrPractice,observed_at:'2026-10-25T12:00:00Z',window:{starts_at:command?.action==='observe'?command.starts_at:'2026-10-25T12:00:00Z',ends_at:command?.action==='observe'?command.ends_at:'2026-10-26T12:00:00Z'},coverage:command?.provider==='tebra'?'returned_rows_only' as const:'more_rows_available' as const,items:[item]};
 return {contract_version:1,...ehrProviderFields(ehrProvider(command??{})),...(command?.provider==='tebra'?{transport:'mock' as const}:{}),...ehrBinding,observation_id:ehrUuid(202),observation_key:command?.idempotency_key??ehrUuid(203),source_sha256:'c'.repeat(64),payload_sha256:await ehrHash(observation),observation};
}
export async function ehrVerifiedReceipt(anchor:EhrReceipt,command?:EhrCommand):Promise<EhrReceipt>{
 if(anchor.observation.kind!=='window')throw new Error('Expected window');const {selectable:_,...original}=anchor.observation.items[0];
 const item:EhrVerifiedItem={...original,patient:anchor.observation.provider==='tebra'?{full_name:'Mira Invented',birth_date:'1980-02-03'}:{first_name:'Mira',last_name:'Invented',birth_date:'1980-02-03'}};item.sha256=await ehrItemHash(item);
 const {items:__,...base}=anchor.observation,observation={...base,kind:'verified_visit' as const,item};
 return {...anchor,observation_id:ehrUuid(204),observation_key:command?.idempotency_key??ehrUuid(205),source_sha256:'d'.repeat(64),payload_sha256:await ehrHash(observation),observation};
}
export function ehrReviewBody(anchor:EhrReceipt):EhrReviewRequest{
 if(anchor.observation.kind==='window')throw new Error('Expected patient');return {...ehrProviderFields(anchor.observation.provider),expected_revision:ehrVisit.revision,idempotency_key:ehrUuid(206),observation_id:anchor.observation_id,observation_sha256:anchor.source_sha256,item_handle:anchor.observation.item.handle,item_sha256:anchor.observation.item.sha256,reviewed_visit:true,reviewed_patient_identity:true,reviewed_exact_snapshot:true,reviewed_untrusted_source:true};
}
export async function ehrReviewResult(anchor:EhrReceipt,body:EhrReviewRequest):Promise<EhrReviewResponse>{
 if(anchor.observation.kind==='window')throw new Error('Expected patient');const content=ehrSourceContent(anchor.observation),entry_id=ehrUuid(207);
 return {...ehrProviderFields(anchor.observation.provider),...(anchor.observation.provider==='tebra'?{transport:'mock' as const}:{}),entry_id,entry_revision:body.expected_revision+1,request_sha256:await ehrReviewHash(ehrVisit.id,body),source_withheld:false,source:{entry_id,source_sha256:await ehrSourceHash(anchor,anchor.observation.item),content_sha256:await ehrContentHash(content)},workspace:{id:ehrVisit.id,label:ehrVisit.label,appointment_id:null,revision:body.expected_revision+1,entries:[{id:entry_id,kind:'ehr_read_source',revision:body.expected_revision+1,source_label:ehrSourceLabel(anchor.observation),content,origin:'authenticated_human',created_at:'2026-10-25T12:00:00Z',ticket:null,ehr_source_state:'current'}],work_candidates:[],model_contract_version:1,model_observed_at:'2026-10-25T12:00:00Z'}};
}

export function ehrProblemsCommand(anchor:EhrReceipt):EhrProblemsRequest{
 if(anchor.observation.kind!=='verified_visit'||anchor.observation.provider!=='elation')throw new Error('Expected Elation verified visit');
 return {action:'problems',connection_id:anchor.connection_id,binding_sha256:anchor.binding_sha256,observation_id:anchor.observation_id,observation_sha256:anchor.source_sha256,item_handle:anchor.observation.item.handle,item_sha256:anchor.observation.item.sha256,idempotency_key:ehrUuid(210)};
}
export async function ehrProblemsReceipt(anchor:EhrReceipt,command:EhrCommand=ehrProblemsCommand(anchor),problems:EhrProblemList={coverage:'more_rows_available',total_count:3,items:[{description:'Invented seasonal concern',status:'Active',start_date:'2025-01-02',resolved_date:null,verification_status:'unconfirmed'},{description:'Invented prior concern',status:'Resolved',start_date:'2024-02-03',resolved_date:'2024-03-04',verification_status:'entered_in_error'}]}):Promise<EhrReceipt>{
 if(anchor.observation.kind!=='verified_visit'||anchor.observation.provider!=='elation')throw new Error('Expected Elation verified visit');
 const item={...anchor.observation.item,problems};item.sha256=await ehrItemHash(item);
 const observation={...anchor.observation,provider:'elation' as const,kind:'verified_problems' as const,parent:{observation_id:anchor.observation_id,source_sha256:anchor.source_sha256,item_sha256:anchor.observation.item.sha256},item};
 return {...anchor,observation_id:ehrUuid(211),observation_key:command.idempotency_key,source_sha256:'e'.repeat(64),payload_sha256:await ehrHash(observation),observation};
}

export const ehrMedicationRow:EhrMedication={medication_name:'Invented medication record',strength:'Recorded strength',route:'Recorded route',form:'Recorded form',directions:'Invented directions, line one.\nInvented directions, line two.',medication_type:'historical',order_type:'Prescription',is_doc_med:false,is_permanent:true,start_date:'2025-01-02',document_date:'2025-01-02T09:15:00',signed_date:'2025-01-02T09:20:00.123456-05:00',deleted_date:null,discontinue_date:null,signature_state:'date_recorded',discontinuation_state:'no_date_recorded',deletion_state:'unknown'};
export const ehrMedicationRows:EhrMedication[]=[ehrMedicationRow,{...ehrMedicationRow,medication_name:'Invented historical record',strength:null,route:null,form:null,directions:null,medication_type:'discontinued',order_type:null,is_doc_med:null,is_permanent:false,start_date:null,document_date:null,signed_date:null,discontinue_date:'2025-03-04',signature_state:'unknown',discontinuation_state:'date_recorded',deletion_state:'no_date_recorded'}];
export function ehrMedicationsCommand(anchor:EhrReceipt):EhrMedicationsRequest{
 if(anchor.observation.kind!=='verified_visit'||anchor.observation.provider!=='elation')throw new Error('Expected Elation verified visit');
 return {action:'medications',connection_id:anchor.connection_id,binding_sha256:anchor.binding_sha256,observation_id:anchor.observation_id,observation_sha256:anchor.source_sha256,item_handle:anchor.observation.item.handle,item_sha256:anchor.observation.item.sha256,idempotency_key:ehrUuid(220)};
}
export async function ehrMedicationsReceipt(anchor:EhrReceipt,command:EhrCommand=ehrMedicationsCommand(anchor),medications:EhrMedicationList={coverage:'more_rows_available',total_count:3,items:structuredClone(ehrMedicationRows)}):Promise<EhrReceipt>{
 if(anchor.observation.kind!=='verified_visit'||anchor.observation.provider!=='elation')throw new Error('Expected Elation verified visit');
 const item={...anchor.observation.item,medications};item.sha256=await ehrItemHash(item);
 const observation={...anchor.observation,provider:'elation' as const,kind:'verified_medications' as const,parent:{observation_id:anchor.observation_id,source_sha256:anchor.source_sha256,item_sha256:anchor.observation.item.sha256},item};
 return {...anchor,observation_id:ehrUuid(221),observation_key:command.idempotency_key,source_sha256:'f'.repeat(64),payload_sha256:await ehrHash(observation),observation};
}
