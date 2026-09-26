import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import golden from "../../tests/fixtures/capture_working.json";
import sourceGolden from "../../tests/fixtures/capture_source.json";
import type { CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";
import { CaptureTranscriptEditor } from "./CaptureTranscriptEditor";
import { correctWorking, readWorking, type WorkingReceipt } from "./capture-working-api";
vi.mock("./capture-working-api",async original => ({...await original<object>(),correctWorking:vi.fn(),readWorking:vi.fn()}));
const base=golden.base as WorkingReceipt, second=golden.second as WorkingReceipt, third=golden.third as WorkingReceipt;
const identity={mode:"clerk_jwt" as const,getToken:vi.fn()}, onLock=vi.fn(),onSource=vi.fn();
let root:Root,container:HTMLDivElement;
const button=(text:string)=>[...container.querySelectorAll("button")].find(b=>b.textContent===text)!;
const input=()=>container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Transcript segment 1"]')!;
async function click(text:string){await act(async()=>button(text).click());}
async function edit(text=second.working_source.segments[0].content){await act(async()=>{
  Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(input(),text);
  input().dispatchEvent(new Event("input",{bubbles:true}));
});}
const render=(locked=false)=>root.render(<CaptureTranscriptEditor workspaceId="workspace" sessionId={base.session_id} rawId={base.raw_transcript_id}
  identity={identity} onLock={onLock} onSource={onSource} locked={locked}/>);
beforeEach(async()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  vi.mocked(readWorking).mockResolvedValue(base);vi.mocked(correctWorking).mockResolvedValue(second);
  container=document.createElement("div");document.body.append(container);root=createRoot(container);
  await act(async()=>render());
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();});
it("edits explicitly and announces only the confirmed current successor",async()=>{
  expect(input()).toBeNull();await click("Correct transcript");await edit();
  expect(onLock).toHaveBeenLastCalledWith(true);
  vi.mocked(readWorking).mockResolvedValue(second);await click("Save transcript corrections");
  expect(vi.mocked(correctWorking).mock.calls[0][2]).toEqual(base);
  expect(vi.mocked(correctWorking).mock.calls[0][3]).toEqual(golden.correction.corrections);
  expect(onSource).toHaveBeenLastCalledWith(second);expect(onLock).toHaveBeenLastCalledWith(false);
  expect(container.textContent).toContain("Transcript correction saved");
});
it("recovers lost replies using the exact original request without inferring success from text",async()=>{
  await click("Correct transcript");await edit();vi.mocked(correctWorking).mockRejectedValueOnce(new Error("private_sentinel"));
  await click("Save transcript corrections");expect(input().disabled).toBe(true);
  expect(container.textContent).not.toContain("private_sentinel");expect(onLock).toHaveBeenLastCalledWith(true);
  vi.mocked(readWorking).mockResolvedValue(second);await click("Retry transcript save");
  const calls=vi.mocked(correctWorking).mock.calls;
  expect(calls[0].slice(2,5)).toEqual(calls[1].slice(2,5));expect(onSource).toHaveBeenLastCalledWith(second);
});
it("keeps later history current when an old committed save is replayed",async()=>{
  await click("Correct transcript");await edit();vi.mocked(readWorking).mockResolvedValue(third);
  await click("Save transcript corrections");expect(input().value).toBe(second.working_source.segments[0].content);
  expect(input().disabled).toBe(true);expect(onSource).toHaveBeenLastCalledWith(third);
  await click("Use saved transcript");expect(input().value).toBe(third.working_source.segments[0].content);
  expect(onLock).toHaveBeenLastCalledWith(false);
});
it("requires deliberate rebasing after a competing save and preserves other segments",async()=>{
  await click("Correct transcript");await edit();vi.mocked(correctWorking).mockRejectedValueOnce({status:409});
  const newer=structuredClone(third);newer.working_source.segments[1].content="A separately saved second segment.";
  vi.mocked(readWorking).mockResolvedValue(newer);await click("Save transcript corrections");
  expect(input().disabled).toBe(true);await click("Keep my corrections for next version");
  await click("Save transcript corrections");
  const call=vi.mocked(correctWorking).mock.calls[1];expect(call[2]).toEqual(newer);
  expect(call[3]).toEqual(golden.correction.corrections);expect(call[4]).not.toEqual(vi.mocked(correctWorking).mock.calls[0][4]);
});
it("retains edited text when current access disappears",async()=>{
  await click("Correct transcript");await edit();vi.mocked(readWorking).mockRejectedValue(new Error("private access"));
  await click("Check current transcript");expect(input().value).toBe(second.working_source.segments[0].content);
  expect(container.textContent).not.toContain("private access");expect(onLock).toHaveBeenLastCalledWith(true);
});
it("cannot edit or save while a note or workspace operation is locked",async()=>{
  await act(async()=>render(true));expect(button("Correct transcript").disabled).toBe(true);
  expect(button("Check current transcript").disabled).toBe(true);expect(correctWorking).not.toHaveBeenCalled();
});
it("aborts outstanding reads on unmount and never publishes their late result",async()=>{
  let resolve!:(v:WorkingReceipt)=>void;
  vi.mocked(readWorking).mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
  await click("Check current transcript");const signal=vi.mocked(readWorking).mock.calls.at(-1)![4];
  await act(async()=>root.unmount());expect(signal?.aborted).toBe(true);
  onSource.mockClear();await act(async()=>resolve(third));expect(onSource).not.toHaveBeenCalled();
  root=createRoot(container);
});
it("keeps the qualified evidence anchor through an uncertain correction retry",async()=>{
  const qualifiedSource=sourceGolden.base as CaptureSourceEnvelope;
  await act(async()=>root.render(<CaptureTranscriptEditor workspaceId="workspace" sessionId={base.session_id} rawId={base.raw_transcript_id}
    identity={identity} onLock={onLock} onSource={onSource} qualifiedSource={qualifiedSource}/>));
  expect(vi.mocked(readWorking).mock.calls.at(-1)?.[5]).toBe(qualifiedSource);
  await click("Correct transcript");await edit();
  vi.mocked(correctWorking).mockRejectedValueOnce(new Error("reply lost"));
  await click("Save transcript corrections");
  vi.mocked(readWorking).mockResolvedValue(second);await click("Retry transcript save");
  const calls=vi.mocked(correctWorking).mock.calls;
  expect(calls[0].slice(2,5)).toEqual(calls[1].slice(2,5));
  expect(calls[0][6]).toBe(qualifiedSource);expect(calls[1][6]).toBe(qualifiedSource);
  expect(onSource).toHaveBeenLastCalledWith(second);
});
