import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {clinicalTeamApi} from './clinical-team-api';
import {memoryDraftStorage} from './draft-test-fixture';
import {CLINICAL_NOTE_LABEL,type ClinicalNoteShareReceipt,type ShareSavedNoteInput} from './clinical-team-contract';
import {modelCanonical} from './model-work-request';
import {vendorSha256} from './vendor-contract';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type BotRole,type PrivateNote,type ProviderTeam,type Workspace} from './workspace-api';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');

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
async function open(factory=storage,recovering=false) {
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={factory}/>));
  await click('Visits and notes');
  await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
  await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')).toBeTruthy();
    if(!recovering)expect(host.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled).toBe(false);});
  if(recovering)return;
  const chief=[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='Chief')!;
  await act(async()=>chief.click());
  await click('Conversation view');
  await act(async()=>{host.querySelector<HTMLDetailsElement>('.clinical-team-disclosure')!.open=true;});
}
async function selectNote() {
  await click('Preview saved note for team');
  await act(async()=>host.querySelector<HTMLInputElement>('.clinical-team-drafts input[type=checkbox]')!.click());
}
async function retained() {const probe=await storage({scope});try{return (await probe.read(`workspace:${workspace.id}`)).value?.body as {note:string;pending:null|{type:string;body:ShareSavedNoteInput}}|undefined;}finally{probe.close();}}
beforeEach(async()=>{
  vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);
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
