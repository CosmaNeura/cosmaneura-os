import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import {ResearchWorkspace} from './ResearchWorkspace';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal,editorAddress} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {researchCatalog,researchObservation,researchIdentity,researchWorkspaceId,researchBotId,researchRunId,researchSaved,researchSavedPacket,researchFixtureId} from './research-test-fixture';
import type {ResearchPort} from './research-api';
import {researchDigest,type ResearchObservation,type ResearchSaved} from './research-contract';
import {researchSavedText} from './research-analysis-contract';
import {WorkspaceApiError,type Workspace} from './workspace-api';
import {noteResearchWorkspace} from './note-research-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
let element:HTMLDivElement,root:Root,port:ResearchPort,access:EditorRecoveryAccess,factory:ReturnType<typeof memoryDraftStorage>,journal:DraftJournal;
const changed=vi.fn(),denied=vi.fn(),workspace:Workspace={id:researchWorkspaceId,appointment_id:'invented-appointment',label:'Invented encounter',revision:2,entries:[],work_candidates:[]};
function button(label:string){const found=[...element.querySelectorAll('button')].find(b=>b.textContent?.trim()===label);expect(found,label).toBeTruthy();return found!;}
async function click(label:string){const found=button(label);expect(found.disabled,label).toBe(false);await act(async()=>found.click());}
async function settle(){await act(async()=>{});}
async function workSettled(){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});await vi.waitFor(async()=>{await settle();expect(element.querySelector('[aria-label="Research operation"]')).toBeNull();});}
async function fill(text:string){const area=element.querySelector('textarea')!;expect(area.disabled).toBe(false);await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(area,text);area.dispatchEvent(new Event('input',{bubbles:true}));});}
async function check(label:string){const found=[...element.querySelectorAll('label')].find(l=>l.textContent?.includes(label))?.querySelector('input')!;expect(found).toBeTruthy();expect(found.disabled).toBe(false);await act(async()=>found.click());}
async function mount(props:Partial<Parameters<typeof ResearchWorkspace>[0]>={}){await act(async()=>root.render(<EditorRecoveryContext.Provider value={access}><ResearchWorkspace identity={researchIdentity} workspaceId={researchWorkspaceId} workspaceRevision={2} bot={{address:researchBotId,team_revision:1}} enabled locked={false} port={port} onChanged={changed} onDenied={denied} {...props}/></EditorRecoveryContext.Provider>));await settle();}
async function prepare(){await fill('Invented general public question');await check('PubMed');await click('Review query');await check('This is a general public question');}
function savedWorkspace(run:ResearchObservation,receipt:ResearchSaved):Workspace{return {...workspace,revision:receipt.entry_revision,entries:[{id:receipt.entry_id,revision:receipt.entry_revision,kind:'evidence',content:researchSavedText(receipt.request.source_hashes.map(hash=>run.results.find(record=>record.sha256===hash)!)),source_label:'Research · public source excerpts',origin:'human',ticket:null,created_at:run.created_at}]};}
async function analysisReady(){for(let attempt=0;attempt<100;attempt++){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});if(element.querySelector('.research-analysis')?.getAttribute('aria-busy')==='false')return;}throw new Error('Preview proof did not settle');}

beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);changed.mockReset();denied.mockReset();factory=memoryDraftStorage();journal=new DraftJournal(await factory({scope:'c'.repeat(64)}));access={journal,workspaceId:researchWorkspaceId,authorize:vi.fn(async()=>workspace),denied};element=document.createElement('div');document.body.append(element);root=createRoot(element);port={catalog:vi.fn(async()=>researchCatalog()),history:vi.fn(async()=>({contract:'research.history.v1' as const,runs:[]})),savedHistory:vi.fn(async()=>({contract:'research.saved_history.v1' as const,workspace_id:researchWorkspaceId,bot:researchBotId,packets:[]})),search:vi.fn(async(_i,_w,body)=>researchObservation(body)),resolve:vi.fn(async(_i,_w,body)=>researchObservation(body)),save:vi.fn(async(_i,_w,_r,body)=>researchSaved(body)),resolveSave:vi.fn(async(_i,_w,_r,body)=>researchSaved(body))};});
afterEach(async()=>{await act(async()=>root.unmount());journal.close();element.remove();vi.unstubAllGlobals();});
it('keeps four primary topic choices, an explicit reviewed public input and separate source evidence',async()=>{
 await mount();expect(element.querySelectorAll('.research-topic-row button')).toHaveLength(4);expect(element.querySelectorAll('textarea')).toHaveLength(1);expect(element.querySelector('textarea')!.value).toBe('');expect(port.search).not.toHaveBeenCalled();
 await fill('Invented general public question');await check('PubMed');await click('Review query');expect(button('Search selected sources').disabled).toBe(true);await check('This is a general public question');await click('Search selected sources');await workSettled();
 expect(port.search).toHaveBeenCalledTimes(1);const request=vi.mocked(port.search).mock.calls[0][2];expect(Object.keys(request).sort()).toEqual(['bot','contract_version','expected_revision','idempotency_key','public_query_confirmed','query','sources','team_revision','topic']);expect(request).toMatchObject({query:'Invented general public question',sources:['pubmed'],bot:researchBotId,public_query_confirmed:true});
 expect(element.textContent).toContain('No AI synthesis or clinical inference');expect(element.textContent).toContain('Source dateNot supplied');expect(element.textContent).toContain('VersionNot supplied');expect(element.textContent).toContain('Excerpt shortened');expect(element.textContent).toContain('Limited result set');expect(port.save).not.toHaveBeenCalled();
 await check('Select excerpt to save');await click('Save selected excerpts');await workSettled();expect(port.save).toHaveBeenCalledTimes(1);const save=vi.mocked(port.save).mock.calls[0][3];expect(Object.keys(save).sort()).toEqual(['contract_version','expected_revision','idempotency_key','source_hashes']);expect(changed).toHaveBeenCalledWith(3);expect(element.textContent).toContain('Clinical review and any follow-up remain separate');
});
async function notePlanReady(){await vi.waitFor(async()=>{await settle();expect(element.querySelector('[aria-label="Research from saved note"]')).not.toBeNull();});}
it('turns an exact saved-note assessment question into a reviewed public lookup without forwarding private source data',async()=>{
 const note=await noteResearchWorkspace(),onSubmit=vi.fn();await mount({workspaceRevision:4,analysis:{workspace:note,model:{enabled:true,model:'Configured model'},onSubmit}});await notePlanReady();
 expect(element.textContent).toContain('Synthetic Person');expect(element.textContent).toContain('Saved note · version 1');expect(port.search).not.toHaveBeenCalled();
 await click('Prepare proposed public query');expect(element.querySelector<HTMLTextAreaElement>('textarea')!.value).toBe('DrugA interaction evidence');expect(document.activeElement).toBe(element.querySelector('textarea'));
 await check('PubMed');await click('Review query');expect(button('Search selected sources').disabled).toBe(true);expect(port.search).not.toHaveBeenCalled();
 await check('This is a general public question');await click('Search selected sources');await workSettled();
 const request=vi.mocked(port.search).mock.calls[0][2];expect(request.query).toBe('DrugA interaction evidence');
 expect(Object.keys(request).sort()).toEqual(['bot','contract_version','expected_revision','idempotency_key','public_query_confirmed','query','sources','team_revision','topic']);
 expect(JSON.stringify(request)).not.toContain('Synthetic Person');expect(JSON.stringify(request)).not.toContain('Private-only');expect(JSON.stringify(request)).not.toContain(note.note!.latest!.content_hash);
 expect(element.textContent).toContain('Invented source title');expect(element.textContent).toContain('Source details & citation');expect(element.textContent).toContain('https://pubmed.ncbi.nlm.nih.gov/12345/');
 const retained=await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));expect(retained).toMatchObject({data:{note_question:{note_id:note.note!.latest!.id,note_version:1,source_fingerprint:note.note!.latest!.source_fingerprint},query:request.query}});
 expect(onSubmit).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();
});
it('does not overwrite an existing public question when assessment proposals are available',async()=>{
 const note=await noteResearchWorkspace();await mount({workspaceRevision:4,analysis:{workspace:note,model:{enabled:true,model:'Configured model'},onSubmit:vi.fn()}});await notePlanReady();
 await fill('Keep my public wording');expect(button('Prepare proposed public query').disabled).toBe(true);expect(element.querySelector('textarea')!.value).toBe('Keep my public wording');expect(port.search).not.toHaveBeenCalled();
});
it('retains an exact private question without inventing public wording or starting a lookup',async()=>{
 const note=await noteResearchWorkspace(),{vendorSha256}=await import('./vendor-contract');
 note.entries[2].reply!.content=note.entries[2].reply!.content.replace('\nGeneral public query: DrugA interaction evidence','');
 note.handoffs![0].result_sha256=await vendorSha256(new TextEncoder().encode(note.entries[2].reply!.content));
 await mount({workspaceRevision:4,analysis:{workspace:note,model:{enabled:true,model:'Configured model'},onSubmit:vi.fn()}});await notePlanReady();
 await click('Write a public query for this question');await workSettled();
 expect(element.querySelector('textarea')!.value).toBe('');expect(document.activeElement).toBe(element.querySelector('textarea'));expect(button('Review query').disabled).toBe(true);
 expect(await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`))).toMatchObject({data:{query:'',note_question:{note_id:note.note!.latest!.id,question_index:0}}});
 expect(port.search).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();
});
it('invalidates a reviewed note-linked query when its exact source changes while preserving the wording',async()=>{
 const note=await noteResearchWorkspace(),analysis={workspace:note,model:{enabled:true,model:'Configured model'},onSubmit:vi.fn()};await mount({workspaceRevision:4,analysis});await notePlanReady();
 await click('Prepare proposed public query');await check('PubMed');await click('Review query');await check('This is a general public question');
 const changedNote=structuredClone(note);changedNote.note!.latest!.sources_changed=true;
 await mount({workspaceRevision:4,analysis:{...analysis,workspace:changedNote}});
 expect(element.querySelector('[aria-label="Review public query"]')).toBeNull();expect(element.querySelector('[aria-label="Research from saved note"]')).toBeNull();
 expect(element.querySelector('textarea')!.value).toBe('DrugA interaction evidence');expect(button('Review query').disabled).toBe(true);expect(port.search).not.toHaveBeenCalled();
 await click('Keep as a separate general question');await click('Review query');expect(button('Search selected sources').disabled).toBe(true);expect(port.search).not.toHaveBeenCalled();
});
it('resolves the exact uncertain lookup after note source changes without repeating the public search',async()=>{
 const note=await noteResearchWorkspace(),analysis={workspace:note,model:{enabled:true,model:'Configured model'},onSubmit:vi.fn()};
 vi.mocked(port.search).mockRejectedValue(new Error('lost synthetic acknowledgement'));await mount({workspaceRevision:4,analysis});await notePlanReady();
 await click('Prepare proposed public query');await check('PubMed');await click('Review query');await check('This is a general public question');await click('Search selected sources');await workSettled();
 const exact=vi.mocked(port.search).mock.calls[0][2],changedNote=structuredClone(note);changedNote.note!.latest!.sources_changed=true;
 await mount({workspaceRevision:5,analysis:{...analysis,workspace:changedNote}});await click('Check saved result');await workSettled();
 expect(port.search).toHaveBeenCalledOnce();expect(vi.mocked(port.resolve).mock.calls[0][2]).toEqual(exact);expect(port.save).not.toHaveBeenCalled();
 expect(element.textContent).toContain('The saved note or Research assessment changed');
});
it('hides private assessment words immediately under a replaced identity until fresh owner data arrives',async()=>{
 const note=await noteResearchWorkspace(),analysis={workspace:note,model:{enabled:true,model:'Configured model'},onSubmit:vi.fn()};await mount({workspaceRevision:4,analysis});await notePlanReady();
 expect(element.textContent).toContain('Synthetic Person');await mount({identity:{mode:'clerk_jwt',getToken:async()=> 'other-invented-session'},workspaceRevision:4,analysis});
 expect(element.querySelector('[aria-label="Research from saved note"]')).toBeNull();expect(element.textContent).not.toContain('Synthetic Person');expect(port.search).not.toHaveBeenCalled();
});
it('reports not connected honestly while preserving a question without public dispatch',async()=>{
 vi.mocked(port.catalog).mockResolvedValue(researchCatalog(false));await mount();await fill('Retain this general question');expect(element.textContent).toContain('Public research is not connected');expect(button('Review query').disabled).toBe(true);expect(port.search).not.toHaveBeenCalled();expect(port.history).not.toHaveBeenCalled();
 const saved=await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));expect(saved).toMatchObject({data:{query:'Retain this general question',pending:null}});
});
it('restores an uncertain exact request after remount and resolves without resending',async()=>{
 vi.mocked(port.search).mockRejectedValue(new Error('response lost'));await mount();await prepare();await click('Search selected sources');await workSettled();const request=vi.mocked(port.search).mock.calls[0][2];expect(element.textContent).toContain('Research request retained');await act(async()=>root.unmount());journal.close();journal=new DraftJournal(await factory({scope:'c'.repeat(64)}));access={...access,journal};root=createRoot(element);await mount();expect(button('Restore research draft')).toBeTruthy();expect(port.search).toHaveBeenCalledTimes(1);
 await click('Restore research draft');expect(port.resolve).not.toHaveBeenCalled();await click('Check saved result');await workSettled();expect(port.resolve).toHaveBeenCalledTimes(1);expect(vi.mocked(port.resolve).mock.calls[0][2]).toEqual(request);expect(port.search).toHaveBeenCalledTimes(1);expect(element.textContent).toContain('Sources retrieved');
});
it('retains an unconfirmed evidence save and checks its exact receipt without resaving',async()=>{
 vi.mocked(port.save).mockRejectedValue(new Error('save response lost'));await mount();await prepare();await click('Search selected sources');await workSettled();await check('Select excerpt to save');await click('Save selected excerpts');await workSettled();const request=vi.mocked(port.save).mock.calls[0][3];expect(element.textContent).toContain('Evidence save retained');await click('Check saved result');await workSettled();expect(port.resolveSave).toHaveBeenCalledTimes(1);expect(vi.mocked(port.resolveSave).mock.calls[0][3]).toEqual(request);expect(port.save).toHaveBeenCalledTimes(1);expect(changed).toHaveBeenCalledWith(3);
});
it('invalidates a prepared review on revision or lock changes and never sends while locked',async()=>{
 await mount();await prepare();await mount({workspaceRevision:3});expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Search selected sources')).toBe(false);await mount({locked:true});expect(button('Review query').matches(':disabled')).toBe(true);expect(port.search).not.toHaveBeenCalled();
});
it('withholds dispatch if durable pending storage fails',async()=>{
 await mount();await prepare();const persist=journal.persist.bind(journal);vi.spyOn(journal,'persist').mockImplementation(async(address,value)=>{if(value?.kind==='editor'&&value.pending)throw new Error('storage failure');return persist(address,value);});await click('Search selected sources');await workSettled();expect(port.search).not.toHaveBeenCalled();expect(element.textContent).toContain('Local editor storage is unavailable');
});
it('ignores cancellation-resistant late responses after unmount and retains the old pending request',async()=>{
 let complete!:(value:ResearchObservation)=>void;vi.mocked(port.search).mockImplementation(()=>new Promise(resolve=>{complete=resolve;}));await mount();await prepare();await click('Search selected sources');const request=vi.mocked(port.search).mock.calls[0][2];await act(async()=>root.unmount());await act(async()=>complete(await researchObservation(request)));const saved=await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));expect(saved).toMatchObject({pending:request.idempotency_key});expect(port.save).not.toHaveBeenCalled();root=createRoot(element);
});
it('keeps running and interrupted requests unresolved and refuses a mismatched resolved observation',async()=>{
 vi.mocked(port.search).mockImplementation(async(_i,_w,request)=>({...await researchObservation(request),state:'interrupted',results:[]}));await mount();await prepare();await click('Search selected sources');await workSettled();expect(element.textContent).toContain('Research request retained');vi.mocked(port.resolve).mockImplementation(async(_i,_w,request)=>({...await researchObservation(request),workspace_id:researchRunId}));await click('Check saved result');await workSettled();expect(element.textContent).toContain('A saved result could not be confirmed');expect(element.textContent).toContain('Research request retained');expect(port.search).toHaveBeenCalledTimes(1);
});
it('shows native source addresses without granting broad external navigation',async()=>{
 await mount({identity:{...researchIdentity,nativeSession:{revision:researchRunId,isCurrent:()=>true}}});await prepare();await click('Search selected sources');await workSettled();expect(element.querySelector('.research-result a')).toBeNull();expect(element.textContent).toContain('Opening external research sites from this app is not connected');
});

it('retains an unconfirmed old request before an acknowledged replacement and never lets its late result replace the new question',async()=>{
 vi.mocked(port.search).mockRejectedValue(new Error('response lost'));vi.mocked(port.resolve).mockRejectedValueOnce(new WorkspaceApiError(404,'research_not_found'));await mount();await prepare();await click('Search selected sources');await workSettled();const old=vi.mocked(port.search).mock.calls[0][2];await click('Check saved result');await workSettled();expect(button('Start a new search').disabled).toBe(true);await check('I understand the previous request may still finish.');await click('Start a new search');await workSettled();expect(element.querySelector('textarea')!.value).toBe('');expect(port.search).toHaveBeenCalledTimes(1);
 const saved=await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));expect(saved).toMatchObject({pending:null,data:{previous_request:{request:old,outcome:'not_found'}}});await fill('A different general public question');await click('Check previous result');await workSettled();expect(element.querySelector('textarea')!.value).toBe('A different general public question');expect(port.search).toHaveBeenCalledTimes(1);
 await click('Review query');await check('This is a general public question');vi.mocked(port.search).mockImplementation(async(_i,_w,request)=>researchObservation(request));await click('Search selected sources');await workSettled();expect(port.search).toHaveBeenCalledTimes(2);expect(vi.mocked(port.search).mock.calls[1][2].idempotency_key).not.toBe(old.idempotency_key);
});
it.each(['search','save'] as const)('recovers a retained %s while paused without enabling any new lookup or save',async(kind)=>{
 if(kind==='search')vi.mocked(port.search).mockRejectedValue(new Error('lost response'));else vi.mocked(port.save).mockRejectedValue(new Error('lost response'));
 await mount();await prepare();await click('Search selected sources');await workSettled();
 if(kind==='save'){await check('Select excerpt to save');await click('Save selected excerpts');await workSettled();}
 await act(async()=>root.unmount());journal.close();journal=new DraftJournal(await factory({scope:'c'.repeat(64)}));access={...access,journal};root=createRoot(element);
 await mount({enabled:false});await click('Restore research draft');expect(button('Review query').matches(':disabled')).toBe(true);
 await mount({enabled:false,locked:true});expect(button('Check saved result').disabled).toBe(true);expect(port.resolve).not.toHaveBeenCalled();expect(port.resolveSave).not.toHaveBeenCalled();
 await mount({enabled:false,locked:false});await click('Check saved result');await workSettled();
 expect(kind==='search'?port.resolve:port.resolveSave).toHaveBeenCalledTimes(1);expect(port.search).toHaveBeenCalledTimes(1);expect(port.save).toHaveBeenCalledTimes(kind==='save'?1:0);
 const saved=await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));expect(saved).toMatchObject({pending:null,data:{pending:null}});
 expect(element.textContent).toContain(kind==='search'?'Sources retrieved':'Selected excerpts saved');expect(button('Review query').matches(':disabled')).toBe(true);
 if(kind==='search')expect(button('Save selected excerpts').disabled).toBe(true);
});
it('retains a verified resolve result when the bot is paused while that read is in progress',async()=>{
 vi.mocked(port.search).mockRejectedValue(new Error('lost response'));await mount();await prepare();await click('Search selected sources');await workSettled();
 const request=vi.mocked(port.search).mock.calls[0][2];let complete!:(value:ResearchObservation)=>void;
 vi.mocked(port.resolve).mockImplementation(()=>new Promise(resolve=>{complete=resolve;}));await click('Check saved result');await mount({enabled:false});
 await act(async()=>complete(await researchObservation(request)));await workSettled();expect(element.textContent).toContain('Sources retrieved');
 expect(await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`))).toMatchObject({pending:null,data:{pending:null}});
 expect(port.search).toHaveBeenCalledTimes(1);expect(port.resolve).toHaveBeenCalledTimes(1);expect(port.save).not.toHaveBeenCalled();
});
it('preserves a reviewed BOM while normalizing Python whitespace around the question',async()=>{
 await mount();await fill('\u0085\ufeffGeneral public question\u00a0');await check('PubMed');await click('Review query');await check('This is a general public question');await click('Search selected sources');await workSettled();
 expect(vi.mocked(port.search).mock.calls[0][2].query).toBe('\ufeffGeneral public question');expect(element.querySelector('textarea')!.value).toBe('\ufeffGeneral public question');
});
it('retains a verified save anchor, restores the selected analysis question and only hands off after fresh consent',async()=>{
 const {analysisWorkspace}=await import('./research-analysis-test-fixture');const submit=vi.fn(async(_body:import('./workspace-api').ConversationInput)=>{}),analysis={workspace:analysisWorkspace(),model:{enabled:true,model:'Configured GPT-4.1'},onSubmit:submit};
 await mount({analysis});await prepare();await click('Search selected sources');await workSettled();await check('Select excerpt to save');await click('Save selected excerpts');await workSettled();
 const request=vi.mocked(port.save).mock.calls[0][3],receipt=await researchSaved(request),run=await researchObservation(vi.mocked(port.search).mock.calls[0][2]);analysis.workspace=savedWorkspace(run,receipt);await mount({workspaceRevision:3,analysis});await analysisReady();await click('Ask Research about saved sources');await check('Use saved source packet');
 const area=element.querySelector('.research-analysis textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(area,'Explain this selected evidence');area.dispatchEvent(new Event('input',{bubbles:true}));});
 await workSettled();const saved=await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`));expect(saved).toMatchObject({data:{saved_packet:{entry_id:receipt.entry_id,entry_revision:3,run_id:receipt.run_id,save_request_sha256:receipt.request_sha256},analysis_draft:{question:'Explain this selected evidence',selected:true}}});
 vi.mocked(port.savedHistory).mockResolvedValue({contract:'research.saved_history.v1',workspace_id:researchWorkspaceId,bot:researchBotId,packets:[{query:run.query,saved:receipt}]});vi.mocked(port.history).mockResolvedValue({contract:'research.history.v1',runs:[run]});await act(async()=>root.unmount());journal.close();journal=new DraftJournal(await factory({scope:'c'.repeat(64)}));access={...access,journal};root=createRoot(element);await mount({workspaceRevision:3,analysis});await click('Restore research draft');await click('Ask Research about saved sources');expect((element.querySelector('.research-analysis textarea') as HTMLTextAreaElement).value).toBe('Explain this selected evidence');expect(submit).not.toHaveBeenCalled();expect(button('Review AI request').disabled).toBe(true);await click('Load saved source details');await workSettled();await analysisReady();expect(element.querySelector('.research-analysis .research-excerpt')?.textContent).toContain('Study type: Invented review');await click('Review AI request');expect(button('Send to Research').disabled).toBe(true);await check('I consent to sending');await click('Send to Research');await workSettled();expect(submit).toHaveBeenCalledOnce();expect(submit.mock.calls[0][0]).toMatchObject({research_analysis:{version:1,consented:true,entries:[{entry_id:receipt.entry_id,entry_revision:3,run_id:receipt.run_id,save_request_sha256:receipt.request_sha256}]}});expect(port.search).toHaveBeenCalledOnce();expect(port.save).toHaveBeenCalledOnce();
});
it('does not hand off selected analysis if its exact local journal commit fails',async()=>{
 const {analysisWorkspace}=await import('./research-analysis-test-fixture');const submit=vi.fn(async(_body:import('./workspace-api').ConversationInput)=>{}),analysis={workspace:analysisWorkspace(),model:{enabled:true,model:'Configured GPT-4.1'},onSubmit:submit};
 await mount({analysis});await prepare();await click('Search selected sources');await workSettled();await check('Select excerpt to save');await click('Save selected excerpts');await workSettled();const run=await researchObservation(vi.mocked(port.search).mock.calls[0][2]),receipt=await researchSaved(vi.mocked(port.save).mock.calls[0][3]);analysis.workspace=savedWorkspace(run,receipt);await mount({workspaceRevision:3,analysis});await analysisReady();await click('Ask Research about saved sources');await check('Use saved source packet');
 const area=element.querySelector('.research-analysis textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(area,'Explain the source');area.dispatchEvent(new Event('input',{bubbles:true}));});await workSettled();await click('Review AI request');await check('I consent to sending');vi.spyOn(journal,'persist').mockRejectedValue(new Error('storage unavailable'));await click('Send to Research');await workSettled();expect(submit).not.toHaveBeenCalled();expect(element.textContent).toContain('Local editor storage is unavailable');
});

it('loads an older lookup page using its last run without changing the question or redispatching',async()=>{
 const runs=await Promise.all([6,5,4,3,2,1].map(async value=>({...await researchObservation(),run_id:researchFixtureId(300+value)})));
 vi.mocked(port.history).mockResolvedValueOnce({contract:'research.history.v1',runs:runs.slice(0,5)}).mockResolvedValueOnce({contract:'research.history.v1',runs:runs.slice(5)});
 await mount();await fill('Keep my current question');await click('Load saved research');await workSettled();await click('Load older lookups');await workSettled();
 expect(vi.mocked(port.history).mock.calls[1][4]).toBe(runs[4].run_id);expect(element.querySelector('textarea')!.value).toBe('Keep my current question');
 expect(element.querySelectorAll('.research-history strong')).toHaveLength(6);expect(element.textContent).not.toContain('Load older lookups');expect(port.search).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();
});

it('selects an older saved packet while preserving the question and clearing both selection and model consent',async()=>{
 const run=await researchObservation(),packets=await Promise.all([7,6,5,4,3,2].map(researchSavedPacket)),submit=vi.fn(async()=>{});for(const packet of packets){packet.saved.request.source_hashes=run.results.map(record=>record.sha256);packet.saved.request_sha256=await researchDigest(packet.saved.request);}vi.mocked(port.history).mockResolvedValue({contract:'research.history.v1',runs:[run]});
 const analysis={workspace:{...workspace,revision:8,entries:packets.map(packet=>({id:packet.saved.entry_id,revision:packet.saved.entry_revision,kind:'evidence' as const,content:researchSavedText(run.results),source_label:'Research · public source excerpts',origin:'human' as const,ticket:null,created_at:'2026-09-22T18:00:00Z'}))},model:{enabled:true,model:'Configured GPT-4.1'},onSubmit:submit};
 const page=(rows:typeof packets)=>({contract:'research.saved_history.v1' as const,workspace_id:researchWorkspaceId,bot:researchBotId,packets:rows});
 vi.mocked(port.savedHistory).mockResolvedValueOnce(page(packets.slice(0,5))).mockResolvedValueOnce(page(packets.slice(5)));
 await mount({workspaceRevision:8,analysis});await click('Load saved research');await workSettled();await click('Load saved packets');await workSettled();await click('Invented packet 7Saved packet · revision 7');await analysisReady();await click('Ask Research about saved sources');await check('Use saved source packet');
 const area=element.querySelector('.research-analysis textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(area,'Compare this exact packet');area.dispatchEvent(new Event('input',{bubbles:true}));});await workSettled();await click('Review AI request');await check('I consent to sending');
 await click('Load older packets');await workSettled();expect(vi.mocked(port.savedHistory).mock.calls[1][4]).toBe(packets[4].saved.entry_id);await click('Invented packet 2Saved packet · revision 2');await workSettled();await analysisReady();
 expect((element.querySelector('.research-analysis textarea') as HTMLTextAreaElement).value).toBe('Compare this exact packet');expect(element.querySelector<HTMLInputElement>('.research-analysis input')!.checked).toBe(false);expect(element.querySelector('.research-analysis small')?.textContent).toContain(packets[5].saved.entry_id);expect(element.querySelector('.research-analysis .research-excerpt')?.textContent).toContain('Study type: Invented review');expect(element.textContent).not.toContain('Send to Research');
 await check('Use saved source packet');await click('Review AI request');expect(button('Send to Research').disabled).toBe(true);
 expect(await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`))).toMatchObject({data:{saved_packet:{entry_id:packets[5].saved.entry_id},analysis_draft:{question:'Compare this exact packet',selected:true}}});
 expect(port.search).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();expect(submit).not.toHaveBeenCalled();expect(changed).not.toHaveBeenCalled();
});

it('keeps a pending lookup exact while saved packets are read and refuses a duplicate older page',async()=>{
 const packets=await Promise.all([7,6,5,4,3].map(researchSavedPacket));const {analysisWorkspace}=await import('./research-analysis-test-fixture');
 vi.mocked(port.savedHistory).mockResolvedValue({contract:'research.saved_history.v1',workspace_id:researchWorkspaceId,bot:researchBotId,packets});
 vi.mocked(port.search).mockRejectedValue(new Error('unknown result'));
 await mount({analysis:{workspace:analysisWorkspace(),model:{enabled:true,model:'Configured GPT-4.1'},onSubmit:vi.fn()}});await prepare();await click('Search selected sources');await workSettled();const request=vi.mocked(port.search).mock.calls[0][2];
 await click('Load saved packets');await workSettled();expect(button('Invented packet 7Saved packet · revision 7').disabled).toBe(true);await click('Load older packets');await workSettled();expect(element.textContent).toContain('Saved source packets could not be confirmed');
 expect(element.querySelectorAll('.research-history strong')).toHaveLength(5);expect(await journal.load(editorAddress(researchWorkspaceId,`research:${researchBotId}`))).toMatchObject({pending:request.idempotency_key,data:{pending:{kind:'search',request}}});expect(port.search).toHaveBeenCalledOnce();expect(port.save).not.toHaveBeenCalled();
});

it('preselects the configured trial registry only after choosing trials and still requires query review',async()=>{
 const catalog=researchCatalog();catalog.sources.find(source=>source.id==='clinical_trials')!.state='enabled';
 vi.mocked(port.catalog).mockResolvedValue(catalog);await mount();await click('Clinical trials');
 expect(element.querySelector<HTMLTextAreaElement>('textarea')!.placeholder).toContain('myocardial infarction');
 expect([...element.querySelectorAll('label')].find(label=>label.textContent?.includes('ClinicalTrials.gov'))?.querySelector<HTMLInputElement>('input')?.checked).toBe(true);
 expect(port.search).not.toHaveBeenCalled();await fill('myocardial infarction AND stem cell');await click('Review query');
 expect(button('Search selected sources').disabled).toBe(true);expect(element.querySelector('.research-query-review')?.textContent).toContain('ClinicalTrials.gov');
 expect(port.search).not.toHaveBeenCalled();
});

it('shows the actual lookup operation without an unconfirmed banner while it is running',async()=>{
 let complete!:(value:ResearchObservation)=>void;
 vi.mocked(port.search).mockImplementation(()=>new Promise(resolve=>{complete=resolve;}));
 await mount();await prepare();await click('Search selected sources');
 expect(element.textContent).toContain('Searching selected public sources…');
 expect(element.querySelector('[aria-label="Unconfirmed research request"]')).toBeNull();
 expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Stop waiting')).toBe(false);
 const request=vi.mocked(port.search).mock.calls[0][2];
 await act(async()=>complete(await researchObservation(request)));await workSettled();
 expect(element.textContent).toContain('Sources retrieved');
});
it('cancels a saved-history read and fences a late reply while allowing another read',async()=>{
 let complete!:(value:Awaited<ReturnType<ResearchPort['history']>>)=>void;
 vi.mocked(port.history).mockImplementationOnce(()=>new Promise(resolve=>{complete=resolve;}));
 await mount();await fill('Keep my question');await click('Load saved research');
 expect(element.textContent).toContain('Loading saved research history…');
 const signal=vi.mocked(port.history).mock.calls[0][3]!;
 await click('Stop waiting');expect(signal.aborted).toBe(true);
 expect(element.querySelector('textarea')!.disabled).toBe(false);
 await click('Load saved research');await workSettled();
 await act(async()=>complete({contract:'research.history.v1',runs:[await researchObservation()]}));
 expect(element.querySelectorAll('.research-history strong')).toHaveLength(0);
 expect(element.querySelector('textarea')!.value).toBe('Keep my question');
 expect(port.search).not.toHaveBeenCalled();expect(port.save).not.toHaveBeenCalled();
});
