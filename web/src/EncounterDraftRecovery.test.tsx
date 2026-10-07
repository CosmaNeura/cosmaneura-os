import { settingsNavigation } from "./settings-test-navigation";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { applyPreset } from "./team-setup-request";
import { catalogFixture, teamUuid } from "./team-setup-test-fixture";
import { teamFixture } from "./team-setup-test-fixture";
import { EncounterWorkspace } from "./EncounterWorkspace";
import { DraftStoreError, type DraftRecord, type DraftStore } from "./draft-store";
import { workspaceApi, WorkspaceApiError, type ProviderTeam, type Workspace } from "./workspace-api";

vi.mock("./team-setup-api", async () => {
  const {WorkspaceApiError}=await import("./workspace-api");
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};
});

vi.mock("./workspace-api", async original => {
  const actual = await original<typeof import("./workspace-api")>();
  return { ...actual, workspaceApi: { ...actual.workspaceApi, privateDrafts:vi.fn(), practiceWorkItem:vi.fn().mockRejectedValue(new Error("Unavailable fixture")), open: vi.fn(), catalog: vi.fn(), team: vi.fn(),
    read: vi.fn(), append: vi.fn(), saveTeam: vi.fn(), saveNote: vi.fn(), decideFollowUp: vi.fn(), completeFollowUp: vi.fn() } };
});
// Namespace hashing and encryption are exercised by private-drafts.test.ts and
// the real runtime trial; this suite isolates the React recovery decisions.
vi.mock("./draft-store", async original => ({...await original<typeof import("./draft-store")>(),
  privateDraftScope: async (scope: string) => scope}));
const access = { mode: "clerk_jwt" as const, getToken: async () => "invented-token-never-stored" };
const workspace: Workspace & {appointment_id:string} = { id: "00000000-0000-4000-8000-000000000021", appointment_id: "00000000-0000-4000-8000-000000000022",
  label: "Invented recovery encounter", revision: 1, entries: [], work_candidates: [] };
const team: ProviderTeam = teamFixture();
let root: Root, element: HTMLDivElement;
let records: Map<string,DraftRecord>, failPending: boolean;
const factory = async ({scope}:{scope:string}): Promise<DraftStore> => {
  let closed=false;
  return { close:()=>{closed=true;}, read:async id=>{if(closed)throw new DraftStoreError("unavailable");return structuredClone(records.get(scope+id)??{revision:null,value:null});},
    write:async(id,expected,value)=>{
      if(closed)throw new DraftStoreError("unavailable");
      if(failPending && (value?.body as {pending:unknown}|undefined)?.pending){failPending=false;throw new DraftStoreError("unavailable");}
      const prior=records.get(scope+id)??{revision:null,value:null};
      if(prior.revision!==expected)throw new DraftStoreError("conflict");
      const saved={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(scope+id,saved);return saved;
    }};
};
async function click(text:string) {
  const button=[...element.querySelectorAll("button")].find(b=>!b.closest('[hidden]')&&(b.textContent?.replace("↗","").trim()===text||[...b.querySelectorAll("strong")].some(label=>label.textContent?.trim()===text)));
  expect(button, text).toBeTruthy();expect(button!.disabled,text).toBe(false);
  await act(async()=>{button!.click();});
}
async function input(selector:string,value:string) {
  const field=element.querySelector<HTMLTextAreaElement>(selector)!;
  expect(field).toBeTruthy();expect(field.disabled).toBe(false);
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(field,value);
    field.dispatchEvent(new Event("input",{bubbles:true}));});
}
async function mount() {root=createRoot(element);await act(async()=>root.render(<EncounterWorkspace authenticated={access} draftStorage={factory}/>));}
async function open() {await click("Visits and notes");await act(async()=>element.querySelector<HTMLButtonElement>(".team-encounter-option")!.click());}
async function restart() {await act(async()=>root.unmount());await mount();}
const notebookRecord=()=>[...records.entries()].find(([key])=>key.endsWith(`workspace:${workspace.id}`))?.[1];
function savedNote(content:string): Workspace { return {...workspace,revision:2,entries:[{id:"invented-entry",revision:2,kind:"scratchpad",content,source_label:null,origin:"human",ticket:null,created_at:"2026-09-21T12:00:00Z"}]}; }

beforeEach(async()=>{
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);vi.clearAllMocks();
  records=new Map();failPending=false;element=document.createElement("div");document.body.append(element);
  vi.mocked(workspaceApi.catalog).mockResolvedValue([{appointment_id:workspace.appointment_id,workspace_id:workspace.id,label:workspace.label}]);
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace,team});
  vi.mocked(workspaceApi.team).mockResolvedValue(team);vi.mocked(workspaceApi.read).mockResolvedValue(workspace);
  vi.mocked(workspaceApi.privateDrafts).mockResolvedValue({contract_version:1,drafts:[],has_more:false});
  await mount();
});
afterEach(async()=>{await act(async()=>root.unmount());element.remove();vi.unstubAllGlobals();});

it("offers stored drafts after remount without submitting them and restores exact text",async()=>{
  await open();await input("#team-notebook","Invented unsaved note across interruption");
  expect((notebookRecord()?.value?.body as {note:string}).note).toContain("across interruption");
  await restart();await open();expect(element.textContent).toContain("A notebook draft is saved on this device");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("");
  expect(workspaceApi.append).not.toHaveBeenCalled();await click("Restore notebook draft");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("Invented unsaved note across interruption");
  const result=savedNote("Invented unsaved note across interruption");
  vi.mocked(workspaceApi.append).mockResolvedValue({workspace:result,entry_id:"invented-entry",entry_revision:2});
  await click("Save notebook revision");expect(notebookRecord()?.value).toBeNull();
});

it("persists the exact request before sending and recovers a lost reply only through explicit retry",async()=>{
  await open();await input("#team-notebook","Invented save with unknown result");
  vi.mocked(workspaceApi.append).mockImplementationOnce(async(_identity,_id,body)=>{
    expect((notebookRecord()?.value?.body as {pending:{body:unknown}}).pending.body).toEqual(body);
    throw new WorkspaceApiError(503);
  });
  await click("Save notebook revision");const original=structuredClone(vi.mocked(workspaceApi.append).mock.calls[0][2]);
  const result=savedNote(original.content);
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:result,team});
  vi.mocked(workspaceApi.read).mockResolvedValue(result);
  await restart();await open();expect(workspaceApi.append).toHaveBeenCalledTimes(1);
  expect(element.textContent).toContain("Its last save is unconfirmed");
  expect([...element.querySelectorAll("button")].some(b=>b.textContent==="Discard local draft")).toBe(false);
  await click("Restore notebook draft");expect(workspaceApi.append).toHaveBeenCalledTimes(1);
  vi.mocked(workspaceApi.append).mockResolvedValue({workspace:result,entry_id:"invented-entry",entry_revision:2});
  await click("Retry same save");expect(vi.mocked(workspaceApi.append).mock.calls[1][2]).toEqual(original);
  expect(notebookRecord()?.value).toBeNull();
});

it("never sends an operation when its durable journal cannot be written",async()=>{
  await open();await input("#team-notebook","Keep this if local persistence fails");failPending=true;
  await click("Save notebook revision");expect(workspaceApi.append).not.toHaveBeenCalled();
  expect(element.textContent).toContain("The request was not sent");
  await click("Recheck draft recovery");await click("Restore notebook draft");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("Keep this if local persistence fails");
});

it("requires comparison when saved history changed while the device was closed",async()=>{
  await open();await input("#team-notebook","Older invented local draft");
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:savedNote("Newer server note"),team});
  vi.mocked(workspaceApi.read).mockResolvedValue(savedNote("Newer server note"));
  await restart();await open();await click("Restore notebook draft");
  expect(element.textContent).toContain("Your text has not been overwritten");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("Older invented local draft");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.disabled).toBe(true);
  expect(workspaceApi.append).not.toHaveBeenCalled();
});

it("recovers standalone team settings without creating a notebook",async()=>{
  await settingsNavigation(element).practice();await input(".team-practice-editor textarea","Invented unfinished setup");
  await restart();await settingsNavigation(element).practice();await click("Restore team draft");
  expect(element.querySelector<HTMLTextAreaElement>(".team-practice-editor textarea")!.value).toBe("Invented unfinished setup");
  expect(workspaceApi.open).not.toHaveBeenCalled();expect(workspaceApi.saveTeam).not.toHaveBeenCalled();
});

it("clears the view on access loss and cannot recover another owner's drafts",async()=>{
  await open();await input("#team-notebook","Private invented owner A text");
  vi.mocked(workspaceApi.read).mockRejectedValueOnce(new WorkspaceApiError(403));
  await click("Refresh encounter");expect(element.textContent).toContain("Private content has been cleared");
  const newOwnerTeam={...team,recovery_scope:"b".repeat(64)};
  vi.mocked(workspaceApi.team).mockResolvedValue(newOwnerTeam);
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace,team:newOwnerTeam});
  await restart();
  await open();expect(element.textContent).not.toContain("Restore notebook draft");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toBe("");
  expect(JSON.stringify([...records.values()])).not.toContain("invented-token-never-stored");
});

it("rechecks encounter access when restoring an offered draft",async()=>{
  await open();await input("#team-notebook","Do not reveal this after revocation");
  await restart();await open();
  vi.mocked(workspaceApi.read).mockRejectedValueOnce(new WorkspaceApiError(403));
  await click("Restore notebook draft");
  expect(element.querySelector("#team-notebook")).toBeNull();
  expect(element.textContent).not.toContain("Do not reveal this after revocation");
  expect(element.textContent).toContain("Private content has been cleared");
  expect(notebookRecord()?.value).not.toBeNull();
});

it("recovers private editor text and its parent save as one exact retry after remount",async()=>{
  await open();await click("Review");await input("#private-note-text","Invented clinical editor recovery");
  vi.mocked(workspaceApi.saveNote).mockRejectedValueOnce(new WorkspaceApiError(503));
  await click("Save note version");const body=structuredClone(vi.mocked(workspaceApi.saveNote).mock.calls[0][2]);
  await restart();await open();expect(workspaceApi.saveNote).toHaveBeenCalledTimes(1);
  await click("Restore private note save");await click("Restore private note draft");
  expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe(body.content);
  const saved={id:"invented-note",version:1,workspace_revision:2,content:body.content,content_hash:"a".repeat(64),source_reply_id:null,
    source_revision:1,source_fingerprint:"b".repeat(64),sources_changed:false,review:null,created_at:"2026-09-21T10:00:00Z"};
  const result={...workspace,revision:2,note:{latest:saved,history:[saved]}};
  vi.mocked(workspaceApi.saveNote).mockResolvedValue({workspace:result,entry_revision:2});
  await click("Retry same save");expect(vi.mocked(workspaceApi.saveNote).mock.calls[1][2]).toEqual(body);
  expect(notebookRecord()?.value).toBeNull();
  expect([...records.entries()].find(([key])=>key.endsWith(`editor:${workspace.id}:private-note`))?.[1].value).toBeNull();
});

it("clears all private editor content if access is revoked after an editor recovery offer",async()=>{
  await open();await click("Review");await input("#private-note-text","Keep private after revocation");
  await restart();await open();await click("Review");vi.mocked(workspaceApi.read).mockRejectedValueOnce(new WorkspaceApiError(403));
  await click("Restore private note draft");expect(element.querySelector("#private-note-text")).toBeNull();
  expect(element.textContent).toContain("Private content has been cleared");
  expect(element.textContent).not.toContain("Keep private after revocation");
});

it("refuses an older backend without recovery scope and never opens unjournaled editors",async()=>{
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace,team:{...team,recovery_scope:undefined}});
  await open();
  expect(element.querySelector("#team-notebook")).toBeNull();
  expect(element.querySelector("#private-note-text")).toBeNull();
  expect(element.textContent).toContain("Existing drafts are retained");
  expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.saveNote).not.toHaveBeenCalled();
});

it("retains notebook and clinical drafts when recovery scope disappears, then restores after recheck",async()=>{
  await open();await input("#team-notebook","Retained notebook while the backend is older");
  await click("Review");
  await input("#private-note-text","Retained clinical draft while the backend is older");
  const before=structuredClone([...records]);
  vi.mocked(workspaceApi.team).mockResolvedValue({...team,recovery_scope:undefined});
  await click("Refresh encounter");
  await click("Notebook");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.disabled).toBe(true);
  expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.disabled).toBe(true);
  expect([...records]).toEqual(before);
  vi.mocked(workspaceApi.team).mockResolvedValue(team);
  await click("Recheck draft recovery");await click("Restore notebook draft");
  expect(element.querySelector<HTMLTextAreaElement>("#team-notebook")!.value).toContain("Retained notebook");
  await click("Review");await click("Restore private note draft");
  expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toContain("Retained clinical draft");
  expect(workspaceApi.append).not.toHaveBeenCalled();expect(workspaceApi.saveNote).not.toHaveBeenCalled();
});

it("rechecks a missing-scope team response without discarding the pending save or changing its key",async()=>{
  await settingsNavigation(element).practice();await input(".team-practice-editor textarea","Keep the exact team request");
  vi.mocked(workspaceApi.saveTeam).mockResolvedValueOnce({...team,revision:2,recovery_scope:undefined});
  await settingsNavigation(element).save();
  const original=structuredClone(vi.mocked(workspaceApi.saveTeam).mock.calls[0][1]);
  expect(element.textContent).toContain("previous save is unconfirmed");
  expect([...element.querySelectorAll("button")].find(button=>button.textContent==="Retry same save")?.disabled).toBe(true);
  vi.mocked(workspaceApi.team).mockResolvedValue({...team,revision:2});
  await click("Recheck draft recovery");
  expect(workspaceApi.saveTeam).toHaveBeenCalledTimes(1);
  vi.mocked(workspaceApi.saveTeam).mockResolvedValue({...team,revision:2,configuration:original.configuration});
  await click("Retry same save");
  expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1]).toEqual(original);
  expect([...records.entries()].find(([key])=>key.endsWith("team"))?.[1].value).toBeNull();
});

it("rejects a changed private owner scope without copying existing drafts into it",async()=>{
  await open();await input("#team-notebook","Private owner A remains in its own journal");
  const before=structuredClone([...records]);
  vi.mocked(workspaceApi.team).mockResolvedValue({...team,recovery_scope:"b".repeat(64)});
  await click("Refresh encounter");
  expect(element.querySelector("#team-notebook")).toBeNull();
  expect(element.textContent).toContain("Private content has been cleared");
  expect([...records]).toEqual(before);
});

const followUp = {
  ticket_id:"00000000-0000-4000-8000-000000000031",revision_id:"00000000-0000-4000-8000-000000000032",
  payload_hash:"c".repeat(64),create_key:"invented-follow-up",state:"pending_approval",body:"Invented selected message",
  due_date:"2026-10-01",expected_outcome:"Invented confirmed result",owner_id:"invented-owner",note_version:1,
  source_changed:false,operation_status:null,receipts:[],
};
async function checkFollowUp(label:string) {
  const holder=[...element.querySelectorAll("label")].find(value=>value.textContent?.includes(label))!;
  const field=holder.querySelector<HTMLInputElement>("input")!;
  expect(field.disabled).toBe(false);await act(async()=>field.click());
}
it.each(["approve","reject"] as const)("journals and explicitly retries the exact %s decision through remount",async choice=>{
  const initial={...workspace,follow_ups:[followUp]};
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:initial,team});
  vi.mocked(workspaceApi.read).mockResolvedValue(initial);
  await open();await click("Work");
  vi.mocked(workspaceApi.decideFollowUp).mockImplementationOnce(async(_identity,_workspace,_ticket,body)=>{
    expect((notebookRecord()?.value?.body as {pending:unknown}).pending).toEqual({type:"followUpDecision",ticketId:followUp.ticket_id,body});
    throw new WorkspaceApiError(503);
  });
  if(choice==="approve") await checkFollowUp("I approve this exact");
  await click(choice==="approve"?"Approve local delivery":"Dismiss proposal");
  expect(workspaceApi.decideFollowUp).toHaveBeenCalledOnce();
  const original=[access,...structuredClone(vi.mocked(workspaceApi.decideFollowUp).mock.calls[0].slice(1))];
  expect(original[3]).toEqual({revision_id:followUp.revision_id,payload_hash:followUp.payload_hash,choice});
  const result={...workspace,revision:2,follow_ups:[{...followUp,state:choice==="approve"?"sent":"rejected"}]};
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:result,team});vi.mocked(workspaceApi.read).mockResolvedValue(result);
  await restart();await open();await click("Restore follow-up request");
  expect(workspaceApi.decideFollowUp).toHaveBeenCalledTimes(1);
  expect(element.querySelector('.team-content')?.getAttribute('data-mobile-panel')).toBe('Work');
  vi.mocked(workspaceApi.decideFollowUp).mockResolvedValue({workspace:result,entry_revision:2});
  await click("Retry same save");expect(vi.mocked(workspaceApi.decideFollowUp).mock.calls[1]).toEqual(original);
  expect(notebookRecord()?.value).toBeNull();expect(workspaceApi.completeFollowUp).not.toHaveBeenCalled();
});

it("journals completion evidence before dispatch and restores its exact key without recording another result",async()=>{
  const initial={...workspace,follow_ups:[{...followUp,state:"sent"}]};
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:initial,team});
  vi.mocked(workspaceApi.read).mockResolvedValue(initial);
  await open();await click("Work");
  await input('.team-follow-up-card textarea',"Invented outcome checked by the provider.");
  await checkFollowUp("I checked that the expected result");
  vi.mocked(workspaceApi.completeFollowUp).mockImplementationOnce(async(_identity,_workspace,_ticket,body)=>{
    expect((notebookRecord()?.value?.body as {pending:unknown}).pending).toEqual({type:"followUpComplete",ticketId:followUp.ticket_id,body});
    throw new WorkspaceApiError(503);
  });
  await click("Record completion");expect(workspaceApi.completeFollowUp).toHaveBeenCalledOnce();
  const original=[access,...structuredClone(vi.mocked(workspaceApi.completeFollowUp).mock.calls[0].slice(1))];
  expect(original[3]).toMatchObject({revision_id:followUp.revision_id,payload_hash:followUp.payload_hash,evidence:"Invented outcome checked by the provider.",idempotency_key:expect.any(String)});
  const result={...workspace,revision:2,follow_ups:[{...followUp,state:"closed"}]};
  vi.mocked(workspaceApi.open).mockResolvedValue({identity:access,workspace:result,team});vi.mocked(workspaceApi.read).mockResolvedValue(result);
  await restart();await open();await click("Restore follow-up request");
  expect(workspaceApi.completeFollowUp).toHaveBeenCalledTimes(1);
  vi.mocked(workspaceApi.completeFollowUp).mockResolvedValue({workspace:result,entry_revision:2});
  await click("Retry same save");expect(vi.mocked(workspaceApi.completeFollowUp).mock.calls[1]).toEqual(original);
  expect(notebookRecord()?.value).toBeNull();
});


it("replays the exact historical team request, then displays the fresh paused team while preserving the independent notebook",async()=>{
  await open();await input("#team-notebook","Independent invented notebook draft");await settingsNavigation(element).practice();await input(".team-practice-editor textarea","First team change");
  vi.mocked(workspaceApi.saveTeam).mockRejectedValueOnce(new WorkspaceApiError(503));await settingsNavigation(element).save();
  const original=structuredClone(vi.mocked(workspaceApi.saveTeam).mock.calls[0][1]);
  const current=teamFixture(structuredClone(original.configuration),3);current.configuration.bots[0].enabled=false;
  vi.mocked(workspaceApi.team).mockResolvedValue(current);
  await restart();await settingsNavigation(element).practice();await click("Restore team draft");
  vi.mocked(workspaceApi.saveTeam).mockResolvedValue(teamFixture(original.configuration,2));await click("Retry same save");
  expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1]).toEqual(original);
  expect(element.textContent).toContain("Current team revision 3 is shown");expect(element.querySelector('.team-roster button')?.textContent).toContain('Paused');
  expect([...records.entries()].find(([key])=>key.endsWith('team'))?.[1].value).toBeNull();
  expect((notebookRecord()?.value?.body as {note:string}).note).toBe("Independent invented notebook draft");
});

it("retains the exact pending team save if its receipt succeeds but the required current-team read fails",async()=>{
  await settingsNavigation(element).practice();await input(".team-practice-editor textarea","Pending until current team is known");
  vi.mocked(workspaceApi.saveTeam).mockImplementation(async(_,body)=>teamFixture(body.configuration,body.expected_revision+1));
  vi.mocked(workspaceApi.team).mockRejectedValueOnce(new WorkspaceApiError(503));await settingsNavigation(element).save();
  const original=structuredClone(vi.mocked(workspaceApi.saveTeam).mock.calls[0][1]);
  expect(element.textContent).toContain('previous save is unconfirmed');
  expect((([...records.entries()].find(([key])=>key.endsWith('team'))?.[1].value?.body) as {pending:unknown}).pending).toEqual(original);
  const current=teamFixture(original.configuration,3);current.configuration.bots[0].blocked_capabilities=['model_answer'];vi.mocked(workspaceApi.team).mockResolvedValue(current);
  await click("Retry same save");expect(vi.mocked(workspaceApi.saveTeam).mock.calls[1][1]).toEqual(original);expect(element.querySelector('.team-roster button')?.textContent).toContain('AI answers blocked');
});

it("withholds private views after an unsupported new pending request without downgrading or deleting its encrypted record",async()=>{
  let n=1;const configuration=applyPreset(team.configuration,catalogFixture(),'front_desk',()=>teamUuid(n++));
  const pending={expected_revision:1,idempotency_key:'new-reviewed-pending',configuration,setup_review:{catalog_version:1 as const,configuration_sha256:'c'.repeat(64),prerequisites_sha256:'d'.repeat(64)}};
  const value={schema:1 as const,updatedAt:'2026-09-21T12:00:00Z',body:{kind:'team',baseRevision:1,configuration,pending}};
  records.set('a'.repeat(64)+'team',{revision:'1',value});
  await restart();
  await settingsNavigation(element).practice();await click('Restore team draft');vi.mocked(workspaceApi.saveTeam).mockRejectedValue(new WorkspaceApiError(426));await click('Retry same save');
  expect(vi.mocked(workspaceApi.saveTeam).mock.calls[0][1]).toEqual(pending);expect(element.querySelector('.team-settings')).toBeNull();expect(element.textContent).toContain('Update required');
  expect(records.get('a'.repeat(64)+'team')?.value).toEqual(value);
});
