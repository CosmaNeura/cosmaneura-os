import {readSessionPrep} from "./session-prep-api";
import {sessionPrepFixture} from "./test-fixtures/session-prep";
import {sessionPrepAnalysis} from "./session-prep-analysis-contract";
vi.mock("./session-prep-api",async original=>({...await original<typeof import("./session-prep-api")>(),readSessionPrep:vi.fn()}));
vi.mock("./encounter-prep-api",async original=>({...await original<typeof import("./encounter-prep-api")>(),ENCOUNTER_PREP_BUILD:true}));
import { settingsNavigation } from "./settings-test-navigation";
import { memoryDraftStorage } from "./draft-test-fixture";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EncounterWorkspace } from "./EncounterWorkspace";
import {CHIEF_STARTERS} from './ChiefStartActions';
import {modelWorkApi} from './model-work-api';
import {modelReceipt,modelUuid,retryReceipt} from './model-work-test-fixture';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
import { workspaceApi, WorkspaceApiError, type Workspace, type ProviderTeam, type BotRole } from "./workspace-api";
import {VisitOpenDeadline} from "./visit-open-deadline";
import {listPrivateRecordings,type PrivateRecordingSnapshot} from "./private-recording-runtime";
vi.mock("./private-recording-runtime",async original=>({...await original<typeof import("./private-recording-runtime")>(),listPrivateRecordings:vi.fn().mockResolvedValue([])}));

import {workspaceProtocolGeneration} from './workspace-protocol';
import {WorkspaceConnectionRecoveryContext} from './PracticeAccessGate';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {DraftStore} from './draft-store';

vi.mock("./team-setup-api", async () => {
  const {WorkspaceApiError}=await import("./workspace-api");
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};
});

vi.mock("./draft-store", async original => ({...await original<typeof import("./draft-store")>(), privateDraftScope:async (scope:string)=>scope}));
vi.mock('./model-work-api',async original=>({...await original<typeof import('./model-work-api')>(),modelWorkApi:{resolve:vi.fn()}}));
vi.mock('./VendorWorkMount',async original=>({...await original<typeof import('./VendorWorkMount')>(),
  VendorWorkspaceMount:({onChanged,locked}:{onChanged?:()=>void;locked?:boolean})=>
    <button disabled={locked} onClick={onChanged}>Observe saved connected delivery</button>}));
let draftStorage: ReturnType<typeof memoryDraftStorage>;
vi.mock("./workspace-api", async importOriginal => {
  const actual = await importOriginal<typeof import("./workspace-api")>();
  return { ...actual, workspaceApi: { checkSyntheticConnection:vi.fn(), practiceWorkItem: vi.fn().mockRejectedValue(new Error("Unavailable fixture")), practiceWork: vi.fn(), workHandoff: vi.fn(), completeWork: vi.fn(), catalog: vi.fn(), open: vi.fn(), read: vi.fn(), append: vi.fn(), link: vi.fn(), team: vi.fn(), saveTeam: vi.fn(), ask: vi.fn(), retryHandoff: vi.fn(), saveNote: vi.fn(), reviewNote: vi.fn(), proposeFollowUp: vi.fn(), decideFollowUp: vi.fn(), completeFollowUp: vi.fn(), privateDraftSummaries:vi.fn(),createPrivateDraft:vi.fn(),linkAppointment:vi.fn(),resolveAppointmentLink:vi.fn() } };
});

const fixture: Workspace & {appointment_id:string} = {
  id: "00000000-0000-4000-8000-000000000071", appointment_id: "appointment-invented", label: "Invented person", revision: 1,
  entries: [{ id: "source-invented", revision: 1, kind: "synthetic_source", content: "Invented prep",
    source_label: "Fixture v1", origin: "synthetic_fixture", ticket: null, created_at: "2026-09-16T00:00:00Z" }],
  work_candidates: [{ id: "work-invented", state: "pending_approval", lane: "synthetic_followup" }],
};
const identity = { boxId: "box-invented", actorId: "actor-invented" };
const roles: BotRole[] = ["scribe", "visit_prep", "follow_up", "chief"];
const names = ["Scribe", "Visit Prep", "Follow-up", "Chief"];
const team: ProviderTeam = {
  revision: 1, recovery_scope: "a".repeat(64), template_version: "provider-team-v1", llm: { enabled: false, model: "gpt-4.1" },
  configuration: { practice_context: "DPC", bots: roles.map((role, index) => ({ role, name: names[index], enabled: true, response_style: "brief", include_notebook: true, include_evidence: true })) },
  members: roles.map((role, index) => ({ role, agent_id: "agent-" + role, name: names[index], initials: names[index].slice(0, 2), description: "Role description", prompt: "Review saved context",
    capabilities: [{ key: role + ".pending", label: "Advanced backend", state: "awaiting_connection", connector: "Core", contract: null }] })),
};

describe("private encounter workspace", () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    vi.stubGlobal('crypto',webcrypto);
    vi.clearAllMocks(); draftStorage = memoryDraftStorage();
    // One-shot responses belong to one journey, including ones it never sends.
    for(const method of Object.values(workspaceApi))if(vi.isMockFunction(method))method.mockReset();
    vi.mocked(modelWorkApi.resolve).mockReset();
    vi.mocked(workspaceApi.checkSyntheticConnection).mockResolvedValue(undefined);
    vi.mocked(workspaceApi.practiceWorkItem).mockRejectedValue(new Error("Unavailable fixture"));
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: structuredClone(fixture), team: structuredClone(team) });
    vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));
    vi.mocked(workspaceApi.read).mockResolvedValue({...structuredClone(fixture),revision:2});
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    await act(async () => root.render(<EncounterWorkspace draftStorage={draftStorage} />));
  });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.useRealTimers(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });
  async function click(text: string) {
    const visits = () => [...container.querySelectorAll<HTMLButtonElement>('[aria-label="Workspace navigation"] button')].find(button=>button.textContent==='Visits and notes')!;
    if(text==='Choose an encounter'){await act(async()=>visits().click());return;}
    if(['Start with Chief','Record a visit','Use an existing recording','🌱 Try a sample'].includes(text)&&
      ![...container.querySelectorAll('button')].some(button=>!button.closest('[hidden]')&&(button.textContent?.trim()===text||[...button.querySelectorAll('strong')].some(label=>label.textContent===text))))await act(async()=>visits().click());
    const button = [...container.querySelectorAll("button")].find(b => !b.closest("[hidden]") && (b.textContent?.replace(/\s*↗$/, "").trim() === text || b.getAttribute("aria-label") === text || [...b.querySelectorAll("strong")].some(label => label.textContent?.trim() === text)));
    expect(button, text).toBeTruthy();
    await act(async () => button!.click());
  }
  const settings = () => settingsNavigation(container);
  function enableModel(){
    const connected=structuredClone(team);connected.llm.enabled=true;
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(fixture),team:connected});
    vi.mocked(workspaceApi.team).mockResolvedValue(connected);
    return connected;
  }
  it('hides pages that cannot render until their required identity is available',async()=>{
    const labels=()=>[...container.querySelectorAll('[aria-label="Workspace navigation"] button')].map(button=>button.textContent);
    expect(labels()).toEqual(['Visits and notes']);
    await click('Choose an encounter');
    expect(labels()).toEqual(['Visits and notes','Current notebook','Practice work','Settings']);
    expect(labels()).not.toContain('Home');
  });
  it('marks Settings active and returns to the previous notebook with Done',async()=>{
    await click('Choose an encounter');await click('Settings');
    expect(container.querySelector('[aria-label="Workspace navigation"] [aria-current="page"]')?.textContent).toBe('Settings');
    await act(async()=>container.querySelector<HTMLButtonElement>('.settings-done')!.click());
    expect(container.querySelector('[data-settings-open="false"]')).not.toBeNull();
    expect(container.querySelector('[aria-label="Workspace navigation"] [aria-current="page"]')?.textContent).toBe('Current notebook');
  });
  it('resets phone page and sidebar scrolling on accepted Settings navigation',async()=>{
    vi.stubGlobal('matchMedia',vi.fn(()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()})));
    const scroll=vi.spyOn(window,'scrollTo').mockImplementation(()=>{});
    await click('Choose an encounter');
    container.querySelector<HTMLElement>('.team-sidebar')!.scrollTop=90;scroll.mockClear();
    await click('Settings');
    expect(scroll).toHaveBeenCalledWith({top:0,left:0,behavior:'instant'});
    expect(container.querySelector<HTMLElement>('.team-sidebar')!.scrollTop).toBe(0);
    scroll.mockRestore();
  });
  it('requires the developer flag before showing execution proof',async()=>{
    const exit=vi.fn();vi.stubEnv('VITE_SHOW_EXECUTION_PROOF','false');
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} onExit={exit}/>));
    expect(container.textContent).not.toContain('Open execution proof');
    vi.stubEnv('VITE_SHOW_EXECUTION_PROOF','true');
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} onExit={exit}/>));
    await click('Open execution proof');expect(exit).toHaveBeenCalledOnce();
  });
  it('keeps account controls reachable in the phone header',async()=>{
    vi.stubGlobal('matchMedia',vi.fn(()=>({matches:true,addEventListener:vi.fn(),removeEventListener:vi.fn()})));
    const account=vi.fn(),access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access} accountControls={<button onClick={account}>Account menu</button>}/>));
    expect(container.querySelector('.team-phone-account-controls button')).not.toBeNull();
    await click('Account menu');expect(account).toHaveBeenCalledOnce();
  });
  it('rechecks a failed synthetic bootstrap without repeating its writes and can connect afterward',async()=>{
    vi.mocked(workspaceApi.open).mockRejectedValueOnce(new WorkspaceApiError(0,'workspace_unreachable'));
    await click('Choose an encounter');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('can’t reach your workspace service');
    await click('Try again');
    expect(workspaceApi.open).toHaveBeenCalledOnce();expect(workspaceApi.checkSyntheticConnection).toHaveBeenCalledOnce();
    expect(container.textContent).toContain('Your workspace service is available.');
    await click('Choose an encounter');expect(container.querySelector('[data-page="notebook"]')).not.toBeNull();
  });
  it('retries a failed visit read and clears page errors when navigating to Settings',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    vi.mocked(workspaceApi.catalog).mockClear().mockRejectedValueOnce(new WorkspaceApiError(0,'workspace_unreachable')).mockResolvedValueOnce([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    await click('Visits and notes');await click('Try again');
    expect(workspaceApi.catalog).toHaveBeenCalledTimes(2);expect(workspaceApi.open).not.toHaveBeenCalled();
    vi.mocked(workspaceApi.catalog).mockRejectedValueOnce(new WorkspaceApiError(0,'workspace_unreachable'));
    await click('Visits and notes');await click('Settings');
    expect(container.querySelector('.workspace-error-banner')).toBeNull();
  });
  it('keeps an unconfirmed save recoverable after dismissing its banner and never offers a general write retry',async()=>{
    await click('Choose an encounter');await input('Jotted notes','Retained invented notes');
    vi.mocked(workspaceApi.append).mockRejectedValueOnce(new WorkspaceApiError(0,'workspace_unreachable'));
    await click('Save notebook revision');
    const banner=container.querySelector('.workspace-error-banner')!;
    expect(banner.textContent).not.toContain('Try again');
    await click('Dismiss');expect(container.querySelector('.workspace-error-banner')).toBeNull();
    expect(container.textContent).toContain('Retry same save');
    expect(workspaceApi.append).toHaveBeenCalledOnce();
  });
  it.each([false,true])('keeps account recovery scoped to the owner after notebook navigation (scope changed: %s)',async scopeChanged=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    let release!:(value:ProviderTeam)=>void,held=false;
    vi.mocked(workspaceApi.team).mockImplementation(async(_identity,signal)=>{
      if(!signal&&!held){held=true;return new Promise(resolve=>{release=resolve;});}
      return structuredClone(team);
    });
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:structuredClone(team)});
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await vi.waitFor(async()=>{await act(async()=>{});expect(held).toBe(true);});
    await click('Visits and notes');
    await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    expect(container.querySelector('#team-notebook')).not.toBeNull();
    await act(async()=>release({...structuredClone(team),recovery_scope:(scopeChanged?'b':'a').repeat(64)}));
    if(scopeChanged){
      expect(container.querySelector('#team-notebook')).toBeNull();
      expect(container.textContent).toContain('Workspace access is unavailable');
    }else{
      expect(container.querySelector('#team-notebook')).not.toBeNull();
      expect(container.textContent).not.toContain('Workspace access is unavailable');
    }
  });
  it('keeps saved recordings available on Home after visit catalog navigation and withholds stale list completions',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    const recording:PrivateRecordingSnapshot={recordingId:modelUuid(901),title:'Invented saved recording',phase:'sealed',elapsedSeconds:19,recordedChunks:2,recordedBytes:608088,workspaceId:null,busy:false,localOnly:true,transcription:'not_requested',failure:null,startupStage:null};
    let stale!:(rows:PrivateRecordingSnapshot[])=>void;
    vi.mocked(listPrivateRecordings).mockResolvedValueOnce([recording]).mockResolvedValueOnce([recording]).mockImplementationOnce(()=>new Promise(resolve=>{stale=resolve;})).mockResolvedValue([recording]);
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([]);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    const saved=()=>container.querySelector('[aria-label="Saved private recordings"]');
    await vi.waitFor(async()=>{await act(async()=>{});expect(saved()?.textContent).toContain('Invented saved recording');});
    await click('Visits and notes');
    await vi.waitFor(()=>expect(listPrivateRecordings).toHaveBeenCalledTimes(2));
    await click('Home');
    await vi.waitFor(async()=>{await act(async()=>{});expect(saved()?.textContent).toContain('Invented saved recording');});
    await click('Visits and notes');
    await vi.waitFor(()=>expect(listPrivateRecordings).toHaveBeenCalledTimes(3));
    await click('Home');
    await click('Visits and notes');
    await vi.waitFor(()=>expect(listPrivateRecordings).toHaveBeenCalledTimes(4));
    await act(async()=>stale([{...recording,title:'Obsolete recording list'}]));
    await click('Home');
    expect(saved()?.textContent).toContain('Invented saved recording');
    expect(saved()?.textContent).not.toContain('Obsolete recording list');
  });
  it('lets Home navigation and note editing continue during a retained visit-link conflict',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()},privateWorkspace:Workspace={id:modelUuid(701),appointment_id:null,label:'Private synthetic recording',revision:1,entries:[],work_candidates:[],private_draft:{title:'Private note',state:'unlinked',link_receipt_id:null,linked_at:null}};
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.mocked(workspaceApi.createPrivateDraft).mockResolvedValue({identity:access,workspace:privateWorkspace,team});
    vi.mocked(workspaceApi.read).mockResolvedValue(privateWorkspace);
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:modelUuid(702),workspace_id:null,label:'Synthetic available visit'}]);
    vi.mocked(workspaceApi.linkAppointment).mockRejectedValue(new WorkspaceApiError(409,'workspace_already_exists'));
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await vi.waitFor(async()=>{await act(async()=>{});expect([...container.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='Start a private note')?.disabled).toBe(false);});
    await click('Start a private note');
    await vi.waitFor(async()=>{await act(async()=>{});expect([...container.querySelectorAll<HTMLButtonElement>('button')].find(b=>b.textContent==='Load available visits')?.disabled).toBe(false);});
    await click('Load available visits');
    const select=container.querySelector<HTMLSelectElement>('.private-draft-link select')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')!.set!.call(select,modelUuid(702));select.dispatchEvent(new Event('change',{bubbles:true}));container.querySelector<HTMLInputElement>('.private-draft-link input[type=checkbox]')!.click();});
    await click('Link this visit');
    await vi.waitFor(async()=>{await act(async()=>{});expect(container.textContent).toContain('This visit already has a notebook.');});
    const home=()=>[...container.querySelectorAll<HTMLButtonElement>('[aria-label="Workspace navigation"] button')].find(b=>b.textContent==='Home')!;
    expect(home().disabled).toBe(false);
    expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')!.disabled).toBe(false);
    await click('Home');expect(container.querySelector('[aria-label="Practice Home"]')?.closest('[hidden]')).toBeNull();
    await click('Current notebook');expect(container.textContent).toContain('The earlier visit link is unconfirmed. Its exact request is retained.');
    expect(workspaceApi.linkAppointment).toHaveBeenCalledOnce();expect(workspaceApi.resolveAppointmentLink).not.toHaveBeenCalled();
  });
  it('uses the admitted startup team once without another initial team read',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    const startup={identity:access,protocolGeneration:workspaceProtocolGeneration(access),expiresAt:performance.now()+15000,value:structuredClone(team)};
    const practiceAccess={role:'owner' as const,onAccessLost:vi.fn(),startupTeam:startup};
    vi.mocked(workspaceApi.team).mockClear();
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access} practiceAccess={practiceAccess}/>));
    expect(container.querySelector('[aria-label="Practice Home"]')).toBeTruthy();
    // Home still performs its fresh private-note authorization. The initial
    // workspace bootstrap is the read with its owned cancellation signal.
    expect(vi.mocked(workspaceApi.team).mock.calls.filter(call=>call[1] instanceof AbortSignal)).toHaveLength(0);
    await act(async()=>root.unmount());root=createRoot(container);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access} practiceAccess={practiceAccess}/>));
    expect(vi.mocked(workspaceApi.team).mock.calls.filter(call=>call[1] instanceof AbortSignal)).toHaveLength(1);
  });
  async function chooseBot(name: string) {
    const button = [...container.querySelectorAll<HTMLButtonElement>(".team-roster button")].find(b => b.textContent?.startsWith(name));
    expect(button).toBeTruthy(); await act(async () => button!.click());
  }
  async function input(label: string, value: string) {
    const labelElement = [...container.querySelectorAll("label")].find(e => e.textContent?.startsWith(label))!;
    const element = (labelElement.htmlFor ? document.getElementById(labelElement.htmlFor) : labelElement.querySelector("textarea, input")) as HTMLTextAreaElement | HTMLInputElement;
    const prototype = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    await act(async () => {
      Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  async function openAuthenticated(access:AuthenticatedWorkspaceIdentity, storage=draftStorage, configured=team) {
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:structuredClone(configured)});
    await act(async()=>root.render(<EncounterWorkspace draftStorage={storage} authenticated={access}/>));
    await click('Visits and notes');
    await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    await vi.waitFor(async()=>{await act(async()=>{});expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled).toBe(false);});
  }
  it('clears a read-only connection pause only after an explicit same-owner reconnect without starting a save',async()=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};
    const retry=vi.fn(),protocolGeneration=workspaceProtocolGeneration(access);
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([]);
    async function draw(sequence:number,phase:'ready'|'blocked',owner=access,checkedGeneration=protocolGeneration){await act(async()=>root.render(
      <WorkspaceConnectionRecoveryContext.Provider value={{identity:owner,sequence,generation:checkedGeneration,phase,busy:false,retry}}>
        <EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>
      </WorkspaceConnectionRecoveryContext.Provider>));}
    await draw(0,'ready');await vi.waitFor(()=>expect(workspaceApi.privateDraftSummaries).toHaveBeenCalled());
    vi.mocked(workspaceApi.catalog).mockRejectedValueOnce(new WorkspaceApiError(503,'workspace_protocol_required'));
    await draw(0,'blocked');await click('Visits and notes');
    expect(container.querySelector('.team-banner.error')?.textContent).toContain('workspace connection is paused');
    expect(container.textContent).not.toContain('Retry the same save');
    await draw(0,'ready');expect(container.querySelector('.team-banner.error')).not.toBeNull();
    await draw(1,'ready',{mode:'clerk_jwt',getToken:vi.fn()});expect(container.querySelector('.team-banner.error')).not.toBeNull();
    await draw(1,'ready',access,protocolGeneration+1);expect(container.querySelector('.team-banner.error')).not.toBeNull();
    await draw(1,'ready');expect(container.querySelector('.team-banner.error')).toBeNull();
    expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.saveNote).not.toHaveBeenCalled();expect(workspaceApi.createPrivateDraft).not.toHaveBeenCalled();
  });
  it.each(['protocol pause','unconfirmed write','conflict'] as const)('preserves %s and working text through explicit reconnect without replaying a write',async kind=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()},retry=vi.fn(),protocolGeneration=workspaceProtocolGeneration(access);
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version:2,drafts:[],has_more:false});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:structuredClone(team)});
    async function draw(sequence:number,phase:'ready'|'blocked'){await act(async()=>root.render(
      <WorkspaceConnectionRecoveryContext.Provider value={{identity:access,sequence,generation:protocolGeneration,phase,busy:false,retry}}>
        <EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>
      </WorkspaceConnectionRecoveryContext.Provider>));}
    await draw(0,'ready');await click('Visits and notes');
    await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    await vi.waitFor(()=>expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled).toBe(false));
    await input('Jotted notes','Invented working text retained through reconnect.');
    const failure=new WorkspaceApiError(kind==='conflict'?409:503,kind==='protocol pause'?'workspace_protocol_required':undefined);
    vi.mocked(workspaceApi.append).mockRejectedValueOnce(failure);
    await draw(0,'blocked');await click('Save notebook revision');
    const request=vi.mocked(workspaceApi.append).mock.calls[0][2];
    await draw(1,'ready');
    expect(workspaceApi.append).toHaveBeenCalledOnce();
    expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe('Invented working text retained through reconnect.');
    if(kind==='protocol pause')expect(container.querySelector('.team-banner.error')).toBeNull();
    else expect(container.querySelector('.team-banner.error p')?.textContent).toBe(failure.message);
    if(kind==='conflict')expect(container.textContent).toContain('Your text has not been overwritten');
    else{
      expect(container.textContent).toContain('previous save is unconfirmed');
      vi.mocked(workspaceApi.append).mockResolvedValue({entry_id:modelUuid(909),entry_revision:2,workspace:{...structuredClone(fixture),revision:2}});
      await click('Retry same save');expect(vi.mocked(workspaceApi.append).mock.calls[1][2]).toEqual(request);
    }
  });

  it.each(['browser hidden','browser pagehide','native suspended'] as const)('flushes the latest draft before its debounce on %s and reports saved only after acknowledgment',async transition=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn(),...(transition==='native suspended'?{
      nativeSession:{revision:modelUuid(951),isCurrent:()=>true}}:{})};
    let release!:()=>void;
    const acknowledgment=new Promise<void>(resolve=>{release=resolve;});
    const writes=vi.fn<DraftStore['write']>();
    const storage:typeof draftStorage=async options=>{
      const store=await draftStorage(options);
      return {...store,write:async(address,expected,value)=>{
        if(address.startsWith('workspace:')){writes(address,expected,value);await acknowledgment;}
        return store.write(address,expected,value);
      }};
    };
    await openAuthenticated(access,storage);vi.useFakeTimers();
    let visibility:ReturnType<typeof vi.spyOn>|undefined;
    try {
      await input('Jotted notes','Invented note typed immediately before backgrounding.');
      await input('Thought or question','Invented unsent multiline question.');
      expect(writes).not.toHaveBeenCalled();
      await act(async()=>{
        if(transition==='native suspended')notifyNativeWorkspaceForeground(access,false);
        else if(transition==='browser pagehide')window.dispatchEvent(new Event('pagehide'));
        else {visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');document.dispatchEvent(new Event('visibilitychange'));}
      });
      expect(writes).toHaveBeenCalledOnce();
      expect(writes.mock.calls[0][2]?.body).toMatchObject({note:'Invented note typed immediately before backgrounding.',thought:'Invented unsent multiline question.',pending:null});
      expect(container.textContent).toContain('Saving notebook and team drafts on this device');
      expect(container.textContent).not.toContain('Working copies saved on this device');
      await act(async()=>release());
      expect(container.textContent).toContain('Working copies saved on this device');
      const probe=await draftStorage({scope:team.recovery_scope!});
      expect((await probe.read(`workspace:${fixture.id}`)).value?.body).toMatchObject({note:'Invented note typed immediately before backgrounding.',thought:'Invented unsent multiline question.',pending:null});
      probe.close();
      expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
      await act(async()=>vi.advanceTimersByTimeAsync(180));expect(writes).toHaveBeenCalledOnce();
    } finally {release();visibility?.mockRestore();notifyNativeWorkspaceForeground(access,true);}
  });

  it('withholds a saved indication when background draft storage fails and keeps the typed text',async()=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};
    const storage:typeof draftStorage=async options=>{
      const store=await draftStorage(options);
      return {...store,write:async(address,expected,value)=>{
        if(address.startsWith('workspace:'))throw new Error('Private disk detail');
        return store.write(address,expected,value);
      }};
    };
    await openAuthenticated(access,storage);vi.useFakeTimers();
    await input('Jotted notes','Keep the invented note after a failed local flush.');
    await act(async()=>window.dispatchEvent(new Event('pagehide')));
    expect(container.textContent).toContain("This device's draft storage could not be checked");
    expect(container.textContent).not.toContain('Working copies saved on this device');
    expect(container.textContent).not.toContain('Private disk detail');
    expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')?.value).toBe('Keep the invented note after a failed local flush.');
    expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
  });

  it('persists a final input update after the native suspension hint without waiting for another timer',async()=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision:modelUuid(955),isCurrent:()=>true}};
    await openAuthenticated(access);vi.useFakeTimers();
    await act(async()=>notifyNativeWorkspaceForeground(access,false));
    await input('Jotted notes','Invented final dictation text received while suspending.');
    const probe=await draftStorage({scope:team.recovery_scope!});
    expect((await probe.read(`workspace:${fixture.id}`)).value?.body).toMatchObject({note:'Invented final dictation text received while suspending.'});
    expect(container.textContent).toContain('Working copies saved on this device');
    expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
    probe.close();notifyNativeWorkspaceForeground(access,true);
  });

  it('withdraws the old saved indication immediately when a newer draft is typed',async()=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn()};
    await openAuthenticated(access);vi.useFakeTimers();
    await input('Jotted notes','First acknowledged invented draft.');
    await act(async()=>vi.advanceTimersByTimeAsync(180));
    expect(container.textContent).toContain('Working copies saved on this device');
    await input('Jotted notes','Second invented draft still waiting for its local timer.');
    const probe=await draftStorage({scope:team.recovery_scope!});
    expect((await probe.read(`workspace:${fixture.id}`)).value?.body).toMatchObject({note:'First acknowledged invented draft.'});
    expect(container.textContent).not.toContain('Working copies saved on this device');
    await act(async()=>vi.advanceTimersByTimeAsync(180));
    expect((await probe.read(`workspace:${fixture.id}`)).value?.body).toMatchObject({note:'Second invented draft still waiting for its local timer.'});
    expect(container.textContent).toContain('Working copies saved on this device');
    probe.close();
  });

  it('flushes native suspension only for the current identity and ignores revoked ownership',async()=>{
    let current=true;
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision:modelUuid(952),isCurrent:()=>current}};
    const other:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn(),nativeSession:{revision:modelUuid(953),isCurrent:()=>true}};
    const writes=vi.fn<DraftStore['write']>();
    const storage:typeof draftStorage=async options=>{
      const store=await draftStorage(options);
      return {...store,write:async(address,expected,value)=>{if(address.startsWith('workspace:'))writes(address,expected,value);return store.write(address,expected,value);}};
    };
    await openAuthenticated(access,storage);vi.useFakeTimers();
    await input('Jotted notes','Invented owner-only draft.');
    await act(async()=>notifyNativeWorkspaceForeground(other,false));expect(writes).not.toHaveBeenCalled();
    current=false;await act(async()=>notifyNativeWorkspaceForeground(access,false));expect(writes).not.toHaveBeenCalled();
    current=true;await act(async()=>notifyNativeWorkspaceForeground(access,false));expect(writes).toHaveBeenCalledOnce();
    expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();
    notifyNativeWorkspaceForeground(access,true);notifyNativeWorkspaceForeground(other,true);
  });

  it.each([false,true])('uses explicit Send for native iOS multiline questions while preserving desktop Enter (native: %s)',async native=>{
    const access:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:vi.fn(),...(native?{nativeSession:{revision:modelUuid(954),isCurrent:()=>true}}:{})};
    await openAuthenticated(access,draftStorage,enableModel());
    await input('Thought or question','First invented line');
    vi.mocked(workspaceApi.ask).mockRejectedValue(new TypeError('Invented offline response'));
    const question=container.querySelector<HTMLTextAreaElement>('#team-question')!;
    for(const options of [{shiftKey:true},{isComposing:true}]){
      const key=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true,...options});
      await act(async()=>question.dispatchEvent(key));expect(key.defaultPrevented).toBe(false);expect(workspaceApi.ask).not.toHaveBeenCalled();
    }
    const enter=new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true});
    await act(async()=>question.dispatchEvent(enter));
    if(native){
      expect(enter.defaultPrevented).toBe(false);expect(workspaceApi.ask).not.toHaveBeenCalled();
      await input('Thought or question','First invented line\nSecond invented line');await click('Send message');
    }else expect(enter.defaultPrevented).toBe(true);
    expect(workspaceApi.ask).toHaveBeenCalledOnce();
    expect(vi.mocked(workspaceApi.ask).mock.calls[0][2].content).toBe(native?'First invented line\nSecond invented line':'First invented line');
  });

  it("opens Research from the initial dashboard after choosing the encounter, without starting a lookup",async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    const {researchApi}=await import('./research-api'),{researchCatalog}=await import('./research-test-fixture');
    const catalogSpy=vi.spyOn(researchApi,'catalog').mockResolvedValue(researchCatalog(false));
    const configured=structuredClone(team),address=modelUuid(411);
    configured.configuration.bots.push({role:'research',instance_id:address,name:'Research',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true});
    configured.members.push({role:'research',instance_id:address,agent_id:modelUuid(412),name:'Research',initials:'Re',description:'Clinical trials and evidence',prompt:'Review public sources',capabilities:[]});
    vi.mocked(workspaceApi.team).mockResolvedValue(configured);
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:configured});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    const launch=[...container.querySelectorAll<HTMLButtonElement>('.team-welcome-shortcuts button')].find(button=>button.textContent?.includes('Research'))!;
    expect(launch.textContent).toContain('Research');await act(async()=>launch.click());
    expect(container.textContent).toContain('Choose a visit for Research');expect(workspaceApi.open).not.toHaveBeenCalled();
    await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    expect(container.querySelector('.team-roster [aria-pressed="true"] strong')?.textContent,container.textContent??'').toBe('Research');
    await vi.waitFor(async()=>{await act(async()=>{});expect(container.querySelector('.research-workspace')).not.toBeNull();});
    expect(workspaceApi.ask).not.toHaveBeenCalled();catalogSpy.mockRestore();
  });

  it('opens Chief and focuses the notebook once, only after private recovery is ready',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    let release!:()=>void;const barrier=new Promise<void>(resolve=>{release=resolve;});
    const delayed:typeof draftStorage=async options=>{await barrier;return draftStorage(options);};
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:structuredClone(team)});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    const focus=vi.spyOn(HTMLTextAreaElement.prototype,'focus');
    try{
      await act(async()=>root.render(<EncounterWorkspace draftStorage={delayed} authenticated={access}/>));
      expect(container.querySelectorAll('.team-welcome-first-tasks button')).toHaveLength(3);
      expect(container.textContent).toContain('🌱 Try a sample');
      await click('🌱 Try a sample');expect(container.querySelector('[role="dialog"]')).not.toBeNull();
      await click('Close sample visit');expect(container.querySelector('[role="dialog"]')).toBeNull();
      await click('Start with Chief');expect(container.querySelector('.team-welcome h1')?.textContent).toBe('Choose a visit for Chief');
      expect(workspaceApi.open).not.toHaveBeenCalled();
      await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
      const notebook=container.querySelector<HTMLTextAreaElement>('#team-notebook')!;
      expect(notebook.disabled).toBe(true);expect(focus.mock.contexts.filter(item=>item===notebook)).toHaveLength(0);
      await act(async()=>release());
      expect(container.querySelector('.team-roster [aria-pressed="true"] strong')?.textContent).toBe('Chief');
      expect(container.querySelector('.team-content')?.getAttribute('data-mobile-panel')).toBe('Notebook');
      expect(document.activeElement).toBe(notebook);expect(focus.mock.contexts.filter(item=>item===notebook)).toHaveLength(1);
      await chooseBot('Scribe');await chooseBot('Chief');
      expect(focus.mock.contexts.filter(item=>item===notebook)).toHaveLength(1);
      expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
    }finally{release();focus.mockRestore();}
  });

  it('keeps a new team inline and recovers its exact explicit activation without losing typed notes',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()},initial={...structuredClone(team),revision:0};
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:initial});
    vi.mocked(workspaceApi.team).mockResolvedValue(initial);
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await click('Start with Chief');await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    expect(container.querySelector('.team-workspace')?.getAttribute('data-settings-open')).toBe('false');
    expect(container.querySelector('[aria-label="Start your team"]')).not.toBeNull();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
    await input('Jotted notes','Keep this invented typed intake');
    vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(503));
    await click('Use this team');const exact=vi.mocked(workspaceApi.saveTeam).mock.calls[0][1];
    expect(exact.expected_revision).toBe(0);expect(exact.configuration.bots.map(bot=>bot.name)).toEqual(names);
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Start your team"] button')!.disabled).toBe(true);
    expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Keep this invented typed intake');
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue(structuredClone(team));vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));
    await click('Retry same save');expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1]).toEqual([access,exact]);
    expect(container.querySelector('[aria-label="Start your team"]')).toBeNull();
    expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Keep this invented typed intake');
    expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
  });

  it('prepares an editable Chief question and uses ordinary admission only when Send is chosen',async()=>{
    const configured=structuredClone(team);configured.llm.enabled=true;
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(fixture),team:configured});
    vi.mocked(workspaceApi.team).mockResolvedValue(configured);
    vi.mocked(workspaceApi.ask).mockImplementation(async(_,id,body)=>modelReceipt(body,id));
    await click('Open synthetic encounter');await chooseBot('Chief');await click('Prepare visit questions');
    const question=container.querySelector<HTMLTextAreaElement>('#team-question')!;
    expect(question.value).toBe(CHIEF_STARTERS[1].prompt);expect(document.activeElement).toBe(question);
    expect(workspaceApi.ask).not.toHaveBeenCalled();
    await click('Organize saved notes');expect(question.value).toBe(CHIEF_STARTERS[1].prompt);
    await click('Send message');expect(workspaceApi.ask).toHaveBeenCalledOnce();
    expect(vi.mocked(workspaceApi.ask).mock.calls[0][2]).toMatchObject({role:'chief',content:CHIEF_STARTERS[1].prompt,expected_revision:1,team_revision:1});
  });

  it('routes an edited first-use team back to review rather than accepting it as the default',async()=>{
    const initial={...structuredClone(team),revision:0};
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(fixture),team:initial});
    vi.mocked(workspaceApi.team).mockResolvedValue(initial);
    await click('Open synthetic encounter');await settings().practice();
    await input('Practice context','Retain this personalized practice context');await settings().click('Done');if(container.querySelector('[role="dialog"]'))await click('Keep draft and continue');
    const panel=container.querySelector('[aria-label="Start your team"]')!;
    expect(panel.textContent).toContain('Review team changes');expect(panel.textContent).not.toContain('Use this team');
    await click('Review team changes');expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
    await settings().practice();
    expect(container.querySelector<HTMLTextAreaElement>('.team-practice-editor textarea')?.value).toBe('Retain this personalized practice context');
  });

  it('requires notebook changes to be saved before a Chief task can use them',async()=>{
    const configured=structuredClone(team);configured.llm.enabled=true;
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(fixture),team:configured});
    await click('Open synthetic encounter');await chooseBot('Chief');await input('Jotted notes','Invented intake, not yet saved');
    expect([...container.querySelectorAll<HTMLButtonElement>('[aria-label="Chief task starters"] button')].every(button=>button.disabled)).toBe(true);
    const saved={...structuredClone(fixture),revision:2,entries:[...structuredClone(fixture.entries),{...fixture.entries[0],id:'typed-intake',revision:2,kind:'scratchpad' as const,content:'Invented intake, not yet saved'}]};
    vi.mocked(workspaceApi.append).mockResolvedValue({entry_id:'typed-intake',entry_revision:2,workspace:saved});
    await click('Save notebook revision');await click('Organize saved notes');
    expect(container.querySelector<HTMLTextAreaElement>('#team-question')!.value).toBe(CHIEF_STARTERS[0].prompt);
    expect(workspaceApi.ask).not.toHaveBeenCalled();
  });

  it.each([['Record a visit','Choose the visit to record'],['Use an existing recording','Choose the recorded visit']])('keeps the %s home action tied to the chosen visit',async(action,title)=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:structuredClone(team)});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await click(action);expect(container.querySelector('.team-welcome h1')?.textContent).toBe(title);expect(workspaceApi.open).not.toHaveBeenCalled();
    await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    expect(workspaceApi.open).toHaveBeenCalledExactlyOnceWith(access,fixture.appointment_id);
    expect(container.querySelector('.team-roster [aria-pressed="true"] strong')?.textContent).toBe('Scribe');
    expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.append).not.toHaveBeenCalled();
  });

  it("includes only the chosen Session Prep in chat and drops selection when switching bots",async()=>{
    const access={mode:"clerk_jwt" as const,getToken:vi.fn()};
    const connected=structuredClone(team);connected.llm.enabled=true;connected.capture={enabled:false,prep_enabled:true};
    connected.members[1].capabilities.push({key:"core.session_prep.read",label:"Session Prep",state:"enabled",connector:"Core",contract:"core.session-prep.brief.v1"});
    vi.mocked(workspaceApi.team).mockResolvedValue(connected);
    vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:structuredClone(fixture),team:connected});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    vi.mocked(readSessionPrep).mockResolvedValue(sessionPrepFixture());
    vi.mocked(workspaceApi.ask).mockImplementation(async(_,id,body)=>modelReceipt(body,id));
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await click("Choose an encounter");await act(async()=>container.querySelector<HTMLButtonElement>(".team-encounter-option")!.click());
    await click("Open Session Prep");expect(container.textContent).not.toContain("Session Prep included");
    await click("Include in chat");await vi.waitFor(async()=>{await act(async()=>{});expect(container.textContent).toContain("Session Prep included");});
    expect(container.querySelector<HTMLDetailsElement>(".session-prep-detail")?.open).toBe(false);
    expect(document.activeElement).toBe(container.querySelector("#team-question"));
    await input("Thought or question","What changed since the previous visit?");await click("Send message");
    await vi.waitFor(async()=>{await act(async()=>{});expect(container.textContent).toContain("Delivered");});
    const first=vi.mocked(workspaceApi.ask).mock.calls[0][2];
    expect(first.session_prep_analysis).toEqual(await sessionPrepAnalysis(sessionPrepFixture()));
    expect(JSON.stringify(first)).not.toContain("Invented reviewed visit summary");
    await chooseBot("Scribe");expect(container.textContent).not.toContain("Session Prep included");
    await input("Thought or question","Use my saved notebook.");await click("Send message");
    await vi.waitFor(async()=>{await act(async()=>{});expect(workspaceApi.ask).toHaveBeenCalledTimes(2);});
    expect(vi.mocked(workspaceApi.ask).mock.calls[1][2]).not.toHaveProperty("session_prep_analysis");
  });

  it("starts without a request and labels unsupported capabilities", async () => {
    expect(workspaceApi.open).not.toHaveBeenCalled();
    await click("Open synthetic encounter");
    expect(container.textContent).toContain("Linked visit");
    expect(container.textContent).toContain("AI chat is not connected yet.");
    await click("During");
    expect((([...container.querySelectorAll("button")].find(b => b.textContent === "Start recording")) as HTMLButtonElement).disabled).toBe(true);
    expect(container.querySelector('nav[aria-label="Encounter stage"] button[aria-pressed="true"]')?.textContent).toBe("During");
  });

  it("protects unsaved notebook and team settings until explicit discard", async () => {
    const blocked=()=>!window.dispatchEvent(new Event("beforeunload",{cancelable:true}));
    await click("Open synthetic encounter");expect(blocked()).toBe(false);
    await input("Jotted notes","Keep this invented unfinished text");expect(blocked()).toBe(true);
    await click("Close notebook");await click("Keep editing");
    expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("Keep this invented unfinished text");
    await settings().practice();await input("Practice context","Unfinished team settings");
    await input("Practice context",team.configuration.practice_context);
    expect(blocked()).toBe(true); // Notebook still owns an independent draft.
    await click("Close notebook");await click("Close anyway");
    expect(container.querySelector("#team-notebook")).toBeNull();expect(blocked()).toBe(false);
    expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
  });

  it("keeps an unconfirmed notebook request after cancelled close, then clears its guard after exact retry", async () => {
    const blocked=()=>!window.dispatchEvent(new Event("beforeunload",{cancelable:true}));
    await click("Open synthetic encounter");await input("Jotted notes","Retry this invented note");
    vi.mocked(workspaceApi.append).mockRejectedValueOnce(new WorkspaceApiError(503));
    await click("Save notebook revision");const first=vi.mocked(workspaceApi.append).mock.calls[0];
    await click("Close notebook");await click("Keep editing");expect(blocked()).toBe(true);
    vi.mocked(workspaceApi.append).mockResolvedValue({entry_id:"saved-note",entry_revision:2,workspace:{...fixture,revision:2,
      entries:[...fixture.entries,{...fixture.entries[0],id:"saved-note",revision:2,kind:"scratchpad",content:first[2].content}]}});
    await click("Retry same save");expect(vi.mocked(workspaceApi.append).mock.calls[1]).toEqual(first);
    expect(blocked()).toBe(false);await click("Close notebook");expect(container.querySelector("#team-notebook")).toBeNull();
  });

  it("shows the close decision while Practice work is open and protects another hidden editor", async () => {
    await click("Open synthetic encounter");await click("Review");
    await input("Private note draft","Unfinished private review");
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[],people:[],next_cursor:null});
    await click("Practice work");await click("Close notebook");
    const keep=[...container.querySelectorAll("button")].find(b=>b.textContent==="Keep editing")!;
    expect(keep.closest("[hidden]")).toBeNull();await click("Keep editing");await click("Back to notebook");
    expect(container.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe("Unfinished private review");
  });

  it("sets up a signed-in provider's team without selecting or creating an encounter", async () => {
    const access = {mode:"clerk_jwt" as const,getToken:vi.fn()};
    vi.mocked(workspaceApi.team).mockResolvedValue({...team,revision:0});
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    expect(workspaceApi.team).toHaveBeenCalledWith(access);
    await settings().practice(); await input("Practice context","Invented independent practice");
    vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(503));
    await settings().save();
    const saved = vi.mocked(workspaceApi.saveTeam).mock.calls[0][1];
    expect(saved).toMatchObject({expected_revision:0,configuration:{practice_context:"Invented independent practice"}});
    expect([...container.querySelectorAll("button")].find(button=>button.textContent==="Set up my team")!.disabled).toBe(true);
    await settings().click("Done");if(container.querySelector('[role="dialog"]'))await click("Keep draft and continue"); const catalogReads=vi.mocked(workspaceApi.catalog).mock.calls.length;await click("Choose an encounter"); expect(vi.mocked(workspaceApi.catalog).mock.calls.length).toBe(catalogReads+1);
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue({...team,configuration:saved.configuration}); vi.mocked(workspaceApi.team).mockResolvedValue({...team,configuration:saved.configuration});
    await click("Retry same save");
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1]).toEqual([access,saved]);
    expect(container.textContent).toContain("Team settings saved · revision 1");
    expect(workspaceApi.open).not.toHaveBeenCalled(); expect(workspaceApi.append).not.toHaveBeenCalled();
  });

  it("recovers a standalone setup conflict while preserving the provider's settings", async () => {
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={{mode:"clerk_jwt",getToken:vi.fn()}}/>));
    await settings().practice(); await input("Practice context","Keep this unsaved practice context");
    vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(409));
    await settings().save();
    vi.mocked(workspaceApi.team).mockResolvedValue({...team,revision:2});
    await click("Load latest — keep my text"); await settings().practice();
    expect(container.querySelector<HTMLTextAreaElement>(".team-practice-editor textarea")!.value).toBe("Keep this unsaved practice context");
    expect(workspaceApi.read).not.toHaveBeenCalled();
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue({...team,revision:3}); vi.mocked(workspaceApi.team).mockResolvedValue({...team,revision:3});
    await settings().save();
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1]).toMatchObject({expected_revision:2,
      configuration:{practice_context:"Keep this unsaved practice context"}});
    expect(workspaceApi.open).not.toHaveBeenCalled();
  });

  it("preserves unfinished setup when the provider opens an encounter", async () => {
    const access = {mode:"clerk_jwt" as const,getToken:vi.fn()};
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await settings().practice(); await input("Practice context","Unfinished setup"); await settings().click("Done");if(container.querySelector('[role="dialog"]'))await click("Keep draft and continue");
    await click("Choose an encounter");
    const visit = container.querySelector<HTMLButtonElement>(".team-encounter-option")!;
    await act(async()=>visit.click()); await settings().practice();
    expect(container.querySelector<HTMLTextAreaElement>(".team-practice-editor textarea")!.value).toBe("Unfinished setup");
    expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
  });

  it("preserves unsaved notebook text through independent team changes", async () => {
    await click("Open synthetic encounter"); await input("Jotted notes","Keep this unfinished notebook");
    await settings().practice(); await input("Practice context","Updated private team");
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue({...team,revision:2}); vi.mocked(workspaceApi.team).mockResolvedValue({...team,revision:2}); await settings().save();
    expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("Keep this unfinished notebook");
    expect(workspaceApi.read).not.toHaveBeenCalled(); expect(workspaceApi.append).not.toHaveBeenCalled();
  });

  it('refreshes the encounter after connected delivery work and preserves unsaved notebook text',async()=>{
    const access={mode:'clerk_jwt' as const,getToken:vi.fn()};
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:fixture.appointment_id,workspace_id:fixture.id,label:fixture.label}]);
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>));
    await click('Choose an encounter');
    await act(async()=>container.querySelector<HTMLButtonElement>('.team-encounter-option')!.click());
    await input('Jotted notes','Retained text while the follow-up is saved');
    const materials=(label:string)=>container.querySelector<HTMLButtonElement>(`nav[aria-label="Encounter materials"] button:nth-child(${label==='Work'?4:1})`)!;
    await act(async()=>materials('Work').click());
    vi.mocked(workspaceApi.read).mockResolvedValue({...structuredClone(fixture),revision:5});
    await click('Observe saved connected delivery');
    for(let i=0;i<50;i++){
      if(container.textContent?.includes('Latest saved history and team loaded.'))break;
      await act(async()=>{await new Promise(resolve=>setTimeout(resolve,5));});
    }
    expect(workspaceApi.read).toHaveBeenCalledWith(access,fixture.id);
    await act(async()=>materials('Notebook').click());
    expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')!.value).toBe('Retained text while the follow-up is saved');
    vi.mocked(workspaceApi.append).mockResolvedValue({entry_id:'invented-notebook-entry',entry_revision:6,workspace:{...structuredClone(fixture),revision:6}});
    await click('Save notebook revision');
    expect(vi.mocked(workspaceApi.append).mock.calls.at(-1)?.[2]).toMatchObject({expected_revision:5,
      content:'Retained text while the follow-up is saved'});
  });

  it("clears setup after account change and ignores the former account's late save", async () => {
    let saved!: (value:ProviderTeam)=>void;
    const access = {mode:"clerk_jwt" as const,getToken:vi.fn()};
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access}/>)); await settings().practice();
    await input("Practice context","Former account private settings");
    vi.mocked(workspaceApi.saveTeam).mockImplementationOnce(()=>new Promise(resolve=>{saved=resolve;}));
    await settings().save();
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={{mode:"clerk_jwt",getToken:vi.fn()}}/>));
    await act(async()=>saved({...team,revision:2,configuration:{...team.configuration,practice_context:"Former account private settings"}}));
    expect(container.textContent).not.toContain("Former account private settings");
    expect(container.textContent).not.toContain("Team settings saved");
    expect(container.querySelector(".team-settings")).toBeNull();
    expect(container.querySelector(".team-roster")!.textContent).not.toContain("Former account");
    expect(container.querySelector('[aria-label="Workspace navigation"] [aria-current="page"]')?.textContent).toBe('Home');
  });

  it("clears private setup when the signed-in binding is revoked", async () => {
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={{mode:"clerk_jwt",getToken:vi.fn()}}/>));
    await settings().practice(); await input("Practice context","Revoked private settings");
    vi.mocked(workspaceApi.team).mockRejectedValueOnce(new WorkspaceApiError(403));
    await settings().click("Back"); await settings().click("Refresh current settings");
    expect(container.querySelector(".team-settings")).toBeNull();
    expect(container.textContent).toContain("Private content has been cleared");
    expect(container.textContent).not.toContain("Revoked private settings");
  });

  async function addScribe() {
    await settings().team(); await settings().overview(); await settings().click("Add a coworker");
    await settings().click("Scribe");
    await input("Bot name", "Visit partner");
    await input("Job", "SOAP documentation");
    await input("Working preferences", "Keep transcript and scratch notes attributed");
  }

  it("adds a private instance, retries the identical configuration, and addresses that instance", async () => {
    const connected=enableModel();
    await click("Open synthetic encounter"); await addScribe();
    vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(503));
    await settings().save();
    const input = vi.mocked(workspaceApi.saveTeam).mock.calls[0][1];
    const added = input.configuration.bots.at(-1)!;
    expect(added).toMatchObject({role: "scribe", name: "Visit partner", job_focus: "SOAP documentation"});
    expect(added.instance_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(input.configuration.bots[0].name).toBe("Scribe");
    expect(container.querySelector<HTMLButtonElement>('.team-flow-footer button')!.disabled).toBe(true);
    const saved = {...connected, revision: 2, configuration: input.configuration,
      members: [...connected.members, {...connected.members[0], instance_id: added.instance_id, agent_id: "extra-principal"}]};
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue(saved); vi.mocked(workspaceApi.team).mockResolvedValue(saved);
    await click("Retry same save");
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1]).toEqual(input);
    expect(container.querySelector(".team-conversation-header h2")?.textContent).toBe("Visit partner");
    const textbox = container.querySelector<HTMLTextAreaElement>("#team-question")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textbox, "Review this visit");
      textbox.dispatchEvent(new Event("input", {bubbles: true}));
    });
    vi.mocked(workspaceApi.ask).mockImplementation(async(_,id,body)=>modelReceipt(body,id));
    await click("Send message");
    expect(vi.mocked(workspaceApi.ask).mock.calls[0][2]).toMatchObject({role: added.instance_id, team_revision: 2});
    await vi.waitFor(async()=>{await act(async()=>{});expect(container.textContent).toContain("Delivered");});
    await settings().editSelected(); await settings().click("Permissions");
    const enabled = [...container.querySelectorAll("label")].find(e => e.textContent === "Enable this bot")!.querySelector<HTMLInputElement>("input")!;
    await act(async () => enabled.click());
    vi.mocked(workspaceApi.saveTeam).mockImplementation(async (_, body) => ({...saved, revision: 3, configuration: body.configuration}));
    await settings().save();
    expect(container.querySelector<HTMLTextAreaElement>("#team-question")!.disabled).toBe(true);
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls.at(-1)![1].configuration.bots[0].enabled).toBe(true);
  });

  it("keeps an unsaved new bot in settings without routing chat to an uninstalled identity", async () => {
    await click("Open synthetic encounter"); await addScribe(); await settings().click("Done");if(container.querySelector('[role="dialog"]'))await click("Keep draft and continue");
    expect(container.querySelector(".team-conversation-header h2")?.textContent).toBe("Scribe");
    expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
    await settings().editSelected();
    await settings().overview();
    expect(container.querySelector('[aria-label="Your coworkers"]')?.textContent).toContain("Visit partner");
  });

  it("shows each custom bot's own conversation and preserves the shared notebook", async () => {
    const bots = ["First partner", "Second partner"].map((name, i) => ({...team.configuration.bots[1],
      role: "custom" as const, instance_id: `custom-address-${i}`, name, job_focus: "Referral checklist", skills: ["saved_context" as const]}));
    const installed = {...team, configuration: {...team.configuration, bots: [...team.configuration.bots, ...bots]},
      members: [...team.members, ...bots.map((bot, i) => ({...team.members[1], ...bot, agent_id: `custom-agent-${i}`}))]};
    const entries: Workspace["entries"] = bots.map((bot, i) => ({id: `custom-turn-${i}`, revision: i + 2,
      kind: "conversation", content: `Private question ${i}`, source_label: null, origin: "human", ticket: null,
      created_at: "2026-09-20T00:00:00Z", reply: {role: "custom", agent_id: `custom-agent-${i}`, agent_name: bot.name,
        backend: "local_source_review_v1", content: `Private response ${i}`, context_revision: 1, citations: []}}));
    vi.mocked(workspaceApi.open).mockResolvedValue({identity, team: installed, workspace: {...fixture, revision: 4,
      entries: [...fixture.entries, ...entries, {id: "shared-note", revision: 4, kind: "scratchpad", content: "Shared encounter notebook",
        source_label: null, origin: "human", ticket: null, created_at: "2026-09-20T00:00:00Z"}]}});
    await click("Open synthetic encounter");
    for (const [i, name] of ["First partner", "Second partner"].entries()) {
      const button = [...container.querySelectorAll<HTMLButtonElement>(".team-roster button")].find(b => b.textContent?.startsWith(name))!;
      await act(async () => button.click());
      expect(container.querySelector(".team-messages")!.textContent).toContain(`Private response ${i}`);
      expect(container.querySelector(".team-messages")!.textContent).not.toContain(`Private response ${1-i}`);
      expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("Shared encounter notebook");
    }
  });

  it("retires an added bot only on exact save and preserves access to its history", async () => {
    const address = "11111111-1111-4111-8111-111111111111";
    const added = {...team.configuration.bots[0], instance_id: address, name: "Visit partner"};
    const installed = {...team, revision: 2, configuration: {...team.configuration, bots: [...team.configuration.bots, added]},
      members: [...team.members, {...team.members[0], instance_id: address, agent_id: "retiring-principal"}]};
    vi.mocked(workspaceApi.open).mockResolvedValue({identity, workspace: structuredClone(fixture), team: installed});
    await click("Open synthetic encounter");
    const rosterBot = [...container.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b => b.textContent?.startsWith("Visit partner"))!;
    await act(async () => rosterBot.click());
    await settings().editSelected(); await settings().click("Permissions");
    const enabled = [...container.querySelectorAll("label")].find(e => e.textContent === "Enable this bot")!.querySelector<HTMLInputElement>("input")!;
    await act(async () => enabled.click());
    await click("Retire bot when saved");
    expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Saving will permanently retire this bot");
    await click("Undo retirement");
    expect([...container.querySelectorAll("button")].find(button=>button.textContent==="Retire bot when saved")!.disabled).toBe(false);
    expect([...container.querySelectorAll("label")].find(e=>e.textContent==="Enable this bot")!.querySelector<HTMLInputElement>("input")!.checked).toBe(false);
    await click("Retire bot when saved");
    vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(503));
    await settings().save();
    const input = vi.mocked(workspaceApi.saveTeam).mock.calls[0][1];
    expect(input.configuration.bots.at(-1)).toMatchObject({instance_id: address, retired: true, enabled: false});
    const retired = {...installed, revision: 3, configuration: input.configuration};
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue(retired); vi.mocked(workspaceApi.team).mockResolvedValue(retired);
    await click("Retry same save");
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1]).toEqual(input);
    expect(container.querySelector<HTMLTextAreaElement>('#team-question')!.disabled).toBe(true);
    expect(container.querySelector<HTMLTextAreaElement>('#team-question')!.placeholder).toContain("retired. Saved history remains available");
    expect(container.querySelector('.team-roster')!.textContent).toContain("Retired · history kept");
    await settings().editSelected();
    expect(container.querySelector<HTMLInputElement>('.team-settings-form input')!.disabled).toBe(true);
    expect(container.textContent).not.toContain("Undo retirement");
    expect(container.textContent).not.toContain("Retire bot when saved");
  });

  it("lets the signed-in provider deliberately choose the encounter", async () => {
    const authenticated = { mode: "clerk_jwt" as const, getToken: vi.fn() };
    vi.mocked(workspaceApi.catalog).mockResolvedValue([
      { appointment_id: "appointment-first", workspace_id: null, label: "First invented visit" },
      { appointment_id: fixture.appointment_id, workspace_id: fixture.id, label: "Second invented visit" },
    ]);
    await act(async () => root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={authenticated} />));
    await click("Choose an encounter");
    expect(workspaceApi.open).not.toHaveBeenCalled();
    expect(container.querySelector('[aria-label="Available encounters"]')?.textContent).toContain("Open saved notes");
    const second = [...container.querySelectorAll("button")].find(button => button.textContent?.includes("Second invented visit"));
    await act(async () => second!.click());
    expect(workspaceApi.open).toHaveBeenCalledWith(authenticated, fixture.appointment_id);
  });

  it("opens a saved visit, and replaces a hung open with Retry at the deadline", async () => {
    const access = {mode: "clerk_jwt" as const, getToken: vi.fn()};
    vi.mocked(workspaceApi.privateDraftSummaries).mockResolvedValue({contract_version: 2, drafts: [], has_more: false});
    vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id: fixture.appointment_id, workspace_id: fixture.id, label: "Invented Alex Example"}]);
    vi.mocked(workspaceApi.open).mockResolvedValue({identity: access, workspace: structuredClone(fixture), team: structuredClone(team)});
    await act(async () => root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={access} />));
    await click("Visits and notes");
    await act(async () => container.querySelector<HTMLButtonElement>(".team-encounter-option")!.click());
    expect(container.querySelector("#team-notebook")).not.toBeNull();
    expect(container.textContent).not.toContain("This visit could not be opened.");

    await click("Visits and notes");
    vi.useFakeTimers();
    vi.mocked(workspaceApi.open).mockImplementation(() => new Promise(() => {}));
    await act(async () => container.querySelector<HTMLButtonElement>(".team-encounter-option")!.click());
    const option = () => container.querySelector<HTMLButtonElement>(".team-encounter-option")!;
    expect(option().disabled).toBe(true);
    expect(container.textContent).toContain("Opening this visit…");
    await act(async () => { await vi.advanceTimersByTimeAsync(VisitOpenDeadline.limitMs - 1); });
    expect(option().disabled).toBe(true);
    expect(container.querySelector(".workspace-error-banner")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(option().disabled).toBe(false);
    expect(container.querySelector(".workspace-error-banner")?.textContent).toContain("This visit could not be opened.");
    expect([...container.querySelectorAll("button")].some(button => button.textContent === "Retry")).toBe(true);
    expect(container.textContent).not.toContain("Opening this visit…");
    vi.mocked(workspaceApi.open).mockResolvedValue({identity: access, workspace: structuredClone(fixture), team: structuredClone(team)});
    await click("Retry");
    expect(container.querySelector("#team-notebook")).not.toBeNull();
    expect(container.querySelector(".workspace-error-banner")).toBeNull();
  });

  it.each(['Choose an encounter','Start with Chief'])("shows an empty signed-in catalog from %s without falling back to demo seeding", async action => {
    vi.mocked(workspaceApi.catalog).mockResolvedValue([]);
    await act(async () => root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={{ mode: "clerk_jwt", getToken: vi.fn() }} />));
    await click(action);
    expect(container.textContent).toContain("No confirmed visits are available.");
    expect(workspaceApi.open).not.toHaveBeenCalled();
  });

  it("keeps the same notebook across stages and saves typed history", async () => {
    await click("Open synthetic encounter");
    await input("Jotted notes", "My invented private note");
    await click("After");
    expect(container.querySelector('nav[aria-label="Visit view"] button[aria-pressed="true"]')?.textContent).toBe("Review");
    await click("Notebook");
    expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")?.value).toBe("My invented private note");
    vi.mocked(workspaceApi.append).mockResolvedValue({ entry_id: "saved", entry_revision: 2, workspace: { ...fixture, revision: 2 } });
    await click("Save notebook revision");
    expect(workspaceApi.append).toHaveBeenCalledWith(identity, fixture.id, expect.objectContaining({
      kind: "scratchpad", content: "My invented private note", expected_revision: 1,
    }));
    expect(container.textContent).toContain("Saved revision 2");
  });

  it('drafts through Scribe after saving the intended notes and keeps edited review text',async()=>{
    const configured=structuredClone(team);configured.llm.enabled=true;
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(fixture),team:configured});
    vi.mocked(workspaceApi.team).mockResolvedValue(configured);
    await click('Open synthetic encounter');await input('Jotted notes','Synthetic dizziness history with uncertain cause.');
    const saved:Workspace={...structuredClone(fixture),revision:2,entries:[...fixture.entries,{...fixture.entries[0],id:'jottings',revision:2,kind:'scratchpad',content:'Synthetic dizziness history with uncertain cause.'}]};
    vi.mocked(workspaceApi.append).mockResolvedValue({workspace:saved,entry_id:'jottings',entry_revision:2});
    vi.mocked(workspaceApi.ask).mockImplementation(async(_identity,id,body)=>{
      expect(workspaceApi.append).toHaveBeenCalledOnce();expect(body.expected_revision).toBe(2);expect(body.role).toBe('scribe');
      vi.mocked(workspaceApi.read).mockResolvedValue({...saved,revision:3,entries:[...saved.entries,{...fixture.entries[0],id:modelUuid(601),revision:3,kind:'conversation',content:body.content,
        reply:{agent_name:'Scribe',role:'scribe',backend:'azure_gpt41',content:'Assessment: dizziness; cause uncertain.',context_revision:2,citations:[]}}]});
      return modelReceipt(body,id,3);
    });
    await click('Draft note from my notes');
    await vi.waitFor(async()=>{await act(async()=>{});expect(container.querySelector<HTMLTextAreaElement>('#private-note-text')?.value).toBe('Assessment: dizziness; cause uncertain.');});
    expect(workspaceApi.ask).toHaveBeenCalledOnce();expect(workspaceApi.saveNote).not.toHaveBeenCalled();
    await input('Private note draft','My edited assessment, preserving uncertainty.');
    await click('Visit notes');await click('Review note');
    expect(container.querySelector<HTMLTextAreaElement>('#private-note-text')?.value).toBe('My edited assessment, preserving uncertainty.');
  });

  it("keeps unsaved notebook typing when opening and returning from shared work", async () => {
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items: [], people: [], next_cursor: null});
    await click("Open synthetic encounter"); await input("Jotted notes", "Keep my private unsaved notes.");
    const notebook = container.querySelector<HTMLTextAreaElement>("#team-notebook");
    await click("Practice work");
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(container.querySelector('[aria-label="Practice work"]')?.textContent).toContain("No shared work");});
    await click("Back to notebook");
    expect(container.querySelector("#team-notebook")).toBe(notebook);
    expect(notebook!.value).toBe("Keep my private unsaved notes.");
    expect(workspaceApi.append).not.toHaveBeenCalled();
  });

  it("opens shared work before selecting a private encounter", async () => {
    const authenticated = {mode: "clerk_jwt" as const, getToken: vi.fn()};
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items: [], people: [], next_cursor: null});
    await act(async () => root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={authenticated} />));
    await click("Practice work");
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(workspaceApi.practiceWork).toHaveBeenCalledWith(authenticated, undefined);});
    expect(workspaceApi.open).not.toHaveBeenCalled();
  });

  it("preserves the private review editor across sources and team settings", async () => {
    await click("Open synthetic encounter"); await click("After");
    await input("Private note draft", "Keep this unsaved review edit.");
    await click("Sources"); await settings().editSelected(); await settings().click("Done");if(container.querySelector('[role="dialog"]'))await click("Keep draft and continue");
    await click("After");
    expect(container.querySelector<HTMLTextAreaElement>("#private-note-text")?.value).toBe("Keep this unsaved review edit.");
  });

  it("retries the same unconfirmed note save without changing its payload", async () => {
    await click("Open synthetic encounter"); await click("After");
    await input("Private note draft", "Invented review note.");
    vi.mocked(workspaceApi.saveNote).mockRejectedValueOnce(new WorkspaceApiError(503));
    await click("Save note version");
    const first = vi.mocked(workspaceApi.saveNote).mock.calls[0][2];
    expect(container.querySelector<HTMLTextAreaElement>("#private-note-text")?.disabled).toBe(true);
    vi.mocked(workspaceApi.saveNote).mockResolvedValue({entry_revision: 2, workspace: {...fixture, revision: 2}});
    await click("Retry same save");
    expect(vi.mocked(workspaceApi.saveNote).mock.calls[1][2]).toEqual(first);
  });

  it("preserves unsaved text on conflict and requires an explicit latest-version load", async () => {
    await click("Open synthetic encounter"); await input("Jotted notes", "Keep my edit");
    vi.mocked(workspaceApi.append).mockRejectedValue(new WorkspaceApiError(409));
    await click("Save notebook revision");
    expect(container.textContent).toContain("Your text has not been overwritten");
    vi.mocked(workspaceApi.read).mockResolvedValue({ ...fixture, revision: 3 });
    await click("Load latest — keep my text");
    expect([...container.querySelectorAll("textarea")].some(e => e.value === "Keep my edit")).toBe(true);
    vi.mocked(workspaceApi.append).mockResolvedValue({ entry_id: "four", entry_revision: 4, workspace: { ...fixture, revision: 4 } });
    await click("Save notebook revision");
    expect(vi.mocked(workspaceApi.append).mock.calls[1][2].expected_revision).toBe(3);
  });

  it("resolves an uncertain model save with the identical payload and key without resubmitting", async () => {
    enableModel();
    await click("Open synthetic encounter"); await input("Thought or question", "Invented question");
    vi.mocked(workspaceApi.ask).mockRejectedValueOnce(new TypeError("network detail must stay private"));
    vi.mocked(modelWorkApi.resolve).mockImplementation(async(_,id,op)=>modelReceipt(op.body as typeof import('./model-work-test-fixture').conversationFixture,id));
    await click("Send message");
    expect(container.textContent).not.toContain("network detail");
    await click("Check saved result");
    expect(vi.mocked(modelWorkApi.resolve).mock.calls[0][2].body).toEqual(vi.mocked(workspaceApi.ask).mock.calls[0][2]);
    expect(workspaceApi.ask).toHaveBeenCalledOnce();
  });

  it("lets the clinician explicitly replace a Chief request that expired before starting, with a fresh key and current revision", async () => {
    const {pendingWorkspace,admissionFixture}=await import('./model-work-test-fixture');
    const connected=structuredClone(team);connected.llm.enabled=true;
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:structuredClone(fixture),team:connected});
    vi.mocked(workspaceApi.team).mockResolvedValue(connected);
    await click("Open synthetic encounter");
    await click("Chief");
    await input("Thought or question","Prepare drafts from the invented Scribe transcript.");
    vi.mocked(workspaceApi.ask).mockRejectedValueOnce(new TypeError('connection dropped before claim'));
    await click("Send message");
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(container.textContent).toContain("Check saved result");});
    const first=vi.mocked(workspaceApi.ask).mock.calls[0][2];expect(first.role).toBe('chief');
    const expired=await pendingWorkspace(first,'abandoned');expired.entries[0].model_request!.bot={address:'chief',role:'chief',name:'Chief',agent_id:modelUuid(102),team_revision:1};
    vi.mocked(workspaceApi.read).mockResolvedValue(expired);
    vi.mocked(modelWorkApi.resolve).mockImplementation(async(_,id)=>({...await modelReceipt(first,id),outcome:'abandoned',saved_entry:null,admission:admissionFixture('abandoned'),reason:'reservation_expired'}));
    await click("Check saved result");
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(container.textContent).toContain("Request expired before starting");});
    expect(workspaceApi.ask).toHaveBeenCalledOnce();
    await click("Start another attempt");
    expect(workspaceApi.ask).toHaveBeenCalledOnce();
    const latest={...expired,revision:4};vi.mocked(workspaceApi.read).mockResolvedValue(latest);
    vi.mocked(workspaceApi.ask).mockImplementation(async(_,id,body)=>{const saved=await pendingWorkspace(body,'completed');saved.revision=5;saved.entries[0].revision=5;saved.entries[0].reply={role:'chief',agent_name:'Chief',backend:'azure_gpt41',content:'Invented fresh response for review.',context_revision:4,citations:[]};saved.entries[0].model_request!.bot={address:'chief',role:'chief',name:'Chief',agent_id:modelUuid(102),team_revision:1};vi.mocked(workspaceApi.read).mockResolvedValue(saved);return modelReceipt(body,id,5);});
    await click("Send new attempt");
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(workspaceApi.ask).toHaveBeenCalledTimes(2);});
    const next=vi.mocked(workspaceApi.ask).mock.calls[1][2];expect(next).toMatchObject({role:'chief',content:first.content,expected_revision:4,team_revision:1});
    expect(next.idempotency_key).not.toBe(first.idempotency_key);
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(container.textContent).toContain("Previous request retained as superseded history");});
  });

  it("retries an unconfirmed follow-up approval with its exact original revision and hash", async () => {
    const followUp = {ticket_id: "ticket", revision_id: "revision", payload_hash: "a".repeat(64),
      state: "pending_approval", create_key: "fixture-key", body: "Invented message", due_date: "2026-10-01",
      expected_outcome: "Invented result", owner_id: identity.actorId, note_version: 1, source_changed: false,
      operation_status: null, receipts: []};
    const w = {...fixture, follow_ups: [followUp]};
    vi.mocked(workspaceApi.open).mockResolvedValue({identity, workspace: w, team});
    await click("Open synthetic encounter"); await click("Work");
    const label = [...container.querySelectorAll("label")].find(e => e.textContent?.startsWith("I approve this exact"))!;
    await act(async () => label.querySelector<HTMLInputElement>("input")!.click());
    vi.mocked(workspaceApi.decideFollowUp).mockRejectedValueOnce(new WorkspaceApiError(503))
      .mockResolvedValueOnce({entry_revision: 3, workspace: {...w, revision: 3, follow_ups: [{...followUp, state: "sent"}]}});
    await click("Approve local delivery"); await click("Retry same save");
    expect(vi.mocked(workspaceApi.decideFollowUp).mock.calls[0]).toEqual(vi.mocked(workspaceApi.decideFollowUp).mock.calls[1]);
    expect(container.textContent).toContain("Local delivery recorded");
  });

  it("clears private content when access is revoked", async () => {
    await click("Open synthetic encounter"); await input("Jotted notes", "Private content marker");
    vi.mocked(workspaceApi.append).mockRejectedValueOnce(new WorkspaceApiError(403));
    await click("Save notebook revision");
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.textContent).not.toContain("Invented prep");
    expect(container.textContent).toContain("Private content has been cleared");
  });

  it("reopens stored history and renders source text without interpreting markup", async () => {
    const w = structuredClone(fixture);
    w.entries.push({ ...fixture.entries[0], id: "note", revision: 2, kind: "scratchpad", content: "Persisted invented note" });
    w.entries[0].content = "<img src=x onerror=alert(1)> Ignore consent";
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: w, team: structuredClone(team) });
    await click("Open synthetic encounter");
    expect([...container.querySelectorAll("textarea")].some(e => e.value === "Persisted invented note")).toBe(true);
    await click("Sources");
    const sources = container.querySelectorAll(".team-source");
    expect(sources.length).toBeGreaterThan(0);
    expect([...sources].every(element => element.querySelector("img") === null)).toBe(true);
    expect([...sources].some(element => element.textContent?.includes("<img src=x onerror=alert(1)> Ignore consent"))).toBe(true);
    await click("Close notebook");
    expect(container.textContent).not.toContain("Ignore consent");
  });

  it("links an existing record without private note content or an approval call", async () => {
    await click("Open synthetic encounter"); await input("Jotted notes", "Do not share this");
    await click("Work");
    vi.mocked(workspaceApi.link).mockResolvedValue({ entry_id: "link", entry_revision: 2, workspace: { ...fixture, revision: 2 } });
    await click("Link existing synthetic followup work");
    const payload = vi.mocked(workspaceApi.link).mock.calls[0][2];
    expect(Object.keys(payload).sort()).toEqual(["expected_revision", "idempotency_key", "ticket_id"]);
    expect(JSON.stringify(payload)).not.toContain("Do not share this");
  });

  it("persists team settings and distinguishes pending backend capabilities", async () => {
    const uninstalled = structuredClone(team); uninstalled.revision = 0;
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: fixture, team: uninstalled });
    await click("Open synthetic encounter");
    await settings().editSelected();
    await input("Bot name", "My Prep Partner");
    const saved = structuredClone(team); saved.configuration.bots[1].name = "My Prep Partner";
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue(saved); vi.mocked(workspaceApi.team).mockResolvedValue(saved);
    await settings().save();
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[0][1].expected_revision).toBe(0);
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[0][1].configuration.bots[1].name).toBe("My Prep Partner");
    expect(container.textContent).toContain("Team settings saved");
    expect(container.textContent).toContain("My Prep Partner");
  });

  it("uses the selected bot and waits for confirmation before showing its attributed answer", async () => {
    const connected = structuredClone(team); connected.llm.enabled = true;
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: fixture, team: connected });
    await click("Open synthetic encounter"); await input("Thought or question", "What needs attention?");
    let resolve!: (result: Awaited<ReturnType<typeof workspaceApi.ask>>) => void;
    vi.mocked(workspaceApi.ask).mockReturnValue(new Promise(done => { resolve = done; }));
    await click("Send message");
    expect(container.textContent).toContain("Waiting for confirmation…");
    expect(container.textContent).not.toContain("Visit Prep is thinking");
    expect(container.querySelector(".message-request-status-dots")).toBeNull();
    expect(vi.mocked(workspaceApi.ask).mock.calls[0][2]).toMatchObject({ role: "visit_prep", expected_revision: 1, team_revision: 1 });
    const result = structuredClone(fixture);
    result.revision = 2;
    result.entries.push({ ...fixture.entries[0], id: "question", kind: "conversation", content: "What needs attention?", revision: 2,
      reply: { agent_name: "Visit Prep", role: "visit_prep", backend: "azure_gpt41", content: "Review the invented source.", context_revision: 1,
        citations: [{ entry_id: "source-invented", revision: 1, label: "Fixture v1", kind: "synthetic_source" }] } });
    vi.mocked(workspaceApi.read).mockResolvedValue(result);
    await act(async () => resolve(await modelReceipt(vi.mocked(workspaceApi.ask).mock.calls[0][2],fixture.id)));
    await act(async()=>{await vi.waitFor(()=>expect(workspaceApi.read).toHaveBeenCalled());});
    expect(container.textContent).toContain("Review the invented source.");
    const citation = [...container.querySelectorAll("button")].find(b => b.textContent?.startsWith("Fixture v1"))!;
    await act(async () => citation.click());
    expect(document.activeElement?.id).toBe("source-source-invented");
  });

  it("keeps a paused bot from sending a message", async () => {
    const paused = structuredClone(team); paused.configuration.bots[1].enabled = false;
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: fixture, team: paused });
    await click("Open synthetic encounter");
    expect(container.querySelector<HTMLTextAreaElement>("#team-question")?.disabled).toBe(true);
    expect(container.querySelector<HTMLButtonElement>('button[aria-label="Send message"]')?.disabled).toBe(true);
    expect(workspaceApi.ask).not.toHaveBeenCalled();
  });

  it.each(["success", "error"])("animates only the selected bot's pending ask and stops immediately on %s", async outcome => {
    enableModel();
    const preference = Object.assign(new EventTarget(), {matches:false});
    vi.stubGlobal("matchMedia", () => preference);
    vi.stubGlobal("IntersectionObserver", class {
      constructor(private callback:IntersectionObserverCallback) {}
      observe() {this.callback([{isIntersecting:true} as IntersectionObserverEntry],this as unknown as IntersectionObserver);}
      disconnect() {}
    });
    const visibility = vi.spyOn(document,"visibilityState","get").mockReturnValue("visible");
    try {
      await click("Open synthetic encounter");
      expect(container.querySelector(".team-conversation-header .bot-avatar-motion")).toBeNull();
      await input("Thought or question","Invented animation integration check");
      let resolve!: (value:Awaited<ReturnType<typeof workspaceApi.ask>>) => void, reject!: (reason:unknown) => void;
      vi.mocked(workspaceApi.ask).mockReturnValueOnce(new Promise((done,failed)=>{resolve=done;reject=failed;}));
      await click("Send message");
      const clip=container.querySelector<HTMLImageElement>(".team-conversation-header .bot-avatar-motion")!;
      expect(clip.getAttribute("src")).toBe("/bots/motion/visit-prep-intro.webp");
      await act(async()=>clip.dispatchEvent(new Event("load")));
      expect(container.querySelector(".team-conversation-header [data-motion-phase=intro]")).not.toBeNull();
      expect(container.querySelector(".team-roster .bot-avatar-motion")).toBeNull();
      await act(async()=>{if(outcome==="success") resolve(await modelReceipt(vi.mocked(workspaceApi.ask).mock.calls[0][2],fixture.id));
        else reject(new WorkspaceApiError(503));});
      if(outcome==='success')await act(async()=>{await vi.waitFor(()=>expect(workspaceApi.read).toHaveBeenCalled());});
      expect(container.querySelector(".team-conversation-header .bot-avatar-motion")).toBeNull();
      if(outcome==="error") expect(container.textContent).toContain("Check saved result");
    } finally {vi.unstubAllGlobals();visibility.mockRestore();}
  });

  it("preserves unsaved team settings through conflict recovery", async () => {
    await click("Open synthetic encounter"); await settings().editSelected();
    await input("Bot name", "Unsaved preferred name");
    vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(409));
    await settings().save();
    vi.mocked(workspaceApi.read).mockResolvedValue(fixture);
    vi.mocked(workspaceApi.team).mockResolvedValue({ ...team, revision: 2 });
    await click("Load latest — keep my text"); await settings().editSelected("Unsaved preferred name");
    expect([...container.querySelectorAll("input")].some(input => input.value === "Unsaved preferred name")).toBe(true);
    vi.mocked(workspaceApi.saveTeam).mockResolvedValue({ ...team, revision: 3 });
    await settings().save();
    expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1].expected_revision).toBe(2);
  });

  function assignedWorkspace(): Workspace {
    const value = structuredClone(fixture);
    value.revision = 2;
    value.entries.push({ ...fixture.entries[0], id: "chief-request", revision: 2, kind: "conversation", content: "Ask Scribe for a draft",
      reply: { role: "chief", agent_name: "Chief", backend: "azure_gpt41", content: "Queuing the draft", context_revision: 1, citations: [] } });
    value.handoffs = [{ id: modelUuid(701), origin_entry_id: "chief-request", recipient_role: "scribe", recipient_name: "Scribe",
      brief: "<img src=x> Organize the saved notes", context_revision: 1, status: "queued", attempt_id: modelUuid(702), attempt_count: 1,
      result_entry_id: null, error_code: null, attempts: [{ id: modelUuid(702), number: 1, status: "queued", error_code: null }] }];
    return value;
  }

  it("shows the delivered draft without overwriting unsaved notes or interpreting the brief as markup", async () => {
    vi.useFakeTimers();
    const assigned = assignedWorkspace();
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: assigned, team });
    await click("Open synthetic encounter");
    await chooseBot("Chief");
    await input("Jotted notes", "My unsaved private thought");
    expect(container.querySelector(".team-handoff p img")).toBeNull();
    expect(container.querySelector(".team-handoff p")?.textContent).toContain("<img src=x>");
    const completed = structuredClone(assigned); completed.revision = 3;
    completed.handoffs![0].status = "completed"; completed.handoffs![0].result_entry_id = "draft-result";
    completed.entries.push({ ...assigned.entries[1], id: "draft-result", revision: 3, kind: "handoff_result", content: "Organize the saved notes",
      reply: { role: "scribe", agent_name: "Scribe", backend: "azure_gpt41_source_draft_v1", content: "Returned invented draft", context_revision: 1, citations: [] } });
    vi.mocked(workspaceApi.read).mockResolvedValue(completed);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(container.textContent).toContain("Draft ready");
    expect(container.textContent).not.toContain("Brief from Chief");
    expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")?.value).toBe("My unsaved private thought");
    await click("Review Scribe result");
    expect(container.textContent).toContain("Brief from Chief");
    expect(document.activeElement?.id).toBe("turn-draft-result");
    expect(container.querySelector("#turn-draft-result .team-pill")?.textContent).toBe("Unreviewed draft");
    expect(workspaceApi.ask).not.toHaveBeenCalled();
  });

  it("reveals a Research result and focuses it once without stealing focus on later polling",async()=>{
    vi.useFakeTimers();
    const configured=structuredClone(team),address=modelUuid(810),agent=modelUuid(811);
    configured.configuration.bots.push({role:'research',instance_id:address,name:'Research',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true});
    configured.members.push({role:'research',instance_id:address,agent_id:agent,name:'Research',initials:'Re',description:'Evidence review',prompt:'Review sources',capabilities:[]});
    const value=assignedWorkspace(),resultId=modelUuid(812);
    value.revision=3;
    value.handoffs!.push({...value.handoffs![0],id:modelUuid(813),recipient_key:address,recipient_agent_id:agent,recipient_role:'research',recipient_name:'Research',status:'completed',result_entry_id:resultId});
    value.entries.push({...value.entries[1],id:resultId,revision:3,kind:'handoff_result',content:'Review the invented cardiac evidence',
      reply:{role:'research',agent_id:agent,agent_name:'Research',backend:'azure_gpt41',content:'Cardiac history and eligibility remain unconfirmed.',context_revision:1,citations:[]}});
    vi.mocked(workspaceApi.open).mockResolvedValue({identity,workspace:value,team:configured});
    await click('Open synthetic encounter');await chooseBot('Research');
    expect(container.querySelector('.team-messages')?.hasAttribute('hidden')).toBe(true);
    await click('Review Research result');
    expect(container.querySelector('.team-messages')?.hasAttribute('hidden')).toBe(false);
    expect(document.activeElement?.id).toBe(`turn-${resultId}`);
    const question=container.querySelector<HTMLTextAreaElement>('#team-question')!;question.focus();
    vi.mocked(workspaceApi.read).mockResolvedValue({...value,revision:4});
    await act(async()=>{await vi.advanceTimersByTimeAsync(5000);});
    expect(document.activeElement).toBe(question);
    expect(workspaceApi.ask).not.toHaveBeenCalled();expect(workspaceApi.retryHandoff).not.toHaveBeenCalled();
  });

  it("requires comparison when another client changes the notebook during a handoff", async () => {
    vi.useFakeTimers();
    const assigned = assignedWorkspace();
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: assigned, team });
    await click("Open synthetic encounter");
    await input("Jotted notes", "Keep my unsaved edit");
    const updated = structuredClone(assigned); updated.revision = 3;
    updated.entries.push({ ...fixture.entries[0], id: "other-note", revision: 3, kind: "scratchpad", content: "Another client's saved notebook" });
    vi.mocked(workspaceApi.read).mockResolvedValue(updated);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(container.textContent).toContain("saved notebook changed while your bot was working");
    expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")?.value).toBe("Keep my unsaved edit");
    expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")?.disabled).toBe(true);
  });

  it("reuses the exact retry key after an uncertain handoff retry", async () => {
    const assigned = assignedWorkspace();
    Object.assign(assigned.handoffs![0], { status: "failed", error_code: "model_unavailable" });
    vi.mocked(workspaceApi.open).mockResolvedValue({ identity, workspace: assigned, team });
    await click("Open synthetic encounter");
    await chooseBot("Chief");
    vi.mocked(workspaceApi.retryHandoff).mockRejectedValueOnce(new TypeError("private network detail"));
    vi.mocked(workspaceApi.read).mockResolvedValue(assigned);
    vi.mocked(modelWorkApi.resolve).mockImplementation(async(_,id,op)=>retryReceipt(op.body as import('./workspace-api').HandoffRetryInput,id,assigned.handoffs![0].id));
    await click("Retry Scribe draft");
    await click("Check saved result");
    expect(vi.mocked(modelWorkApi.resolve).mock.calls[0][2].body).toEqual(vi.mocked(workspaceApi.retryHandoff).mock.calls[0][3]);
    expect(workspaceApi.retryHandoff).toHaveBeenCalledOnce();
    expect(container.textContent).not.toContain("private network detail");
  });
});
