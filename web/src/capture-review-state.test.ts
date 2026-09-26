import {expect,it} from "vitest";
import type {CaptureDraft} from "./capture-notes-api";
import type {Workspace} from "./workspace-api";
import {withObservedCaptureDraft} from "./capture-review-state";
const source={session_id:"session",scribe_source_id:"raw",source_sha256:"source-hash",schema_ref:"schema",note_ref:"note",note_sha256:"note-hash",transcript_ref:"transcript"};
const note={id:"private-note",version:2,core_source:source,sources_changed:false,content:"Preserved reviewed wording",review:{id:"review"}};
const workspace={id:"workspace",note:{latest:note,history:[note]},follow_ups:[{core_check_required:true,note_version:2,source_changed:false,state:"closed",receipts:["preserved"]}]} as unknown as Workspace;
const draft={...source,status:"draft"} as CaptureDraft;
it("marks an observed source change while retaining review and completed work history",()=>{
 const updated=withObservedCaptureDraft(workspace,{...draft,source_sha256:"new-source",status:"not_prepared",note_ref:null});
 expect(updated.note!.latest!.sources_changed).toBe(true);expect(updated.note!.latest!.review).toEqual(note.review);
 expect(updated.note!.latest!.content).toBe(note.content);expect(updated.follow_ups![0].source_changed).toBe(true);
 expect(updated.follow_ups![0].state).toBe("closed");expect(updated.follow_ups![0].receipts).toEqual(["preserved"]);
 expect(workspace.note!.latest!.sources_changed).toBe(false);
});
it("marks a changed note version on the same template and recognizes a new exact review",()=>{
 const newer={...draft,note_ref:"next-note",note_sha256:"next-hash"};
 expect(withObservedCaptureDraft(workspace,newer).note!.latest!.sources_changed).toBe(true);
 const linked={...workspace,note:{...workspace.note!,latest:{...note,core_source:newer}}} as unknown as Workspace;
 expect(withObservedCaptureDraft(linked,newer)).toBe(linked);
});
it("does not mark another session or template stale merely because its note differs",()=>{
 expect(withObservedCaptureDraft(workspace,{...draft,session_id:"other",source_sha256:"other"})).toBe(workspace);
 expect(withObservedCaptureDraft(workspace,{...draft,schema_ref:"other",note_ref:"other"})).toBe(workspace);
 expect(withObservedCaptureDraft(workspace,draft)).toBe(workspace);
});
