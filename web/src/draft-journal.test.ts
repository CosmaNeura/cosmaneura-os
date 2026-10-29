import {expect,it,vi} from "vitest";
import {DraftJournal,type NotebookDraft} from "./draft-journal";
import {memoryDraftStorage} from "./draft-test-fixture";

const workspaceId="00000000-0000-4000-8000-000000000021";
const ticketId="00000000-0000-4000-8000-000000000031";
const revision_id="00000000-0000-4000-8000-000000000032",payload_hash="c".repeat(64);
const decision={type:"followUpDecision" as const,ticketId,body:{revision_id,payload_hash,choice:"approve" as const}};
const complete={type:"followUpComplete" as const,ticketId,body:{revision_id,payload_hash,idempotency_key:"invented-completion-key",evidence:"Invented result checked."}};
const draft=(pending:unknown)=>({kind:"workspace",workspaceId,baseRevision:4,note:"Retained notebook",thought:"",evidence:"",source:"",pending}) as NotebookDraft;
const address=`workspace:${workspaceId}`;

it('checks an optional expected revision inside the write queue and preserves a newer queued edit',async()=>{
 const factory=memoryDraftStorage(),options={scope:'e'.repeat(64)},store=await factory(options);let release!:()=>void,hold=false;
 const journal=new DraftJournal({...store,async write(where,expected,value){if(hold){hold=false;await new Promise<void>(resolve=>{release=resolve;});}return store.write(where,expected,value);}});
 await journal.load(address);await journal.persist(address,draft(null));const expected=journal.records.get(address)!.revision;
 hold=true;const newer=journal.persist(address,{...draft(null),note:'Newer edit'});await vi.waitFor(()=>expect(release).toBeTypeOf('function'));
 const cleanup=journal.persist(address,{...draft(null),note:'Old restored value'},expected),refused=expect(cleanup).rejects.toMatchObject({code:'conflict'});
 release();await newer;await refused;expect(await journal.load(address)).toMatchObject({note:'Newer edit'});journal.close();
 const reopened=new DraftJournal(await factory(options));expect(await reopened.load(address)).toMatchObject({note:'Newer edit'});
});

it('checks expected revision before an identical-body no-op while leaving ordinary callers unchanged',async()=>{
 const journal=new DraftJournal(await memoryDraftStorage()({scope:'f'.repeat(64)}));await journal.load(address);
 await journal.persist(address,draft(null),null);const saved=journal.records.get(address)!.revision;
 await expect(journal.persist(address,draft(null),null)).rejects.toMatchObject({code:'conflict'});
 await journal.persist(address,draft(null),saved);await journal.persist(address,{...draft(null),note:'Ordinary caller'});
 expect(await journal.load(address)).toMatchObject({note:'Ordinary caller'});
});

it.each([decision,{...decision,body:{...decision.body,choice:"reject"}},complete])("round-trips the exact ticket request without adding notebook authority fields (%j)",async pending=>{
  const factory=memoryDraftStorage();const options={scope:"a".repeat(64)};
  const journal=new DraftJournal(await factory(options));await journal.load(address);
  await journal.persist(address,draft(pending));journal.close();
  const reopened=new DraftJournal(await factory(options));
  expect(await reopened.load(address)).toEqual(draft(pending));reopened.close();
});

it.each([
  {type:['entry'],body:{expected_revision:4,idempotency_key:'array-operation-type'}},
  {...decision,ticketId:"unbound-ticket"},
  {...decision,body:{...decision.body,revision_id:"not-a-revision"}},
  {...decision,body:{...decision.body,payload_hash:"wrong"}},
  {...decision,body:{...decision.body,choice:"automatic"}},
  {...decision,body:{...decision.body,expected_revision:4}},
  {...complete,body:{...complete.body,idempotency_key:"short"}},
  {...complete,body:{...complete.body,evidence:" "}},
  {...complete,body:{...complete.body,evidence:"x".repeat(2001)}},
])("refuses malformed ticket authority or completion evidence before persisting",async pending=>{
  const factory=memoryDraftStorage();const journal=new DraftJournal(await factory({scope:"a".repeat(64)}));
  await journal.load(address);await expect(journal.persist(address,draft(pending))).rejects.toMatchObject({code:"integrity"});
  expect(await journal.load(address)).toBeNull();journal.close();
});

it('preserves prior exact model uncertainty after settlement, rejects altered bindings, and never adopts mismatching history',async()=>{
 const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto'),{modelRequestHash}=await import('./model-work-request');
 const body={expected_revision:1,team_revision:1,idempotency_key:'prior-model-request',role:'scribe' as const,content:'Invented earlier question'};
 const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto');Object.defineProperty(globalThis,'crypto',{configurable:true,value:webcrypto});
 try{
  const prior={workspace_id:workspaceId,operation:{type:'ask' as const,body},request_sha256:await modelRequestHash(body),outcome:'unknown' as const,observed_at:'2026-09-21T22:00:00Z',origin:'durable_admission_v1' as const,legacy_uncertainty_acknowledged:false};
  const factory=memoryDraftStorage(),scope={scope:'d'.repeat(64)},journal=new DraftJournal(await factory(scope));await journal.load(address);const retained={...draft(null),previous_model_request:prior};await journal.persist(address,retained);journal.close();
  const reopened=new DraftJournal(await factory(scope));expect(await reopened.load(address)).toEqual(retained);
  await expect(reopened.persist(address,{...retained,previous_model_request:{...prior,operation:{...prior.operation,body:{...body,content:'Altered private text'}}}})).rejects.toMatchObject({code:'integrity'});
  expect(await reopened.load(address)).toEqual(retained);
  await expect(reopened.persist(address,{...retained,previous_model_request:{...prior,workspace_id:ticketId}})).rejects.toMatchObject({code:'integrity'});reopened.close();
 }finally{if(descriptor)Object.defineProperty(globalThis,'crypto',descriptor);}
});

it('retains only the exact reviewed Scribe request metadata and rejects added transcript text or missing sharing authority',async()=>{
 const data={idempotency_key:ticketId,expected_revision:4,selection:{version:1,session_id:revision_id,source_transcript_version:1,working_transcript_id:workspaceId,working_transcript_version:2,snapshot_sha256:'a'.repeat(64)},reviewed:true,share_with_team:true};
 const retained={kind:'editor' as const,workspaceId,editor:'scribe-source' as const,data,pending:ticketId},where=`editor:${workspaceId}:scribe-source`;
 const factory=memoryDraftStorage(),options={scope:'d'.repeat(64)},journal=new DraftJournal(await factory(options));await journal.load(where);
 await journal.persist(where,retained);journal.close();const reopened=new DraftJournal(await factory(options));expect(await reopened.load(where)).toEqual(retained);
 for(const changed of [{...data,transcript:'Must not be stored here'},{...data,reviewed:false},{...data,share_with_team:false},{...data,selection:{...data.selection,working_transcript_version:0}}])
  await expect(reopened.persist(where,{...retained,data:changed})).rejects.toMatchObject({code:'integrity'});
 await expect(reopened.persist(where,{...retained,pending:revision_id})).rejects.toMatchObject({code:'integrity'});
 expect(await reopened.load(where)).toEqual(retained);reopened.close();
});

it('round-trips only saved-note compose identity beside unsent words, rejecting extra authority or altered source metadata',async()=>{
  const task={contract:'chief-note-task.compose.v1' as const,note_id:revision_id,note_version:2,content_hash:'a'.repeat(64),source_fingerprint:'b'.repeat(64)};
  const retained={...draft(null),thought:'Verbatim invented owner directions. 界',chief_note_task:task};
  const factory=memoryDraftStorage(),options={scope:'d'.repeat(64)},journal=new DraftJournal(await factory(options));await journal.load(address);
  await journal.persist(address,retained);journal.close();const reopened=new DraftJournal(await factory(options));
  expect(await reopened.load(address)).toEqual(retained);
  for(const changed of [{...task,share_with_team:true},{...task,content:'Extra note content'},{...task,note_id:'unbound-note'},
    {...task,note_version:0},{...task,content_hash:'wrong'},{...task,source_fingerprint:'wrong'},
    {...task,note_id:[task.note_id]},{...task,content_hash:[task.content_hash]},{...task,source_fingerprint:[task.source_fingerprint]}])
    await expect(reopened.persist(address,{...retained,chief_note_task:changed as typeof task})).rejects.toMatchObject({code:'integrity'});
  expect(await reopened.load(address)).toEqual(retained);reopened.close();
});
