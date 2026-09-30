import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {ExistingScribeSourcePanel} from './ExistingScribeSourcePanel';
import {readExistingScribeSource,saveScribeSourcePacket,type ExistingScribeSource,type ScribeSourcePacket} from './scribe-source-api';
import {EditorRecoveryContext,type EditorRecoveryAccess} from './editor-recovery';
import {DraftJournal} from './draft-journal';
import {memoryDraftStorage} from './draft-test-fixture';
import {BffResponseError} from '../../clients/capture/src/bff/http-client';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
vi.mock('./scribe-source-api',async()=>({...await vi.importActual('./scribe-source-api'),readExistingScribeSource:vi.fn(),saveScribeSourcePacket:vi.fn()}));
vi.mock('./workspace-api',async()=>{const actual=await vi.importActual<typeof import('./workspace-api')>('./workspace-api');return {...actual,workspaceApi:{...actual.workspaceApi,read:vi.fn()}};});
const wid='00000000-0000-4000-8000-000000000001',sid='00000000-0000-4000-8000-000000000002',tid='00000000-0000-4000-8000-000000000003',gid='00000000-0000-4000-8000-000000000004';
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const workspace:Workspace={id:wid,appointment_id:gid,label:'Invented visit',revision:1,entries:[],work_candidates:[]};
const selection={version:1 as const,session_id:sid,source_transcript_version:1,working_transcript_id:tid,working_transcript_version:2,snapshot_sha256:'a'.repeat(64)};
function recording():ExistingScribeSource{
  const segment={source_segment_id:gid,source_segment_version:1,speaker_id:gid,speaker_role:'patient' as const,source_locale:'en-US' as const,start_ms:0,end_ms:1000,content:'Invented complete transcript <script>never execute</script>'};
  return {contract_version:1,workspace_id:wid,status:'available',selection,review:{schema_version:'1.0',session_id:sid,status:'transcript_ready',translation_progress:[],
    source:{schema_version:'1.0',source_transcript_version:1,duration_ms:1000,language_mode:'en-US',transcription_adapter_id:'test',transcription_model_profile_id:'test',normalization_profile_id:'test',segments:[segment]},
    working:{schema_version:'1.0',working_transcript_id:tid,working_transcript_version:2,source_transcript_version:1,note_ready:true,blockers:[],segments:[{...segment,resolution:'english_source'}]},
    review_queue:{schema_version:'1.0',session_id:sid,source_transcript_version:1,working_transcript_id:tid,working_transcript_version:2,status:'complete',items:[]}}};
}
let host:HTMLDivElement,root:Root,access:EditorRecoveryAccess,onSaved:ReturnType<typeof vi.fn>,onBusy:ReturnType<typeof vi.fn>;
const button=(label:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent?.includes(label))!;
const click=(label:string)=>act(async()=>button(label).click());
const mount=(owner=identity,recovery:EditorRecoveryAccess|null=access,openRequest=0)=>act(async()=>root.render(<EditorRecoveryContext.Provider value={recovery}>
  <ExistingScribeSourcePanel workspace={workspace} identity={owner} locked={false} openRequest={openRequest} onSaved={onSaved} onBusyChange={onBusy}/></EditorRecoveryContext.Provider>));
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);
  access={workspaceId:wid,journal:new DraftJournal(await memoryDraftStorage()({scope:'a'.repeat(64)})),authorize:vi.fn().mockResolvedValue(workspace),denied:vi.fn()};
  onSaved=vi.fn();onBusy=vi.fn();vi.mocked(readExistingScribeSource).mockResolvedValue(recording());vi.mocked(workspaceApi.read).mockResolvedValue(workspace);
  vi.mocked(saveScribeSourcePacket).mockResolvedValue({workspace:{...workspace,revision:2}} as ScribeSourcePacket);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();host.remove();});

it('requires explicit lookup, complete preview, review and team sharing; stores metadata before saving',async()=>{
  await mount();expect(readExistingScribeSource).not.toHaveBeenCalled();await click('Use a Scribe recording');
  expect(host.textContent).toContain('Invented complete transcript');expect(host.querySelector('script')).toBeNull();
  expect(host.textContent).toContain('Source version 1');expect(host.textContent).toContain('will not update automatically');
  expect(button('Use this version with my team').disabled).toBe(true);expect(saveScribeSourcePacket).not.toHaveBeenCalled();
  vi.mocked(saveScribeSourcePacket).mockImplementationOnce(async(_w,_i,body)=>{
    const stored=await access.journal.load(`editor:${wid}:scribe-source`);
    expect(stored).toMatchObject({pending:body.idempotency_key,data:body});
    expect(JSON.stringify(stored)).not.toContain('Invented complete transcript');
    return {workspace:{...workspace,revision:2}} as ScribeSourcePacket;
  });
  await act(async()=>host.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await click('Use this version with my team');
  expect(saveScribeSourcePacket).toHaveBeenCalledOnce();expect(onSaved).toHaveBeenCalledWith({...workspace,revision:2});
  expect(await access.journal.load(`editor:${wid}:scribe-source`)).toBeNull();expect(host.textContent).toContain('Chief of Staff can use this version');
});
it('restores the same immutable request after a lost reply and rechecks before repeating it',async()=>{
  vi.mocked(saveScribeSourcePacket).mockRejectedValueOnce(new BffResponseError(503,'capture_request_unconfirmed',null));
  await mount();await click('Use a Scribe recording');await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());await click('Use this version with my team');
  const original=vi.mocked(saveScribeSourcePacket).mock.calls[0][2];
  await act(async()=>root.unmount());root=createRoot(host);await mount();
  expect(host.textContent).toContain('save is unconfirmed');expect(saveScribeSourcePacket).toHaveBeenCalledTimes(1);
  await click('Restore scribe source draft');expect(saveScribeSourcePacket).toHaveBeenCalledTimes(1);
  const laterWorkspace={...workspace,revision:4};vi.mocked(workspaceApi.read).mockResolvedValueOnce(laterWorkspace);
  await click('Check saved result');expect(workspaceApi.read).toHaveBeenCalledOnce();
  expect(vi.mocked(saveScribeSourcePacket).mock.calls[1][2]).toEqual(original);expect(onSaved).toHaveBeenCalledExactlyOnceWith(laterWorkspace);
});
it('ignores late source contents after an identity change',async()=>{
  let finish!:(value:ExistingScribeSource)=>void;
  vi.mocked(readExistingScribeSource).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await mount();await click('Use a Scribe recording');await mount({...identity,getToken:async()=>null},null);
  await act(async()=>finish(recording()));expect(host.textContent).not.toContain('Invented complete transcript');expect(saveScribeSourcePacket).not.toHaveBeenCalled();
});
it('shows continuity uncertainty and does not silently replace a changed source',async()=>{
  const value=recording();value.review!.capture_continuity={schema_version:'1.0',continuity:'interrupted_or_unconfirmed',missing_audio:'unknown',starts:[{source_start_id:sid,first_sequence_number:0},{source_start_id:tid,first_sequence_number:3}]};
  vi.mocked(readExistingScribeSource).mockResolvedValue(value);vi.mocked(saveScribeSourcePacket).mockRejectedValueOnce(new BffResponseError(409,'scribe_source_changed',null));
  await mount();await click('Use a Scribe recording');expect(host.textContent).toContain('Speech may be missing');
  await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());await click('Use this version with my team');
  expect(host.textContent).toContain('Scribe has a newer version');expect(readExistingScribeSource).toHaveBeenCalledOnce();expect(onSaved).not.toHaveBeenCalled();
  expect(await access.journal.load(`editor:${wid}:scribe-source`)).toBeNull();expect(button('Use a Scribe recording').disabled).toBe(false);
});
it('keeps unavailable recording and unavailable recovery distinct',async()=>{
  await mount(identity,null);expect(button('Use a Scribe recording').disabled).toBe(true);expect(readExistingScribeSource).not.toHaveBeenCalled();
  vi.mocked(readExistingScribeSource).mockResolvedValue({contract_version:1,workspace_id:wid,status:'not_prepared',review:null,selection:null});
  await mount();await click('Use a Scribe recording');expect(host.textContent).toContain('No Scribe recording is linked');expect(button('Use this version with my team')).toBeUndefined();
});
it('explains an already-shared transcript without inventing a second save',async()=>{
  vi.mocked(saveScribeSourcePacket).mockRejectedValueOnce(new BffResponseError(409,'scribe_source_already_saved',null));
  await mount();await click('Use a Scribe recording');await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());await click('Use this version with my team');
  expect(host.textContent).toContain('already shared with your team');expect(saveScribeSourcePacket).toHaveBeenCalledOnce();expect(onSaved).not.toHaveBeenCalled();
  expect(await access.journal.load(`editor:${wid}:scribe-source`)).toBeNull();
});

it('distinguishes the first save from checking an uncertain saved result',async()=>{
  let finish!:(receipt:ScribeSourcePacket)=>void;
  vi.mocked(saveScribeSourcePacket).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await mount();await click('Use a Scribe recording');await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());
  await click('Use this version with my team');
  expect(host.textContent).toContain('Saving reviewed version…');expect(host.textContent).not.toContain('Keep this request for checking');
  await act(async()=>finish({workspace:{...workspace,revision:2}} as ScribeSourcePacket));
  expect(onSaved).toHaveBeenCalledOnce();
});

it('consumes an explicit home-screen lookup once after recovery is ready, without sharing',async()=>{
  await mount(identity,null,1);expect(readExistingScribeSource).not.toHaveBeenCalled();
  await mount(identity,access,1);expect(readExistingScribeSource).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('Invented complete transcript');
  await mount(identity,access,1);expect(readExistingScribeSource).toHaveBeenCalledOnce();
  expect(saveScribeSourcePacket).not.toHaveBeenCalled();expect(onSaved).not.toHaveBeenCalled();
});
it('does not replace a retained uncertain save with a home-screen lookup',async()=>{
  vi.mocked(saveScribeSourcePacket).mockRejectedValueOnce(new Error('lost invented response'));
  await mount();await click('Use a Scribe recording');await act(async()=>host.querySelector<HTMLInputElement>('input')!.click());await click('Use this version with my team');
  await act(async()=>root.unmount());root=createRoot(host);
  await mount(identity,access,1);expect(host.textContent).toContain('save is unconfirmed');
  expect(readExistingScribeSource).toHaveBeenCalledOnce();expect(saveScribeSourcePacket).toHaveBeenCalledOnce();
});
