import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {noteResearchWorkspace} from './note-research-test-fixture';
import {noteResearchQuestionSelection,noteResearchSelectionMatches,validNoteResearchSelection,verifyNoteResearchPlan} from './note-research-workflow';
import {researchBotId} from './research-test-fixture';
import {validateResearchDraft} from './research-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));
afterEach(()=>vi.unstubAllGlobals());

it('verifies the exact saved-note and private assignment bytes before exposing questions',async()=>{
  const workspace=await noteResearchWorkspace(),plan=await verifyNoteResearchPlan(workspace,researchBotId);
  expect(plan?.directions).toContain('Private-only direction');
  expect(plan?.questions).toEqual([{content:'1. Confirm interaction evidence for Synthetic Person.\nGeneral public query: DrugA interaction evidence',proposedQuery:'DrugA interaction evidence'}]);
  expect(plan?.selection).toMatchObject({note_id:workspace.note!.latest!.id,note_version:1,source_fingerprint:workspace.note!.latest!.source_fingerprint,
    chief_entry_id:workspace.entries[1].id,handoff_id:workspace.handoffs![0].id,result_sha256:workspace.handoffs![0].result_sha256});
  const selection=noteResearchQuestionSelection(plan!,0)!;
  expect(validNoteResearchSelection(selection)).toBe(true);expect(noteResearchSelectionMatches(plan,selection)).toBe(true);
  expect(validateResearchDraft({version:1,bot:researchBotId,topic:'literature',query:'DrugA interaction evidence',sources:[],pending:null,note_question:selection},researchBotId)).toMatchObject({note_question:selection});
});
it.each(['note_bytes','new_note','transcript_change','assignment_source','assignment_origin','result_bytes','result_hash','wrong_bot','new_chief_directions','stale_review'] as const)('rejects changed %s without reusing an earlier assessment',async(change)=>{
  const w=await noteResearchWorkspace();
  if(change==='note_bytes'){w.note!.latest!.content+=' changed';const shared=JSON.parse(w.entries[0].content);shared.note.content=w.note!.latest!.content;w.entries[0].content=JSON.stringify(shared);}
  if(change==='new_note')w.note!.latest!.version=2;
  if(change==='transcript_change')w.note!.latest!.sources_changed=true;
  if(change==='assignment_source')w.handoffs![0].task_brief!.source_versions[0].sha256='a'.repeat(64);
  if(change==='assignment_origin')w.handoffs![0].task_brief!.depends_on.revision=1;
  if(change==='result_bytes')w.entries[2].reply!.content+=' changed';
  if(change==='result_hash')w.handoffs![0].result_sha256='a'.repeat(64);
  if(change==='wrong_bot')w.handoffs![0].recipient_agent_id='00000000-0000-4000-8000-000000000999';
  if(change==='new_chief_directions'){const newer=structuredClone(w.entries[1]);newer.id='00000000-0000-4000-8000-000000000999';newer.revision=5;const body=JSON.parse(newer.content);body.owner_directions='Changed directions';newer.content=JSON.stringify(body);w.entries.push(newer);w.revision=5;}
  if(change==='stale_review')w.handoffs![0].review_status='stale';
  expect(await verifyNoteResearchPlan(w,researchBotId)).toBeNull();
});
it.each(['unknown','private_words','index','hash','identity'] as const)('rejects malformed local query provenance: %s',async(change)=>{
  const plan=(await verifyNoteResearchPlan(await noteResearchWorkspace(),researchBotId))!,selection:Record<string,unknown>={...noteResearchQuestionSelection(plan,0)!};
  if(change==='unknown')selection.extra=true;
  if(change==='private_words')selection.note_content='Private words';
  if(change==='index')selection.question_index=12;
  if(change==='hash')selection.result_sha256='invalid';
  if(change==='identity')selection.note_id='invalid';
  expect(validNoteResearchSelection(selection)).toBe(false);
  expect(()=>validateResearchDraft({version:1,bot:researchBotId,topic:'literature',query:'General question',sources:[],pending:null,note_question:selection},researchBotId)).toThrow();
});
