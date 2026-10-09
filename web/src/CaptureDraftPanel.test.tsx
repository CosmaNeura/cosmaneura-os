import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CaptureDraftPanel } from "./CaptureDraftPanel";
import { captureDraft, captureNoteTemplates, type CaptureDraft } from "./capture-notes-api";

vi.mock("./capture-notes-api", () => ({ captureDraft: vi.fn(), captureNoteTemplates: vi.fn(), saveCaptureDraft: vi.fn() }));
const workspace = "00000000-0000-4000-8000-000000000002";
const session = "00000000-0000-4000-8000-000000000003";
const source = "00000000-0000-4000-8000-000000000004";
const schema = `doctor_note_schema_${"0".repeat(25)}1`;
const identity = { mode: "clerk_jwt" as const, getToken: vi.fn() };
const empty: CaptureDraft = { session_id: session, scribe_source_id: source, source_sha256: "a".repeat(64), schema_ref: schema,
  status: "not_prepared", note_type: "Visit note", transcript_ref: null, note_ref: null, fields: null, field_order: null,
  note_sha256: null, created_at: null, review_required: true };
const saved: CaptureDraft = { ...empty, status: "draft", note_ref: "synthetic-note", transcript_ref: "synthetic-transcript",
  fields: { Plan: "Discuss sleep at follow-up.", CC: "Invented sleep visit" }, field_order: ["CC", "Plan"],
  note_sha256: "b".repeat(64), created_at: "2026-09-17T09:00:00Z" };
let root: Root, container: HTMLDivElement;
const button = (text: string) => [...container.querySelectorAll("button")].find(value => value.textContent === text)!;
async function click(text: string) { await act(async () => button(text).click()); }
async function mount() { await act(async () => root.render(<CaptureDraftPanel workspaceId={workspace} sessionId={session} sourceId={source} identity={identity} />)); }

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true }); vi.clearAllMocks();
  vi.mocked(captureNoteTemplates).mockResolvedValue([{ schema_ref: schema, note_type: "Visit note", field_names: ["CC", "Plan"] }]);
  vi.mocked(captureDraft).mockResolvedValue(empty);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

it("checks for a saved draft and requires explicit preparation", async () => {
  await mount();
  expect(captureDraft).toHaveBeenCalledTimes(1);
  expect(vi.mocked(captureDraft).mock.calls[0][5]).toBe("read");
  expect(container.textContent).not.toContain("Saved in Core");
  vi.mocked(captureDraft).mockResolvedValueOnce(saved);
  await click("Prepare draft note");
  expect(vi.mocked(captureDraft).mock.calls[1][5]).toBe("prepare");
  expect(container.textContent).toContain("Saved in Core · clinical review required");
  expect([...container.querySelectorAll("h4")].map(item => item.textContent)).toEqual(["CC", "Plan"]);
  expect(button("Prepare draft note")).toBeUndefined();
});

it("reopens an existing draft without regeneration", async () => {
  vi.mocked(captureDraft).mockResolvedValueOnce(saved);
  await mount();
  expect(container.textContent).toContain("Invented sleep visit");
  expect(vi.mocked(captureDraft).mock.calls.map(call => call[5])).toEqual(["read"]);
});

it('opens the simple saved-recording note ready to edit and preserves explicit preparation',async()=>{
  await act(async()=>root.render(<CaptureDraftPanel workspaceId={workspace} sessionId={session} sourceId={source} identity={identity} simpleFlow/>));
  expect(vi.mocked(captureDraft).mock.calls.map(call=>call[5])).toEqual(['read']);
  expect(button('Create visit note')).toBeDefined();
  vi.mocked(captureDraft).mockResolvedValueOnce(saved);
  await click('Create visit note');
  expect(container.querySelectorAll('textarea')).toHaveLength(2);
  expect(button('Save visit note').disabled).toBe(true);
  expect(button('Edit draft')).toBeUndefined();
  expect(button('Check saved draft')).toBeUndefined();
});

it("checks saved work after a lost response before offering generation again", async () => {
  await mount();
  vi.mocked(captureDraft).mockRejectedValueOnce(new Error("private upstream detail"));
  await click("Prepare draft note");
  expect(container.textContent).not.toContain("private upstream detail");
  expect(button("Prepare draft note")).toBeUndefined();
  vi.mocked(captureDraft).mockResolvedValueOnce(saved);
  await click("Check saved draft");
  expect(container.textContent).toContain("Saved in Core");
  expect(vi.mocked(captureDraft).mock.calls.map(call => call[5])).toEqual(["read", "prepare", "read"]);
});

it("does not start generation when no provider template exists", async () => {
  vi.mocked(captureNoteTemplates).mockResolvedValueOnce([]);
  await mount();
  expect(captureDraft).not.toHaveBeenCalled();
  expect(container.textContent).toContain("No note templates are available");
});

it("selects the unique SOAP template and sends the exact saved notes and bot identity only on preparation", async () => {
  const entry = "00000000-0000-4000-8000-000000000005";
  const taskBot = {selection: {address: "scribe", team_revision: 2}, name: "Visit partner", enabled: true, includeNotebook: true};
  vi.mocked(captureNoteTemplates).mockResolvedValueOnce([
    {schema_ref: schema + "other", note_type: "Letter", field_names: ["Text"]},
    {schema_ref: schema, note_type: "SOAP note", field_names: ["CC", "Plan"]},
  ]);
  const render = (dirty: boolean) => root.render(<CaptureDraftPanel workspaceId={workspace} sessionId={session} sourceId={source} identity={identity}
    scratchpad={{id: entry, revision: 4}} notebookDirty={dirty} taskBot={taskBot} />);
  await act(async () => render(true));
  expect(container.querySelector("select")?.value).toBe(schema);
  expect(button("Prepare draft note").disabled).toBe(true);
  expect(vi.mocked(captureDraft).mock.calls[0][7]).toBe(entry);
  expect(vi.mocked(captureDraft).mock.calls[0][8]).toBeUndefined();
  await act(async () => render(false));
  vi.mocked(captureDraft).mockResolvedValueOnce({...saved, notebook_source: {
    kind: "clinician_scratch_notes", workspace_id: workspace, entry_id: entry, revision: 4, content_sha256: "c".repeat(64)}});
  await click("Prepare draft note");
  expect(vi.mocked(captureDraft).mock.calls.at(-1)?.slice(7)).toEqual([entry, taskBot.selection]);
  expect(container.textContent).toContain("saved scratch notes (revision 4)");
});

it("retains an earlier draft when notes change and requires deliberate preparation of the next version", async () => {
  const entry = "00000000-0000-4000-8000-000000000005";
  vi.mocked(captureDraft).mockResolvedValueOnce({...saved, notebook_source: {
    kind: "clinician_scratch_notes", workspace_id: workspace, entry_id: entry, revision: 2, content_sha256: "c".repeat(64)}});
  const render = (id: string) => root.render(<CaptureDraftPanel workspaceId={workspace} sessionId={session} sourceId={source} identity={identity}
    scratchpad={{id, revision: id === entry ? 2 : 3}} />);
  await act(async () => render(entry));
  await act(async () => render("00000000-0000-4000-8000-000000000006"));
  expect(container.textContent).toContain("Invented sleep visit");
  expect(captureDraft).toHaveBeenCalledTimes(1);
  expect(button("Prepare new draft from saved notes")).toBeTruthy();
});
