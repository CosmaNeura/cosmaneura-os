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
