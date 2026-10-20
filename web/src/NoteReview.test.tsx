import { act, useLayoutEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NoteReview } from "./NoteReview";
import type { PrivateNote, Workspace } from "./workspace-api";
import gapFixture from "../../tests/fixtures/capture_gap_draft.json";
import { validateCaptureGapReview } from "./capture-gap-review";

const saved: PrivateNote = {id: "note-one", version: 1, workspace_revision: 2,
  content: "Saved invented note.", content_hash: "a".repeat(64), source_reply_id: null, source_revision: 1,
  source_fingerprint: "b".repeat(64), sources_changed: false, review: null, created_at: "2026-09-16T12:00:00Z"};
const initial: Workspace = {id: "workspace", appointment_id: "appointment", label: "Invented person", revision: 2,
  entries: [], work_candidates: [], note: {latest: saved, history: [saved]}};

describe("private note review", () => {
  let root: Root; let container: HTMLDivElement;
  const onSave = vi.fn(); const onSources = vi.fn();
  async function render(w = initial, locked = false) {
    await act(async () => root.render(<NoteReview workspace={w} locked={locked} onSave={onSave} onSources={onSources} />));
  }
  beforeEach(async () => {
    Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); vi.clearAllMocks();
    container = document.createElement("div"); document.body.append(container); root = createRoot(container);
    await render();
  });
  afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
  const button = (name: string) => [...container.querySelectorAll("button")].find(b => b.textContent === name)!;
  async function click(name: string) { await act(async () => button(name).click()); }
  async function input(value: string) {
    const element = container.querySelector("textarea")!;
    await act(async () => { Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event("input", {bubbles: true})); });
  }

  it("requires explicit human review of the exact saved version and removes review after editing", async () => {
    expect(button("Record private review").disabled).toBe(true);
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("Record private review");
    expect(onSave).toHaveBeenCalledWith({type: "review", noteId: saved.id, body: {
      expected_revision: 2, idempotency_key: expect.any(String), content_hash: saved.content_hash, source_fingerprint: saved.source_fingerprint,
    }});
    await input("Human corrected text.");
    expect(button("Record private review")).toBeUndefined();
    await click("Save note version");
    expect(onSave).toHaveBeenLastCalledWith({type: "note", body: expect.objectContaining({base_note_id: saved.id,
      content: "Human corrected text.", sources_reconciled: false})});
  });

  it("preserves unsaved text when a different client saves a note", async () => {
    await input("My unsaved edit.");
    const other = {...saved, id: "note-two", version: 2, content: "Other client's text."};
    await render({...initial, revision: 3, note: {latest: other, history: [saved, other]}});
    expect(container.querySelector("textarea")!.value).toBe("My unsaved edit.");
    expect(button("Save note version").disabled).toBe(true);
    expect(container.textContent).toContain("Other client's text.");
    await click("Use latest saved note");
    expect(container.querySelector("textarea")!.value).toBe("Other client's text.");
  });

  it('opens team preparation only from the exact saved unchanged note without creating work',async()=>{
    const next=vi.fn();const mount=(w=initial)=>act(async()=>root.render(<NoteReview workspace={w} locked={false} onSave={onSave} onSources={onSources} onTeamDrafts={next}/>));
    await mount();await click('Prepare follow-up and research');expect(next).toHaveBeenCalledExactlyOnceWith(saved.id);expect(onSave).not.toHaveBeenCalled();
    await input('My unsaved change');expect(button('Prepare follow-up and research').disabled).toBe(true);
    await click('Prepare follow-up and research');expect(next).toHaveBeenCalledOnce();
    await input(saved.content);await mount({...initial,note:{latest:{...saved,sources_changed:true},history:[saved]}});
    expect(button('Prepare follow-up and research').disabled).toBe(true);expect(onSave).not.toHaveBeenCalled();
  });

  it("blocks stale source review until reconciliation is saved as a new note", async () => {
    await render({...initial, revision: 3, note: {latest: {...saved, sources_changed: true}, history: [saved]}});
    expect(button("Record private review")).toBeUndefined();
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("Save note version");
    expect(onSave).toHaveBeenCalledWith({type: "note", body: expect.objectContaining({sources_reconciled: true, expected_revision: 3})});
  });

  it("requires confirmation before replacing editor text with a generated draft", async () => {
    const w: Workspace = {...initial, entries: [{id: "reply", revision: 3, kind: "handoff_result", origin: "agent_handoff",
      content: "Brief", source_label: null, ticket: null, created_at: saved.created_at,
      reply: {agent_name: "Scribe", role: "scribe", backend: "azure_gpt41_source_draft_v1", content: "Generated draft.", context_revision: 1, citations: []}}]};
    await render(w); await click("Use latest Scribe draft");
    expect(container.querySelector("textarea")!.value).toBe(saved.content);
    await click("Replace editor with draft");
    expect(container.querySelector("textarea")!.value).toBe("Generated draft.");
    expect(onSave).not.toHaveBeenCalled();
    await click("Save note version");
    expect(onSave).toHaveBeenCalledWith({type: "note", body: expect.objectContaining({source_reply_id: "reply"})});
  });

  it("opens an available Scribe draft into an empty review without replacing existing edits", async () => {
    await act(async () => root.unmount()); root = createRoot(container);
    const w:Workspace={...initial,note:{latest:null,history:[]},entries:[{id:"scribe",revision:2,kind:"handoff_result",origin:"agent_handoff",content:"",source_label:null,ticket:null,created_at:saved.created_at,
      reply:{agent_name:"Scribe",role:"scribe",backend:"azure_gpt41_source_draft_v1",content:"Draft to review",context_revision:1,citations:[]}}]};
    await act(async()=>root.render(<NoteReview workspace={w} active locked={false} onSave={onSave} onSources={onSources}/>));
    expect(container.querySelector("textarea")!.value).toBe("Draft to review");
    expect(container.textContent).toContain("Review version not saved");expect(onSave).not.toHaveBeenCalled();
    await input("My working edit");await render(w);
    await act(async()=>root.render(<NoteReview workspace={w} active locked={false} onSave={onSave} onSources={onSources}/>));
    expect(container.querySelector("textarea")!.value).toBe("My working edit");
  });

  it.each([false,true])('initializes an available Scribe draft before the first editable commit and preserves the immediate edit (initially locked: %s)',async initiallyLocked=>{
    await act(async()=>root.unmount());root=createRoot(container);
    const draft:Workspace={...initial,note:{latest:null,history:[]},entries:[{id:'scribe-initial',revision:2,kind:'handoff_result',origin:'agent_handoff',
      content:'',source_label:null,ticket:null,created_at:saved.created_at,reply:{agent_name:'Scribe',role:'scribe',backend:'azure_gpt41_source_draft_v1',
        content:'Initial Scribe draft for review.',context_revision:1,citations:[]}}]};
    const commits:Array<{disabled:boolean;content:string}>=[];
    function ObserveReview({value,locked}:{value:Workspace;locked:boolean}) {
      // Observe the committed DOM before passive effects, the same readiness
      // boundary a browser's visible/editable locator uses for its first fill.
      useLayoutEffect(()=>{const editor=container.querySelector<HTMLTextAreaElement>('#private-note-text')!;
        commits.push({disabled:editor.disabled,content:editor.value});});
      return <NoteReview workspace={value} active locked={locked} onSave={onSave} onSources={onSources}/>;
    }
    await act(async()=>root.render(<ObserveReview value={draft} locked={initiallyLocked}/>));
    if(initiallyLocked)await act(async()=>root.render(<ObserveReview value={draft} locked={false}/>));
    expect(commits.some(commit=>!commit.disabled&&!commit.content.trim())).toBe(false);
    expect(container.querySelector<HTMLTextAreaElement>('#private-note-text')?.disabled).toBe(false);
    expect(container.querySelector<HTMLTextAreaElement>('#private-note-text')?.value).toBe('Initial Scribe draft for review.');
    const human='Invented reviewed note. Confirm contact consent and medication list before outreach.';
    await input(human);
    const newer={...draft,revision:3,entries:[...draft.entries,{...draft.entries[0],id:'scribe-newer',revision:3,
      reply:{...draft.entries[0].reply!,content:'Newer Scribe draft must not replace the human edit.'}}]};
    await act(async()=>root.render(<ObserveReview value={newer} locked={false}/>));
    expect(container.querySelector<HTMLTextAreaElement>('#private-note-text')?.value).toBe(human);
    await click('Save note version');
    expect(onSave).toHaveBeenCalledWith({type:'note',body:expect.objectContaining({content:human,source_reply_id:'scribe-initial',expected_revision:3})});
  });

  it('preserves text typed before a Scribe draft arrives instead of adopting over it',async()=>{
    await act(async()=>root.unmount());root=createRoot(container);
    const empty:Workspace={...initial,note:{latest:null,history:[]},entries:[]};
    await act(async()=>root.render(<NoteReview workspace={empty} active locked={false} onSave={onSave} onSources={onSources}/>));
    await input('My invented note typed before Scribe was ready.');
    const draft={...empty,revision:3,entries:[{id:'late-scribe',revision:3,kind:'handoff_result' as const,origin:'agent_handoff',content:'',source_label:null,ticket:null,
      created_at:saved.created_at,reply:{agent_name:'Scribe',role:'scribe' as const,backend:'azure_gpt41_source_draft_v1',content:'Late generated draft.',context_revision:1,citations:[]}}]};
    await act(async()=>root.render(<NoteReview workspace={draft} active locked={false} onSave={onSave} onSources={onSources}/>));
    expect(container.querySelector<HTMLTextAreaElement>('#private-note-text')?.value).toBe('My invented note typed before Scribe was ready.');
    await click('Save note version');
    expect(onSave).toHaveBeenCalledWith({type:'note',body:expect.objectContaining({content:'My invented note typed before Scribe was ready.',source_reply_id:null})});
  });

  it("adopts a remotely created note only when the editor is still empty", async () => {
    await act(async () => root.unmount()); root = createRoot(container);
    await render({...initial, revision: 1, note: {latest: null, history: []}});
    await render(initial);
    expect(container.querySelector("textarea")!.value).toBe(saved.content);
    expect(button("Use latest saved note")).toBeUndefined();
  });

  it("can keep a conflicting edit as the next version after explicit comparison", async () => {
    await input("My unsaved correction.");
    const other = {...saved, id: "note-two", version: 2, content: "Other saved text."};
    await render({...initial, revision: 3, note: {latest: other, history: [saved, other]}});
    await click("Keep my text as next version");
    expect(container.querySelector("textarea")!.value).toBe("My unsaved correction.");
    await click("Save note version");
    expect(onSave).toHaveBeenCalledWith({type: "note", body: expect.objectContaining({
      base_note_id: "note-two", expected_revision: 3, content: "My unsaved correction.",
    })});
  });

  it("requires a separate gap acknowledgment and resets it when exact evidence changes", async () => {
    const draft = gapFixture.draft;
    const gap = validateCaptureGapReview(draft.capture_gap_review);
    const core = {...saved, core_source: {session_id: draft.session_id, scribe_source_id: draft.scribe_source_id,
      source_sha256: draft.source_sha256, schema_ref: draft.schema_ref, transcript_ref: draft.transcript_ref,
      note_ref: draft.note_ref, note_sha256: draft.note_sha256, note_type: draft.note_type, capture_gap_review: gap}};
    await render({...initial, note: {latest: core, history: [core]}});
    expect(container.textContent).toContain("Some conversation may be missing");
    const checks = () => [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(checks()).toHaveLength(2);
    expect(checks().map(c => c.checked)).toEqual([false, false]);
    await act(async () => checks()[0].click());
    expect(button("Record private review")!.disabled).toBe(true);
    await act(async () => checks()[1].click());
    expect(button("Record private review")!.disabled).toBe(false);
    await click("Record private review");
    expect(onSave).toHaveBeenLastCalledWith({type: "review", noteId: saved.id, body: expect.objectContaining({
      gap_acknowledgment: {acknowledged: true, recovery_sha256: gap.recovery_sha256},
    })});
    const changed = {...core, core_source: {...core.core_source, capture_gap_review: {...gap, recovery_sha256: "f".repeat(64)}}};
    await render({...initial, note: {latest: changed, history: [changed]}});
    expect(checks()[1].checked).toBe(false);
    expect(button("Record private review")!.disabled).toBe(true);
  });

  it("reviews an exact Core copy without allowing a separate edited record", async () => {
    const core = {...saved, core_source: {session_id: "session", scribe_source_id: "source", source_sha256: "c".repeat(64),
      schema_ref: "schema", transcript_ref: "transcript", note_ref: "core-note", note_sha256: "d".repeat(64), note_type: "Visit"}};
    await render({...initial, note: {latest: core, history: [core]}});
    expect(container.querySelector("textarea")!.readOnly).toBe(true);
    expect(button("Save note version")).toBeUndefined();
    expect(container.textContent).toContain("Core is checked again");
    await act(async () => container.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click());
    await click("Record private review");
    expect(onSave).toHaveBeenLastCalledWith({type: "review", noteId: saved.id, body: expect.objectContaining({content_hash: saved.content_hash})});
    await render({...initial, note: {latest: {...core, sources_changed: true}, history: [core]}});
    expect(button("Record private review")).toBeUndefined();
    expect(button("Save note version")).toBeUndefined();
  });
});
