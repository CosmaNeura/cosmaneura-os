import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import type {Workspace} from '../src/workspace-api';
import {researchAnalysisPreview} from '../src/research-analysis-contract';
import {researchBotId,researchIdentity,researchRequest,researchWorkspaceId} from '../src/research-test-fixture';
import {researchRehearsal} from './research';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let workspace:Workspace;
const open=(reset=false)=>researchRehearsal(()=>workspace,value=>{workspace=value;},'invented-research-test',reset,researchBotId);
beforeEach(()=>{vi.stubGlobal('crypto',webcrypto);sessionStorage.clear();history.replaceState(null,'','/');workspace={id:researchWorkspaceId,appointment_id:null,label:'Invented visit',revision:2,entries:[],work_candidates:[],follow_ups:[]};});
afterEach(()=>{vi.unstubAllGlobals();history.replaceState(null,'','/');});
async function selected(port= open()){
 const request=researchRequest(),run=await port.search(researchIdentity,workspace.id,request);
 const body={contract_version:1 as const,idempotency_key:crypto.randomUUID(),expected_revision:workspace.revision,source_hashes:run.results.map(result=>result.sha256)};
 return {port,run,body};
}
it('stores an exact source packet which the production Research proof verifier accepts',async()=>{
 const {port,run,body}=await selected();const saved=await port.save(researchIdentity,workspace.id,run.run_id,body);
 const anchor={entry_id:saved.entry_id,entry_revision:saved.entry_revision,run_id:run.run_id,save_request_sha256:saved.request_sha256};
 expect(await researchAnalysisPreview(workspace,anchor,run,saved,researchBotId)).toContain('Invented source excerpt');
 expect(workspace.entries[0].revision).toBe(workspace.revision);expect(workspace.entries[0].source_label).toBe('Research · public source excerpts');
 workspace.entries[0].content+=' Changed after save';expect(await researchAnalysisPreview(workspace,anchor,run,saved,researchBotId)).toBeNull();
});
it('resolves a lost save after a fixture reload without repeating the lookup or writing another source',async()=>{
 history.replaceState(null,'','/?research-scenario=lost-save-reply');const {port,run,body}=await selected();
 await expect(port.save(researchIdentity,workspace.id,run.run_id,body)).rejects.toMatchObject({status:503});
 const restored=open(),saved=await restored.resolveSave(researchIdentity,workspace.id,run.run_id,body);
 expect(workspace.entries).toHaveLength(1);expect(saved.entry_id).toBe(workspace.entries[0].id);
 const historyResult=await restored.history(researchIdentity,workspace.id,researchBotId),packets=await restored.savedHistory(researchIdentity,workspace.id,researchBotId);
 expect(historyResult.runs[0]).toEqual(run);expect(packets.packets[0].saved).toEqual(saved);
 expect((window as Window&{researchRehearsalStats?:unknown}).researchRehearsalStats).toMatchObject({searches:0,saves:0,resolveSaves:1,externalCalls:0});
});
it('rejects another workspace and a changed exact save request during recovery',async()=>{
 const {port,run,body}=await selected();await port.save(researchIdentity,workspace.id,run.run_id,body);const restored=open();
 await expect(restored.resolveSave(researchIdentity,crypto.randomUUID(),run.run_id,body)).rejects.toMatchObject({status:404});
 await expect(restored.resolveSave(researchIdentity,workspace.id,run.run_id,{...body,source_hashes:['a'.repeat(64)]})).rejects.toThrow();
 await expect(restored.history(researchIdentity,workspace.id,crypto.randomUUID())).rejects.toMatchObject({status:404});
 expect(workspace.entries).toHaveLength(1);
});
it('does not create a source from a stale revision or a hash absent from the retained lookup',async()=>{
 const {port,run,body}=await selected();await expect(port.save(researchIdentity,workspace.id,run.run_id,{...body,expected_revision:1})).rejects.toMatchObject({status:409});
 await expect(port.save(researchIdentity,workspace.id,run.run_id,{...body,source_hashes:['a'.repeat(64)]})).rejects.toMatchObject({status:422});
 expect(workspace.entries).toHaveLength(0);
});
