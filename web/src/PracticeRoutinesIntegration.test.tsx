import { settingsNavigation } from "./settings-test-navigation";
import {teamFixture} from "./team-setup-test-fixture";
import { memoryDraftStorage } from "./draft-test-fixture";
import {act} from "react";
import {createRoot} from "react-dom/client";
import {beforeEach,expect,it,vi} from "vitest";
import {EncounterWorkspace} from "./EncounterWorkspace";
import {workspaceApi,type ProviderTeam} from "./workspace-api";
import {brief,routine} from "./routine-test-fixture";
vi.mock("./team-setup-api", async () => {
  const {WorkspaceApiError}=await import("./workspace-api");
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};
});

vi.mock("./draft-store", async original => ({...await original<typeof import("./draft-store")>(), privateDraftScope:async (scope:string)=>scope}));
let draftStorage: ReturnType<typeof memoryDraftStorage>;
vi.mock("./workspace-api",async original=>({...await original<typeof import("./workspace-api")>(),workspaceApi:{
  team:vi.fn(),
  practiceWork:vi.fn(async()=>({items:[],people:[],next_cursor:null})),open:vi.fn(),catalog:vi.fn()}}));
vi.mock("./routine-api",async original=>({...await original<typeof import("./routine-api")>(),ROUTINES_BUILD:true,
  routineApi:{read:vi.fn(async()=>routine()),run:vi.fn(async()=>brief()),save:vi.fn()}}));
const fixture:ProviderTeam=teamFixture();
beforeEach(()=>{vi.clearAllMocks();draftStorage=memoryDraftStorage();vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(fixture));});
it("opens private briefs before selecting or writing any encounter",async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});const container=document.createElement("div");document.body.append(container);const root=createRoot(container);
  try {
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={{mode:"clerk_jwt",getToken:async()=>"invented.token.value"}}/>));
    await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent==="Practice work")!.click());
    await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});expect(container.textContent).toContain("Private work briefs");});expect(container.textContent).toContain("Work observed on 2026-09-21");
    expect(container.querySelector('[aria-label="Configure Provider Team"]')).not.toBeNull();
    expect(workspaceApi.team).toHaveBeenCalledTimes(3);expect(workspaceApi.open).not.toHaveBeenCalled();expect(workspaceApi.catalog).not.toHaveBeenCalled();
  }finally{await act(async()=>root.unmount());container.remove();}
});

it.each([false,true])("refreshes team authority from briefs and preserves edited settings (%s)",async edited=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});const container=document.createElement("div");document.body.append(container);const root=createRoot(container);
  const click=async(text:string)=>{let button:HTMLButtonElement|undefined;await vi.waitFor(async()=>{await act(async()=>{await Promise.resolve();});button=[...container.querySelectorAll("button")].find(b=>b.textContent===text||b.getAttribute("aria-label")===text);expect(button).toBeDefined();});await act(async()=>button!.click());};
  const context=()=>container.querySelector<HTMLTextAreaElement>(".team-practice-editor textarea")!;
  try{
    await act(async()=>root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={{mode:"clerk_jwt",getToken:async()=>"invented.token.value"}}/>));
    await click("Practice work");await settingsNavigation(container).practice();
    if(edited)await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(context(),"Keep my unfinished settings");context().dispatchEvent(new Event("input",{bubbles:true}));});
    await click("Practice work");
    vi.mocked(workspaceApi.team).mockResolvedValue({...fixture,revision:2,configuration:{...fixture.configuration,practice_context:"Saved by another client"}});
    await click("Refresh briefs");await settingsNavigation(container).practice();
    expect(context().value).toBe(edited?"Keep my unfinished settings":"Saved by another client");
    expect(context().disabled).toBe(edited);
    if(edited)expect(container.textContent).toContain("Unsaved settings are preserved");
    expect(workspaceApi.open).not.toHaveBeenCalled();expect(workspaceApi.catalog).not.toHaveBeenCalled();
  }finally{await act(async()=>root.unmount());container.remove();}
});
