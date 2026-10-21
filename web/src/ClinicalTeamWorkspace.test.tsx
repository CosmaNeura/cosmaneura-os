import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {clinicalTeamApi} from './clinical-team-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {CLINICAL_NOTE_LABEL,clinicalTeamRequest,currentSharedNote,noteSelection,type ClinicalNoteShareReceipt,type ShareSavedNoteInput} from './clinical-team-contract';
import {modelCanonical} from './model-work-request';
import {modelWorkApi} from './model-work-api';
import {modelReceipt,pendingWorkspace} from './model-work-test-fixture';
import {vendorSha256} from './vendor-contract';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type BotRole,type PrivateNote,type ProviderTeam,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

vi.mock('./model-work-api',async original=>{const actual=await original<typeof import('./model-work-api')>();return {...actual,modelWorkApi:{...actual.modelWorkApi,resolve:vi.fn()}};});
vi.mock('./clinical-team-api',()=>({clinicalTeamApi:{share:vi.fn(),resolve:vi.fn()}}));
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(scope:string)=>scope}));
vi.mock('./private-recording-runtime',async original=>({...await original<typeof import('./private-recording-runtime')>(),listPrivateRecordings:vi.fn().mockResolvedValue([])}));
vi.mock('./team-setup-api',async()=>{
  const {WorkspaceApiError}=await import('./workspace-api');
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};
});
vi.mock('./workspace-api',async original=>{
  const actual=await original<typeof import('./workspace-api')>();
  return {...actual,workspaceApi:{...actual.workspaceApi,team:vi.fn(),catalog:vi.fn(),open:vi.fn(),read:vi.fn(),
    privateDraftSummaries:vi.fn(),practiceWork:vi.fn(),ask:vi.fn(),append:vi.fn()}};
});

const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const scope='a'.repeat(64),workingText='Retain this invented notebook text while sharing the separate saved note.';
const roles:BotRole[]=['scribe','chief','follow_up','research'];
const team:ProviderTeam={revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:true,model:'gpt-4.1'},
  configuration:{practice_context:'Invented practice',bots:roles.map(role=>({role,name:role==='chief'?'Chief':role,enabled:true,
    response_style:'brief',include_notebook:true,include_evidence:true,...(role==='research'?{instance_id:uuid(930)}:{})}))},
  members:roles.map((role,index)=>({role,agent_id:uuid(940+index),name:role==='chief'?'Chief':role,initials:role.slice(0,2),description:'Invented private teammate',
    prompt:'Use explicitly shared invented sources.',capabilities:[],...(role==='research'?{instance_id:uuid(930)}:{})}))};

let root:Root,host:HTMLDivElement,workspace:Workspace,identity:AuthenticatedWorkspaceIdentity,storage:ReturnType<typeof memoryDraftStorage>;
function deferred<T>() {let resolve!:(value:T)=>void,reject!:(reason:unknown)=>void;const promise=new Promise<T>((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
function saved(body:ShareSavedNoteInput,base=workspace):ClinicalNoteShareReceipt {
  const next=structuredClone(base),note=next.note!.latest!;
  next.revision++;
  const entry={id:uuid(955),revision:next.revision,kind:'conversation' as const,source_label:CLINICAL_NOTE_LABEL,origin:'human_note_share',
    content:JSON.stringify({contract:'clinical-note-team-source.v1',request:body,note:{id:note.id,version:note.version,content_hash:note.content_hash,
      source_fingerprint:note.source_fingerprint,content:note.content}}),reply:null,ticket:null,created_at:'2026-10-20T12:00:00Z'};
  next.entries.push(entry);
  return {contract:'clinical-note-share.v1',outcome:'saved',source_entry_id:entry.id,source_entry_revision:entry.revision,workspace:next};
}
function notFound(revision=workspace.revision):ClinicalNoteShareReceipt {
  return {contract:'clinical-note-share.v1',outcome:'not_found',source_entry_id:null,source_entry_revision:null,
    workspace:{...structuredClone(workspace),revision}};
}
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
async function click(name:string) {const selected=button(name);expect(selected,name).toBeTruthy();expect(selected!.disabled,name).toBe(false);await act(async()=>selected!.click());}
async function open(factory=storage,recovering=false,showPlan=true) {
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={factory}/>));
  await click('Visits and notes');
  await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')).toBeTruthy();
    if(!recovering)expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled).toBe(false);});
  if(recovering)return;
  const chief=[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;
  await act(async()=>chief.click());
  await click('Conversation view');
  if(showPlan)await act(async()=>{host.querySelector<HTMLDetailsElement>('.clinical-team-disclosure')!.open=true;});
}
async function selectNote() {
  await click('Preview saved note for team');
  await act(async()=>host.querySelector<HTMLInputElement>('.clinical-team-drafts input[type=checkbox]')!.click());
}
async function retained() {const probe=await storage({scope});try{return (await probe.read(`workspace:${workspace.id}`)).value?.body as {note:string;pending:null|{type:string;body:ShareSavedNoteInput}}|undefined;}finally{probe.close();}}
function preparationServer(base=workspace){
  let current=structuredClone(base);
  vi.mocked(clinicalTeamApi.share).mockImplementation(async(_owner,_id,body)=>{const receipt=saved(body,current);current=receipt.workspace;return receipt;});
  vi.mocked(workspaceApi.read).mockImplementation(async()=>structuredClone(current));
  vi.mocked(workspaceApi.ask).mockImplementation(async(_owner,id,body)=>{
    expect((await retained())?.pending).toEqual({type:'ask',model_contract:1,origin:'durable_admission_v1',body});
    expect(body.expected_revision).toBe(current.revision);
    const receipt=await modelReceipt(body,id,current.revision+1);current.revision++;
    current.entries.push({id:receipt.saved_entry!.id,revision:current.revision,kind:'conversation',content:body.content,source_label:null,origin:'human',ticket:null,
      created_at:'2026-10-20T12:00:00Z',reply:{agent_name:'Chief',role:'chief',backend:'invented',content:'Private team preparation received.',context_revision:body.expected_revision,citations:[]}});
    return receipt;
  });
  return {get current(){return current;},set current(value:Workspace){current=value;}};
}
beforeEach(async()=>{
  vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);
  team.members.find(member=>member.role==='chief')!.capabilities=[{key:'workspace.clinical.drafts',label:'Saved-note drafts',state:'enabled',connector:'Provider Team',contract:'clinical-team-drafts.request.v2'}];
  storage=memoryDraftStorage();identity={mode:'clerk_jwt',getToken:vi.fn()};
  const content='Invented saved sleep note for private provider review.';
  const note:PrivateNote={id:uuid(951),version:1,workspace_revision:2,content,
    content_hash:await vendorSha256(new TextEncoder().encode(modelCanonical({content}))),source_reply_id:null,source_revision:1,
    source_fingerprint:'b'.repeat(64),sources_changed:false,review:null,created_at:'2026-10-20T12:00:00Z'};
  workspace={id:uuid(950),appointment_id:uuid(949),label:'Invented sleep visit',revision:2,work_candidates:[],note:{latest:note,history:[note]},
    entries:[{id:uuid(948),revision:1,kind:'scratchpad',content:workingText,source_label:null,origin:'human',ticket:null,created_at:'2026-10-20T12:00:00Z'}]};
  vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));
  vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:workspace.appointment_id!,workspace_id:workspace.id,label:workspace.label}]);
  vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(workspace),team:structuredClone(team)});
  vi.mocked(workspaceApi.read).mockResolvedValue(structuredClone(workspace));
  vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
  vi.mocked(clinicalTeamApi.share).mockImplementation(async(_identity,_wid,body)=>saved(body));
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.unstubAllGlobals();});

it('opens the exact saved-note plan directly from native Chief without sharing or replacing the owner’s directions',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
  if(identity.mode!=='clerk_jwt')throw Error('Invented native identity required');
  identity.nativeSession={revision:uuid(970),isCurrent:()=>true};
  await open(storage,false,false);
  const question=host.querySelector<HTMLTextAreaElement>('#team-question')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question,'My next directions, still editable');question.dispatchEvent(new Event('input',{bubbles:true}));});
  expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"]')).toBeTruthy();
  expect(host.querySelector('.chief-saved-note-shortcut')?.textContent).toContain('version 1');
  await click('Plan from saved visit note version 1');
  expect(host.querySelector('[aria-label="Saved note for Follow-up and Research"]')?.textContent).toBe(workspace.note!.latest!.content);
  expect(host.querySelector<HTMLDetailsElement>('.clinical-team-disclosure')?.open).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')).toBe(question);
  expect(question.value).toBe('My next directions, still editable');expect(question.disabled).toBe(true);
  expect(question.closest('[hidden]')).toBeTruthy();
  const plan=host.querySelector<HTMLTextAreaElement>('.clinical-team-directions')!;
  expect(plan).toBeTruthy();expect(plan.closest('[hidden]')).toBeNull();expect(plan.disabled).toBe(false);expect(plan.value).toBe(question.value);
  expect(button('Prepare Follow-up and Research')?.disabled).toBe(false);
  expect(host.querySelector('[aria-label="Your directions for Chief"]')?.textContent).toContain('Add optional directions here.');
  expect(clinicalTeamApi.share).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
  await click('Back to chat');expect(host.querySelector<HTMLTextAreaElement>('#team-question')).toBe(question);
  expect(question.value).toBe('My next directions, still editable');expect(question.disabled).toBe(false);
});

it('refuses the native saved-note shortcut when the captured native session expires',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
  if(identity.mode!=='clerk_jwt')throw Error('Invented native identity required');
  let current=true;identity.nativeSession={revision:uuid(970),isCurrent:()=>current};
  await open(storage,false,false);const shortcut=button('Plan from saved visit note version 1')!;expect(shortcut).toBeTruthy();
  current=false;await act(async()=>shortcut.click());
  expect(host.querySelector<HTMLDetailsElement>('.clinical-team-disclosure')?.open).toBe(false);
  expect(clinicalTeamApi.share).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});

it('keeps the saved-note shortcut locked beside the exact unconfirmed native message',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
  if(identity.mode!=='clerk_jwt')throw Error('Invented native identity required');
  identity.nativeSession={revision:uuid(970),isCurrent:()=>true};
  vi.mocked(workspaceApi.ask).mockRejectedValueOnce(new WorkspaceApiError(503));
  await open(storage,false,false);const question=host.querySelector<HTMLTextAreaElement>('#team-question')!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question,'Keep this exact message');question.dispatchEvent(new Event('input',{bubbles:true}));});
  await click('Send message');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Unconfirmed model request"]')).toBeTruthy();});
  const sent=vi.mocked(workspaceApi.ask).mock.calls[0][2];
  expect((await retained())?.pending).toMatchObject({type:'ask',body:sent});
  const shortcut=button('Plan from saved visit note version 1')!;expect(shortcut.disabled).toBe(true);await act(async()=>shortcut.click());
  expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"]')).toBeTruthy();
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')).toBe(question);expect(question.disabled).toBe(false);
  expect(host.querySelector<HTMLDetailsElement>('.clinical-team-disclosure')?.open).toBe(false);
  expect(clinicalTeamApi.share).not.toHaveBeenCalled();expect(workspaceApi.ask).toHaveBeenCalledOnce();
  expect((await retained())?.pending).toMatchObject({type:'ask',body:sent});
});

it('acknowledges the exact share in the draft journal before making any network request',async()=>{
  const ack=deferred<void>();let captured:unknown;
  const factory:typeof storage=async options=>{
    const store=await storage(options);
    return {...store,write:async(address,revision,value)=>{
      if((value?.body as {pending?:{type?:string}})?.pending?.type==='clinicalNoteShare'){captured=structuredClone(value!.body);await ack.promise;}
      return store.write(address,revision,value);
    }};
  };
  await open(factory);await selectNote();await click('Share saved note with team');
  expect(captured).toMatchObject({note:workingText,pending:{type:'clinicalNoteShare',body:{expected_revision:2,note_id:workspace.note!.latest!.id,
    note_version:1,content_hash:workspace.note!.latest!.content_hash,source_fingerprint:'b'.repeat(64),share_with_team:true}}});
  expect(clinicalTeamApi.share).not.toHaveBeenCalled();
  let durableBeforeNetwork=false;
  vi.mocked(clinicalTeamApi.share).mockImplementation(async(_identity,wid,body)=>{
    expect(wid).toBe(workspace.id);expect((await retained())?.pending).toEqual({type:'clinicalNoteShare',body});durableBeforeNetwork=true;return saved(body);
  });
  await act(async()=>ack.resolve());
  expect(durableBeforeNetwork).toBe(true);expect(clinicalTeamApi.share).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('This exact saved note is shared with your private team');
  expect((await retained())?.pending??null).toBeNull();expect(workspaceApi.ask).not.toHaveBeenCalled();
});

it('reopens a lost share reply as an exact resolve-only request without another share or bot call',async()=>{
  vi.mocked(clinicalTeamApi.share).mockRejectedValueOnce(new TypeError('Invented lost response'));
  await open();await selectNote();await click('Share saved note with team');
  const body=vi.mocked(clinicalTeamApi.share).mock.calls[0][2];
  expect((await retained())?.pending).toEqual({type:'clinicalNoteShare',body});expect(button('Retry same note share')).toBeUndefined();
  await act(async()=>root.unmount());root=createRoot(host);
  await open(storage,true);await click('Restore notebook draft');
  vi.mocked(clinicalTeamApi.resolve).mockResolvedValue(saved(body));
  await click('Check saved note share');
  expect(vi.mocked(clinicalTeamApi.resolve).mock.calls[0]).toEqual([identity,workspace.id,body]);
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
  expect(button('Check saved note share')).toBeUndefined();expect((await retained())?.pending??null).toBeNull();
});

it('offers explicit exact retry only after a matching not-found read and retains the same body and key',async()=>{
  vi.mocked(clinicalTeamApi.share).mockRejectedValueOnce(new TypeError('Invented lost response'));
  await open();await selectNote();await click('Share saved note with team');
  const body=vi.mocked(clinicalTeamApi.share).mock.calls[0][2];
  expect(button('Retry same note share')).toBeUndefined();
  vi.mocked(clinicalTeamApi.resolve).mockResolvedValueOnce(notFound(1));await click('Check saved note share');
  expect(button('Retry same note share')).toBeUndefined();expect(button('Close rejected note share')).toBeUndefined();
  vi.mocked(clinicalTeamApi.resolve).mockResolvedValueOnce(notFound());await click('Check saved note share');
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(button('Retry same note share')).toBeTruthy();
  await click('Retry same note share');
  expect(vi.mocked(clinicalTeamApi.share).mock.calls[1]).toEqual([identity,workspace.id,body]);
  expect(clinicalTeamApi.resolve).toHaveBeenCalledTimes(2);expect(workspaceApi.ask).not.toHaveBeenCalled();
});

it('requires explicit close for an advanced-revision not-found share and retains the local working text',async()=>{
  vi.mocked(clinicalTeamApi.share).mockRejectedValueOnce(new TypeError('Invented lost response'));
  await open();await selectNote();await click('Share saved note with team');
  const body=vi.mocked(clinicalTeamApi.share).mock.calls[0][2],receipt=notFound(4);
  receipt.workspace.entries.push({...receipt.workspace.entries[0],id:uuid(956),revision:4,content:'Different saved notebook text from another authorized session.'});
  vi.mocked(clinicalTeamApi.resolve).mockResolvedValue(receipt);await click('Check saved note share');
  expect(button('Retry same note share')).toBeUndefined();expect(button('Close rejected note share')).toBeTruthy();
  expect((await retained())?.pending).toEqual({type:'clinicalNoteShare',body});
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe(workingText);
  await click('Close rejected note share');
  expect(host.textContent).toContain('Rejected note share closed. Your working text is retained');
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe(workingText);
  expect((await retained())?.note).toBe(workingText);expect((await retained())?.pending).toBeNull();
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
});

it('ignores a late identity denial from the old share after a different owner has opened',async()=>{
  const response=deferred<ClinicalNoteShareReceipt>();vi.mocked(clinicalTeamApi.share).mockReturnValue(response.promise);
  await open();await selectNote();await click('Share saved note with team');
  const next:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};
  vi.mocked(workspaceApi.team).mockResolvedValue({...structuredClone(team),recovery_scope:'c'.repeat(64)});
  await act(async()=>root.render(<EncounterWorkspace authenticated={next} draftStorage={storage}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Practice Home"]')).toBeTruthy();});
  await act(async()=>response.reject(new WorkspaceApiError(403)));
  expect(host.textContent).not.toContain('Workspace access is unavailable');expect(host.textContent).not.toContain(workingText);
  expect(host.querySelector('#team-notebook')).toBeNull();expect(button('Check saved note share')).toBeUndefined();
  const probe=await storage({scope:'c'.repeat(64)});expect((await probe.read(`workspace:${workspace.id}`)).value).toBeNull();probe.close();
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
});

it('prepares from one gesture only after the exact share is durably cleared and uses the confirmed new revision',async()=>{
  const clear=deferred<void>();let sharing=false,cleared=false;
  const factory:typeof storage=async options=>{const store=await storage(options);return {...store,write:async(address,revision,value)=>{
    if((value?.body as {pending?:{type?:string}})?.pending?.type==='clinicalNoteShare')sharing=true;
    if(sharing&&value===null&&!cleared){await clear.promise;const result=await store.write(address,revision,value);cleared=true;return result;}
    return store.write(address,revision,value);
  }};};
  const server=preparationServer();await open(factory);
  expect(host.querySelector('[aria-label="Saved note for Follow-up and Research"]')?.textContent).toContain(workspace.note!.latest!.content);
  await click('Prepare Follow-up and Research');
  await vi.waitFor(()=>expect(clinicalTeamApi.share).toHaveBeenCalledOnce());expect(workspaceApi.ask).not.toHaveBeenCalled();
  expect((await retained())?.pending?.type).toBe('clinicalNoteShare');
  await act(async()=>clear.resolve());
  await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledOnce();expect((await retained())?.pending??null).toBeNull();});
  expect(cleared).toBe(true);expect(vi.mocked(workspaceApi.ask).mock.calls[0][2]).toMatchObject({expected_revision:3,team_revision:1,role:'chief',
    content:clinicalTeamRequest(currentSharedNote(server.current)!)});
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe(workingText);
});

it('does not chain or replay Chief after an uncertain combined share, including resolve after remount',async()=>{
  vi.mocked(clinicalTeamApi.share).mockRejectedValueOnce(new TypeError('Invented lost combined reply'));
  await open();await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>expect((await retained())?.pending?.type).toBe('clinicalNoteShare'));
  const body=vi.mocked(clinicalTeamApi.share).mock.calls[0][2];expect(workspaceApi.ask).not.toHaveBeenCalled();
  await act(async()=>root.unmount());root=createRoot(host);await open(storage,true);await click('Restore notebook draft');
  vi.mocked(clinicalTeamApi.resolve).mockResolvedValue(saved(body));await click('Check saved note share');
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(clinicalTeamApi.resolve).toHaveBeenCalledExactlyOnceWith(identity,workspace.id,body);
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect((await retained())?.pending??null).toBeNull();
});

it('reuses the exact already-shared source without another share and prepares directly from saved-note review',async()=>{
  workspace=saved(noteSelection(workspace.note!.latest!,workspace.revision)).workspace;
  const server=preparationServer(workspace);vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(workspace),team:structuredClone(team)});
  await open();await click('Workspace view');await click('Review');await click('Prepare follow-up and research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledOnce();expect((await retained())?.pending??null).toBeNull();});
  expect(clinicalTeamApi.share).not.toHaveBeenCalled();expect(vi.mocked(workspaceApi.ask).mock.calls[0][2].content).toBe(clinicalTeamRequest(currentSharedNote(server.current)!));
  expect(host.querySelector<HTMLDetailsElement>('.clinical-team-disclosure')?.open).toBe(true);
});

it.each(['note','team'] as const)('stops the combined continuation when the fresh %s changes after sharing',async changed=>{
  const server=preparationServer();await open();
  if(changed==='note')vi.mocked(workspaceApi.read).mockImplementation(async()=>{const next=structuredClone(server.current);next.note!.latest!.sources_changed=true;return next;});
  else vi.mocked(workspaceApi.team).mockResolvedValue({...structuredClone(team),revision:2});
  await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('No new Chief request was sent');});
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();expect((await retained())?.pending??null).toBeNull();
});

it('cancels combined preparation under owner replacement while its pre-share journal write is held',async()=>{
  const write=deferred<void>();let recorded=false;
  const factory:typeof storage=async options=>{const store=await storage(options);return {...store,write:async(address,revision,value)=>{
    if((value?.body as {pending?:{type?:string}})?.pending?.type==='clinicalNoteShare'){recorded=true;await write.promise;}
    return store.write(address,revision,value);
  }};};
  await open(factory);await click('Prepare Follow-up and Research');await vi.waitFor(()=>expect(recorded).toBe(true));
  const next:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};
  vi.mocked(workspaceApi.team).mockResolvedValue({...structuredClone(team),recovery_scope:'c'.repeat(64)});
  await act(async()=>root.render(<EncounterWorkspace authenticated={next} draftStorage={factory}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Practice Home"]')).toBeTruthy();});
  await act(async()=>write.resolve());expect(clinicalTeamApi.share).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain(workingText);
});

it('does not enqueue Chief for a replaced owner after sharing while the fresh source read is held',async()=>{
  const fresh=deferred<Workspace>();preparationServer();await open();vi.mocked(workspaceApi.read).mockReturnValue(fresh.promise);
  await click('Prepare Follow-up and Research');await vi.waitFor(()=>expect(workspaceApi.read).toHaveBeenCalled());
  const body=vi.mocked(clinicalTeamApi.share).mock.calls[0][2],receipt=saved(body);
  const next:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};vi.mocked(workspaceApi.team).mockResolvedValue({...structuredClone(team),recovery_scope:'c'.repeat(64)});
  await act(async()=>root.render(<EncounterWorkspace authenticated={next} draftStorage={storage}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Practice Home"]')).toBeTruthy();});
  await act(async()=>fresh.resolve(receipt.workspace));expect(workspaceApi.ask).not.toHaveBeenCalled();expect(host.textContent).not.toContain(workingText);
});

it('does not duplicate a Chief request discovered in the fresh source read',async()=>{
  const server=preparationServer();await open();vi.mocked(workspaceApi.read).mockImplementation(async()=>{
    const latest=structuredClone(server.current),source=currentSharedNote(latest)!;
    const existing=await pendingWorkspace({expected_revision:latest.revision,team_revision:1,idempotency_key:'invented-existing-chief',role:'chief',content:clinicalTeamRequest(source)});
    const entry=existing.entries[0];entry.model_request!.bot.role='chief';entry.model_request!.bot.name='Chief';entry.revision=++latest.revision;latest.entries.push(entry);return latest;
  });
  await click('Prepare Follow-up and Research');await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('Chief’s request is already saved');});
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
});


async function enterDirections(value:string){
  const question=[...host.querySelectorAll<HTMLTextAreaElement>('.clinical-team-directions,#team-question')].find(field=>!field.closest('[hidden]'))!;
  expect(question).toBeTruthy();expect(question.disabled).toBe(false);
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(question,value);question.dispatchEvent(new Event('input',{bubbles:true}));});
  return question;
}
function nativeChief(){
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
  if(identity.mode!=='clerk_jwt')throw Error('Invented native identity required');
  identity.nativeSession={revision:uuid(970),isCurrent:()=>true};
}
it('binds exact owner directions and saved-note identity before clearing the native composer, then preserves an identical next draft',async()=>{
  nativeChief();const server=preparationServer(),reply=deferred<Awaited<ReturnType<typeof modelReceipt>>>();
  vi.mocked(workspaceApi.ask).mockReturnValue(reply.promise);
  await open(storage,false,false);await click('Plan from saved visit note version 1');const directions='  Keep the patient email brief.\nAsk Research about missing evidence. 界🩺  ';
  const question=await enterDirections(directions);
  expect(button('Prepare Follow-up and Research')?.disabled).toBe(false);
  await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledOnce();});
  const body=vi.mocked(workspaceApi.ask).mock.calls[0][2],source=currentSharedNote(server.current)!;
  expect(JSON.parse(body.content)).toEqual({contract:'clinical-team-drafts.request.v2',source_entry_id:source.entry.id,
    note_id:source.snapshot.note.id,note_version:1,content_hash:source.snapshot.note.content_hash,owner_directions:directions});
  expect(question.value).toBe('');expect(question.disabled).toBe(false);
  expect((await retained())?.pending).toMatchObject({type:'ask',body});
  await enterDirections(directions);
  const result=await modelReceipt(body,workspace.id,server.current.revision+1);
  server.current={...server.current,revision:server.current.revision+1,entries:[...server.current.entries,{id:result.saved_entry!.id,revision:server.current.revision+1,
    kind:'conversation',source_label:null,origin:'human',ticket:null,created_at:'2026-10-20T12:00:00Z',content:body.content,
    reply:{agent_name:'Chief',role:'chief',backend:'invented',content:'Private drafts queued.',context_revision:body.expected_revision,citations:[]}}]};
  await act(async()=>reply.resolve(result));
  await vi.waitFor(async()=>{await act(async()=>{});expect((await retained())?.pending??null).toBeNull();});
  expect(question.value).toBe(directions);expect(host.querySelector('.clinical-team-directions')).toBe(question);
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();
});
it('retains v2 directions under an exact lost Chief response and remount only checks that same request',async()=>{
  nativeChief();const server=preparationServer();vi.mocked(workspaceApi.ask).mockRejectedValueOnce(new WorkspaceApiError(503));
  await open(storage,false,false);await click('Plan from saved visit note version 1');const directions='Use the stated plan only; medicine list remains unknown.\n界';await enterDirections(directions);
  await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Unconfirmed model request"]')).toBeTruthy();});
  const body=vi.mocked(workspaceApi.ask).mock.calls[0][2];expect(JSON.parse(body.content).owner_directions).toBe(directions);
  expect((await retained())?.pending).toMatchObject({type:'ask',body});
  await act(async()=>root.unmount());root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(button('Restore notebook draft')).toBeTruthy();});await click('Restore notebook draft');
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect((await retained())?.pending).toMatchObject({type:'ask',body});
  const observation={...await modelReceipt(body,workspace.id),outcome:'not_found' as const,saved_entry:null};
  vi.mocked(modelWorkApi.resolve).mockResolvedValue(observation);
  await click(button('Check message')?'Check message':'Check saved result');
  expect(modelWorkApi.resolve).toHaveBeenCalledExactlyOnceWith(identity,workspace.id,expect.objectContaining({type:'ask',body}));
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect(clinicalTeamApi.share).toHaveBeenCalledOnce();
  const older=structuredClone(team);older.members.find(member=>member.role==='chief')!.capabilities=[];vi.mocked(workspaceApi.team).mockResolvedValue(older);
  await vi.waitFor(async()=>{await act(async()=>{});expect(button('Retry message')??button('Send this saved request')).toBeTruthy();});
  await click(button('Retry message')?'Retry message':'Send this saved request');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('cannot confirm saved-note directions support');});
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect((await retained())?.pending).toMatchObject({type:'ask',body});
  await click(button('Check message')?'Check message':'Check saved result');expect(modelWorkApi.resolve).toHaveBeenCalledTimes(2);
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect((await retained())?.pending).toMatchObject({type:'ask',body});expect(server.current.note!.latest!.content).toBe(workspace.note!.latest!.content);
});
it('returns from the phone plan to native chat during a held Chief dispatch and keeps identical next typing after its lost reply',async()=>{
  nativeChief();preparationServer();const dispatch=deferred<Awaited<ReturnType<typeof modelReceipt>>>();vi.mocked(workspaceApi.ask).mockReturnValue(dispatch.promise);
  await open(storage,false,false);await click('Plan from saved visit note version 1');const directions='Keep the email brief. 界🩺';
  await enterDirections(directions);await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledOnce();expect(button('Back to chat')?.disabled).toBe(false);});
  const body=vi.mocked(workspaceApi.ask).mock.calls[0][2];expect((await retained())?.pending).toMatchObject({type:'ask',body});
  await click('Back to chat');expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"][data-chief-tools="false"]')).toBeTruthy();
  const question=await enterDirections(directions);expect(question.id).toBe('team-question');expect(question.closest('[hidden]')).toBeNull();
  expect(button('Send message')?.disabled).toBe(true);
  await act(async()=>dispatch.reject(new WorkspaceApiError(503)));
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Unconfirmed model request"]')?.closest('[hidden]')).toBeNull();
    expect((await retained())?.pending).toMatchObject({type:'ask',body});});
  expect(question.value).toBe(directions);expect(question.disabled).toBe(false);expect(host.querySelector('#team-question')).toBe(question);
  const probe=await storage({scope});try{await vi.waitFor(async()=>{await act(async()=>{});expect((await probe.read(`workspace:${workspace.id}`)).value?.body).toMatchObject({thought:directions,pending:{type:'ask',body}});});}finally{probe.close();}
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect(JSON.parse(body.content).owner_directions).toBe(directions);
});
it('keeps clinical uncertainty out of generic chat replacement and explicitly reselects the current note and directions',async()=>{
  nativeChief();const server=preparationServer();vi.mocked(workspaceApi.ask).mockRejectedValueOnce(new WorkspaceApiError(503));
  await open(storage,false,false);await click('Plan from saved visit note version 1');await enterDirections('Original human drafting directions.');
  await click('Prepare Follow-up and Research');await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Unconfirmed model request"]')).toBeTruthy();});
  const old=vi.mocked(workspaceApi.ask).mock.calls[0][2];
  const updated={...server.current.note!.latest!,id:uuid(956),version:2,content:'Updated invented saved Scribe note; diagnosis remains unverified.'};
  updated.content_hash=await vendorSha256(new TextEncoder().encode(modelCanonical({content:updated.content})));
  server.current={...server.current,revision:server.current.revision+1,note:{latest:updated,history:[updated,server.current.note!.latest!]}};
  const older=structuredClone(team);older.members.find(member=>member.role==='chief')!.capabilities=[];vi.mocked(workspaceApi.team).mockResolvedValue(older);
  vi.mocked(modelWorkApi.resolve).mockResolvedValue({...await modelReceipt(old,workspace.id),outcome:'not_found',saved_entry:null});
  await click('Check message');await vi.waitFor(async()=>{await act(async()=>{});expect(button('Retry message')).toBeTruthy();});
  expect(button('Start another attempt')).toBeUndefined();expect(host.querySelector('label')?.textContent).not.toBe('Review new question');
  await click('Retry message');await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('cannot confirm saved-note directions support');});
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect((await retained())?.pending).toMatchObject({type:'ask',body:old});
  vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));await click('Check message');
  await vi.waitFor(async()=>{await act(async()=>{});expect(button('Review saved note and directions for a new request')?.disabled).toBe(true);});
  await enterDirections('Use this updated note, with a shorter email. 界');
  const acknowledge=[...host.querySelectorAll<HTMLInputElement>('[aria-label="Unconfirmed model request"] input[type=checkbox]')][0];
  await act(async()=>acknowledge.click());await click('Review saved note and directions for a new request');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[aria-label="Saved note for Follow-up and Research"]')?.textContent).toBe(updated.content);expect(button('Prepare Follow-up and Research')?.disabled).toBe(false);});
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect(clinicalTeamApi.share).toHaveBeenCalledOnce();
  const probe=await storage({scope});try{expect((await probe.read(`workspace:${workspace.id}`)).value?.body).toMatchObject({pending:null,previous_model_request:{operation:{type:'ask',body:old}}});}finally{probe.close();}
  await click('Prepare Follow-up and Research');await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledTimes(2);});
  const next=vi.mocked(workspaceApi.ask).mock.calls[1][2];expect(next.idempotency_key).not.toBe(old.idempotency_key);
  expect(JSON.parse(next.content)).toMatchObject({contract:'clinical-team-drafts.request.v2',note_id:updated.id,note_version:2,content_hash:updated.content_hash,owner_directions:'Use this updated note, with a shorter email. 界'});
});
it('does not send captured directions if the owner edits while the fresh saved-note read is held',async()=>{
  nativeChief();const server=preparationServer(),fresh=deferred<Workspace>();await open(storage,false,false);await click('Plan from saved visit note version 1');
  vi.mocked(workspaceApi.read).mockReturnValueOnce(fresh.promise);await enterDirections('Keep the email concise.');
  await click('Prepare Follow-up and Research');await vi.waitFor(()=>expect(clinicalTeamApi.share).toHaveBeenCalledOnce());
  await enterDirections('Ask a different question instead.');
  await act(async()=>fresh.resolve(server.current));
  await vi.waitFor(async()=>{await act(async()=>{});expect(button('Prepare Follow-up and Research')?.disabled).toBe(false);});
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect(host.querySelector<HTMLTextAreaElement>('.clinical-team-directions')?.value).toBe('Ask a different question instead.');
});

it('keeps directions visible and sends no share when an older service has not advertised v2',async()=>{
  nativeChief();const old=structuredClone(team);old.members.find(member=>member.role==='chief')!.capabilities=[];
  vi.mocked(workspaceApi.team).mockResolvedValue(old);vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(workspace),team:old});await open(storage,false,false);await click('Plan from saved visit note version 1');
  const question=await enterDirections('My exact directions.');
  expect(button('Prepare Follow-up and Research')?.disabled).toBe(true);expect(host.textContent).toContain('service needs an update');
  expect(question.value).toBe('My exact directions.');expect(workspaceApi.ask).not.toHaveBeenCalled();expect(clinicalTeamApi.share).not.toHaveBeenCalled();
  await enterDirections('');expect(button('Prepare Follow-up and Research')?.disabled).toBe(false);
});
it('retains the exact v2 request and visible words when deployed support disappears after its journal acknowledgement',async()=>{
  nativeChief();let downgraded=false;preparationServer();
  vi.mocked(workspaceApi.team).mockImplementation(async()=>{const latest=structuredClone(team);if(downgraded)latest.members.find(member=>member.role==='chief')!.capabilities=[];return latest;});
  const factory:typeof storage=async options=>{const store=await storage(options);return {...store,write:async(address,revision,value)=>{
    const result=await store.write(address,revision,value);if((value?.body as {pending?:{type?:string}})?.pending?.type==='ask')downgraded=true;return result;
  }};};
  await open(factory,false,false);await click('Plan from saved visit note version 1');const directions='Keep the documented plan exact. 界';
  const question=await enterDirections(directions);await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('cannot confirm saved-note directions support');});
  expect(clinicalTeamApi.share).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
  const pending=(await retained())?.pending;expect(pending).toMatchObject({type:'ask'});
  expect(JSON.parse((pending as unknown as {body:{content:string}}).body.content).owner_directions).toBe(directions);
  expect(question.value).toBe(directions);expect(host.querySelector('.clinical-team-directions')).toBe(question);
});
it.each(['new_words','edit_back_to_same'] as const)('preserves newer words during the initial v2 journal write: %s',async change=>{
  nativeChief();preparationServer();const ack=deferred<void>();let written=false;
  const factory:typeof storage=async options=>{const store=await storage(options);return {...store,write:async(address,revision,value)=>{
    if((value?.body as {pending?:{type?:string}})?.pending?.type==='ask'&&!written){written=true;await ack.promise;}return store.write(address,revision,value);
  }};};
  await open(factory,false,false);await click('Plan from saved visit note version 1');const directions='Keep exact provider directions.';
  const question=await enterDirections(directions);await click('Prepare Follow-up and Research');await vi.waitFor(()=>expect(written).toBe(true));
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect(question.value).toBe(directions);
  await enterDirections('A different next draft.');if(change==='edit_back_to_same')await enterDirections(directions);
  const next=question.value;await act(async()=>ack.resolve());
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('prepared request is retained');});
  expect(question.value).toBe(next);expect(workspaceApi.ask).not.toHaveBeenCalled();
  expect((await retained())?.pending).toMatchObject({type:'ask'});
});
it('keeps the original composer and sends nothing when the exact v2 pending write fails',async()=>{
  nativeChief();preparationServer();const factory:typeof storage=async options=>{const store=await storage(options);return {...store,write:async(address,revision,value)=>{
    if((value?.body as {pending?:{type?:string}})?.pending?.type==='ask')throw new Error('Invented local write failure');return store.write(address,revision,value);
  }};};
  await open(factory,false,false);await click('Plan from saved visit note version 1');const question=await enterDirections('Retain these directions after failed storage.');
  await click('Prepare Follow-up and Research');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.textContent).toContain('No new request was sent');});
  expect(question.value).toBe('Retain these directions after failed storage.');expect(workspaceApi.ask).not.toHaveBeenCalled();
});
