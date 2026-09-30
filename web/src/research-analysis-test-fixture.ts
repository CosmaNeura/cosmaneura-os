import type {ConversationInput,Workspace} from './workspace-api';
import type {ResearchAnalysis,ResearchEvidenceAnchor} from './research-analysis-contract';
import {modelUuid,modelTimestamp,conversationFixture,pendingWorkspace} from './model-work-test-fixture';
import {researchDigest,type ResearchObservation,type ResearchResult,type ResearchSave,type ResearchSaved,type ResearchSearch} from './research-contract';
import {researchSavedText} from './research-analysis-contract';
import previewSamples from './__fixtures__/research-analysis-preview.json';
export const analysisAnchor:ResearchEvidenceAnchor={entry_id:modelUuid(75),entry_revision:3,run_id:modelUuid(73),save_request_sha256:'a'.repeat(64)};
export const analysisSelection:ResearchAnalysis={version:1,consented:true,entries:[analysisAnchor]};
export const analysisBody:ConversationInput={...conversationFixture,role:modelUuid(72),content:'Compare the evidence and distinguish inference café β.',research_analysis:analysisSelection};
export const analysisWorkspace=(content='Invented saved public-source packet. No clinical evidence.'):Workspace=>({id:modelUuid(71),appointment_id:modelUuid(72),label:'Invented source analysis',revision:3,work_candidates:[],entries:[{id:analysisAnchor.entry_id,revision:3,kind:'evidence',content,source_label:'Public Research sources',origin:'human',ticket:null,created_at:modelTimestamp}]});
export async function analysisProjection(){const value=await pendingWorkspace(analysisBody,'unknown');const metadata=value.entries[0].model_request!;if(metadata.request.kind!=='conversation')throw new Error('Expected invented conversation');metadata.request={...metadata.request,research_analysis:structuredClone(analysisSelection)};metadata.bot={...metadata.bot,role:'research',name:'Research'};return value;}

export async function analysisProofFixture(records=structuredClone(previewSamples.cases[2].records) as ResearchResult[]){
 const request:ResearchSearch={contract_version:1,idempotency_key:modelUuid(74),expected_revision:2,team_revision:1,bot:analysisBody.role,topic:'trials',sources:['clinical_trials'],query:previewSamples.query,public_query_confirmed:true};
 const run:ResearchObservation={contract:'research.lookup.v1',workspace_id:modelUuid(71),run_id:modelUuid(73),idempotency_key:request.idempotency_key,request_sha256:await researchDigest(request),request,bot:request.bot,topic:request.topic,query:request.query,sources:request.sources,created_at:modelTimestamp,state:'completed',results:records,errors:[]};
 const save:ResearchSave={contract_version:1,idempotency_key:modelUuid(76),expected_revision:2,source_hashes:records.map(record=>record.sha256)};
 const saved:ResearchSaved={contract:'research.saved.v1',workspace_id:run.workspace_id,run_id:run.run_id,idempotency_key:save.idempotency_key,request_sha256:await researchDigest(save),request:save,entry_id:modelUuid(75),entry_revision:3};
 const anchor:ResearchEvidenceAnchor={entry_id:saved.entry_id,entry_revision:saved.entry_revision,run_id:saved.run_id,save_request_sha256:saved.request_sha256};
 const workspace=analysisWorkspace(researchSavedText(records));workspace.entries[0].source_label='Research · public source excerpts';
 return {workspace,run,saved,anchor};
}
