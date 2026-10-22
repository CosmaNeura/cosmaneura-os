import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {memoryDraftStorage} from './draft-test-fixture';
import type {PrivateNotebookResult,PrivateRecordingPanelProps} from './PrivateRecordingPanel';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
import {listPrivateRecordings,type PrivateRecordingSnapshot} from './private-recording-runtime';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const panel=vi.hoisted(()=>({props:null as PrivateRecordingPanelProps|null,mounts:0,holdClose:false,completeClose:null as (()=>void)|null}));
// No microphone adapter is constructed in this navigation test. The production
// recording panel's consent/runtime behavior has its own adapter integration tests.
vi.mock('./PrivateRecordingPanel',()=>({PrivateRecordingPanel:(props:PrivateRecordingPanelProps)=>{
  panel.props=props;
  useEffect(()=>{panel.mounts++;},[]);
  return <><aside hidden={!props.minimized}><button onClick={props.onExpand}>Return to recording</button></aside>
    <section hidden={props.minimized} className="private-recording-panel" aria-label="Private Scribe recording"><header>
      <button onClick={props.onMinimize}>Browse workspace</button><h1 tabIndex={-1}>Start a private recording</h1>
      <button onClick={()=>{if(panel.holdClose)panel.completeClose=props.onClose;else props.onClose();}}>Close recording</button>
    </header></section></>;
}}));
vi.mock('./capture-api',async original=>({...await original<typeof import('./capture-api')>(),CAPTURE_WORKSPACE_BUILD:true}));
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(scope:string)=>scope}));
vi.mock('./private-recording-runtime',async original=>({...await original<typeof import('./private-recording-runtime')>(),listPrivateRecordings:vi.fn().mockResolvedValue([])}));
vi.mock('./team-setup-api',async()=>{
  const {WorkspaceApiError}=await import('./workspace-api');
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};
});
vi.mock('./workspace-api',async original=>{
  const actual=await original<typeof import('./workspace-api')>();
  return {...actual,workspaceApi:{...actual.workspaceApi,team:vi.fn(),catalog:vi.fn(),privateDraftSummaries:vi.fn(),
    createPrivateDraft:vi.fn(),openPrivateDraft:vi.fn(),linkAppointment:vi.fn(),read:vi.fn(),ask:vi.fn(),append:vi.fn()}};
});
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const scope='a'.repeat(64),workingNote='Invented working note, kept while preparing a recording.',workingQuestion='Invented next question for Chief.';
const team:ProviderTeam={revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},
  configuration:{practice_context:'Invented practice',bots:['chief','scribe'].map(role=>({role:role as 'chief'|'scribe',name:role==='chief'?'Chief':'Scribe',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}))},
  members:['chief','scribe'].map((role,index)=>({role:role as 'chief'|'scribe',agent_id:uuid(810+index),name:role==='chief'?'Chief':'Scribe',initials:role.slice(0,2),description:'Invented teammate',prompt:'Use saved context',capabilities:[]}))};
let root:Root,host:HTMLDivElement,identity:AuthenticatedWorkspaceIdentity,workspace:Workspace;
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
async function click(name:string){const selected=button(name);expect(selected,name).toBeTruthy();expect(selected!.disabled,name).toBe(false);await act(async()=>selected!.click());}
async function write(selector:string,value:string){const field=host.querySelector<HTMLTextAreaElement>(selector)!;
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
async function open(){
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector<HTMLButtonElement>('.practice-quick-start button[type=submit]')?.disabled).toBe(false);});
  await act(async()=>host.querySelector<HTMLButtonElement>('.practice-quick-start button[type=submit]')!.click());
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled).toBe(false);});
  await click('Conversation view');await write('#team-notebook',workingNote);await write('#team-question',workingQuestion);
}
const notebookResult=():PrivateNotebookResult=>({identity,workspace:structuredClone(workspace),team:structuredClone(team)});
beforeEach(()=>{
  vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);panel.props=null;panel.mounts=0;panel.holdClose=false;panel.completeClose=null;
  identity={mode:'clerk_jwt',getToken:vi.fn()};
  workspace={id:uuid(800),appointment_id:null,label:'Invented private note',revision:1,entries:[],work_candidates:[],
    private_draft:{title:'Invented private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
  vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));
  vi.mocked(workspaceApi.catalog).mockResolvedValue([]);
  vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
  vi.mocked(workspaceApi.createPrivateDraft).mockImplementation(async()=>notebookResult());
  vi.mocked(workspaceApi.openPrivateDraft).mockImplementation(async()=>notebookResult());
  vi.mocked(workspaceApi.read).mockImplementation(async()=>structuredClone(workspace));
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.unstubAllGlobals();});

it.each(['Start a private recording','Scribe'])('opens consent preparation from an unlinked note through %s without creating or linking another notebook',async entry=>{
  await open();
  if(entry==='Scribe')await act(async()=>[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='Scribe')!.click());
  else await click(entry);
  expect(host.querySelector('[aria-label="Private Scribe recording"]')).toBeTruthy();
  expect(workspaceApi.openPrivateDraft).not.toHaveBeenCalled();expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();
  expect(panel.props!.title).toBe(workspace.private_draft!.title);expect(panel.props!.isCurrent()).toBe(true);
  const result=await panel.props!.prepareNotebook!();
  expect(workspaceApi.openPrivateDraft).toHaveBeenCalledExactlyOnceWith(identity,workspace.id);
  expect(result.workspace.id).toBe(workspace.id);expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();
  expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();
  await click('Close recording');
  expect(host.querySelector('.workspace-notebook')?.closest('[hidden]')).toBeNull();
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toBe(workingQuestion);
});

it.each(['onNotebook','onTranscribe'] as const)('retains working text when %s returns a newer signed version of that same private notebook',async callback=>{
  await open();await click('Start a private recording');
  const current=panel.props!,result=notebookResult();result.workspace.revision=2;
  result.workspace.entries=[{id:uuid(802),revision:2,kind:'scratchpad',content:'Different saved text from the signed read.',source_label:null,origin:'human',ticket:null,created_at:'2026-10-20T00:00:00Z'}];
  await act(async()=>callback==='onNotebook'?current.onNotebook!(result):current.onTranscribe!(result,uuid(803)));
  expect(host.querySelector('[aria-label="Private Scribe recording"]')).toBeNull();
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toBe(workingQuestion);
  expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();
});

it.each(['workspace','identity','scope','linked'] as const)('rejects a signed preparation result with a different %s instead of attaching a recording',async mismatch=>{
  await open();await click('Start a private recording');const result=notebookResult();
  if(mismatch==='workspace')result.workspace.id=uuid(804);
  if(mismatch==='identity')result.identity={mode:'clerk_jwt',getToken:vi.fn()};
  if(mismatch==='scope')result.team.recovery_scope='b'.repeat(64);
  if(mismatch==='linked'){result.workspace.appointment_id=uuid(805);result.workspace.private_draft!.state='linked';}
  vi.mocked(workspaceApi.openPrivateDraft).mockResolvedValue(result);
  await expect(panel.props!.prepareNotebook!()).rejects.toMatchObject({status:403});
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();
});

it('rejects a notebook read completed after native owner access ends',async()=>{
  let current=true;identity={mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision:'invented-native-revision',isCurrent:()=>current} as NonNullable<Extract<AuthenticatedWorkspaceIdentity,{mode:'clerk_jwt'}>['nativeSession']>};
  await open();await click('Start a private recording');
  let release!:(value:PrivateNotebookResult)=>void;
  vi.mocked(workspaceApi.openPrivateDraft).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  const prepared=panel.props!.prepareNotebook!();
  await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
  current=false;release(notebookResult());
  await expect(prepared).rejects.toMatchObject({status:403});
  expect(panel.props!.isCurrent()).toBe(false);expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();
});

it('keeps both private recording entry points visibly locked while an exact conversation save is unconfirmed',async()=>{
  await open();vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(()=>{}));
  await click('Send message');
  await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledOnce();});
  expect(button('Start a private recording')!.disabled).toBe(true);
  const scribe=[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='Scribe')!;
  expect(scribe.disabled).toBe(true);await act(async()=>scribe.click());
  expect(host.querySelector('[aria-label="Private Scribe recording"]')).toBeNull();
  expect(workspaceApi.openPrivateDraft).not.toHaveBeenCalled();
});

it('returns between the focused phone recorder and the same working notebook without remounting the recorder',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true}));await open();await click('Start a private recording');
  const pane=host.querySelector('[aria-label="Private Scribe recording"]'),owner=panel.props!.identity;
  expect(host.querySelector('.team-workspace')?.getAttribute('data-recording-focused')).toBe('true');expect(panel.mounts).toBe(1);
  await click('Browse workspace');
  expect(host.querySelector('.team-workspace')?.getAttribute('data-recording-focused')).toBe('false');
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toBe(workingQuestion);
  expect(panel.props!.identity).toBe(owner);expect(panel.props!.minimized).toBe(true);expect(panel.mounts).toBe(1);
  await click('Return to recording');
  expect(host.querySelector('.team-workspace')?.getAttribute('data-recording-focused')).toBe('true');
  expect(host.querySelector('[aria-label="Private Scribe recording"]')).toBe(pane);expect(panel.mounts).toBe(1);
  await click('Close recording');
  expect(host.querySelector('.team-workspace')?.getAttribute('data-recording-focused')).toBe('false');
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(workspaceApi.createPrivateDraft).toHaveBeenCalledOnce();expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();
});

it.each(['browser','native'] as const)('reopens the exact retained %s clip expanded after an earlier close completes while browsing',async mode=>{
  vi.stubGlobal('matchMedia',()=>({matches:true}));
  if(mode==='native')identity=nativeOwner();
  const row:PrivateRecordingSnapshot={recordingId:uuid(850),title:'Invented retained clip',phase:'sealed',elapsedSeconds:23,recordedChunks:3,
    recordedBytes:736132,workspaceId:null,busy:false,localOnly:true,transcription:'not_requested',failure:null,startupStage:null};
  vi.mocked(listPrivateRecordings).mockResolvedValue([row]);
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(button('Start recording')?.disabled).toBe(false);});await click('Start recording');
  panel.holdClose=true;await click('Close recording');await click('Browse workspace');
  expect(panel.props!.minimized).toBe(true);await act(async()=>panel.completeClose!());
  const retained=()=>[...host.querySelectorAll<HTMLButtonElement>('.practice-home-recordings button')].find(b=>b.querySelector('strong')?.textContent===row.title);
  await vi.waitFor(async()=>{await act(async()=>{});expect(retained()?.disabled).toBe(false);});await act(async()=>retained()!.click());
  expect(panel.props!.recordingId).toBe(row.recordingId);expect(panel.props!.identity).toBe(identity);
  expect(panel.props!.minimized).toBe(false);expect(host.querySelector('.team-workspace')?.getAttribute('data-recording-focused')).toBe('true');
  expect(host.querySelector('[aria-label="Private Scribe recording"]')?.hasAttribute('hidden')).toBe(false);
  const recorderHost=host.querySelector<HTMLElement>('.private-recording-host')!,documentScroll=vi.fn();recorderHost.scrollIntoView=documentScroll;
  await click('Browse workspace');await click('Return to recording');
  expect(host.querySelector('.private-recording-host')).toBe(recorderHost);expect(panel.props!.recordingId).toBe(row.recordingId);
  expect(documentScroll).toHaveBeenCalledTimes(mode==='native'?0:1);
  expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();
});

const nativeOwner=():AuthenticatedWorkspaceIdentity=>({mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision:'invented-private-phone-owner',isCurrent:()=>true}});
it('opens a saved native note directly in Notes without starting Chief, Scribe, or a new notebook',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true}));identity=nativeOwner();
  workspace.revision=2;workspace.entries=[{id:uuid(863),revision:2,kind:'scratchpad',content:workingNote,origin:'human',source_label:null,ticket:null,created_at:'2026-10-21T00:00:00Z'}];
  vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[{workspace_id:workspace.id,title:workspace.label,title_revision:0,revision:2,
    created_at:'2026-10-21T00:00:00Z',updated_at:'2026-10-21T00:00:00Z',link_state:'unlinked',appointment_id:null,patient_label:null,visit_at:null,note_state:'draft',duration_seconds:null,recording_state:'none'}],has_more:false});
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  await vi.waitFor(async()=>{await act(async()=>{});expect(button('Open note')?.disabled).toBe(false);});
  await click('Open note');
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('.team-content')?.getAttribute('data-mobile-panel')).toBe('Notebook');});
  expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(host.querySelector('.workspace-notebook-body')?.getAttribute('data-view')).toBe('workspace');
  expect(workspaceApi.openPrivateDraft).toHaveBeenCalledExactlyOnceWith(identity,workspace.id);
  expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();expect(panel.props).toBeNull();
});
async function privatePanel(name:string){
  const selected=host.querySelector<HTMLButtonElement>(`.team-mobile-tabs button[data-panel="${name}"]`)!;
  expect(selected.disabled).toBe(false);await act(async()=>selected.click());
}
it('opens an unlinked native phone note without visit-phase or duplicate progress chrome, retaining working words and real review/recording routes',async()=>{
  vi.stubGlobal('matchMedia',()=>({matches:true}));identity=nativeOwner();await open();await click('Open private note');
  expect(host.querySelector('.workspace-notebook')?.getAttribute('data-native-private-note')).toBe('true');
  for(const label of ['Encounter stage','Note progress','Current task'])expect(host.querySelector<HTMLElement>(`[aria-label="${label}"]`)!.hidden,label).toBe(true);
  const editor=host.querySelector<HTMLTextAreaElement>('#team-notebook')!;expect(editor.value).toBe(workingNote);
  const actions=host.querySelector('.team-material-content > .team-task-actions')!;expect(editor.compareDocumentPosition(actions)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(editor.rows).toBe(8);
  const link=host.querySelector('.private-draft-link')!;expect(link.classList.contains('private-draft-link-compact')).toBe(true);
  expect(link.querySelector('details>summary')).toBeTruthy();expect(link.querySelector('h2')).toBeNull();
  await privatePanel('Review');expect(host.querySelector('.team-note-review')?.closest('[hidden]')).toBeNull();
  await privatePanel('Sources');expect(host.querySelector('.team-content')?.getAttribute('data-mobile-panel')).toBe('Sources');
  await privatePanel('Notebook');expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(host.querySelector<HTMLTextAreaElement>('#team-question')!.value).toBe(workingQuestion);
  await click('Start a private recording');expect(panel.props!.isCurrent()).toBe(true);expect((await panel.props!.prepareNotebook!()).workspace.id).toBe(workspace.id);
  await click('Close recording');expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe(workingNote);
  expect(workspaceApi.linkAppointment).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it.each(['browser-phone','native-tablet','linked-native-phone'] as const)('preserves existing visit/progress presentation for %s',async mode=>{
  vi.stubGlobal('matchMedia',()=>({matches:mode!=='native-tablet'}));if(mode!=='browser-phone')identity=nativeOwner();
  if(mode==='linked-native-phone'){workspace.appointment_id=uuid(860);workspace.private_draft={...workspace.private_draft!,state:'linked',link_receipt_id:uuid(861),linked_at:'2026-10-21T00:00:00Z'};}
  await open();await click(mode==='native-tablet'?'Workspace view':'Open private note');expect(host.querySelector('.workspace-notebook')?.getAttribute('data-native-private-note')).toBe('false');
  for(const label of ['Encounter stage','Note progress','Current task'])expect(host.querySelector<HTMLElement>(`[aria-label="${label}"]`)!.hidden,label).toBe(false);
  expect(host.querySelector('.private-draft-link-compact')).toBeNull();const editor=host.querySelector<HTMLTextAreaElement>('#team-notebook')!;expect(editor.value).toBe(workingNote);
  expect(editor.compareDocumentPosition(host.querySelector('.team-material-content > .team-task-actions')!)&Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();expect(editor.rows).toBe(14);
});

it.each(['saved','unconfirmed'] as const)('keeps the notes-first native editor and exact save semantics when Save notes is %s',async outcome=>{
  vi.useFakeTimers();vi.stubGlobal('matchMedia',()=>({matches:true}));identity=nativeOwner();await open();await click('Open private note');
  const editor=host.querySelector<HTMLTextAreaElement>('#team-notebook')!;
  await act(async()=>{await vi.runOnlyPendingTimersAsync();});
  const healthy=host.querySelector<HTMLElement>('.workspace-draft-save-status>p:not([role])');expect(healthy).toBeTruthy();expect(healthy!.hidden).toBe(true);
  let finish!:(value:Awaited<ReturnType<typeof workspaceApi.append>>)=>void,fail!:(cause:unknown)=>void;
  vi.mocked(workspaceApi.append).mockImplementation(()=>new Promise((resolve,reject)=>{finish=resolve;fail=reject;}));
  await click('Save notes');await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.append).toHaveBeenCalledOnce();});
  const body=vi.mocked(workspaceApi.append).mock.calls[0][2];expect(body).toMatchObject({kind:'scratchpad',expected_revision:1,content:workingNote});
  expect(editor.disabled).toBe(true);expect(editor.value).toBe(workingNote);expect(button('Save notes')!.disabled).toBe(true);expect(workspaceApi.ask).not.toHaveBeenCalled();
  if(outcome==='saved'){
    const latest=structuredClone(workspace);latest.revision=2;latest.entries=[{id:uuid(862),revision:2,kind:'scratchpad',content:workingNote,origin:'human',source_label:null,ticket:null,created_at:'2026-10-21T00:00:00Z'}];
    await act(async()=>finish({entry_id:uuid(862),entry_revision:2,workspace:latest}));await vi.waitFor(async()=>{await act(async()=>{});expect(editor.disabled).toBe(false);});
    expect(host.querySelector('#team-notebook')).toBe(editor);expect(editor.value).toBe(workingNote);expect(host.querySelector('.team-material-content form .team-pill')?.textContent).toBe('Saved');
    expect(button('Save notes')!.disabled).toBe(true);
  }else{
    await act(async()=>fail(new WorkspaceApiError(503)));await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('[role="alert"]')).toBeTruthy();});
    expect(host.querySelector('#team-notebook')).toBe(editor);expect(editor.value).toBe(workingNote);expect(editor.disabled).toBe(true);expect(button('Save notes')!.disabled).toBe(true);
    expect(host.querySelector('.team-material-content form .team-pill')?.textContent).toBe('Not saved to notebook');
  }
  expect(workspaceApi.append).toHaveBeenCalledOnce();expect(workspaceApi.ask).not.toHaveBeenCalled();
});
