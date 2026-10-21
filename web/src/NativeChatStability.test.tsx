import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {EncounterWorkspace} from './EncounterWorkspace';
import {DraftStoreError,type DraftStore,type DraftRecord} from './draft-store';
import type {NotebookDraft} from './draft-journal';
import {modelReceipt,modelUuid,modelTimestamp} from './model-work-test-fixture';
import {modelWorkApi} from './model-work-api';
import {teamFixture} from './team-setup-test-fixture';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {listPrivateRecordings} from './private-recording-runtime';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import type {PrivateRecordingPanelProps} from './PrivateRecordingPanel';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
vi.mock('./team-setup-api',async()=>{const {WorkspaceApiError}=await import('./workspace-api');return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};});
vi.mock('./draft-store',async original=>({...await original<typeof import('./draft-store')>(),privateDraftScope:async(scope:string)=>scope}));
vi.mock('./private-recording-runtime',async original=>({...await original<typeof import('./private-recording-runtime')>(),listPrivateRecordings:vi.fn().mockResolvedValue([])}));
vi.mock('./capture-api',async original=>({...await original<typeof import('./capture-api')>(),CAPTURE_WORKSPACE_BUILD:true}));
vi.mock('./model-work-api',async original=>({...await original<typeof import('./model-work-api')>(),modelWorkApi:{resolve:vi.fn()}}));
vi.mock('./PrivateRecordingPanel',()=>({PrivateRecordingPanel:({identity,onTranscribe}:PrivateRecordingPanelProps)=><button onClick={()=>void onTranscribe?.({identity,workspace,team},modelUuid(989))}>Finish synthetic saved recording</button>}));
vi.mock('./RecordingVisitPanel',()=>({RecordingVisitPanel:({origin,onSelected}:Parameters<typeof import('./RecordingVisitPanel').RecordingVisitPanel>[0])=><button onClick={()=>void onSelected(origin,null)}>Open synthetic saved transcript</button>}));
vi.mock('./SavedRecordingTranscriptionPanel',()=>({SavedRecordingTranscriptionPanel:()=> <section aria-label="Saved recording transcription"><h2>Review your transcript</h2><p role="alert">Your transcript cannot currently be retrieved. Choose Refresh to check again.</p><button>Refresh</button></section>}));
vi.mock('./workspace-api',async original=>{const actual=await original<typeof import('./workspace-api')>();return {...actual,workspaceApi:{...actual.workspaceApi,open:vi.fn(),catalog:vi.fn(),team:vi.fn(),read:vi.fn(),privateDraftSummaries:vi.fn(),ask:vi.fn()}};});
const team=teamFixture();team.capture={enabled:false};
const workspace:Workspace={id:modelUuid(71),appointment_id:modelUuid(72),label:'Invented native chat',revision:1,entries:[],work_candidates:[],model_contract_version:1,model_observed_at:modelTimestamp};
let root:Root,host:HTMLDivElement,records:Map<string,DraftRecord>,access:AuthenticatedWorkspaceIdentity;
let intercept:((value:NotebookDraft|null)=>Promise<void>)|null;
const storage=async({scope}:{scope:string}):Promise<DraftStore>=>({close(){},async read(address){return structuredClone(records.get(scope+address)??{revision:null,value:null});},async write(address,expected,value){
  await intercept?.(value?.body as NotebookDraft|null);const before=records.get(scope+address)??{revision:null,value:null};if(before.revision!==expected)throw new DraftStoreError('conflict');
  const saved={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(scope+address,saved);return saved;
}});
const draft=()=>records.get(team.recovery_scope!+`workspace:${workspace.id}`)?.value?.body as NotebookDraft|null|undefined;
async function ready(check:()=>void){await vi.waitFor(async()=>{await act(async()=>{});check();});}
async function click(label:string){let button:HTMLButtonElement|undefined;await ready(()=>{button=[...host.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===label||b.textContent?.trim()===label);expect(button,label).toBeTruthy();expect(button!.disabled,label).toBe(false);});await act(async()=>button!.click());}
async function type(value:string){await act(async()=>{const field=host.querySelector<HTMLTextAreaElement>('#team-question')!;expect(field.disabled).toBe(false);Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
const question=()=>host.querySelector<HTMLTextAreaElement>('#team-question')!;
const send=()=>host.querySelector<HTMLButtonElement>('[aria-label="Send message"]')!;
async function positionConversation(top:number){
  const scroller=host.querySelector<HTMLDivElement>('.mobile-chat-scroll')!;
  Object.defineProperties(scroller,{
    scrollHeight:{configurable:true,get:()=>(scroller.querySelector('.team-human-message')?1400:1000)+(scroller.querySelector('[aria-label="Unconfirmed model request"]')?600:0)},
    clientHeight:{configurable:true,get:()=>200},
  });
  await act(async()=>{scroller.scrollTop=top;scroller.dispatchEvent(new Event('scroll',{bubbles:true}));});
  return scroller;
}
beforeEach(async()=>{
  vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  vi.stubGlobal('matchMedia',()=>({matches:true,addEventListener(){},removeEventListener(){}}));
  vi.spyOn(window,'matchMedia').mockImplementation(()=>({matches:true,addEventListener(){},removeEventListener(){}} as unknown as MediaQueryList));
  records=new Map();intercept=null;access={mode:'clerk_jwt',getToken:async()=> 'invented-token',nativeSession:{revision:modelUuid(955),isCurrent:()=>true}};
  vi.mocked(listPrivateRecordings).mockResolvedValue([]);
  vi.mocked(workspaceApi.team).mockResolvedValue(team);vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:workspace.appointment_id!,workspace_id:workspace.id,label:workspace.label}]);
  vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace,team});vi.mocked(workspaceApi.read).mockResolvedValue({...workspace,revision:2});
  host=document.createElement('div');document.body.append(host);root=createRoot(host);await act(async()=>root.render(<EncounterWorkspace authenticated={access} draftStorage={storage}/>));
  await click('Visits and notes');await ready(()=>expect(host.querySelector('.team-encounter-option')).toBeTruthy());await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
  await ready(()=>expect(question()).toBeTruthy());const chief=[...host.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.querySelector('strong')?.textContent==='chief')!;await act(async()=>chief.click());
  await ready(()=>expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"]')).toBeTruthy());
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});

it('reveals the submitted native message before its saved reply arrives without scrolling for next-draft typing',async()=>{
  vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(()=>{}));
  const scroller=await positionConversation(800);
  await type('Invented outgoing message');expect(scroller.scrollTop).toBe(800);
  question().focus();await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());
  expect(scroller.querySelector('.team-human-message')?.textContent).toContain('Invented outgoing message');
  expect(scroller.scrollTop).toBe(1200);expect(document.activeElement).toBe(question());
  const sent=structuredClone(vi.mocked(workspaceApi.ask).mock.calls[0][2]);
  await act(async()=>{scroller.scrollTop=1180;scroller.dispatchEvent(new Event('scroll',{bubbles:true}));});
  await type('Next unsent question');expect(scroller.scrollTop).toBe(1180);
  expect(draft()?.pending).toMatchObject({type:'ask',body:sent});expect(workspaceApi.ask).toHaveBeenCalledOnce();
});
it('preserves an older native message position when an outgoing question is submitted away from the bottom',async()=>{
  vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(()=>{}));
  const scroller=await positionConversation(200);
  await type('Invented outgoing message');await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());
  expect(scroller.querySelector('.team-human-message')?.textContent).toContain('Invented outgoing message');
  expect(scroller.scrollTop).toBe(200);expect(send().disabled).toBe(true);
});

it('keeps new typing and keyboard focus while the old exact request saves, with Send locked',async()=>{
  let release!:(receipt:Awaited<ReturnType<typeof modelReceipt>>)=>void;
  vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  await type('First invented message');question().focus();await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());
  const sent=structuredClone(vi.mocked(workspaceApi.ask).mock.calls[0][2]);expect(send().disabled).toBe(true);expect(question().disabled).toBe(false);
  await type('Next invented question\nStill drafting');expect(document.activeElement).toBe(question());
  await act(async()=>notifyNativeWorkspaceForeground(access,false));await ready(()=>expect(draft()?.thought).toBe('Next invented question\nStill drafting'));
  expect(draft()?.pending).toMatchObject({type:'ask',body:sent});expect(sent.content).toBe('First invented message');expect(workspaceApi.ask).toHaveBeenCalledOnce();
  await act(async()=>release(await modelReceipt(sent,workspace.id)));await ready(()=>expect(draft()?.pending).toBeNull());
  expect(question().value).toBe('Next invented question\nStill drafting');expect(draft()?.thought).toBe(question().value);expect(document.activeElement).toBe(question());
  notifyNativeWorkspaceForeground(access,true);
});
it('retains the new working question alongside the immutable old request after a lost reply',async()=>{
  let reject!:(cause:unknown)=>void;vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise((_resolve,fail)=>{reject=fail;}));
  const scroller=await positionConversation(200);
  await type('Original exact request');question().focus();const input=question();await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());const sent=structuredClone(vi.mocked(workspaceApi.ask).mock.calls[0][2]);
  await type('Unsent next question');await act(async()=>reject(new WorkspaceApiError(503)));await ready(()=>expect(host.textContent).toContain('unconfirmed'));
  expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"]')).toBeTruthy();
  expect(host.querySelector('.mobile-chat-scroll')).toBe(scroller);expect(scroller.scrollTop).toBe(200);
  const recovery=host.querySelector('[aria-label="Unconfirmed model request"]');
  expect(host.querySelectorAll('[aria-label="Unconfirmed model request"]')).toHaveLength(1);expect(scroller.contains(recovery)).toBe(true);
  expect(question()).toBe(input);expect(document.activeElement).toBe(input);
  await act(async()=>notifyNativeWorkspaceForeground(access,false));await ready(()=>expect(draft()?.thought).toBe('Unsent next question'));
  expect(draft()?.pending).toMatchObject({type:'ask',body:sent});expect(send().disabled).toBe(true);expect(workspaceApi.ask).toHaveBeenCalledOnce();notifyNativeWorkspaceForeground(access,true);
});
it('reveals native recovery at the bottom and permits only explicit same-key send after a verified missing result',async()=>{
  let reject!:(cause:unknown)=>void;
  vi.mocked(workspaceApi.ask).mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail;})).mockImplementation((_identity,id,body)=>modelReceipt(body,id));
  vi.mocked(modelWorkApi.resolve).mockImplementation(async(_identity,id,operation)=>{
    if(operation.type!=='ask')throw new Error('Invented conversation required');
    return {...await modelReceipt(operation.body,id),outcome:'not_found',saved_entry:null,admission:null,reason:null};
  });
  const scroller=await positionConversation(800);await type('Original exact request');question().focus();const input=question();
  await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());const sent=structuredClone(vi.mocked(workspaceApi.ask).mock.calls[0][2]);
  expect(scroller.scrollTop).toBe(1200);await type('Next unsent question');await act(async()=>reject(new WorkspaceApiError(503)));
  await ready(()=>expect(scroller.querySelector('[aria-label="Unconfirmed model request"]')).toBeTruthy());
  expect(scroller.scrollTop).toBe(1800);expect(question()).toBe(input);expect(document.activeElement).toBe(input);
  expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"]')).toBeTruthy();expect(send().disabled).toBe(true);
  expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Retry message')).toBe(false);
  await click('Check message');await ready(()=>expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Retry message'&&!button.disabled)).toBe(true));
  expect(modelWorkApi.resolve).toHaveBeenCalledExactlyOnceWith(access,workspace.id,expect.objectContaining({type:'ask',body:sent}));
  expect(workspaceApi.ask).toHaveBeenCalledOnce();expect(draft()?.pending).toMatchObject({type:'ask',body:sent});
  expect(host.querySelector('.mobile-chat-scroll')).toBe(scroller);expect(scroller.scrollTop).toBe(1800);
  await type('Next unsent question after checking');expect(scroller.scrollTop).toBe(1800);
  await click('Retry message');await ready(()=>expect(draft()?.pending).toBeNull());
  expect(workspaceApi.ask).toHaveBeenNthCalledWith(2,access,workspace.id,sent);expect(workspaceApi.ask).toHaveBeenCalledTimes(2);
  expect(question()).toBe(input);expect(question().value).toBe('Next unsent question after checking');expect(document.activeElement).toBe(input);
  expect(host.querySelector('.workspace-notebook-body[data-native-chat="true"]')).toBeTruthy();
});
it('preserves typing that arrives while the settled encrypted write is in flight',async()=>{
  let release!:(receipt:Awaited<ReturnType<typeof modelReceipt>>)=>void,finishWrite!:()=>void,held=false;
  vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  await type('Original exact request');await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());const sent=vi.mocked(workspaceApi.ask).mock.calls[0][2];
  intercept=async value=>{if(!held&&(!value||value.pending===null)){held=true;await new Promise<void>(resolve=>{finishWrite=resolve;});}};
  await type('First next draft');await act(async()=>release(await modelReceipt(sent,workspace.id)));await ready(()=>expect(held).toBe(true));
  await type('Newest draft during receipt write');await act(async()=>finishWrite());await ready(()=>expect(question().value).toBe('Newest draft during receipt write'));
  await ready(()=>{expect(draft()?.pending).toBeNull();expect(draft()?.thought).toBe('Newest draft during receipt write');});expect(workspaceApi.ask).toHaveBeenCalledOnce();
});
it('locks native editing when its draft store fails without modifying the original request',async()=>{
  vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(()=>{}));await type('Original exact request');await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());
  const sent=structuredClone(vi.mocked(workspaceApi.ask).mock.calls[0][2]);intercept=async value=>{if(value?.thought==='New local draft')throw new DraftStoreError('conflict');};
  await type('New local draft');await act(async()=>notifyNativeWorkspaceForeground(access,false));await ready(()=>expect(question().disabled).toBe(true));
  expect(send().disabled).toBe(true);expect(draft()?.pending).toMatchObject({type:'ask',body:sent});expect(workspaceApi.ask).toHaveBeenCalledOnce();notifyNativeWorkspaceForeground(access,true);
});
it('withholds editing and Send when native session authority expires',async()=>{
  await type('Unsent private question');
  if(access.mode!=='clerk_jwt')throw new Error('Invented native test identity required');
  access.nativeSession!.isCurrent=()=>false;
  await act(async()=>root.render(<EncounterWorkspace authenticated={access} draftStorage={storage}/>));
  expect(question().disabled).toBe(true);expect(send().disabled).toBe(true);expect(workspaceApi.ask).not.toHaveBeenCalled();
});
it('does not let an old settling receipt block or overwrite the next owner’s local draft',async()=>{
  let release!:(receipt:Awaited<ReturnType<typeof modelReceipt>>)=>void,finishWrite!:()=>void,held=false;
  vi.mocked(workspaceApi.ask).mockImplementation(()=>new Promise(resolve=>{release=resolve;}));
  await type('Old owner exact request');await click('Send message');await ready(()=>expect(workspaceApi.ask).toHaveBeenCalledOnce());const sent=vi.mocked(workspaceApi.ask).mock.calls[0][2];
  intercept=async value=>{if(!held&&(!value||value.pending===null)){held=true;await new Promise<void>(resolve=>{finishWrite=resolve;});}};
  await act(async()=>release(await modelReceipt(sent,workspace.id)));await ready(()=>expect(held).toBe(true));
  const nextTeam={...team,recovery_scope:'b'.repeat(64)},next:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=> 'invented-next-owner',nativeSession:{revision:modelUuid(956),isCurrent:()=>true}};
  vi.mocked(workspaceApi.team).mockResolvedValue(nextTeam);vi.mocked(workspaceApi.open).mockResolvedValue({identity:next,workspace,team:nextTeam});
  await act(async()=>root.render(<EncounterWorkspace authenticated={next} draftStorage={storage}/>));
  await click('Visits and notes');await ready(()=>expect(host.querySelector('.team-encounter-option')).toBeTruthy());await act(async()=>host.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());await ready(()=>expect(question()?.disabled).toBe(false));
  await type('New owner working draft');await ready(()=>expect((records.get(nextTeam.recovery_scope+`workspace:${workspace.id}`)?.value?.body as NotebookDraft)?.thought).toBe('New owner working draft'));
  await act(async()=>finishWrite());expect(question().value).toBe('New owner working draft');expect(host.textContent).not.toContain('Conversation saved.');
});

it('releases native conversation containment for a saved transcription review and its recovery controls',async()=>{
  await click('Home');await click('Start recording');await click('Finish synthetic saved recording');
  await ready(()=>expect(host.querySelector('.workspace-notebook-body[data-native-chat="false"]')).toBeTruthy());
  await click('Open synthetic saved transcript');
  await ready(()=>expect(host.querySelector('[aria-label="Saved recording transcription"]')).toBeTruthy());
  const review=host.querySelector('[aria-label="Saved recording transcription"]')!;
  expect(review.closest('[data-native-chat="true"]')).toBeNull();
  expect(review.closest('.workspace-notebook-body')).toBeNull();
  expect(host.querySelector('.team-workspace[data-native-chat="true"]')).toBeNull();
  expect(review.querySelector('[role="alert"]')?.textContent).toContain('cannot currently be retrieved');
  expect(review.querySelector('button')?.textContent).toBe('Refresh');
});
