import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {actual,inboxFixtureOperation,inboxFixtureScope as scope} from './inbox-test-fixture';
import {emptyInboxRecovery,emptyInboxDraft,validateInboxRecovery,withInboxDraft,withInboxCommand,continueInboxReview,unresolvedInboxCommand,parkInboxCommand,resumeInboxCommand,INBOX_RECOVERY_BYTES,INBOX_PROOF_RESERVE_BYTES} from './inbox-recovery';
import {validateInbox} from './inbox-contract';
import {vendorBytes} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it.each(['review','rejected'] as const)('keeps the exact terminal %s proof with its command',async kind=>{
  const operation=await inboxFixtureOperation(kind),receipt=validateInbox('Receipt',actual[`${kind}_receipt`]);
  const initial={...emptyInboxRecovery(scope),pending:operation,receipt};
  expect(unresolvedInboxCommand(initial)).toBe(false);
  const archived=continueInboxReview(await validateInboxRecovery(initial,scope));
  expect(archived.pending).toBeNull();expect(archived.history).toEqual([{operation,receipt}]);
  expect(await validateInboxRecovery(archived,scope)).toEqual(archived);
});
it('never discards a not_found or unknown command',async()=>{
  const operation=await inboxFixtureOperation(),record=withInboxCommand(emptyInboxRecovery(scope),operation);
  const missing=validateInbox('Receipt',{...actual.review_receipt,outcome:'not_found',effect:null,rejection:null,receipt_id:null,recorded_at:null,receipt_sha256:null});
  const next=await validateInboxRecovery({...record,receipt:missing},scope);
  expect(unresolvedInboxCommand(next)).toBe(true);expect(()=>continueInboxReview(next)).toThrow();
  expect(()=>withInboxCommand(next,operation)).toThrow();expect(next.pending).toEqual(operation);
});
it('retains separate typed drafts for current and earlier sources without stored consent',async()=>{
  const d=emptyInboxDraft(actual.initial.summary.item_id,actual.initial.summary.source_id,actual.initial.summary.source_sha256);
  let record=withInboxDraft(emptyInboxRecovery(scope),{...d,instructions:'Earlier unfinished instructions'});
  record=withInboxDraft(record,{...d,source_id:crypto.randomUUID(),source_sha256:'f'.repeat(64),instructions:'Current instructions'});
  expect((await validateInboxRecovery(record,scope)).drafts.map(v=>v.instructions)).toEqual(['Earlier unfinished instructions','Current instructions']);
  await expect(validateInboxRecovery({...record,drafts:[{...d,reviewed_patient:true}]},scope)).rejects.toThrow();
});
it.each(['scope','altered_command','altered_receipt','duplicate','unpaired_source','unknown_field','oversize'] as const)('rejects %s recovery without dropping its original input',async fault=>{
  const op=await inboxFixtureOperation(),receipt=validateInbox('Receipt',actual.review_receipt);
  const original={...emptyInboxRecovery(scope),pending:op,receipt},bad=structuredClone(original) as any;
  if(fault==='scope')bad.scope.owner_id=crypto.randomUUID();
  if(fault==='altered_command')bad.pending.request.expected_version++;
  if(fault==='altered_receipt')bad.receipt.receipt_sha256='f'.repeat(64);
  if(fault==='duplicate')bad.history=[{operation:op,receipt}];
  if(fault==='unpaired_source')bad.drafts=[{...emptyInboxDraft(op.request.item_id,null,null),source_sha256:'f'.repeat(64)}];
  if(fault==='unknown_field')bad.discard_pending=true;
  if(fault==='oversize')bad.drafts=Array.from({length:101},()=>emptyInboxDraft(crypto.randomUUID(),null,null));
  await expect(validateInboxRecovery(bad,scope)).rejects.toThrow();
  expect(original.pending).toEqual(op);expect(original.receipt).toEqual(receipt);
});
it('parks an unresolved exact command without authorizing another command for that item',async()=>{
  const op=await inboxFixtureOperation(),initial=withInboxCommand(emptyInboxRecovery(scope),op);
  const parked=await validateInboxRecovery(parkInboxCommand(initial),scope);
  expect(parked.pending).toBeNull();expect(parked.parked).toEqual([{operation:op,receipt:null}]);
  expect(()=>withInboxCommand(parked,op)).toThrow();
  const resumed=resumeInboxCommand(parked,op.request.item_id);
  expect(resumed.pending).toEqual(op);expect(resumed.receipt).toBeNull();expect(resumed.parked).toEqual([]);
});
it('rejects duplicate parked items and terminal proofs mislabeled as unresolved',async()=>{
  const op=await inboxFixtureOperation(),record=emptyInboxRecovery(scope);
  await expect(validateInboxRecovery({...record,parked:[{operation:op,receipt:null},{operation:op,receipt:null}]},scope)).rejects.toThrow();
  await expect(validateInboxRecovery({...record,parked:[{operation:op,receipt:actual.review_receipt}]},scope)).rejects.toThrow();
});
it('reserves journal space for a later receipt before admitting a command or expanding another draft',async()=>{
  const op=await inboxFixtureOperation(),record=emptyInboxRecovery(scope);
  record.drafts=Array.from({length:40},()=>emptyInboxDraft(crypto.randomUUID(),null,null));
  let remaining=INBOX_RECOVERY_BYTES-1024-vendorBytes(record);
  for(const draft of record.drafts)for(const field of ['instructions','result_evidence'] as const){const size=Math.min(remaining,2000);draft[field]='x'.repeat(size);remaining-=size;}
  expect(remaining).toBe(0);expect(await validateInboxRecovery(record,scope)).toEqual(record);
  expect(()=>withInboxCommand(record,op)).toThrow();expect(record.pending).toBeNull();
  const parked={...record,parked:[{operation:op,receipt:null}]};
  expect(()=>withInboxDraft(parked,{...record.drafts.at(-1)!,instructions:'Retained earlier input'})).toThrow();
  expect(parked.parked[0].operation).toEqual(op);
});
it('the closed maximum-length receipt fits its reserved proof bytes',()=>{
  const receipt=validateInbox('Receipt',{...actual.verify_receipt,command_kind:'verify',idempotency_key:'x'.repeat(100),effect:{...actual.verify_receipt.effect,version:100,state:'closed_local_review'}});
  expect(vendorBytes(receipt)+64).toBeLessThan(INBOX_PROOF_RESERVE_BYTES);
});
it.each(['review','rejected'] as const)('migrates only the known earlier version1 shape while preserving exact %s work',async kind=>{
  const operation=await inboxFixtureOperation(kind),receipt=validateInbox('Receipt',actual[`${kind}_receipt`]);
  const current={...emptyInboxRecovery(scope),drafts:[{...emptyInboxDraft(operation.request.item_id,null,null),instructions:'Earlier saved input'}],pending:operation,receipt};
  const {parked:_empty,...legacy}=current;
  expect(await validateInboxRecovery(legacy,scope)).toEqual(current);
  await expect(validateInboxRecovery({...legacy,forgotten_commands:[]},scope)).rejects.toThrow();
  expect(legacy.pending).toEqual(operation);expect(legacy.receipt).toEqual(receipt);
});
