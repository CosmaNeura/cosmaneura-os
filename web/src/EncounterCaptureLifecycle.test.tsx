import { memoryDraftStorage } from "./draft-test-fixture";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EncounterWorkspace } from "./EncounterWorkspace";
import { workspaceApi, type BotRole, type ProviderTeam, type Workspace } from "./workspace-api";
import { prepareCapture } from "./capture-api";
import { openCaptureRuntime, type CaptureRuntime } from "./capture-runtime";
import type { CaptureFlowSnapshot } from "../../clients/capture/src/flow/controller";

vi.mock("./team-setup-api", async () => {
  const {WorkspaceApiError}=await import("./workspace-api");
  return {teamSetupApi:{read:vi.fn().mockRejectedValue(new WorkspaceApiError(404)),rehearse:vi.fn()}};
});

vi.mock("./draft-store", async original => ({...await original<typeof import("./draft-store")>(), privateDraftScope:async (scope:string)=>scope}));
let draftStorage: ReturnType<typeof memoryDraftStorage>;
vi.mock("./workspace-api", async original => {
  const actual = await original<typeof import("./workspace-api")>();
  return { ...actual, workspaceApi: { ...actual.workspaceApi,
    catalog: vi.fn(), open: vi.fn(), append: vi.fn(), read: vi.fn(), team: vi.fn() } };
});
vi.mock("./capture-api", async original => ({ ...await original<object>(),
  CAPTURE_WORKSPACE_BUILD: true, CAPTURE_NOTES_BUILD: false, CAPTURE_CORRECTIONS_BUILD: false,
  CAPTURE_RECOVERY_BUILD: false, prepareCapture: vi.fn() }));
vi.mock("./capture-runtime", () => ({ openCaptureRuntime: vi.fn() }));

const roles: BotRole[] = ["scribe", "visit_prep", "follow_up", "chief"];
const names = ["Scribe", "Visit Prep", "Follow-up", "Chief"];
const identity = { boxId: "box-invented", actorId: "actor-invented" };
const authenticated = { mode: "clerk_jwt" as const, getToken: vi.fn() };
const team: ProviderTeam = {
  revision: 1, recovery_scope: "a".repeat(64), template_version: "provider-team-v1", llm: { enabled: false, model: "gpt-4.1" },
  capture: { enabled: true, notes_enabled: false },
  configuration: { practice_context: "DPC", bots: roles.map((role, index) => ({
    role, name: names[index], enabled: true, response_style: "brief", include_notebook: true, include_evidence: true })) },
  members: roles.map((role, index) => ({ role, agent_id: "agent-" + role, name: names[index],
    initials: names[index].slice(0, 2), description: "Invented role", prompt: "Review saved context", capabilities: [] })),
};
const visit = (number: number): Workspace => ({
  id: `00000000-0000-4000-8000-00000000000${number}`, appointment_id: `appointment-${number}`,
  label: `Invented visit ${number}`, revision: 1, entries: [], work_candidates: [],
});
const session = "00000000-0000-4000-8000-000000000003";
let root: Root, container: HTMLDivElement, runtime: CaptureRuntime, snapshot: CaptureFlowSnapshot;
let listener: ((value: CaptureFlowSnapshot) => void) | undefined;

beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks(); draftStorage = memoryDraftStorage();
  listener = undefined;
  vi.mocked(workspaceApi.catalog).mockResolvedValue([1, 2].map(number => ({
    appointment_id: `appointment-${number}`, workspace_id: null, label: `Invented visit ${number}` })));
  vi.mocked(workspaceApi.open).mockImplementation(async (_identity, appointment) => ({
    identity, workspace: visit(appointment === "appointment-2" ? 2 : 1), team: structuredClone(team) }));
  vi.mocked(workspaceApi.team).mockResolvedValue(structuredClone(team));
  vi.mocked(prepareCapture).mockImplementation(async workspace => ({ status: "prepared", workspace_id: workspace,
    session_id: session, consent_record_id: "00000000-0000-4000-8000-000000000004" }));
  snapshot = { state: "ready", statusCode: "ready", sessionId: session, recordedChunks: 0, queuedChunks: 0,
    elapsedSeconds: 0, remainingBudgetSeconds: 900, remainingAuthoritySeconds: 900,
    transcriptionStatus: null, transcript: null };
  runtime = { sourceKind: "synthetic", close: vi.fn().mockResolvedValue(undefined), controller: {
    get snapshot() { return snapshot; },
    subscribe: vi.fn(callback => { listener = callback; callback(snapshot); return () => { listener = undefined; }; }),
    startRecording: vi.fn(async () => { snapshot = { ...snapshot, state: "recording" }; listener?.(snapshot); }),
    stopRecording: vi.fn(async () => { snapshot = { ...snapshot, state: "processing", recordedChunks: 1 }; listener?.(snapshot); }),
    resumePendingWork: vi.fn(), acknowledgeGap: vi.fn(), finishInterruptedCapture: vi.fn(), refreshTranscriptionStatus: vi.fn(),
  } };
  vi.mocked(openCaptureRuntime).mockResolvedValue(runtime);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
  await act(async () => root.render(<EncounterWorkspace draftStorage={draftStorage} authenticated={authenticated} />));
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

async function click(label: string, scope: ParentNode = container) {
  const button = [...scope.querySelectorAll("button")].find(button =>
    button.getAttribute("aria-label") === label || button.textContent?.trim().startsWith(label));
  expect(button, label).toBeTruthy();
  expect(button!.disabled).toBe(false);
  await act(async () => button!.click());
}
async function open(number: number) {
  await click("Choose an encounter");
  await click(`Invented visit ${number}`, container.querySelector('[aria-label="Available encounters"]')!);
}
async function start() {
  await open(1);
  await click("Scribe", container.querySelector('[aria-label="Provider Team"]')!);
  await click("Record visit");
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  await click("Start synthetic capture");
}

it("keeps recording and scratch-note saving in the same encounter across notebook, bot and settings navigation", async () => {
  await start();
  const panel = container.querySelector('[aria-label="Scribe recording"]');
  const sharedWork = [...container.querySelectorAll("button")].find(button => button.textContent === "Practice work");
  expect(sharedWork?.disabled).toBe(true);
  await click("Scratch notes", panel!);
  expect(container.querySelector(".team-content")?.getAttribute("data-mobile-panel")).toBe("Notebook");
  const note = container.querySelector<HTMLTextAreaElement>("#team-notebook")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(note, "Invented observation during recording");
    note.dispatchEvent(new Event("input", { bubbles: true }));
  });
  vi.mocked(workspaceApi.append).mockImplementation(async (_identity, id, body) => ({
    entry_id: "saved-scratch", entry_revision: 2, workspace: { ...visit(1), id, revision: 2,
      entries: [{ id: "saved-scratch", revision: 2, kind: "scratchpad", content: body.content,
        source_label: null, origin: "provider", ticket: null, created_at: "2026-09-20T00:00:00Z" }] } }));
  await click("Save notebook revision");
  expect(workspaceApi.append).toHaveBeenCalledWith(identity, visit(1).id,
    expect.objectContaining({ kind: "scratchpad", content: "Invented observation during recording" }));
  await click("Chief", container.querySelector('[aria-label="Provider Team"]')!);
  await click("Configure Provider Team");
  await click("Done");
  await click("During", container.querySelector('[aria-label="Encounter stage"]')!);
  expect(container.querySelector('[aria-label="Scribe recording"]')).toBe(panel);
  expect(panel?.textContent).toContain("Recording");
  expect(runtime.close).not.toHaveBeenCalled();
  expect(openCaptureRuntime).toHaveBeenCalledTimes(1);
  expect(runtime.controller.startRecording).toHaveBeenCalledTimes(1);
  await click("Stop and upload", panel!);
  expect(runtime.controller.stopRecording).toHaveBeenCalledTimes(1);
  expect(panel?.textContent).toContain("Audio uploaded");
});

it("requires a new recording request after closing one encounter and opening another", async () => {
  await start();
  await click("Close notebook");
  expect(runtime.close).not.toHaveBeenCalled();
  await click("Keep editing");
  expect(runtime.close).not.toHaveBeenCalled();
  await click("Close notebook");
  await click("Close anyway");
  expect(runtime.close).toHaveBeenCalledTimes(1);
  await open(2);
  expect(prepareCapture).toHaveBeenCalledTimes(1);
  expect(openCaptureRuntime).toHaveBeenCalledTimes(1);
  expect(container.querySelector('[aria-label="Scribe recording"]')?.textContent).toContain("Consent first");
  expect(container.querySelector<HTMLTextAreaElement>("#team-notebook")?.value).toBe("");
  await click("Record visit", container.querySelector('[aria-label="Scribe recording"]')!);
  expect(prepareCapture).toHaveBeenCalledTimes(2);
  expect(vi.mocked(prepareCapture).mock.calls[1][0]).toBe(visit(2).id);
  expect(runtime.controller.startRecording).toHaveBeenCalledTimes(1);
});

it('opens a listed visit, confirms fresh consent and starts in two explicit actions with saved defaults', async () => {
  const {saveRecordingPreferences} = await import('./recording-preferences');
  saveRecordingPreferences(team.recovery_scope, {regions:'US-NY',language:'en-US'});
  vi.mocked(prepareCapture).mockRejectedValueOnce({code:'capture_consent_required'});
  await click('Choose an encounter'); // Meeting selection is available; no recorder has opened.
  await click('Record Invented visit 1'); // 1: Select the visit and prepare its consent screen.
  expect(runtime.controller.startRecording).not.toHaveBeenCalled();
  expect(container.querySelector('[aria-label="Recording consent"]')?.textContent).toContain('US-NY');
  expect(container.querySelector<HTMLDetailsElement>('.capture-options')?.open).toBe(false);
  await click('Confirm consent & record'); // 2: Fresh per-visit consent and recording.
  expect(prepareCapture).toHaveBeenLastCalledWith(visit(1).id, authenticated,
    expect.objectContaining({all_parties_consented:true,participant_regions:['US-NY']}),
    expect.any(String),undefined,expect.objectContaining({address:'scribe',team_revision:1}),undefined);
  expect(runtime.controller.startRecording).toHaveBeenCalledTimes(1);
  localStorage.clear();
});
