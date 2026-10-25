import {WorkspaceApiError,type Workspace} from '../src/workspace-api';
import type {ResearchPort} from '../src/research-api';
import {validateResearchObservation,validateResearchSaved,type ResearchObservation,type ResearchSaved,type ResearchSavedPacket} from '../src/research-contract';
import {researchCatalog,researchObservation,researchSaved} from '../src/research-test-fixture';
import {researchSavedText} from '../src/research-analysis-contract';

/** Invented tab-owned server state. No request leaves this rehearsal. */
export function researchRehearsal(read:()=>Workspace,write:(workspace:Workspace)=>void,storageKey:string,reset:boolean,bot:string):ResearchPort {
 const key=storageKey+':research',stored=reset?null:sessionStorage.getItem(key);
 const state: {runs:ResearchObservation[];packets:ResearchSavedPacket[];receipts:[string,ResearchObservation|ResearchSaved][];lostSaveReply:boolean}=stored?JSON.parse(stored):{runs:[],packets:[],receipts:[],lostSaveReply:false};
 const receipts=new Map(state.receipts),persist=()=>{state.receipts=[...receipts];sessionStorage.setItem(key,JSON.stringify(state));};
 const stats={searches:0,saves:0,resolveSearches:0,resolveSaves:0,historyReads:0,packetReads:0,externalCalls:0};Object.assign(window,{researchRehearsalStats:stats});
 const check=(workspace:string,address=bot)=>{if(workspace!==read().id||address!==bot)throw new WorkspaceApiError(404);};
 const page=<T,>(items:T[],before:string|undefined,id:(item:T)=>string)=>{const index=before?items.findIndex(item=>id(item)===before):-1;if(before&&index<0)throw new WorkspaceApiError(404);return structuredClone(items.slice(index+1,index+6));};
 persist();
 return {
  catalog:async()=>researchCatalog(),
  history:async(_identity,workspace,address,_signal,before)=>{check(workspace,address);stats.historyReads++;return {contract:'research.history.v1',runs:page(state.runs,before,item=>item.run_id)};},
  savedHistory:async(_identity,workspace,address,_signal,before)=>{check(workspace,address);stats.packetReads++;return {contract:'research.saved_history.v1',workspace_id:workspace,bot,packets:page(state.packets,before,item=>item.saved.entry_id)};},
  search:async(_identity,workspace,body)=>{
   check(workspace,body.bot);stats.searches++;
   const prior=receipts.get(body.idempotency_key);if(prior)return validateResearchObservation(structuredClone(prior),workspace,body,bot);
   if(body.expected_revision!==read().revision)throw new WorkspaceApiError(409);
   const result=await validateResearchObservation({...await researchObservation(body),workspace_id:workspace,run_id:crypto.randomUUID()},workspace,body,bot);
   state.runs.unshift(result);receipts.set(body.idempotency_key,result);persist();return structuredClone(result);
  },
  resolve:async(_identity,workspace,body)=>{
   check(workspace,body.bot);stats.resolveSearches++;const result=receipts.get(body.idempotency_key);if(!result)throw new WorkspaceApiError(404,'research_not_found');
   return validateResearchObservation(structuredClone(result),workspace,body,bot);
  },
  save:async(_identity,workspace,run,body)=>{
   check(workspace);stats.saves++;const prior=receipts.get(body.idempotency_key);if(prior)return validateResearchSaved(structuredClone(prior),workspace,run,body);
   const current=read();if(body.expected_revision!==current.revision)throw new WorkspaceApiError(409);
   const observation=state.runs.find(item=>item.run_id===run&&item.bot===bot);if(!observation)throw new WorkspaceApiError(404);
   const selected=body.source_hashes.map(hash=>observation.results.find(item=>item.sha256===hash));if(selected.some(item=>!item))throw new WorkspaceApiError(422);
   const result=await validateResearchSaved({...await researchSaved(body),workspace_id:workspace,run_id:run,entry_id:crypto.randomUUID()},workspace,run,body);
   const next=structuredClone(current);next.revision=result.entry_revision;next.entries.push({id:result.entry_id,revision:result.entry_revision,kind:'evidence',content:researchSavedText(selected.filter(item=>item!==undefined)),source_label:'Research · public source excerpts',origin:'synthetic_fixture',ticket:null,created_at:new Date().toISOString()});
   write(next);state.packets.unshift({query:observation.query,saved:result});receipts.set(body.idempotency_key,result);persist();
   if(new URLSearchParams(location.search).get('research-scenario')==='lost-save-reply'&&!state.lostSaveReply){state.lostSaveReply=true;persist();throw new WorkspaceApiError(503);}
   return structuredClone(result);
  },
  resolveSave:async(_identity,workspace,run,body)=>{
   check(workspace);stats.resolveSaves++;const result=receipts.get(body.idempotency_key);if(!result)throw new WorkspaceApiError(404,'research_not_found');
   return validateResearchSaved(structuredClone(result),workspace,run,body);
  },
 };
}
