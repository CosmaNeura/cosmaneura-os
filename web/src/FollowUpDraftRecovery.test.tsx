import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FollowUpWork } from "./FollowUpWork";
import { DraftJournal, editorAddress, type EditorDraft } from "./draft-journal";
import { DraftStoreError, type DraftRecord, type DraftStore } from "./draft-store";
import { EditorRecoveryContext, type EditorRecoveryAccess } from "./editor-recovery";
import type { FollowUp, Workspace } from "./workspace-api";

const id="00000000-0000-4000-8000-000000000021";
const ticket="00000000-0000-4000-8000-000000000031", revision="00000000-0000-4000-8000-000000000032";
const note={id:"00000000-0000-4000-8000-000000000041",version:1,workspace_revision:2,content:"Private note stays private",
  content_hash:"a".repeat(64),source_reply_id:null,source_revision:1,source_fingerprint:"b".repeat(64),sources_changed:false,
  review:{id:"review",reviewer_id:"owner",created_at:"2026-09-21T12:00:00Z"},created_at:"2026-09-21T12:00:00Z"};
const item:FollowUp={ticket_id:ticket,revision_id:revision,payload_hash:"c".repeat(64),create_key:"earlier-key",state:"sent",
  body:"Invented follow-up",due_date:"2026-10-01",expected_outcome:"Invented result",owner_id:"owner",responsible_id:"owner",
  note_version:1,source_changed:false,operation_status:"succeeded",receipts:[]};
const workspace:Workspace={id,appointment_id:"00000000-0000-4000-8000-000000000022",label:"Invented recovery encounter",revision:4,
  entries:[],work_candidates:[],note:{latest:note,history:[note]},follow_ups:[item]};
const proposalAddress=editorAddress(id,"follow-up-proposal"),resultAddress=editorAddress(id,`follow-up-result:${ticket}`);
let root:Root,element:HTMLDivElement,records:Map<string,DraftRecord>,access:EditorRecoveryAccess,failWrites:boolean;
const onSave=vi.fn();
function makeAccess():EditorRecoveryAccess {
  let closed=false;
  const store:DraftStore={close(){closed=true;},async read(address){
    if(closed)throw new DraftStoreError("unavailable");return structuredClone(records.get(address)??{revision:null,value:null});
  },async write(address,expected,value){
    if(closed || failWrites)throw new DraftStoreError("unavailable");
    const previous=records.get(address)??{revision:null,value:null};
    if(previous.revision!==expected)throw new DraftStoreError("conflict");
    const next={revision:String(Number(expected??0)+1),value:structuredClone(value)};records.set(address,next);return next;
  }};
  return {journal:new DraftJournal(store),workspaceId:id,authorize:vi.fn().mockResolvedValue(workspace),denied:vi.fn()};
}
async function render(w=workspace,context:EditorRecoveryAccess|null=access){
  await act(async()=>root.render(<EditorRecoveryContext.Provider value={context}><FollowUpWork workspace={w} locked={false} onSave={onSave} onReview={()=>{}}/></EditorRecoveryContext.Provider>));
}
async function restart(w=workspace){
  await act(async()=>root.unmount());access.journal.close();access=makeAccess();vi.mocked(access.authorize).mockResolvedValue(w);root=createRoot(element);await render(w);
}
const button=(label:string)=>[...element.querySelectorAll("button")].find(b=>b.textContent===label)!;
async function click(label:string){expect(button(label),label).toBeTruthy();expect(button(label).disabled,label).toBe(false);await act(async()=>button(label).click());}
const field=(label:string)=>[...element.querySelectorAll("label")].find(e=>e.textContent?.startsWith(label))!.querySelector("textarea,input") as HTMLTextAreaElement|HTMLInputElement;
async function input(label:string,value:string){
  const target=field(label);expect(target.disabled).toBe(false);const proto=target.tagName==="TEXTAREA"?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;
  await act(async()=>{Object.getOwnPropertyDescriptor(proto,"value")!.set!.call(target,value);target.dispatchEvent(new Event("input",{bubbles:true}));});
}
async function check(label:string){const target=field(label) as HTMLInputElement;expect(target.disabled).toBe(false);await act(async()=>target.click());}
const data=(address:string)=>(records.get(address)?.value?.body as EditorDraft|undefined)?.data;
async function fillProposal(){await input("Follow-up message","Unsent invented message");await input("Due date","10/");await input("Expected result","Unfinished invented result");}
beforeEach(()=>{
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT",true);vi.clearAllMocks();records=new Map();failWrites=false;access=makeAccess();
  element=document.createElement("div");document.body.append(element);root=createRoot(element);
});
afterEach(async()=>{await act(async()=>root.unmount());access.journal.close();element.remove();vi.unstubAllGlobals();});

it("restores unsent proposal fields including a partial date without restoring sharing consent",async()=>{
  await render();await fillProposal();await check("Share this message");
  expect(data(proposalAddress)).toEqual({body:"Unsent invented message",due:"10/",outcome:"Unfinished invented result",baseNoteId:note.id,submitted:null});
  await restart();expect(field("Follow-up message").value).toBe("");expect(button("Save follow-up proposal").disabled).toBe(true);
  await click("Restore follow-up proposal draft");expect(access.authorize).toHaveBeenCalledOnce();
  expect(field("Follow-up message").value).toBe("Unsent invented message");expect(field("Due date").value).toBe("10/");
  expect((field("Share this message") as HTMLInputElement).checked).toBe(false);expect(onSave).not.toHaveBeenCalled();
  await input("Due date","10/01/2026");await check("Share this message");await click("Save follow-up proposal");
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({body:expect.objectContaining({note_id:note.id,share:true})}));
});

it("requires explicit comparison when the source note changed before restore",async()=>{
  await render();await fillProposal();await input("Due date","10/01/2026");
  const current={...workspace,note:{latest:{...note,id:"00000000-0000-4000-8000-000000000042",version:2},history:[note]}};
  await restart(current);await click("Restore follow-up proposal draft");
  expect(element.textContent).toContain("belongs to an earlier note");expect(field("Share this message").disabled).toBe(true);
  expect(onSave).not.toHaveBeenCalled();await click("Use this text with the current reviewed note");
  expect((field("Share this message") as HTMLInputElement).checked).toBe(false);await check("Share this message");await click("Save follow-up proposal");
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({body:expect.objectContaining({note_id:current.note.latest.id})}));
});

it("rechecks access before revealing saved text and retains the record after revocation",async()=>{
  await render();await fillProposal();await restart();vi.mocked(access.authorize).mockRejectedValue({status:403});
  const before=structuredClone(records.get(proposalAddress));await click("Restore follow-up proposal draft");
  expect(field("Follow-up message").value).toBe("");expect(records.get(proposalAddress)).toEqual(before);
  expect(access.denied).toHaveBeenCalledWith({status:403});expect(onSave).not.toHaveBeenCalled();
});

it("recognizes the original proposal after a lost response and never presents it as new work",async()=>{
  await render();await fillProposal();await input("Due date","10/01/2026");await check("Share this message");await click("Save follow-up proposal");
  const sent=onSave.mock.calls[0][0].body;
  expect(data(proposalAddress)).toMatchObject({submitted:sent.idempotency_key});
  const current={...workspace,follow_ups:[{...item,create_key:sent.idempotency_key,body:sent.body,due_date:sent.due_date,expected_outcome:sent.expected_outcome,state:"pending_approval"}]};
  await restart(current);await click("Restore follow-up proposal draft");
  expect(field("Follow-up message").value).toBe("");expect(records.get(proposalAddress)?.value).toBeNull();expect(onSave).toHaveBeenCalledTimes(1);
});

it("restores only this ticket's completion text and requires a fresh result check",async()=>{
  await render();await input("Completion evidence","Invented result checked");await check("I checked that");
  expect(data(resultAddress)).toEqual({evidence:"Invented result checked",revisionId:revision,payloadHash:item.payload_hash});
  await restart();await click("Restore follow-up result draft");
  expect(field("Completion evidence").value).toBe("Invented result checked");expect((field("I checked that") as HTMLInputElement).checked).toBe(false);
  expect(onSave).not.toHaveBeenCalled();await check("I checked that");await click("Record completion");
  expect(onSave).toHaveBeenCalledWith({type:"followUpComplete",ticketId:ticket,body:expect.objectContaining({revision_id:revision,payload_hash:item.payload_hash,evidence:"Invented result checked"})});
});

it("keeps evidence attached to the earlier revision until the human explicitly compares it",async()=>{
  await render();await input("Completion evidence","Earlier result wording");
  const current={...workspace,follow_ups:[{...item,revision_id:"00000000-0000-4000-8000-000000000033",payload_hash:"d".repeat(64)}]};
  await restart(current);await click("Restore follow-up result draft");
  expect(field("Earlier completion evidence").value).toBe("Earlier result wording");expect(button("Record completion").disabled).toBe(true);
  await click("Use this text for the current result");expect((field("I checked that") as HTMLInputElement).checked).toBe(false);
  await check("I checked that");await click("Record completion");expect(onSave).toHaveBeenCalledWith(expect.objectContaining({body:expect.objectContaining({revision_id:current.follow_ups[0].revision_id})}));
});

it.each(["closed","reassigned"])("retains unfinished evidence when work is %s elsewhere",async state=>{
  await render();await input("Completion evidence","My earlier unfinished evidence");
  const current={...workspace,follow_ups:[{...item,...(state==="closed"?{state:"closed"}:{responsible_id:"colleague"})}]};
  await restart(current);await click("Restore follow-up result draft");
  expect(field("Earlier completion evidence").value).toBe("My earlier unfinished evidence");expect(button("Record completion")).toBeUndefined();
  expect(data(resultAddress)).toMatchObject({evidence:"My earlier unfinished evidence"});expect(onSave).not.toHaveBeenCalled();
  await click("Discard earlier result draft");expect(records.get(resultAddress)?.value).toBeNull();
});

it("clears local evidence only when the same revision contains the owner's exact saved result",async()=>{
  await render();await input("Completion evidence","Exact checked evidence");
  const current={...workspace,follow_ups:[{...item,state:"closed",receipts:[{id:"receipt",kind:"human_completion" as const,actor_id:"owner",content:"Exact checked evidence",created_at:note.created_at}]}]};
  await render(current);expect(records.get(resultAddress)?.value).toBeNull();expect(element.textContent).toContain("Exact checked evidence");expect(onSave).not.toHaveBeenCalled();
});

it("refuses malformed recovery contents without overwriting or transmitting them",async()=>{
  await render();await input("Completion evidence","Retain this record");
  (records.get(resultAddress)!.value!.body as EditorDraft).data={evidence:"Retain this record",revisionId:revision,payloadHash:item.payload_hash,checked:true};
  const before=structuredClone(records.get(resultAddress));await restart();await click("Restore follow-up result draft");
  expect(element.textContent).toContain("could not be restored");expect(records.get(resultAddress)).toEqual(before);expect(onSave).not.toHaveBeenCalled();
});

it("blocks form actions when device storage fails and preserves earlier committed text",async()=>{
  await render();await input("Completion evidence","Earlier durable wording");failWrites=true;await input("Completion evidence","New typing when storage fails");
  expect(button("Record completion").disabled).toBe(true);expect(data(resultAddress)).toMatchObject({evidence:"Earlier durable wording"});
  expect(onSave).not.toHaveBeenCalled();failWrites=false;await restart();await click("Restore follow-up result draft");
  expect(field("Completion evidence").value).toBe("Earlier durable wording");
});

it("does not bypass recovery while the authenticated journal is unavailable",async()=>{
  await render(workspace,null);expect(field("Follow-up message").disabled).toBe(true);expect(field("Completion evidence").disabled).toBe(true);
  expect(button("Record completion").disabled).toBe(true);expect(onSave).not.toHaveBeenCalled();
});
