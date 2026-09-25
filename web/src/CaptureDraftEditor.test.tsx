import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CaptureDraftEditor } from "./CaptureDraftEditor";
import { captureDraft, saveCaptureDraft, type CaptureDraft } from "./capture-notes-api";

vi.mock("./capture-notes-api", () => ({captureDraft: vi.fn(), saveCaptureDraft: vi.fn()}));
const base: CaptureDraft = {session_id:"session", scribe_source_id:"source", source_sha256:"a".repeat(64),
  schema_ref:"schema", transcript_ref:"transcript", note_ref:"note-one", status:"draft", note_type:"Visit",
  fields:{CC:"Invented visit", Plan:"Initial discussion"}, field_order:["CC","Plan"],
  note_sha256:"b".repeat(64), created_at:"2026-09-17T10:00:00Z", review_required:true};
const corrected: CaptureDraft = {...base, note_ref:"note-two", fields:{...base.fields, Plan:"My synthetic correction"}, note_sha256:"c".repeat(64)};
const identity = {mode:"clerk_jwt" as const, getToken:vi.fn()};
const onLock = vi.fn();
let root:Root, container:HTMLDivElement;
const button = (text:string) => [...container.querySelectorAll("button")].find(value => value.textContent === text)!;
async function click(text:string) { await act(async () => button(text).click()); }
const plan = () => container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Draft Plan"]')!;
async function input(value:string) { await act(async () => {
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(plan(),value);
  plan().dispatchEvent(new Event("input",{bubbles:true}));
}); }
beforeEach(async () => {
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true}); vi.clearAllMocks();
  vi.mocked(captureDraft).mockResolvedValue(base); vi.mocked(saveCaptureDraft).mockResolvedValue(corrected);
  container=document.createElement("div"); document.body.append(container); root=createRoot(container);
  await act(async () => root.render(<CaptureDraftEditor initial={base} workspaceId="workspace" identity={identity} onLock={onLock} />));
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });

it("edits only on request and saves against the exact opened version", async () => {
  expect(container.querySelector("textarea")).toBeNull();
  await click("Edit draft"); expect(button("Save draft edits").disabled).toBe(true);
  await input("My synthetic correction"); expect(onLock).toHaveBeenLastCalledWith(true);
  await click("Save draft edits");
  expect(saveCaptureDraft).toHaveBeenCalledWith("workspace",identity,base,corrected.fields,expect.any(String),expect.any(AbortSignal));
  expect(container.textContent).toContain("Your text is saved in Core");
  expect(button("Save draft edits").disabled).toBe(true);
  expect(onLock).toHaveBeenLastCalledWith(false);
});

it("recovers a lost save reply without discarding text or saving twice", async () => {
  await click("Edit draft"); await input("My synthetic correction");
  vi.mocked(saveCaptureDraft).mockRejectedValueOnce(new Error("private upstream sentinel"));
  await click("Save draft edits");
  expect(plan().value).toBe("My synthetic correction"); expect(plan().disabled).toBe(true);
  expect(container.textContent).not.toContain("private upstream sentinel");
  vi.mocked(captureDraft).mockResolvedValueOnce(corrected);
  await click("Check saved draft");
  expect(saveCaptureDraft).toHaveBeenCalledTimes(1);
  expect(plan().value).toBe("My synthetic correction"); expect(plan().disabled).toBe(false);
  expect(container.textContent).toContain("Your text is saved in Core");
});

it("retains the same request key when a checked save must be retried", async () => {
  await click("Edit draft"); await input("My synthetic correction");
  vi.mocked(saveCaptureDraft).mockRejectedValueOnce(new Error("unconfirmed"));
  await click("Save draft edits"); await click("Check saved draft"); await click("Save draft edits");
  expect(vi.mocked(saveCaptureDraft).mock.calls[0][4]).toBe(vi.mocked(saveCaptureDraft).mock.calls[1][4]);
});

it("preserves local text and requires a deliberate choice after another save", async () => {
  await click("Edit draft"); await input("My synthetic correction");
  const other = {...corrected,fields:{...base.fields, Plan:"Other saved correction"}};
  vi.mocked(captureDraft).mockResolvedValueOnce(other);
  await click("Check saved draft");
  expect(plan().value).toBe("My synthetic correction"); expect(plan().disabled).toBe(true);
  expect(saveCaptureDraft).not.toHaveBeenCalled();
  await click("Keep my text for next version"); await click("Save draft edits");
  expect(vi.mocked(saveCaptureDraft).mock.calls[0][2]).toEqual(other);
  expect(vi.mocked(saveCaptureDraft).mock.calls[0][3]).toEqual(corrected.fields);
});

it("blocks saving when the source has changed and retains the editor", async () => {
  await click("Edit draft"); await input("My synthetic correction");
  vi.mocked(captureDraft).mockResolvedValueOnce({...base,source_sha256:"d".repeat(64)});
  await click("Check saved draft");
  expect(plan().value).toBe("My synthetic correction"); expect(button("Save draft edits").disabled).toBe(true);
  expect(container.textContent).toContain("recording source changed");
});

it("links only the saved Core version and blocks review of unsaved or uncertain edits", async () => {
  const onReviewDraft = vi.fn();
  await act(async () => root.render(<CaptureDraftEditor initial={base} workspaceId="workspace" identity={identity}
    onLock={onLock} onReviewDraft={onReviewDraft} />));
  await click("Use saved draft for review");
  expect(onReviewDraft).toHaveBeenLastCalledWith(base);
  await click("Edit draft"); await input("My synthetic correction");
  expect(button("Use saved draft for review").disabled).toBe(true);
  vi.mocked(saveCaptureDraft).mockRejectedValueOnce(new Error("unconfirmed"));
  await click("Save draft edits");
  expect(button("Use saved draft for review").disabled).toBe(true);
  vi.mocked(captureDraft).mockResolvedValueOnce(corrected);
  await click("Check saved draft"); await click("Use saved draft for review");
  expect(onReviewDraft).toHaveBeenLastCalledWith(corrected);
  expect(onReviewDraft).toHaveBeenCalledTimes(2);
});

it("requires an explicit discard before leaving a local edit whose source changed", async () => {
  const reload=vi.fn(),observed=vi.fn();
  await act(async()=>root.render(<CaptureDraftEditor initial={base} workspaceId="workspace" identity={identity}
    onLock={onLock} onCurrentDraft={observed} onReloadSource={reload}/>));
  await click("Edit draft");await input("Retain my local note wording.");
  const changed={...base,status:"not_prepared" as const,source_sha256:"f".repeat(64),note_ref:null,fields:null,field_order:null,note_sha256:null,created_at:null};
  vi.mocked(captureDraft).mockResolvedValueOnce(changed);await click("Check saved draft");
  expect(plan().value).toBe("Retain my local note wording.");expect(reload).not.toHaveBeenCalled();
  expect(observed).toHaveBeenLastCalledWith(changed);
  await click("Discard local edits and reload source");expect(reload).toHaveBeenCalledTimes(1);
});
