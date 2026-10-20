import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {ClinicalTeamDraftsPanel} from './ClinicalTeamDraftsPanel';
import {CLINICAL_NOTE_LABEL,clinicalRequestDisplay,clinicalTeamRequest,currentSharedNote,noteSelection,verifyClinicalNoteShareReceipt,type SharedClinicalNote} from './clinical-team-contract';
import {EncounterSources} from './EncounterSources';
import {modelCanonical} from './model-work-request';
import {vendorSha256} from './vendor-contract';
import type {DraftHandoff,ProviderTeam,Workspace,WorkspaceEntry} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`,time='2026-10-20T14:00:00Z';
let host:HTMLDivElement,root:Root,workspace:Workspace,team:ProviderTeam;
const share=vi.fn(),ask=vi.fn(),review=vi.fn(),retry=vi.fn();
async function shared(w=workspace):Promise<Workspace>{
  const note=w.note!.latest!,body=noteSelection(note,w.revision,'invented-note-share');
  const snapshot:SharedClinicalNote={contract:'clinical-note-team-source.v1',request:body,note:{id:note.id,version:note.version,
    content:note.content,content_hash:note.content_hash,source_fingerprint:note.source_fingerprint}};
  const entry:WorkspaceEntry={id:id(4),revision:w.revision+1,kind:'conversation',content:modelCanonical(snapshot),source_label:CLINICAL_NOTE_LABEL,origin:'authenticated_human',ticket:null,created_at:time};
  return {...w,revision:w.revision+1,entries:[...w.entries,entry]};
}
const button=(text:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===text)!;
const click=(text:string)=>act(async()=>button(text).click());
const mount=()=>act(async()=>root.render(<ClinicalTeamDraftsPanel workspace={workspace} team={team} locked={false} onShare={share} onAskChief={ask} onReview={review} onRetry={retry}/>));
function chiefRequest() {
  const entry:WorkspaceEntry={id:id(10),revision:4,kind:'conversation',content:clinicalTeamRequest(currentSharedNote(workspace)!),source_label:null,origin:'authenticated_human',ticket:null,created_at:time,
    reply:{agent_name:'Chief',role:'chief',backend:'invented',content:'Saved private assignments',context_revision:3,citations:[]}};
  workspace.entries.push(entry);return entry;
}
function draft(role:'follow_up'|'research',n:number,originId:string,content:string):DraftHandoff {
  const entry:WorkspaceEntry={id:id(n+4),revision:n,kind:'handoff_result',content:'Saved task',source_label:null,origin:'agent_handoff',ticket:null,created_at:time,
    reply:{agent_name:role,agent_id:id(n+2),role,backend:'invented',content,context_revision:3,citations:[]}};
  workspace.entries.push(entry);
  return {id:id(n),origin_entry_id:originId,recipient_role:role,recipient_name:role,recipient_agent_id:id(n+2),brief:'Exact saved note',context_revision:3,
    status:'completed',attempt_id:id(n+3),attempt_count:1,result_entry_id:entry.id,result_sha256:'b'.repeat(64),error_code:null,attempts:[],review_status:'not_reviewed'};
}
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.stubGlobal('crypto',webcrypto);vi.clearAllMocks();
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
  const content='Subjective: Invented patient reports symptoms.\nAssessment: Current medicine list unavailable.\nPlan: Provider to confirm medicines. 界🩺';
  const note={id:id(3),version:1,workspace_revision:2,content,content_hash:await vendorSha256(new TextEncoder().encode(modelCanonical({content}))),source_reply_id:null,
    source_revision:1,source_fingerprint:'a'.repeat(64),sources_changed:false,created_at:time,review:null};
  workspace={id:id(1),appointment_id:id(2),label:'Invented encounter',revision:2,entries:[],work_candidates:[],note:{latest:note,history:[note]}};
  team={revision:1,template_version:'1',llm:{enabled:true,model:'invented'},members:[],configuration:{practice_context:'Invented',bots:['chief','follow_up','research'].map(role=>
    ({role:role as 'chief'|'follow_up'|'research',name:role,enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}))}};
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
it('requires full preview and explicit sharing, and only shows sharing after an acknowledged snapshot',async()=>{
  await mount();expect(share).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();expect(button('Share saved note with team').disabled).toBe(true);
  await click('Preview saved note for team');expect(host.querySelector('[role=group]')?.textContent).toContain(workspace.note!.latest!.content);
  expect(button('Share saved note with team').disabled).toBe(true);await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());
  await click('Share saved note with team');expect(share).toHaveBeenCalledOnce();expect(share.mock.calls[0][0]).toMatchObject({note_id:id(3),note_version:1,share_with_team:true});
  expect(JSON.stringify(share.mock.calls[0][0])).not.toContain('Invented patient');expect(ask).not.toHaveBeenCalled();expect(host.textContent).not.toContain('is shared with this private team');
  workspace=await shared();await mount();expect(host.textContent).toContain('version 1 is shared with this private team');
  await click('Ask Chief for follow-up and research drafts');expect(ask).toHaveBeenCalledExactlyOnceWith(clinicalTeamRequest(currentSharedNote(workspace)!));
  expect(ask.mock.calls[0][0]).not.toContain(workspace.note!.latest!.content);
});
it('invalidates preview consent and team source after a newer note or changed transcript',async()=>{
  await mount();await click('Preview saved note for team');await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());
  workspace={...workspace,note:{...workspace.note!,latest:{...workspace.note!.latest!,id:id(9),version:2}}};await mount();
  expect(host.querySelector('input')).toBeNull();expect(button('Share saved note with team').disabled).toBe(true);
  workspace=await shared();workspace.note!.latest!.sources_changed=true;await mount();
  expect(button('Ask Chief for follow-up and research drafts').disabled).toBe(true);expect(host.textContent).toContain('Reconcile and save');expect(currentSharedNote(workspace)).toBeNull();
});
it.each(['x'.repeat(20000),'界'.repeat(4000)])('preflights the exact persisted snapshot bound without shortening saved note text',async content=>{
  workspace.note!.latest!.content=content;workspace.note!.latest!.content_hash=await vendorSha256(new TextEncoder().encode(modelCanonical({content})));
  await mount();expect(host.textContent).toContain('too large for one team snapshot');await click('Preview saved note for team');
  expect(host.querySelector('pre')!.textContent).toBe(content);expect(host.querySelector<HTMLInputElement>('input')!.disabled).toBe(true);
  expect(button('Share saved note with team').disabled).toBe(true);expect(share).not.toHaveBeenCalled();
});
it.each(['unlinked','history_limit'])('does not offer an unusable saved-note share: %s',async boundary=>{
  if(boundary==='unlinked')workspace.appointment_id=null;else workspace.revision=500;
  await mount();await click('Preview saved note for team');
  expect(host.querySelector<HTMLInputElement>('input')!.disabled).toBe(true);expect(button('Share saved note with team').disabled).toBe(true);
  expect(button('Ask Chief for follow-up and research drafts').disabled).toBe(true);expect(share).not.toHaveBeenCalled();expect(ask).not.toHaveBeenCalled();
  expect(host.textContent).toContain(boundary==='unlinked'?'Connect this notebook to a visit':'saved-history limit');
});
it.each(['include_evidence','private_draft_handoff'] as const)('requires specialist source and draft grants: %s',async gate=>{
  workspace=await shared();const research=team.configuration.bots.find(b=>b.role==='research')!;
  if(gate==='include_evidence')research.include_evidence=false;else research.blocked_capabilities=['private_draft_handoff'];
  await mount();expect(button('Ask Chief for follow-up and research drafts').disabled).toBe(true);expect(ask).not.toHaveBeenCalled();
});
it('distinguishes both draft outcomes and only labels current accepted human review',async()=>{
  workspace=await shared();const content=clinicalTeamRequest(currentSharedNote(workspace)!);
  const origin:WorkspaceEntry={id:id(10),revision:4,kind:'conversation',content,source_label:null,origin:'authenticated_human',ticket:null,created_at:time,
    reply:{agent_name:'Chief',role:'chief',backend:'invented',content:'Two private assignments',context_revision:3,citations:[]}};
  workspace.entries.push(origin);workspace.handoffs=[{id:id(11),origin_entry_id:origin.id,recipient_role:'follow_up',recipient_name:'Follow-up',recipient_agent_id:id(12),brief:'Email and actions',
    context_revision:3,status:'completed',attempt_id:id(13),attempt_count:1,result_entry_id:id(15),result_sha256:'b'.repeat(64),error_code:null,attempts:[],review_status:'current',
    review:{id:id(14),attempt_id:id(13),result_entry_id:id(15),result_sha256:'b'.repeat(64),decision:'accepted',feedback:'',created_at:time}},
    {id:id(16),origin_entry_id:origin.id,recipient_role:'research',recipient_name:'Research',recipient_agent_id:id(17),brief:'Assess same note',context_revision:3,status:'queued',attempt_id:id(18),attempt_count:1,
      result_entry_id:null,result_sha256:null,error_code:null,attempts:[],review_status:'not_reviewed'}];
  workspace.entries.push({id:id(15),revision:5,kind:'handoff_result',content:'Email and actions',source_label:null,origin:'agent_handoff',ticket:null,created_at:time,
    reply:{agent_name:'Follow-up',agent_id:id(12),role:'follow_up',backend:'invented',content:'Private email draft and provider tasks.',context_revision:3,citations:[]}});
  await mount();expect(host.querySelector('[aria-label="Follow-up drafts"]')?.textContent).toContain('Accepted private draft');
  expect(host.querySelector('[aria-label="Research assessment"]')?.textContent).toContain('Draft queued');await click('Review follow-up draft');expect(review).toHaveBeenCalledWith(id(11));
  workspace.handoffs![0].review_status='stale';await mount();expect(host.textContent).not.toContain('Accepted private draft');expect(host.textContent).toContain('Source changed');
});
it('shows separate saved email, provider actions and research sections while retaining each complete draft',async()=>{
  workspace=await shared();const origin=chiefRequest();
  const email='## Patient email draft\n**Subject:** Your invented visit\n**Body:** Please confirm your medicines with your provider.\n\n## Provider action items\n- Proposed owner: provider. Confirm the current medicine list.';
  const research='## Provider treatment assessment\n## Source-supported findings\nThe saved note says the medicine list is unavailable.\n## Drug and treatment questions\nWhich medicines are currently taken?\n## Missing evidence / next checks\nCurrent drug evidence is unavailable. No public search was performed.';
  workspace.handoffs=[draft('follow_up',20,origin.id,email),draft('research',30,origin.id,research)];await mount();
  expect(host.querySelector('[aria-label="Patient email draft"]')?.textContent).toContain('Please confirm your medicines');
  expect(host.querySelector('[aria-label="Patient email draft"]')?.textContent).not.toContain('Proposed owner');
  expect(host.querySelector('[aria-label="Provider action items"]')?.textContent).toContain('Proposed owner');
  expect(host.querySelector('[aria-label="Drug and treatment questions"]')?.textContent).toContain('Which medicines');
  expect(host.querySelector('[aria-label="Missing evidence / next checks"]')?.textContent).toContain('No public search');
  const originals=[...host.querySelectorAll('details')].filter(d=>d.querySelector('summary')?.textContent==='Complete saved draft');
  expect(originals).toHaveLength(2);expect(originals[0].textContent).toContain('Proposed owner');
  await click('Review follow-up draft');await click('Review research draft');expect(review.mock.calls).toEqual([[id(20)],[id(30)]]);
});
it('keeps each specialist on the exact provider-requested revision and preserves earlier review access',async()=>{
  workspace=await shared();const origin=chiefRequest(),parent=draft('follow_up',20,origin.id,'Earlier email.'),child=draft('follow_up',40,id(90),'Revised email applying the provider feedback.');
  const feedback='Keep the medicine list explicitly unconfirmed.';
  parent.review_status='current';parent.review={id:id(80),attempt_id:parent.attempt_id,result_entry_id:parent.result_entry_id!,result_sha256:parent.result_sha256!,decision:'changes_requested',feedback,created_at:time,revision_handoff_id:child.id};
  child.recipient_agent_id=parent.recipient_agent_id;workspace.entries.find(e=>e.id===child.result_entry_id)!.reply!.agent_id=parent.recipient_agent_id;
  child.revision_request={parent_handoff_id:parent.id,review_id:parent.review.id,attempt_id:parent.attempt_id,result_entry_id:parent.result_entry_id!,result_sha256:parent.result_sha256!,feedback};
  const unrelated=draft('follow_up',60,id(99),'Unrelated newer work must stay outside this workflow.');workspace.handoffs=[parent,unrelated,child];
  await mount();const card=host.querySelector('[aria-label="Follow-up drafts"]')!;
  expect(card.textContent).toContain('revision 2');expect(card.textContent).toContain('Revised email');expect(card.textContent).not.toContain('Unrelated newer work');
  await click('Review follow-up draft');expect(review).toHaveBeenLastCalledWith(child.id);
  await click('Open earlier follow-up review');expect(review).toHaveBeenLastCalledWith(parent.id);
  child.revision_request.feedback='Different unbound feedback';await mount();expect(card.textContent).not.toContain('Revised email');
  await click('Continue follow-up changes');expect(review).toHaveBeenLastCalledWith(parent.id);
});
it('blocks duplicate pending Chief work but allows a deliberate new request after a completed reply saved no assignments',async()=>{
  workspace=await shared();const origin=chiefRequest();origin.reply=null;
  origin.model_request={contract_version:1,request_sha256:'c'.repeat(64),request:{kind:'conversation',expected_revision:3,team_revision:1,idempotency_key:'invented-chief-request',role:'chief'},
    bot:{address:'chief',agent_id:id(88),role:'chief',name:'Chief',team_revision:1},admission:{id:id(89),state:'running',unit:1,admitted_at:time,dispatch:'started',usage:'unknown',input_tokens:null,output_tokens:null},reason:null};
  await mount();expect(button('Ask Chief for follow-up and research drafts').disabled).toBe(true);expect(host.textContent).toContain('no second request is needed');
  origin.model_request.admission.state='completed';origin.reply={agent_name:'Chief',role:'chief',backend:'invented',content:'No assignments were prepared.',context_revision:3,citations:[]};
  await mount();expect(host.textContent).toContain('did not save any team assignments');await click('Ask Chief again for both drafts');
  expect(ask).toHaveBeenCalledExactlyOnceWith(clinicalTeamRequest(currentSharedNote(workspace)!));
});
it('retries the exact retained specialist assignment and withholds unavailable saved result content',async()=>{
  workspace=await shared();const origin=chiefRequest(),row=draft('follow_up',20,origin.id,'Withheld original draft');row.status='failed';row.error_code='model_unavailable';workspace.handoffs=[row];
  await mount();await click('Retry follow-up draft');expect(retry).toHaveBeenCalledExactlyOnceWith(row);expect(ask).not.toHaveBeenCalled();
  row.status='completed';workspace.entries.find(e=>e.id===row.result_entry_id)!.fax_source_state='unavailable';await mount();
  expect(host.textContent).not.toContain('Withheld original draft');expect(button('Review follow-up draft').disabled).toBe(true);
});
it('verifies exact Unicode content, request binding, saved revision and recovery outcome',async()=>{
  const w=await shared(),body=noteSelection(workspace.note!.latest!,workspace.revision,'invented-note-share');
  const receipt={contract:'clinical-note-share.v1',outcome:'saved',source_entry_id:id(4),source_entry_revision:3,workspace:w};
  await expect(verifyClinicalNoteShareReceipt(receipt,w.id,body)).resolves.toEqual(receipt);
  for(const malformed of [{...receipt,source_entry_revision:4},{...receipt,workspace:{...w,id:id(99)}},
    {...receipt,outcome:'not_found'},{...receipt,extra_authority:true}])await expect(verifyClinicalNoteShareReceipt(malformed,w.id,body)).rejects.toThrow();
  const tampered=structuredClone(receipt);tampered.workspace.entries[0].content=tampered.workspace.entries[0].content.replace('reports symptoms','denies symptoms');
  await expect(verifyClinicalNoteShareReceipt(tampered,w.id,body)).rejects.toThrow();
  await expect(verifyClinicalNoteShareReceipt({...receipt,outcome:'not_found',source_entry_id:null,source_entry_revision:null},w.id,body)).resolves.toMatchObject({outcome:'not_found'});
});
it('shows cited shared-note text with attribution, version and hash instead of its transport JSON',async()=>{
  workspace=await shared();const source=currentSharedNote(workspace)!;
  const render=()=>act(async()=>root.render(<EncounterSources workspace={workspace} selectedSource={source.entry.id} locked={false} source="" evidence=""
    setSource={vi.fn()} setEvidence={vi.fn()} onSave={vi.fn()} onNotebook={vi.fn()}/>));
  await render();const article=host.querySelector(`#source-${source.entry.id}`)!;
  expect(article.classList.contains('selected')).toBe(true);expect(article.textContent).toContain(workspace.note!.latest!.content);
  expect(article.textContent).toContain('Saved note version 1');expect(article.textContent).toContain(source.snapshot.note.content_hash);
  expect(article.textContent).not.toContain('clinical-note-team-source.v1');expect(article.textContent).not.toContain('Newer than the note');
  workspace.note!.latest!.sources_changed=true;await render();expect(article.textContent).toContain('Historical saved-note snapshot');
  expect(clinicalRequestDisplay(clinicalTeamRequest(source))).toContain('patient email draft, provider action items');
  const malformed=JSON.stringify({...JSON.parse(clinicalTeamRequest(source)),send:true});expect(clinicalRequestDisplay(malformed)).toBe(malformed);
});
