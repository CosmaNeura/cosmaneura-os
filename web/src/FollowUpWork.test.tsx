import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FollowUpWork } from "./FollowUpWork";
import type { FollowUp, Workspace } from "./workspace-api";

const note = { id: "note-one", version: 1, workspace_revision: 2, content: "Private note must stay private.",
  content_hash: "a".repeat(64), source_reply_id: null, source_revision: 1, source_fingerprint: "b".repeat(64),
  sources_changed: false, review: {id: "review", reviewer_id: "human", created_at: "2026-09-16T12:00:00Z"}, created_at: "2026-09-16T12:00:00Z" };
const initial: Workspace = { id: "workspace", appointment_id: "appointment", label: "Invented person", revision: 3,
  entries: [], work_candidates: [], follow_ups: [], note: {latest: note, history: [note]} };
const item: FollowUp = {ticket_id: "ticket", revision_id: "revision", payload_hash: "c".repeat(64), create_key: "saved-key",
  state: "pending_approval", body: "Selected invented message", due_date: "2026-10-01", expected_outcome: "Confirm next visit",
  owner_id: "human", note_version: 1, source_changed: false, operation_status: null, receipts: []};

describe("follow-up work", () => {
  let root: Root; let container: HTMLDivElement;
  const onSave = vi.fn(); const onReview = vi.fn();
  async function render(w = initial, locked = false) {
    await act(async () => root.render(<FollowUpWork workspace={w} locked={locked} onSave={onSave} onReview={onReview} />));
  }
  beforeEach(async () => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); vi.clearAllMocks();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container); await render();
  });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
  const button = (name: string) => [...container.querySelectorAll("button")].find(b => b.textContent === name)!;
  async function click(name: string) { await act(async () => button(name).click()); }
  async function input(label: string, value: string) {
    const holder = [...container.querySelectorAll("label")].find(e => e.textContent?.startsWith(label))!;
    const element = holder.querySelector("textarea,input") as HTMLTextAreaElement | HTMLInputElement;
    const prototype = element.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    await act(async () => { Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event("input", {bubbles: true})); });
  }
  async function check(label: string) {
    const holder = [...container.querySelectorAll("label")].find(e => e.textContent?.includes(label))!;
    await act(async () => holder.querySelector<HTMLInputElement>("input")!.click());
  }

  it("requires a current reviewed note and keeps private note text out of the proposal", async () => {
    expect(container.textContent).not.toContain(note.content);
    expect(container.querySelector("textarea")!.value).toBe("");
    await render({...initial, note: {latest: {...note, review: null}, history: []}});
    expect(button("Save follow-up proposal")).toBeUndefined();
    await click("Open note review"); expect(onReview).toHaveBeenCalled();
    await render({...initial, note: {latest: {...note, sources_changed: true}, history: []}});
    expect(button("Save follow-up proposal")).toBeUndefined();
  });

  it("shares only deliberately selected fields, and clears only after this proposal is saved", async () => {
    await input("Follow-up message", "My selected message"); await input("Due date", "10/01/2026");
    await input("Expected result", "My selected result");
    expect(button("Save follow-up proposal").disabled).toBe(true);
    await check("Share this message"); await click("Save follow-up proposal");
    const sent = onSave.mock.calls[0][0];
    expect(sent).toEqual({type: "followUpPropose", body: { expected_revision: 3, idempotency_key: expect.any(String),
      note_id: note.id, body: "My selected message", due_date: "2026-10-01", expected_outcome: "My selected result", share: true }});
    await render({...initial, follow_ups: [item]});
    expect(container.querySelector("textarea")!.value).toBe("My selected message");
    await render({...initial, follow_ups: [{...item, create_key: sent.body.idempotency_key}]});
    expect(container.querySelector("textarea")!.value).toBe("");
  });

  it("invalidates share confirmation after proposal or source changes", async () => {
    await check("Share this message"); await input("Follow-up message", "New message");
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
    await check("Share this message");
    await render({...initial, note: {latest: {...note, id: "new-note"}, history: []}});
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
  });

  it("binds explicit approval to the exact revision and removes approval when sources change", async () => {
    await render({...initial, follow_ups: [item]});
    expect(button("Approve local delivery").disabled).toBe(true);
    await check("I approve this exact"); await click("Approve local delivery");
    expect(onSave).toHaveBeenCalledWith({type: "followUpDecision", ticketId: item.ticket_id,
      body: {revision_id: item.revision_id, payload_hash: item.payload_hash, choice: "approve"}});
    await render({...initial, follow_ups: [{...item, source_changed: true}]});
    expect(button("Approve local delivery")).toBeUndefined();
    await click("Dismiss proposal");
    expect(onSave).toHaveBeenLastCalledWith(expect.objectContaining({body: expect.objectContaining({choice: "reject"})}));
  });

  it("separates local delivery from completion and requires checked evidence", async () => {
    await render({...initial, follow_ups: [{...item, state: "sent", operation_status: "succeeded", receipts: [
      {id: "receipt", kind: "local_delivery", actor_id: "human", content: "Recorded locally", created_at: note.created_at}]}]});
    expect(container.textContent).toContain("Local delivery recorded");
    expect(container.textContent).not.toContain("Completed · human recorded");
    await input("Completion evidence", "Invented confirmation received.");
    expect(button("Record completion").disabled).toBe(true);
    await check("I checked that"); await click("Record completion");
    expect(onSave).toHaveBeenCalledWith({type: "followUpComplete", ticketId: item.ticket_id,
      body: {revision_id: item.revision_id, payload_hash: item.payload_hash, idempotency_key: expect.any(String), evidence: "Invented confirmation received."}});
  });

  it("holds all action controls while a request is unconfirmed", async () => {
    await render({...initial, follow_ups: [item]}, true);
    for (const button of container.querySelectorAll<HTMLButtonElement>("button")) expect(button.disabled).toBe(true);
    for (const field of container.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input,textarea")) expect(field.disabled).toBe(true);
  });

  it("rejects impossible dates and offers embedded-browser-safe date shortcuts", async () => {
    await input("Follow-up message", "Message"); await input("Expected result", "Result");
    await input("Due date", "02/30/2026"); await check("Share this message");
    expect(button("Save follow-up proposal").disabled).toBe(true);
    expect(container.textContent).toContain("Enter a valid date");
    await click("Tomorrow");
    expect(container.querySelector<HTMLInputElement>('input[type="text"]')!.getAttribute("aria-invalid")).toBe("false");
    expect(container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
    await check("Share this message");
    expect(button("Save follow-up proposal").disabled).toBe(false);
  });
});
