import {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {EncounterWorkspace} from "./EncounterWorkspace";
import {readEncounterPrep, type EncounterPrep} from "./encounter-prep-api";
import {workspaceApi, type Workspace} from "./workspace-api";
import {modelWorkApi} from "./model-work-api";
import {teamFixture} from "./team-setup-test-fixture";
import {memoryDraftStorage} from "./draft-test-fixture";

vi.mock("./encounter-prep-api", () => ({ENCOUNTER_PREP_BUILD:true, readEncounterPrep:vi.fn()}));
vi.mock("./CapturePanel", () => ({CapturePanel:() => null}));
vi.mock("./team-setup-api", async () => {
  const {WorkspaceApiError}=await import("./workspace-api");
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404))}};
});
vi.mock("./draft-store", async original => ({...await original<typeof import("./draft-store")>(), privateDraftScope:async (scope:string)=>scope}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");
const identity={mode:"clerk_jwt" as const, getToken:async()=>"invented-owner"};
const workspace:Workspace={id:"00000000-0000-4000-8000-000000000071", appointment_id:"invented-visit",
  label:"Invented preparation encounter", revision:1, entries:[], work_candidates:[]};
const receipt:EncounterPrep={appointment_ref:"a".repeat(64), snapshot_sha256:"b".repeat(64), display_sha256:"c".repeat(64),
  additional_notes_available:false, sources:[{source_id:"d".repeat(64), appointment_ref:"e".repeat(64),
    kind:"generated_visit_note", label:"Prior draft", source_at:"2026-09-23T12:00:00Z", content_sha256:"f".repeat(64),
    content:"Invented saved preparation for review", truncated:false, content_redacted:false}]};
let host:HTMLDivElement, root:Root;
beforeEach(()=>{
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);vi.stubGlobal("crypto",webcrypto);
  vi.clearAllMocks();vi.mocked(readEncounterPrep).mockResolvedValue(receipt);
  vi.spyOn(workspaceApi,"catalog").mockResolvedValue([{appointment_id:workspace.appointment_id, workspace_id:workspace.id, label:workspace.label}]);
  vi.spyOn(workspaceApi,"ask");vi.spyOn(modelWorkApi,"resolve");
  host=document.createElement("div");document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();vi.unstubAllGlobals();});
function button(label:string) {return [...host.querySelectorAll<HTMLButtonElement>("button")].find(b=>b.textContent?.trim().startsWith(label));}
async function click(label:string) {
  expect(button(label),label).toBeTruthy();expect(button(label)!.disabled,label).toBe(false);
  await act(async()=>button(label)!.click());
}
async function open(includeEvidence=true, prepEnabled=true) {
  const team=teamFixture();team.capture={enabled:false, prep_enabled:prepEnabled};
  team.configuration.bots.find(bot=>bot.role==="visit_prep")!.include_evidence=includeEvidence;
  team.members.find(bot=>bot.role==="visit_prep")!.prompt="Review the saved preparation";
  vi.spyOn(workspaceApi,"open").mockResolvedValue({identity,workspace,team});
  vi.spyOn(workspaceApi,"team").mockResolvedValue(team);
  await act(async()=>root.render(<EncounterWorkspace authenticated={identity} draftStorage={memoryDraftStorage()}/>));
  await click("Choose an encounter");await click(workspace.label);
}
it("loads actual visit context without offering or dispatching the empty model shortcut",async()=>{
  await open();
  expect(host.querySelector(".team-conversation-empty")).toBeNull();
  expect(host.querySelector(".team-messages")?.hasAttribute("hidden")).toBe(true);
  expect(button("Review the saved preparation")).toBeUndefined();
  expect(readEncounterPrep).not.toHaveBeenCalled();
  await click("Review visit context");
  expect(readEncounterPrep).toHaveBeenCalledWith(workspace.id,identity,{address:"visit_prep",team_revision:1},expect.any(AbortSignal));
  expect(host.textContent).toContain(receipt.sources[0].content);
  expect(workspaceApi.ask).not.toHaveBeenCalled();expect(modelWorkApi.resolve).not.toHaveBeenCalled();
});
it("keeps the deliberate source action disabled when saved sources are excluded",async()=>{
  await open(false);expect(button("Review visit context")!.disabled).toBe(true);
  expect(button("Review the saved preparation")).toBeUndefined();
  expect(readEncounterPrep).not.toHaveBeenCalled();expect(modelWorkApi.resolve).not.toHaveBeenCalled();
});
it("preserves the normal saved-notebook starter when the Core preparation reader is unavailable",async()=>{
  await open(true,false);expect(button("Review visit context")).toBeUndefined();
  expect(button("Review the saved preparation")).toBeTruthy();
  expect(readEncounterPrep).not.toHaveBeenCalled();expect(modelWorkApi.resolve).not.toHaveBeenCalled();
});
