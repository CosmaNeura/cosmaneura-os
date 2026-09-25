// @ts-expect-error The test runner supplies Node crypto; product code uses WebCrypto.
import { createHash, webcrypto } from "node:crypto";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CaptureDraftEditor } from "./CaptureDraftEditor";
import { CaptureTranscriptEditor } from "./CaptureTranscriptEditor";
import { NoteReview } from "./NoteReview";
import { captureDraft, resolveCaptureSave, saveCaptureDraft, type CaptureDraft } from "./capture-notes-api";
import { correctWorking, readWorking, type WorkingReceipt } from "./capture-working-api";
import { DraftJournal, editorAddress, type EditorDraft, type EditorKind } from "./draft-journal";
import { DraftStoreError, type DraftRecord, type DraftStore } from "./draft-store";
import { EditorRecoveryContext, type EditorRecoveryAccess } from "./editor-recovery";
import type { PrivateNote, Workspace } from "./workspace-api";
import noteFixture from "../../tests/fixtures/capture_gap_draft.json";
import workingFixture from "../../tests/fixtures/capture_working.json";
import sourceFixture from "../../tests/fixtures/capture_source.json";
import type { CaptureSourceEnvelope } from "../../clients/capture/src/bff/source-contracts";

vi.mock("./capture-notes-api",async original=>({...await original<object>(),captureDraft:vi.fn(),saveCaptureDraft:vi.fn(),resolveCaptureSave:vi.fn()}));
vi.mock("./capture-working-api",async original=>({...await original<object>(),readWorking:vi.fn(),correctWorking:vi.fn()}));
const id="00000000-0000-4000-8000-000000000022";
const identity={mode:"clerk_jwt" as const,getToken:async()=>"invented-credential-never-journaled"};
const privateNote:PrivateNote={id:"invented-note-one",version:1,workspace_revision:1,content:"Saved invented private note",content_hash:"a".repeat(64),
  source_reply_id:null,source_revision:1,source_fingerprint:"b".repeat(64),sources_changed:false,review:null,created_at:"2026-09-21T10:00:00Z"};
const workspace:Workspace={id,appointment_id:"00000000-0000-4000-8000-000000000023",label:"Invented recovery encounter",revision:1,
  entries:[],work_candidates:[],note:{latest:privateNote,history:[privateNote]}};
const core=noteFixture.draft as CaptureDraft;
const working=workingFixture.base as WorkingReceipt, second=workingFixture.second as WorkingReceipt, third=workingFixture.third as WorkingReceipt;
const source=sourceFixture.base as CaptureSourceEnvelope;
const correction=()=>{
  const fields={...core.fields,Plan:"Invented W22 retained Core correction"} as Record<string,string>;
  return {...core,fields,note_ref:"visit_note_00000000000000000000000002",
    note_sha256:createHash("sha256").update(JSON.stringify(core.field_order!.map(k=>[k,fields[k]]))).digest("hex")};
};
let root:Root, element:HTMLDivElement, records:Map<string,DraftRecord>, access:EditorRecoveryAccess;
let failPending:boolean, writes:number;
const onSave=vi.fn(), onLock=vi.fn(), onSource=vi.fn();
const readRecord=(kind:EditorKind)=>records.get(editorAddress(id,kind))?.value?.body as EditorDraft | undefined;
function makeAccess() {
  let closed=false;
  const store:DraftStore={close:()=>{closed=true;},read:async address=>{
    if(closed)throw new DraftStoreError("unavailable");return structuredClone(records.get(address)??{revision:null,value:null});
  },write:async(address,expected,value)=>{
    if(closed)throw new DraftStoreError("unavailable");
    if(failPending && (value?.body as EditorDraft | undefined)?.pending){failPending=false;throw new DraftStoreError("unavailable");}
    const old=records.get(address)??{revision:null,value:null};
    if(old.revision!==expected)throw new DraftStoreError("conflict");
    writes++;const result={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(address,result);return result;
  }};
  return {journal:new DraftJournal(store),workspaceId:id,authorize:vi.fn().mockResolvedValue(workspace),denied:vi.fn()};
}
async function render(content:ReactNode, context:EditorRecoveryAccess|null|undefined=access) {
  await act(async()=>{root.render(<EditorRecoveryContext.Provider value={context}>{content}</EditorRecoveryContext.Provider>);});
}
async function restart(content:ReactNode) {
  await act(async()=>root.unmount());access.journal.close();access=makeAccess();root=createRoot(element);await render(content);
}
function button(text:string){return [...element.querySelectorAll("button")].find(b=>b.textContent===text);}
async function click(text:string){
  expect(button(text),text).toBeTruthy();expect(button(text)!.disabled,text).toBe(false);await act(async()=>button(text)!.click());
}
async function input(label:string,text:string){
  const field=element.querySelector<HTMLTextAreaElement>(label)!;expect(field).toBeTruthy();expect(field.disabled).toBe(false);
  await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value")!.set!.call(field,text);field.dispatchEvent(new Event("input",{bubbles:true}));});
}
const privateEditor=(value=workspace)=><NoteReview workspace={value} locked={false} onSave={onSave} onSources={()=>{}}/>;
const coreEditor=(value=core)=><CaptureDraftEditor initial={value} workspaceId={id} identity={identity} onLock={onLock}/>;
const transcriptEditor=()=> <CaptureTranscriptEditor workspaceId={id} sessionId={working.session_id} rawId={working.raw_transcript_id}
  identity={identity} qualifiedSource={source} onLock={onLock} onSource={onSource}/>;
beforeEach(()=>{
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);
  // Real receipt hashes without a separate worker let React's act await each complete
  // interaction. Native WebCrypto/encryption runs in the storage/runtime suites.
  vi.stubGlobal("crypto",{randomUUID:webcrypto.randomUUID.bind(webcrypto),subtle:{digest:async(algorithm:string,data:BufferSource)=>{
    const bytes=ArrayBuffer.isView(data)?new Uint8Array(data.buffer,data.byteOffset,data.byteLength):new Uint8Array(data);
    return Uint8Array.from(createHash(algorithm.toLowerCase().replace("-","")).update(bytes).digest()).buffer;
  }}});
  vi.clearAllMocks();records=new Map();failPending=false;writes=0;
  access=makeAccess();element=document.createElement("div");document.body.append(element);root=createRoot(element);
  vi.mocked(captureDraft).mockResolvedValue(core);vi.mocked(saveCaptureDraft).mockResolvedValue(correction());
  vi.mocked(readWorking).mockResolvedValue(working);vi.mocked(correctWorking).mockResolvedValue(second);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();element.remove();vi.unstubAllGlobals();});

it("restores private note text with fresh authority, without submitting or restoring a review checkbox",async()=>{
  await render(privateEditor());await input("#private-note-text","Unfinished invented private note");
  expect(readRecord("private-note")?.data).toMatchObject({content:"Unfinished invented private note"});
  await restart(privateEditor());expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe(privateNote.content);
  await click("Restore private note draft");expect(access.authorize).toHaveBeenCalledTimes(1);
  expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe("Unfinished invented private note");
  expect(onSave).not.toHaveBeenCalled();await click("Save note version");
  expect(onSave).toHaveBeenCalledWith({type:"note",body:expect.objectContaining({content:"Unfinished invented private note",sources_reconciled:false})});
  expect(JSON.stringify([...records.values()])).not.toContain("invented-credential-never-journaled");
});

it("requires comparison against a different saved private note after process loss",async()=>{
  await render(privateEditor());await input("#private-note-text","My retained private wording");
  const newer={...workspace,revision:2,note:{latest:{...privateNote,id:"note-two",version:2,content:"Other provider-device text"},history:[privateNote]}};
  await restart(privateEditor(newer));vi.mocked(access.authorize).mockResolvedValue(newer);
  await click("Restore private note draft");expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe("My retained private wording");
  expect(button("Save note version")!.disabled).toBe(true);await click("Keep my text as next version");
  await click("Save note version");expect(onSave).toHaveBeenCalledWith({type:"note",body:expect.objectContaining({base_note_id:"note-two"})});
});

it("keeps earlier private wording separate when the encounter switches to a saved Core note",async()=>{
  await render(privateEditor());await input("#private-note-text","Earlier unfinished private wording");
  const next:PrivateNote={...privateNote,id:"invented-core-link",content:"Current exact Core text",core_source:{
    session_id:core.session_id,scribe_source_id:core.scribe_source_id,source_sha256:core.source_sha256,schema_ref:core.schema_ref,
    transcript_ref:core.transcript_ref!,note_ref:core.note_ref!,note_sha256:core.note_sha256!,note_type:core.note_type}};
  const linked={...workspace,revision:2,note:{latest:next,history:[privateNote,next]}};
  await render(privateEditor(linked));
  expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe(next.content);
  expect(readRecord("private-note")?.data).toMatchObject({content:"Earlier unfinished private wording"});
  expect(button("Record private review")!.disabled).toBe(true);
  await restart(privateEditor(linked));vi.mocked(access.authorize).mockResolvedValue(linked);await click("Restore private note draft");
  expect(element.querySelector<HTMLTextAreaElement>("#private-note-text")!.value).toBe(next.content);
  expect([...element.querySelectorAll("textarea")].some(field=>field.value==="Earlier unfinished private wording" && field.readOnly)).toBe(true);
  await click("Discard recovered earlier private draft");expect(records.get(editorAddress(id,"private-note"))?.value).toBeNull();
  expect(onSave).not.toHaveBeenCalled();
});

it("restores a Core editor without submitting and validates the original source receipt",async()=>{
  await render(coreEditor());await click("Edit draft");await input('[aria-label="Draft Plan"]',correction().fields!.Plan);
  await restart(coreEditor());expect(button("Edit draft")!.disabled).toBe(true);
  await click("Restore core note draft");expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Draft Plan"]')!.value).toBe(correction().fields!.Plan);
  expect(saveCaptureDraft).not.toHaveBeenCalled();expect(access.authorize).toHaveBeenCalledTimes(1);
});

it("journals a Core save before transport and replays the identical request after remount",async()=>{
  await render(coreEditor());await click("Edit draft");await input('[aria-label="Draft Plan"]',correction().fields!.Plan);
  vi.mocked(saveCaptureDraft).mockImplementationOnce(async(_id,_identity,base,fields,key)=>{
    expect(readRecord("core-note")).toMatchObject({data:{base,fields},pending:key});throw Error("lost reply");
  });
  await click("Save draft edits");const original=vi.mocked(saveCaptureDraft).mock.calls[0].slice(2,5);
  vi.mocked(captureDraft).mockResolvedValue(correction());await restart(coreEditor(correction()));
  await click("Restore core note draft");await click("Check saved draft");
  expect(saveCaptureDraft).toHaveBeenCalledTimes(1);expect(readRecord("core-note")!.pending).toBe(original[2]);
  await click("Retry Core note save");expect(vi.mocked(saveCaptureDraft).mock.calls[1].slice(2,5)).toEqual(original);
  expect(records.get(editorAddress(id,"core-note"))?.value).toBeNull();
});

async function pendingCoreEdit(content=coreEditor()) {
  await render(content);await click("Edit draft");await input('[aria-label="Draft Plan"]',correction().fields!.Plan);
  vi.mocked(saveCaptureDraft).mockRejectedValueOnce(Error("lost reply"));await click("Save draft edits");
  return vi.mocked(saveCaptureDraft).mock.calls[0][4];
}
function resolution(key:string,status:"saved"|"closed") {
  return {session_id:core.session_id,schema_ref:core.schema_ref,client_key:key,request_sha256:"a".repeat(64),status,
    result_note_ref:status==="saved"?correction().note_ref:null,result_sha256:status==="saved"?correction().note_sha256:null};
}

it("resolves a restored save after its source changes while retaining text and requiring deliberate discard",async()=>{
  const reload=vi.fn(),review=vi.fn();
  const editor=(value:CaptureDraft)=><CaptureDraftEditor initial={value} workspaceId={id} identity={identity} onLock={onLock} onReloadSource={reload} onReviewDraft={review}/>;
  const key=await pendingCoreEdit(editor(core));
  const changed={...core,source_sha256:"c".repeat(64)};
  vi.mocked(captureDraft).mockResolvedValue(changed);await restart(editor(changed));await click("Restore core note draft");
  expect(button("Retry Core note save")!.disabled).toBe(true);expect(button("Discard local edits and reload source")!.disabled).toBe(true);
  vi.mocked(resolveCaptureSave).mockResolvedValue(resolution(key,"saved"));await click("Resolve original save");
  expect(readRecord("core-note")).toMatchObject({pending:null,data:{fields:correction().fields}});
  expect(element.textContent).toContain("original save is confirmed in Core history");
  expect(button("Use saved draft for review")!.disabled).toBe(true);expect(review).not.toHaveBeenCalled();
  expect(button("Discard local edits and reload source")!.disabled).toBe(false);
  await click("Discard local edits and reload source");expect(reload).toHaveBeenCalledTimes(1);expect(records.get(editorAddress(id,"core-note"))?.value).toBeNull();
});

it("retains an unsaved closed request's text and uses a new key only after another explicit save",async()=>{
  const key=await pendingCoreEdit();vi.mocked(resolveCaptureSave).mockResolvedValue(resolution(key,"closed"));
  await click("Resolve original save");
  expect(readRecord("core-note")).toMatchObject({pending:null,data:{fields:correction().fields}});
  expect(element.textContent).toContain("closed without saving");expect(button("Save draft edits")!.disabled).toBe(false);
  expect(saveCaptureDraft).toHaveBeenCalledTimes(1);
  vi.mocked(captureDraft).mockResolvedValue(correction());await click("Save draft edits");
  expect(vi.mocked(saveCaptureDraft).mock.calls[1][4]).not.toBe(key);
});

it("retains the original pending journal if resolution or its current-source read is unavailable",async()=>{
  const key=await pendingCoreEdit();vi.mocked(resolveCaptureSave).mockRejectedValueOnce({status:503});
  await click("Resolve original save");expect(readRecord("core-note")!.pending).toBe(key);
  vi.mocked(resolveCaptureSave).mockResolvedValue(resolution(key,"saved"));vi.mocked(captureDraft).mockRejectedValueOnce({status:503});
  await click("Resolve original save");expect(readRecord("core-note")!.pending).toBe(key);
  expect(element.textContent).toContain("could not be resolved");expect(saveCaptureDraft).toHaveBeenCalledTimes(1);
});

it("requires comparison when resolution confirms a historical edit and a newer draft is current",async()=>{
  const key=await pendingCoreEdit();
  const newer={...correction(),note_ref:"visit_note_00000000000000000000000003",fields:{...correction().fields,Plan:"Newer saved wording"}};
  vi.mocked(captureDraft).mockResolvedValue(newer);vi.mocked(resolveCaptureSave).mockResolvedValue(resolution(key,"saved"));
  await click("Resolve original save");expect(readRecord("core-note")!.pending).toBeNull();
  expect(button("Save draft edits")!.disabled).toBe(true);expect(button("Use saved version")!.disabled).toBe(false);
  expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Draft Plan"]')!.value).toBe(correction().fields!.Plan);
});

it("does not send a Core operation when its local pending journal fails",async()=>{
  await render(coreEditor());await click("Edit draft");await input('[aria-label="Draft Plan"]',"Retain after local failure");failPending=true;
  await click("Save draft edits");expect(saveCaptureDraft).not.toHaveBeenCalled();expect(element.textContent).toContain("The request was not sent");
  await click("Recheck core note recovery");await click("Restore core note draft");
  expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Draft Plan"]')!.value).toBe("Retain after local failure");
});

it("retains corrupt or foreign-context Core records instead of overwriting or sending them",async()=>{
  await render(coreEditor());await click("Edit draft");await input('[aria-label="Draft Plan"]',"Retain corrupt record for investigation");
  const record=records.get(editorAddress(id,"core-note"))!;
  (record.value!.body as {data:{base:CaptureDraft}}).data.base.note_sha256="f".repeat(64);
  const before=structuredClone(record);await restart(coreEditor());await click("Restore core note draft");
  expect(element.textContent).toContain("could not be restored");expect(button("Edit draft")!.disabled).toBe(true);
  expect(records.get(editorAddress(id,"core-note"))).toEqual(before);expect(saveCaptureDraft).not.toHaveBeenCalled();
});

it("recovers unfinished transcript text, including a temporarily empty segment",async()=>{
  await render(transcriptEditor());await click("Correct transcript");await input('[aria-label="Transcript segment 1"]',"");
  await restart(transcriptEditor());await click("Restore transcript draft");
  expect(access.denied).not.toHaveBeenCalled();
  expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Transcript segment 1"]')!.value).toBe("");
  expect(button("Save transcript corrections")!.disabled).toBe(true);expect(correctWorking).not.toHaveBeenCalled();
});

it("recovers the exact transcript correction and its qualified source anchor after a lost reply",async()=>{
  await render(transcriptEditor());await click("Correct transcript");await input('[aria-label="Transcript segment 1"]',second.working_source.segments[0].content);
  vi.mocked(correctWorking).mockImplementationOnce(async(_id,_identity,base,edits,key)=>{
    expect(readRecord("transcript")).toMatchObject({pending:key,data:{base,qualifiedSource:source}});
    expect(edits).toEqual(workingFixture.correction.corrections);throw Error("lost reply");
  });
  await click("Save transcript corrections");const original=vi.mocked(correctWorking).mock.calls[0];
  vi.mocked(readWorking).mockResolvedValue(second);await restart(transcriptEditor());await click("Restore transcript draft");
  expect(access.denied).not.toHaveBeenCalled();
  expect(correctWorking).toHaveBeenCalledTimes(1);await click("Retry transcript save");const retry=vi.mocked(correctWorking).mock.calls[1];
  expect(retry.slice(2,5)).toEqual(original.slice(2,5));expect(retry[6]).toEqual(original[6]);
  expect(records.get(editorAddress(id,"transcript"))?.value).toBeNull();expect(onSource).toHaveBeenLastCalledWith(second);
});

it("keeps a recovered transcript draft separate from newer server history until explicit comparison",async()=>{
  await render(transcriptEditor());await click("Correct transcript");await input('[aria-label="Transcript segment 1"]',second.working_source.segments[0].content);
  vi.mocked(readWorking).mockResolvedValue(third);await restart(transcriptEditor());await click("Restore transcript draft");
  expect(button("Save transcript corrections")!.disabled).toBe(true);expect(correctWorking).not.toHaveBeenCalled();
  await click("Keep my corrections for next version");expect(button("Save transcript corrections")!.disabled).toBe(false);
});

it("never submits transcript corrections after local request-journal failure",async()=>{
  await render(transcriptEditor());await click("Correct transcript");await input('[aria-label="Transcript segment 1"]',second.working_source.segments[0].content);failPending=true;
  await click("Save transcript corrections");expect(correctWorking).not.toHaveBeenCalled();expect(element.textContent).toContain("The request was not sent");
  await click("Recheck transcript recovery");await click("Restore transcript draft");
  expect(element.querySelector<HTMLTextAreaElement>('[aria-label="Transcript segment 1"]')!.value).toBe(second.working_source.segments[0].content);
});

it("checks authority at Restore and keeps private content hidden after revocation",async()=>{
  await render(coreEditor());await click("Edit draft");await input('[aria-label="Draft Plan"]',"Private recovered text must remain hidden");
  await restart(coreEditor());vi.mocked(access.authorize).mockRejectedValueOnce({status:403});
  await click("Restore core note draft");expect(access.denied).toHaveBeenCalledWith({status:403});
  expect(element.textContent).not.toContain("Private recovered text must remain hidden");expect(element.querySelector("textarea")).toBeNull();
  expect(readRecord("core-note")?.data).toMatchObject({fields:{Plan:"Private recovered text must remain hidden"}});
});

it("refuses to bypass required recovery while its authenticated store is unavailable",async()=>{
  await render(coreEditor(),null);expect(button("Edit draft")!.disabled).toBe(true);expect(writes).toBe(0);
  await render(coreEditor());expect(button("Edit draft")!.disabled).toBe(false);
});

it("preserves a concurrent writer's record and requires rechecking before further edits",async()=>{
  await render(coreEditor());await click("Edit draft");await input('[aria-label="Draft Plan"]',"First local text");
  const address=editorAddress(id,"core-note"), other=structuredClone(records.get(address)!);
  other.revision=String(Number(other.revision)+1);(other.value!.body as {data:{fields:Record<string,string>}}).data.fields.Plan="Another process's retained text";
  records.set(address,other);await input('[aria-label="Draft Plan"]',"Stale local writer");
  expect(records.get(address)).toEqual(other);expect(button("Save draft edits")!.disabled).toBe(true);
  expect(element.textContent).toContain("Local editor storage is unavailable");
});
