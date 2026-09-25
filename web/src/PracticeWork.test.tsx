// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PracticeWork } from "./PracticeWork";
import { workspaceApi, WorkspaceApiError, type PracticeWorkItem } from "./workspace-api";

vi.mock("./workspace-api", async original => ({...await original<typeof import("./workspace-api")>(),
  workspaceApi: {practiceWork: vi.fn(), workHandoff: vi.fn(), completeWork: vi.fn()}}));
const provider = {id: "provider", name: "Invented provider", available: true};
const staff = {id: "staff", name: "Invented colleague", available: true};
const fixture: PracticeWorkItem = {ticket_id: "work", version: 4, revision_id: "revision", payload_hash: "digest",
  state: "sent", body: "Confirm the invented appointment", due_date: "2020-01-01", expected_outcome: "Visit confirmed",
  viewer_id: provider.id, originator: provider, responsible: provider, pending_offer: null, handoffs: [], receipts: []};
const identity = {boxId: "box", actorId: provider.id};

describe("shared practice work", () => {
  let container: HTMLDivElement; let root: Root;
  const changed = vi.fn(); const lost = vi.fn();
  beforeEach(() => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); vi.clearAllMocks();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items: [structuredClone(fixture)], people: [provider, staff], next_cursor: null});
  });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
  async function render() { await act(async () => root.render(<PracticeWork identity={identity} onChanged={changed} onAccessLost={lost} />)); }
  async function click(text: string) {
    const button = [...container.querySelectorAll("button")].find(value => value.textContent === text);
    expect(button, text).toBeTruthy(); await act(async () => button!.click());
  }
  async function input(selector: string, value: string) {
    const element = container.querySelector(selector) as HTMLSelectElement | HTMLTextAreaElement;
    await act(async () => {
      Object.getOwnPropertyDescriptor(element.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLTextAreaElement.prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event(element.tagName === "SELECT" ? "change" : "input", {bubbles: true}));
    });
  }

  it("retries an unconfirmed offer with the exact request and keeps original responsibility", async () => {
    const offered = {...fixture, version: 5, pending_offer: {id: "offer", from: provider, to: staff}};
    vi.mocked(workspaceApi.workHandoff).mockRejectedValueOnce(new Error("lost reply")).mockResolvedValueOnce(offered);
    await render(); expect(container.textContent).toContain("Overdue");
    await input("select", staff.id); await click("Send responsibility offer");
    expect(container.querySelector("select")!.disabled).toBe(true);
    expect(workspaceApi.workHandoff).toHaveBeenCalledTimes(1);
    const original = vi.mocked(workspaceApi.workHandoff).mock.calls[0];
    await click("Retry same action");
    expect(vi.mocked(workspaceApi.workHandoff).mock.calls[1]).toEqual(original);
    expect(original[2]).toMatchObject({expected_version: 4, revision_id: "revision", payload_hash: "digest", recipient_id: staff.id, kind: "offer"});
    expect(container.textContent).toContain("Invented provider remains responsible until acceptance");
    expect(changed).toHaveBeenCalledOnce();
  });

  it("requires recipient acceptance before offering verified completion", async () => {
    const offered = {...fixture, viewer_id: staff.id, version: 5, pending_offer: {id: "offer", from: provider, to: staff}};
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items: [offered], people: [provider, staff], next_cursor: null});
    vi.mocked(workspaceApi.workHandoff).mockResolvedValue({...offered, version: 6, responsible: staff, pending_offer: null});
    await render(); expect(container.textContent).not.toContain("Record verified result");
    await click("Accept responsibility"); expect(workspaceApi.workHandoff).not.toHaveBeenCalled();
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("Accept responsibility");
    expect(vi.mocked(workspaceApi.workHandoff).mock.calls[0][2]).toMatchObject({kind: "accept", offer_id: "offer", expected_version: 5});
    expect(container.textContent).toContain("Record verified result");
    await input("textarea", "Invented appointment confirmed directly.");
    await click("Record completion"); expect(workspaceApi.completeWork).not.toHaveBeenCalled();
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    vi.mocked(workspaceApi.completeWork).mockResolvedValue({...offered, version: 7, responsible: staff, pending_offer: null, state: "closed",
      receipts: [{id: "receipt", kind: "human_completion", content: "Verified result", actor: staff, created_at: "2026-09-21T00:00:00Z"}]});
    await click("Record completion");
    expect(container.textContent).toContain("Result checked by Invented colleague");
    expect(container.textContent).not.toContain("Record verified result");
  });

  it("keeps typed evidence after a conflict and requires refresh before another action", async () => {
    vi.mocked(workspaceApi.completeWork).mockRejectedValue(new WorkspaceApiError(409));
    await render(); await input("textarea", "Unsaved invented evidence");
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("Record completion");
    expect(container.querySelector("textarea")!.value).toBe("Unsaved invented evidence");
    expect(container.querySelector("textarea")!.disabled).toBe(true);
    expect(container.textContent).not.toContain("Retry same action");
    await click("Refresh work");
    expect(container.querySelector("textarea")!.value).toBe("Unsaved invented evidence");
    expect(container.querySelector("textarea")!.disabled).toBe(false);
  });

  it("clears shared content when signed access is revoked", async () => {
    await render(); vi.mocked(workspaceApi.practiceWork).mockRejectedValue(new WorkspaceApiError(403));
    await click("Refresh work");
    expect(container.textContent).not.toContain(fixture.body);
    expect(lost).toHaveBeenCalledOnce();
  });

  it("discards a delayed response after switching signed identity", async () => {
    let resolve: (value: {items: PracticeWorkItem[]; people: typeof provider[]; next_cursor: null}) => void;
    vi.mocked(workspaceApi.practiceWork).mockImplementationOnce(() => new Promise(done => { resolve = done; }))
      .mockResolvedValueOnce({items: [], people: [staff], next_cursor: null});
    await render();
    await act(async () => root.render(<PracticeWork identity={{boxId: "box", actorId: staff.id}} onChanged={changed} onAccessLost={lost} />));
    await act(async () => resolve!({items: [fixture], people: [provider, staff], next_cursor: null}));
    expect(container.textContent).not.toContain(fixture.body);
    expect(container.textContent).toContain("No shared work");
  });

  it("records preparation readiness with the current version and waits for provider verification", async () => {
    const preparation: PracticeWorkItem = {...fixture, work_kind:"visit_preparation", ready_for_review:false, state:"approved",
      receipts:[{id:"publication",kind:"internal_publication",content:"Shared preparation",actor:provider,created_at:"2026-09-21T00:00:00Z"}]};
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[preparation],people:[provider,staff],next_cursor:null});
    vi.mocked(workspaceApi.completeWork).mockResolvedValue({...preparation,version:5,ready_for_review:true,
      receipts:[...preparation.receipts,{id:"ready",kind:"ready_for_review",content:"Intake checked; provider question retained.",actor:provider,created_at:"2026-09-21T00:01:00Z"}]});
    await render();
    expect(container.querySelector('[aria-label="Shared visit preparation"]')).not.toBeNull();
    expect(container.textContent).toContain("Preparation in progress");
    expect(container.textContent).toContain("Shared internally by Invented provider");
    expect(container.textContent).not.toContain("Delivery receipt");
    await input("textarea","Intake checked; provider question retained.");
    await click("Mark ready for review");expect(workspaceApi.completeWork).not.toHaveBeenCalled();
    await act(async()=>container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("Mark ready for review");
    expect(vi.mocked(workspaceApi.completeWork).mock.calls[0][2]).toMatchObject({expected_version:4,revision_id:fixture.revision_id,payload_hash:fixture.payload_hash,evidence:"Intake checked; provider question retained."});
    expect(container.textContent).toContain("Ready for provider review");
    expect(container.textContent).not.toContain("Completed");
    expect(container.textContent).not.toContain("Mark ready for review");
    expect(container.textContent).not.toContain("Offer to a colleague");
    expect(changed).toHaveBeenCalledOnce();
  });

  it("lets the original provider reclaim ready preparation without changing the readiness receipt", async () => {
    const ready:PracticeWorkItem={...fixture,work_kind:"visit_preparation",ready_for_review:true,state:"approved",responsible:staff,
      receipts:[{id:"ready",kind:"ready_for_review",content:"Prepared by staff",actor:staff,created_at:"2026-09-21T00:01:00Z"}]};
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[ready],people:[provider,staff],next_cursor:null});
    vi.mocked(workspaceApi.workHandoff).mockResolvedValue({...ready,version:5,responsible:provider});
    await render();expect(container.textContent).not.toContain("Mark ready for review");
    await click("Reclaim responsibility");
    expect(vi.mocked(workspaceApi.workHandoff).mock.calls[0][2]).toMatchObject({kind:"reclaim",expected_version:4});
    expect(container.textContent).toContain("Ready for provider review");
    expect(container.textContent).toContain("Prepared by staff");
    expect(workspaceApi.completeWork).not.toHaveBeenCalled();
  });

  it.each([false,true])("requires a provider receipt before showing preparation as verified complete (%s)",async verified=>{
    const closed:PracticeWorkItem={...fixture,work_kind:"visit_preparation",ready_for_review:false,state:"closed",
      receipts:verified?[{id:"verified",kind:"provider_verification",content:"Provider checked the preparation",actor:provider,created_at:"2026-09-21T00:02:00Z"}]:[]};
    vi.mocked(workspaceApi.practiceWork).mockResolvedValue({items:[closed],people:[provider,staff],next_cursor:null});
    await render();expect(container.textContent).toContain(verified?"Completed · provider verified":"Completion unverified");
    expect(container.textContent).not.toContain("Mark ready for review");
    expect(container.textContent).not.toContain("Record completion");
    expect(container.textContent).not.toContain("Completed · human recorded");
  });
});
