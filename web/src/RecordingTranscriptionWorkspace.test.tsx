import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {memoryDraftStorage} from './draft-test-fixture';
import type {PrivateRecordingPanelProps} from './PrivateRecordingPanel';
import type {RecordingVisitPanel} from './RecordingVisitPanel';
import type {SavedRecordingTranscriptionPanel,RecordingTranscriptionGesture} from './SavedRecordingTranscriptionPanel';
import {workspaceApi,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
const panels=vi.hoisted(()=>({recording:null as PrivateRecordingPanelProps|null,visit:null as Parameters<typeof RecordingVisitPanel>[0]|null,saved:null as Parameters<typeof SavedRecordingTranscriptionPanel>[0]|null}));
vi.mock('./PrivateRecordingPanel',()=>({PrivateRecordingPanel:(props:PrivateRecordingPanelProps)=>{panels.recording=props;return <section aria-label="Synthetic recording preparation"/>;}}));
vi.mock('./RecordingVisitPanel',()=>({RecordingVisitPanel:(props:Parameters<typeof RecordingVisitPanel>[0])=>{panels.visit=props;return <section aria-label="Synthetic exact visit confirmation"/>;}}));
vi.mock('./SavedRecordingTranscriptionPanel',()=>({SavedRecordingTranscriptionPanel:(props:Parameters<typeof SavedRecordingTranscriptionPanel>[0])=>{panels.saved=props;return <section aria-label="Synthetic handed-off transcription"/>;}}));
vi.mock('./capture-api',async original=>({...await original<typeof import('./capture-api')>(),CAPTURE_WORKSPACE_BUILD:true}));
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(scope:string)=>scope}));
vi.mock('./private-recording-runtime',async original=>({...await original<typeof import('./private-recording-runtime')>(),listPrivateRecordings:vi.fn().mockResolvedValue([])}));
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};});
vi.mock('./workspace-api',async original=>{const actual=await original<typeof import('./workspace-api')>();return {...actual,workspaceApi:{...actual.workspaceApi,team:vi.fn(),catalog:vi.fn(),privateDraftSummaries:vi.fn(),createPrivateDraft:vi.fn(),openPrivateDraft:vi.fn(),read:vi.fn()}};});
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`,scope='a'.repeat(64);
const team:ProviderTeam={revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},capture:{enabled:true},
 configuration:{practice_context:'Invented practice',bots:['chief','scribe'].map(role=>({role:role as 'chief'|'scribe',name:role==='chief'?'Chief':'Scribe',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}))},
 members:['chief','scribe'].map((role,index)=>({role:role as 'chief'|'scribe',agent_id:id(810+index),name:role==='chief'?'Chief':'Scribe',initials:role.slice(0,2),description:'Invented teammate',prompt:'Use saved context',capabilities:[]}))};
const origin:Workspace={id:id(800),appointment_id:null,label:'Invented original private note',revision:1,entries:[],work_candidates:[],private_draft:{title:'Invented original private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
const target:Workspace={id:id(801),appointment_id:id(802),label:'Invented selected visit',revision:7,entries:[],work_candidates:[]};
let root:Root,host:HTMLDivElement,identity:AuthenticatedWorkspaceIdentity,hold:boolean,release:(()=>void)|null;
const memory=()=>memoryDraftStorage();let storage:ReturnType<typeof memoryDraftStorage>;
const button=(name:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&(b.textContent?.trim()===name||b.getAttribute('aria-label')===name));
async function waitFor(assert:()=>unknown){const deadline=performance.now()+2000;let failure:unknown;while(performance.now()<deadline){await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});try{assert();return;}catch(error){failure=error;}}throw failure;}
async function click(name:string){expect(button(name),name).toBeTruthy();expect(button(name)!.disabled,name).toBe(false);await act(async()=>button(name)!.click());}
beforeEach(()=>{vi.clearAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('crypto',webcrypto);HTMLElement.prototype.scrollIntoView=vi.fn();panels.recording=null;panels.visit=null;panels.saved=null;hold=false;release=null;
 identity={mode:'clerk_jwt',getToken:vi.fn()};const backing=memory();storage=async options=>{const store=await backing(options);return {...store,read:async address=>{const result=await store.read(address);if(hold&&address===`workspace:${target.id}`)await new Promise<void>(resolve=>{release=resolve;});return result;}};};
 vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));vi.mocked(workspaceApi.catalog).mockResolvedValue([]);vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
 vi.mocked(workspaceApi.createPrivateDraft).mockImplementation(async()=>({identity,workspace:structuredClone(origin),team:structuredClone(team)}));vi.mocked(workspaceApi.openPrivateDraft).mockImplementation(async()=>({identity,workspace:structuredClone(origin),team:structuredClone(team)}));vi.mocked(workspaceApi.read).mockImplementation(async(_identity,wid)=>structuredClone(wid===target.id?target:origin));
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{release?.();await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
async function openRecording(){await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));await waitFor(()=>expect(button('Start a private note')?.disabled).toBe(false));await click('Start a private note');await waitFor(()=>expect(button('Start a private recording')?.disabled).toBe(false));await click('Start a private recording');
 await act(async()=>panels.recording!.onTranscribe!({identity,workspace:structuredClone(origin),team:structuredClone(team)},id(803)));await waitFor(()=>expect(panels.visit).toBeTruthy());
}
function gesture():RecordingTranscriptionGesture{return {identity,recordingId:id(803),scope,intent_sha256:'b'.repeat(64),claim:vi.fn(()=>true)};}
it('adopts the exact target revision and current gesture only after actual target recovery completes',async()=>{
 await openRecording();const intent=gesture();await act(async()=>panels.visit!.onSelected(structuredClone(target),null,intent));await waitFor(()=>expect(panels.saved).toBeTruthy());
 expect(panels.saved!.workspace).toMatchObject({id:target.id,revision:7,appointment_id:target.appointment_id});expect(panels.saved!.entry.transcriptionGesture).toBe(intent);expect(panels.saved!.entry.originWorkspace?.id).toBe(origin.id);expect(panels.saved!.entry.recordingId).toBe(id(803));expect(panels.saved!.isCurrent()).toBe(true);expect(origin.appointment_id).toBeNull();
});
it.each(['home','identity','notebook'] as const)('withholds an armed transcription after %s replaces a held target opening',async replacement=>{
 await openRecording();hold=true;const intent=gesture();let pending!:Promise<void>;await act(async()=>{pending=panels.visit!.onSelected(structuredClone(target),null,intent);});await waitFor(()=>expect(release).toBeTypeOf('function'));
 if(replacement==='identity'){identity={mode:'clerk_jwt',getToken:vi.fn()};await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={storage}/>));}
 else {await click('Home');if(replacement==='notebook'){vi.mocked(workspaceApi.createPrivateDraft).mockResolvedValue({identity,team:structuredClone(team),workspace:{...origin,id:id(804),label:'Invented newer notebook'}});await waitFor(()=>expect(button('Start a private note')?.disabled).toBe(false));await click('Start a private note');}}
 hold=false;await act(async()=>{release!();await pending;});expect(panels.saved).toBeNull();expect(intent.claim).not.toHaveBeenCalled();expect(host.querySelector('[aria-label="Synthetic handed-off transcription"]')).toBeNull();
});
