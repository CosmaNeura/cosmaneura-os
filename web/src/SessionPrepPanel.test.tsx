import {act} from "react";
import {createRoot, type Root} from "react-dom/client";
import {afterEach, beforeEach, expect, it, vi} from "vitest";
import {BffResponseError} from "../../clients/capture/src/bff/http-client";
import {SessionPrepPanel} from "./SessionPrepPanel";
import {readSessionPrep, type SessionPrep} from "./session-prep-api";
import {sessionPrepFixture} from "./test-fixtures/session-prep";
vi.mock("./session-prep-api", () => ({readSessionPrep: vi.fn()}));
const identity = {mode: "clerk_jwt" as const, getToken: vi.fn()}, denied = vi.fn();
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>("node:crypto");
let root: Root, container: HTMLDivElement;
async function mount(workspaceId = "w", enabled = true) {await act(async () => root.render(<SessionPrepPanel workspaceId={workspaceId} identity={identity}
  bot={{address: "visit_prep", team_revision: 1}} enabled={enabled} locked={false} onAccessLost={denied}/>));}
async function click() {await act(async () => container.querySelector("button")!.click());}
beforeEach(() => {vi.stubGlobal("crypto",webcrypto);Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); vi.clearAllMocks(); vi.mocked(readSessionPrep).mockResolvedValue(sessionPrepFixture());
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);});
afterEach(async () => {await act(async () => root.unmount()); container.remove();vi.unstubAllGlobals();});
it("opens only on request and links each statement to its displayed source", async () => {
  await mount(); expect(readSessionPrep).not.toHaveBeenCalled(); await click();
  expect(container.textContent).toContain("Invented reviewed visit summary.");
  expect(container.textContent).toContain("Finalized clinician note");
  const link = container.querySelector("a")!;
  expect(document.getElementById(link.hash.slice(1))?.textContent).toContain("Finalized clinician note");
});
it("keeps pending separate from ready and lets the provider check again", async () => {
  vi.mocked(readSessionPrep).mockResolvedValueOnce(sessionPrepFixture("pending")); await mount(); await click();
  expect(container.textContent).toContain("Your brief is being prepared"); expect(readSessionPrep).toHaveBeenCalledTimes(1);
  await click(); expect(readSessionPrep).toHaveBeenCalledTimes(2); expect(container.textContent).toContain("Invented reviewed visit summary.");
});
it("marks an old, partial brief before displaying its contents", async () => {
  const value = sessionPrepFixture("refreshing"); value.completeness = "partial";
  vi.mocked(readSessionPrep).mockResolvedValue(value); await mount(); await click();
  expect(container.textContent).toContain("previous version"); expect(container.textContent).toContain("Some records are not included");
});
it("withholds a late response after the encounter or permission changes", async () => {
  let release!: (value: SessionPrep) => void;
  vi.mocked(readSessionPrep).mockImplementation(() => new Promise(resolve => {release = resolve;}));
  await mount(); await click(); const signal = vi.mocked(readSessionPrep).mock.calls[0][3];
  await mount("different", false); expect(signal.aborted).toBe(true);
  await act(async () => release(sessionPrepFixture()));
  expect(container.textContent).not.toContain("Invented reviewed"); await click(); expect(readSessionPrep).toHaveBeenCalledTimes(1);
});
it("clears earlier clinical text on access failure without exposing provider errors", async () => {
  await mount(); await click(); vi.mocked(readSessionPrep).mockRejectedValue(new BffResponseError(403, "Private sentinel", null)); await click();
  expect(denied).toHaveBeenCalledOnce(); expect(container.textContent).not.toContain("Invented reviewed"); expect(container.textContent).not.toContain("Private sentinel");
});

it("does not attach a late selection after a refresh replaces the displayed brief",async()=>{
  const selected=vi.fn();
  await act(async()=>root.render(<SessionPrepPanel workspaceId="w" identity={identity} bot={{address:"visit_prep",team_revision:1}} enabled locked={false} onSelect={selected}/>));
  await click();selected.mockClear();
  let finish!:(v:ArrayBuffer)=>void;
  vi.stubGlobal("crypto",{...webcrypto,subtle:{digest:()=>new Promise<ArrayBuffer>(resolve=>{finish=resolve;})}});
  await act(async()=>[...container.querySelectorAll("button")].find(b=>b.textContent==="Include in chat")!.click());
  await click();expect(selected).toHaveBeenLastCalledWith(null);
  await act(async()=>finish(new ArrayBuffer(32)));
  expect(selected.mock.calls.every(([value])=>value===null)).toBe(true);
});
