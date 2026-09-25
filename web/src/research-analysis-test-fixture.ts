import type {ConversationInput,Workspace} from './workspace-api';
import type {ResearchAnalysis,ResearchEvidenceAnchor} from './research-analysis-contract';
import {modelUuid,modelTimestamp,conversationFixture,pendingWorkspace} from './model-work-test-fixture';
export const analysisAnchor:ResearchEvidenceAnchor={entry_id:modelUuid(75),entry_revision:3,run_id:modelUuid(73),save_request_sha256:'a'.repeat(64)};
export const analysisSelection:ResearchAnalysis={version:1,consented:true,entries:[analysisAnchor]};
export const analysisBody:ConversationInput={...conversationFixture,role:modelUuid(72),content:'Compare the evidence and distinguish inference café β.',research_analysis:analysisSelection};
export const analysisWorkspace=(content='Invented saved public-source packet. No clinical evidence.'):Workspace=>({id:modelUuid(71),appointment_id:modelUuid(72),label:'Invented source analysis',revision:3,work_candidates:[],entries:[{id:analysisAnchor.entry_id,revision:3,kind:'evidence',content,source_label:'Public Research sources',origin:'human',ticket:null,created_at:modelTimestamp}]});
export async function analysisProjection(){const value=await pendingWorkspace(analysisBody,'unknown');const metadata=value.entries[0].model_request!;if(metadata.request.kind!=='conversation')throw new Error('Expected invented conversation');metadata.request={...metadata.request,research_analysis:structuredClone(analysisSelection)};metadata.bot={...metadata.bot,role:'research',name:'Research'};return value;}
