import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {DraftJournal,type NotebookDraft} from './draft-journal';
import {DraftStoreError,type DraftRecord,type DraftStore} from './draft-store';
import {modelWorkApi} from './model-work-api';
import {researchApi} from './research-api';
import {modelRequestHash,type ModelOperation} from './model-work-request';
import {admissionFixture,conversationFixture,modelReceipt,modelTimestamp,modelUuid,pendingWorkspace,retryReceipt} from './model-work-test-fixture';
import {teamFixture} from './team-setup-test-fixture';
import {workspaceApi,WorkspaceApiError,type ConversationInput,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./research-api',async()=>{const {researchCatalog}=await import('./research-test-fixture');return {researchApi:{catalog:vi.fn(async()=>researchCatalog(false)),history:vi.fn(),savedHistory:vi.fn(),search:vi.fn(),save:vi.fn()}};});
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(s:string)=>s}));
vi.mock('./model-work-api',async original=>({...await original<typeof import('./model-work-api')>(),modelWorkApi:{resolve:vi.fn()}}));
vi.mock('./workspace-api',async original=>{const actual=await original<typeof import('./workspace-api')>();return {...actual,workspaceApi:{...actual.workspaceApi,open:vi.fn(),catalog:vi.fn(),team:vi.fn(),read:vi.fn(),ask:vi.fn(),retryHandoff:vi.fn()}};});
const access={mode:'clerk_jwt' as const,getToken:async()=> 'invented-token'},team=teamFixture(),id=modelUuid(71),address=`workspace:${id}`;
const original:Workspace={id,appointment_id:modelUuid(72),label:'Invented recovery visit',revision:1,entries:[],work_candidates:[],model_contract_version:1,model_observed_at:modelTimestamp};
let records:Map<string,DraftRecord>,root:Root,element:HTMLDivElement,failReplacement:boolean,replacementWrites:number;
const factory=async({scope}:{scope:string}):Promise<DraftStore>=>{let closed=false;return {close(){closed=true;},async read(key){if(closed)throw new DraftStoreError('unavailable');return structuredClone(records.get(scope+key)??{revision:null,value:null});},async write(key,expected,value){
  if(closed)throw new DraftStoreError('unavailable');if((value?.body as NotebookDraft)?.pending&&'previous_model_request' in (value!.body as NotebookDraft).pending!){replacementWrites++;if(failReplacement)throw new DraftStoreError('conflict');}
  const before=records.get(scope+key)??{revision:null,value:null};if(before.revision!==expected)throw new DraftStoreError('conflict');const next={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(scope+key,next);return next;}};};
const currentDraft=()=>records.get(team.recovery_scope!+address)?.value?.body as NotebookDraft|null|undefined;
async function mount(){root=createRoot(element);await act(async()=>root.render(<EncounterWorkspace authenticated={access} draftStorage={factory}/>));}
async function click(text:string){let button:HTMLButtonElement|undefined;await vi.waitFor(async()=>{await act(async()=>{});button=[...element.querySelectorAll('button')].find(b=>b.textContent?.replace(/\s*↗$/,'').trim()===text||b.getAttribute('aria-label')===text||[...b.querySelectorAll('strong')].some(label=>label.textContent?.trim()===text));expect(button,text).toBeTruthy();expect(button!.disabled,text).toBe(false);});await act(async()=>button!.click());if(text==='Check saved result'&&button!.isConnected&&button!.disabled)await vi.waitFor(async()=>{await act(async()=>{});expect(!button!.isConnected||!button!.disabled).toBe(true);});}
async function input(selector:string,value:string){const field=element.querySelector<HTMLTextAreaElement>(selector)!;expect(field).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function open(){await click('Choose an encounter');await act(async()=>element.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());}
async function restart(){await act(async()=>root.unmount());await mount();await open();await vi.waitFor(async()=>{await act(async()=>{});expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Restore notebook draft')).toBe(true);});}
async function seed(operation:ModelOperation){const journal=new DraftJournal(await factory({scope:team.recovery_scope!}));await journal.load(address);await journal.persist(address,{kind:'workspace',workspaceId:id,baseRevision:1,note:'Keep invented notebook',thought:operation.type==='ask'?operation.body.content:'',evidence:'Keep invented evidence',source:'Invented source',pending:operation});journal.close();}
async function restore(operation:ModelOperation){await seed(operation);await open();expect(workspaceApi.ask).not.toHaveBeenCalled();await click('Restore notebook draft');}
async function unresolved(operation:ModelOperation,outcome:'not_found'|'unknown'='not_found'){
  const saved=await modelReceipt(operation.body as ConversationInput,id);return {...saved,outcome,saved_entry:null,admission:outcome==='not_found'?null:admissionFixture('unknown'),reason:outcome==='not_found'?null:'dispatch_interrupted' as const};
}
beforeEach(async()=>{vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);records=new Map();failReplacement=false;replacementWrites=0;
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(original),team:structuredClone(team)});
  vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:original.appointment_id,workspace_id:id,label:original.label}]);vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));vi.mocked(workspaceApi.read).mockResolvedValue(structuredClone(original));
  element=document.createElement('div');document.body.append(element);await mount();});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();vi.useRealTimers();vi.restoreAllMocks();});

it('retains an exact lost ask across remount and settles an old saved receipt omitted from the current projection',async()=>{
  await open();await input('#team-notebook','Keep invented notebook');await input('#team-question','Invented interrupted question');
  vi.mocked(workspaceApi.ask).mockRejectedValue(new WorkspaceApiError(503));await click('Send message');const saved=structuredClone(currentDraft()!);
  expect(saved.pending).toMatchObject({type:'ask',model_contract:1,origin:'durable_admission_v1'});
  await restart();expect(workspaceApi.ask).toHaveBeenCalledOnce();await click('Restore notebook draft');expect(workspaceApi.ask).toHaveBeenCalledOnce();
  const body=(saved.pending as ModelOperation&{type:'ask'}).body;
  vi.mocked(modelWorkApi.resolve).mockResolvedValue(await modelReceipt(body,id,8));vi.mocked(workspaceApi.read).mockResolvedValue({...original,revision:15,entries:[]});
  await click('Check saved result');expect(modelWorkApi.resolve).toHaveBeenCalledWith(access,id,saved.pending);
  expect(currentDraft()?.pending).toBeNull();expect(currentDraft()?.note).toBe('Keep invented notebook');expect(element.textContent).toContain('Conversation saved.');expect(workspaceApi.ask).toHaveBeenCalledOnce();
});
it('keeps the pending body when an exact saved receipt is followed by a failed current read',async()=>{
  const operation:ModelOperation={type:'ask',body:conversationFixture,model_contract:1,origin:'durable_admission_v1'};await restore(operation);
  vi.mocked(modelWorkApi.resolve).mockResolvedValue(await modelReceipt(conversationFixture,id));vi.mocked(workspaceApi.read).mockRejectedValue(new WorkspaceApiError(503));
  await click('Check saved result');expect(currentDraft()?.pending).toEqual(operation);expect(element.textContent).toContain('unconfirmed');
});
it('permits only explicit same-key send after a verified modern not_found and no automatic resubmission',async()=>{
  const operation:ModelOperation={type:'ask',body:conversationFixture,model_contract:1,origin:'durable_admission_v1'};await restore(operation);
  vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved(operation));await click('Check saved result');expect(workspaceApi.ask).not.toHaveBeenCalled();
  expect(currentDraft()?.pending).toEqual(operation);vi.mocked(workspaceApi.ask).mockResolvedValue(await modelReceipt(conversationFixture,id));vi.mocked(workspaceApi.read).mockResolvedValue({...original,revision:2});
  await click('Send this saved request');expect(workspaceApi.ask).toHaveBeenCalledWith(access,id,conversationFixture);expect(currentDraft()?.pending).toBeNull();
});
it('requires explicit legacy uncertainty acknowledgment and retains the exact old binding under a new request',async()=>{
  const old:ModelOperation={type:'ask',body:conversationFixture};await restore(old);vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved(old));await click('Check saved result');
  expect(element.textContent).not.toContain('Send this saved request');await click('Start another attempt');const send=[...element.querySelectorAll('button')].find(b=>b.textContent==='Send new attempt')!;expect(send.disabled).toBe(true);
  const check=[...element.querySelectorAll('label')].find(l=>l.textContent?.includes('earlier provider outcome is unknown'))!.querySelector<HTMLInputElement>('input')!;await act(async()=>check.click());
  vi.mocked(workspaceApi.ask).mockRejectedValue(new WorkspaceApiError(503));await click('Send new attempt');await act(async()=>{await vi.waitFor(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());});
  const next=currentDraft()?.pending as ModelOperation;expect(next.model_contract).toBe(1);expect(next.body.idempotency_key).not.toBe(old.body.idempotency_key);
  expect(next.previous_model_request).toMatchObject({workspace_id:id,operation:old,outcome:'not_found',origin:'legacy_unknown',legacy_uncertainty_acknowledged:true,request_sha256:await modelRequestHash(old.body)});
  await restart();await vi.waitFor(async()=>{await act(async()=>{});expect([...element.querySelectorAll('button')].some(b=>b.textContent==='Restore notebook draft')).toBe(true);});await click('Restore notebook draft');expect(currentDraft()?.pending).toEqual(next);expect(workspaceApi.ask).toHaveBeenCalledOnce();
});
it('does not dispatch a replacement when journal CAS fails and retains old uncertainty and forms',async()=>{
  const old:ModelOperation={type:'ask',body:conversationFixture,model_contract:1,origin:'durable_admission_v1'};await restore(old);
  vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved(old,'unknown'));await click('Check saved result');await click('Start another attempt');failReplacement=true;
  await click('Send new attempt');await act(async()=>{await vi.waitFor(()=>expect(replacementWrites).toBe(1));});expect(workspaceApi.ask).not.toHaveBeenCalled();expect(currentDraft()?.pending).toEqual(old);
  expect(currentDraft()?.note).toBe('Keep invented notebook');expect(element.textContent).toContain('No new request was sent');
});
it('settles an exact queued historical retry independently of the newer current attempt',async()=>{
  const body={expected_revision:1,previous_attempt_id:modelUuid(702),idempotency_key:'historical-retry'},old:ModelOperation={type:'retry',handoffId:modelUuid(701),body};
  await restore(old);const receipt=await retryReceipt(body,id,modelUuid(701));vi.mocked(modelWorkApi.resolve).mockResolvedValue(receipt);
  vi.mocked(workspaceApi.read).mockResolvedValue({...original,revision:8,handoffs:[{id:modelUuid(701),origin_entry_id:modelUuid(610),recipient_role:'scribe',recipient_name:'Scribe',brief:'Invented brief',context_revision:1,status:'failed',attempt_id:modelUuid(704),attempt_count:3,result_entry_id:null,error_code:'model_unavailable',attempts:[]}]});
  await click('Check saved result');expect(currentDraft()?.pending).toBeNull();expect(element.textContent).toContain('Draft request recorded.');expect(workspaceApi.retryHandoff).not.toHaveBeenCalled();expect(currentDraft()?.evidence).toBe('Keep invented evidence');
});
it('renders a second-device terminal request without a reply or local journal and only resolves on explicit choice',async()=>{
  const workspace=await pendingWorkspace(undefined,'unknown');vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace,team});vi.mocked(workspaceApi.read).mockResolvedValue(workspace);
  await open();expect(element.textContent).toContain(conversationFixture.content);expect(element.textContent).toContain('Outcome unconfirmed');expect(modelWorkApi.resolve).not.toHaveBeenCalled();
  vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved({type:'ask',body:conversationFixture},'unknown'));await click('Check saved result');
  await act(async()=>{await vi.waitFor(()=>expect(modelWorkApi.resolve).toHaveBeenCalledOnce());});expect(vi.mocked(modelWorkApi.resolve).mock.calls[0][2].body).toEqual(conversationFixture);expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('merges a same-revision lifecycle poll and preserves unsaved notebook text, stopping when hidden or terminal',async()=>{
  const workspace=await pendingWorkspace(),terminal=await pendingWorkspace(undefined,'unknown');vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace,team});vi.mocked(workspaceApi.read).mockResolvedValue(terminal);
  const visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');vi.useFakeTimers();await open();await input('#team-notebook','Keep my typing');
  await act(async()=>vi.advanceTimersByTimeAsync(15000));expect(workspaceApi.read).not.toHaveBeenCalled();visibility.mockReturnValue('visible');await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  expect(workspaceApi.read).toHaveBeenCalledOnce();expect(element.textContent).toContain('Outcome unconfirmed');expect(element.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Keep my typing');
  await act(async()=>vi.advanceTimersByTimeAsync(15000));expect(workspaceApi.read).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
  await act(async()=>window.dispatchEvent(new Event('focus')));expect(workspaceApi.read).toHaveBeenCalledOnce();
  expect(element.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Keep my typing');
});
it('deduplicates the local bubble against an admitted server question while keeping the original encrypted body',async()=>{
  await open();await input('#team-question',conversationFixture.content);
  vi.mocked(workspaceApi.ask).mockImplementation(async(_access,_id,body)=>{const receipt=await modelReceipt(body,id),workspace=await pendingWorkspace(body);
    vi.mocked(workspaceApi.read).mockResolvedValue(workspace);return {...receipt,outcome:'reserved',admission:admissionFixture(),saved_entry:null};});
  await click('Send message');await vi.waitFor(async()=>{await act(async()=>{});expect(element.querySelectorAll('.team-human-message')).toHaveLength(1);expect(element.textContent).toContain('Request recorded');});
  expect(currentDraft()?.pending).not.toBeNull();expect(element.textContent).toContain('Request recorded');expect(workspaceApi.ask).toHaveBeenCalledOnce();
});

it('retains superseded exact uncertainty after the replacement settles and later notebook autosaves',async()=>{
 const old:ModelOperation={type:'ask',body:conversationFixture,model_contract:1,origin:'durable_admission_v1'};await restore(old);
 vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved(old,'unknown'));await click('Check saved result');await click('Start another attempt');
 vi.mocked(workspaceApi.ask).mockImplementation(async(_access,_id,body)=>modelReceipt(body,id));vi.mocked(workspaceApi.read).mockResolvedValue({...original,revision:2});
 await click('Send new attempt');await act(async()=>{await vi.waitFor(()=>expect(currentDraft()?.previous_model_request).toBeTruthy());});
 expect(currentDraft()?.pending).toBeNull();const history=structuredClone(currentDraft()!.previous_model_request);expect(history?.operation).toEqual(old.type==='ask'?{type:'ask',body:old.body}:old);
 expect(element.textContent).toContain('superseded history');await restart();await click('Restore notebook draft');
 await input('#team-notebook','Edited after restored history');await act(async()=>{await vi.waitFor(()=>expect(currentDraft()?.note).toBe('Edited after restored history'));});
 expect(currentDraft()?.previous_model_request).toEqual(history);expect(workspaceApi.ask).toHaveBeenCalledOnce();
});

it('settles an exact result while preserving changed notebook context for explicit comparison',async()=>{
 const old:ModelOperation={type:'ask',body:conversationFixture,model_contract:1,origin:'durable_admission_v1'};await restore(old);
 vi.mocked(modelWorkApi.resolve).mockResolvedValue(await modelReceipt(conversationFixture,id));vi.mocked(workspaceApi.read).mockResolvedValue({...original,revision:3,entries:[{id:modelUuid(801),kind:'scratchpad',revision:3,content:'Different saved notebook',source_label:null,origin:'human',ticket:null,created_at:modelTimestamp}]});
 await click('Check saved result');expect(currentDraft()?.pending).toBeNull();expect(currentDraft()?.note).toBe('Keep invented notebook');expect(element.textContent).toContain('saved notebook or team changed');expect(element.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Keep invented notebook');
 const save=[...element.querySelectorAll('button')].find(b=>b.textContent==='Save notebook revision');expect(save).toBeTruthy();expect(save!.disabled).toBe(true);
});
it('restores and resolves selected analysis with its exact anchors while preserving unsaved notebook content',async()=>{
 const {analysisBody}=await import('./research-analysis-test-fixture');const operation:ModelOperation={type:'ask',body:analysisBody,model_contract:1,origin:'durable_admission_v1'};await restore(operation);
 expect(element.textContent).toContain('Retained selected-source request');await restart();await click('Restore notebook draft');vi.mocked(modelWorkApi.resolve).mockResolvedValue(await modelReceipt(analysisBody,id));vi.mocked(workspaceApi.read).mockResolvedValue({...original,revision:2});await click('Check saved result');expect(vi.mocked(modelWorkApi.resolve).mock.calls[0][2]).toEqual(operation);expect(currentDraft()?.pending).toBeNull();expect(currentDraft()?.note).toBe('Keep invented notebook');expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('prepares a fresh analysis only after acknowledgment and retains the prior selection without submitting or converting it to ordinary chat',async()=>{
 const {analysisBody}=await import('./research-analysis-test-fixture');const operation:ModelOperation={type:'ask',body:analysisBody,model_contract:1,origin:'durable_admission_v1'};await restore(operation);vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved(operation,'unknown'));await click('Check saved result');expect(element.textContent).not.toContain('Start another attempt');const prepare=[...element.querySelectorAll('button')].find(b=>b.textContent==='Review sources for a new request')!;expect(prepare.disabled).toBe(true);
 const check=[...element.querySelectorAll('label')].find(l=>l.textContent?.includes('earlier model outcome may remain unconfirmed'))!.querySelector<HTMLInputElement>('input')!;await act(async()=>check.click());await click('Review sources for a new request');await vi.waitFor(async()=>{await act(async()=>{});expect(currentDraft()?.pending).toBeNull();});expect(currentDraft()?.previous_model_request?.operation).toEqual({type:'ask',body:analysisBody});expect(element.textContent).toContain('Nothing has been sent.');expect(workspaceApi.ask).not.toHaveBeenCalled();
});

it('second-device analysis recovery reconstructs selected anchors from retained server metadata',async()=>{
 const {analysisBody,analysisProjection}=await import('./research-analysis-test-fixture');const configured=teamFixture();configured.configuration.bots.push({role:'research',instance_id:analysisBody.role,name:'Research',enabled:true,response_style:'brief',include_notebook:false,include_evidence:false});configured.members.push({role:'research',instance_id:analysisBody.role,agent_id:modelUuid(102),name:'Research',initials:'R',description:'Public source analysis',prompt:'Review selected sources',capabilities:[]});configured.capture={enabled:false};
 const projection=await analysisProjection();vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:projection,team:configured});vi.mocked(workspaceApi.team).mockResolvedValue(configured);vi.mocked(workspaceApi.read).mockResolvedValue(projection);await open();
 const research=[...element.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.textContent?.includes('Research'));expect(research).toBeTruthy();await act(async()=>research!.click());await click('Saved encounter conversation');
 vi.mocked(modelWorkApi.resolve).mockResolvedValue(await unresolved({type:'ask',body:analysisBody},'unknown'));await click('Check saved result');expect(vi.mocked(modelWorkApi.resolve).mock.calls[0][2].body).toEqual(analysisBody);expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('hands the compact selected-source consent panel into the actual model journal and preserves its selection on response loss',async()=>{
 const {analysisBody,analysisProofFixture}=await import('./research-analysis-test-fixture');const {workspace:current,run,saved,anchor:analysisAnchor}=await analysisProofFixture();const {editorAddress}=await import('./draft-journal');const configured=teamFixture();configured.configuration.bots.push({role:'research',instance_id:analysisBody.role,name:'Research',enabled:true,response_style:'brief',include_notebook:false,include_evidence:false});configured.members.push({role:'research',instance_id:analysisBody.role,agent_id:modelUuid(102),name:'Research',initials:'R',description:'Public source analysis',prompt:'Review selected sources',capabilities:[]});configured.capture={enabled:false};
 vi.mocked(researchApi.history).mockResolvedValue({contract:'research.history.v1',runs:[run]});vi.mocked(researchApi.savedHistory).mockResolvedValue({contract:'research.saved_history.v1',workspace_id:id,bot:analysisBody.role,packets:[{query:run.query,saved}]});vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:current,team:configured});vi.mocked(workspaceApi.team).mockResolvedValue(configured);vi.mocked(workspaceApi.read).mockResolvedValue(current);const journal=new DraftJournal(await factory({scope:configured.recovery_scope!}));const savedAddress=editorAddress(id,`research:${analysisBody.role}`);await journal.load(savedAddress);await journal.persist(savedAddress,{kind:'editor',workspaceId:id,editor:`research:${analysisBody.role}`,pending:null,data:{version:1,bot:analysisBody.role,topic:'literature',query:'',sources:[],pending:null,saved_packet:analysisAnchor,analysis_draft:{question:analysisBody.content,selected:true}}});journal.close();
 await open();await input('#team-notebook','Do not overwrite my private notes');const research=[...element.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.textContent?.includes('Research'))!;await act(async()=>research.click());await click('Restore research draft');await click('Ask Research about saved sources');expect([...element.querySelectorAll('button')].find(b=>b.textContent==='Review AI request')!.disabled).toBe(true);await click('Load saved source details');await vi.waitFor(async()=>{await act(async()=>{await new Promise(resolve=>setTimeout(resolve,20));});expect(element.querySelector('[aria-label="Research operation"]')).toBeNull();expect(element.querySelector('.research-analysis')?.getAttribute('aria-busy')).toBe('false');expect(element.querySelector('.research-analysis .research-excerpt')?.textContent).toContain('Retained source details:');});await click('Review AI request');expect(researchApi.history).toHaveBeenCalledOnce();expect(researchApi.savedHistory).toHaveBeenCalledOnce();expect(researchApi.search).not.toHaveBeenCalled();expect(researchApi.save).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
 const consent=[...element.querySelectorAll('label')].find(l=>l.textContent?.includes('I consent to sending'))!.querySelector<HTMLInputElement>('input')!;await act(async()=>consent.click());vi.mocked(workspaceApi.ask).mockRejectedValue(new WorkspaceApiError(503));await click('Send to Research');await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledOnce();});
 const sent=vi.mocked(workspaceApi.ask).mock.calls[0][2];expect(sent).toMatchObject({expected_revision:3,role:analysisBody.role,content:analysisBody.content,research_analysis:{version:1,consented:true,entries:[analysisAnchor]}});expect(currentDraft()?.pending).toMatchObject({type:'ask',body:sent});expect(currentDraft()?.note).toBe('Do not overwrite my private notes');expect(configured.configuration.bots.at(-1)).toMatchObject({include_evidence:false,include_notebook:false});expect(element.textContent).toContain('Retained selected-source request');
});
