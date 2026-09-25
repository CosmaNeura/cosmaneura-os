import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {actual,inboxFixtureOperation,inboxFixtureScope as scope} from './inbox-test-fixture';
import {prepareInboxOperation,validateInbox,verifyInboxOperationReceipt} from './inbox-contract';
import {emptyInboxRecovery,emptyInboxDraft,validateInboxRecovery,withInboxDraft,withInboxCommand,continueInboxReview,parkInboxCommand,resumeInboxCommand,INBOX_RECOVERY_BYTES,INBOX_PROOF_RESERVE_BYTES,type InboxRecoveryRecord} from './inbox-recovery';
import {vendorBytes,vendorCanonical} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());

// Fill only invented editor text; all requests and terminal proofs remain exact
// copies of the frozen signed-main-app fixture. A second item is explicitly derived.
function fillTo(record:InboxRecoveryRecord,target:number):InboxRecoveryRecord{
  const next=structuredClone(record);
  next.drafts=Array.from({length:40},(_,i)=>emptyInboxDraft(`00000000-0000-4000-8000-${(i+1).toString(16).padStart(12,'0')}`,null,null));
  let remaining=target-vendorBytes(next);expect(remaining).toBeGreaterThanOrEqual(0);
  for(const draft of next.drafts)for(const field of ['instructions','result_evidence'] as const){
    const size=Math.min(remaining,2000);draft[field]='x'.repeat(size);remaining-=size;
  }
  expect(remaining).toBe(0);expect(vendorBytes(next)).toBe(target);return next;
}
async function fixture(kind:'review'|'rejected'='review'){
  const operation=await inboxFixtureOperation(kind),receipt=await verifyInboxOperationReceipt(operation,actual[`${kind}_receipt`]);
  const missing=validateInbox('Receipt',{...receipt,outcome:'not_found',effect:null,rejection:null,receipt_id:null,recorded_at:null,receipt_sha256:null});
  await verifyInboxOperationReceipt(operation,missing);return {operation,receipt,missing};
}
const growth=(receipt:InboxRecoveryRecord['receipt'])=>Math.max(0,INBOX_PROOF_RESERVE_BYTES-vendorBytes(receipt));

it.each([['pending','unknown'],['pending','not_found'],['parked','unknown'],['parked','not_found']] as const)('rejects a restored %s / %s record that cannot retain its eventual real proof',async(place,outcome)=>{
  const {operation,receipt,missing}=await fixture(),proof=outcome==='unknown'?null:missing;
  const seed:InboxRecoveryRecord=place==='pending'?{...emptyInboxRecovery(scope),pending:operation,receipt:proof}:{...emptyInboxRecovery(scope),parked:[{operation,receipt:proof}]};
  const record=fillTo(seed,INBOX_RECOVERY_BYTES-64),before=vendorCanonical(record);
  const active=place==='pending'?record:resumeInboxCommand(record,operation.request.item_id);
  expect(vendorBytes({...active,receipt})).toBeGreaterThan(INBOX_RECOVERY_BYTES);
  await expect(validateInboxRecovery(record,scope)).rejects.toThrow();expect(vendorCanonical(record)).toBe(before);
});

it('reserves the sum of pending and parked receipt growth rather than one command only',async()=>{
  const {operation}=await fixture();
  const second=await prepareInboxOperation(scope,'review',validateInbox('Review',{...actual.review_request,item_id:'00000000-0000-4000-8000-000000000099',idempotency_key:'invented-second-review'}));
  const record=fillTo({...emptyInboxRecovery(scope),pending:operation,parked:[{operation:second,receipt:null}]},INBOX_RECOVERY_BYTES-2500),before=vendorCanonical(record);
  expect(vendorBytes(record)+growth(null)+64).toBeLessThan(INBOX_RECOVERY_BYTES);
  await expect(validateInboxRecovery(record,scope)).rejects.toThrow();expect(vendorCanonical(record)).toBe(before);
});

it('checks normalized earlier version-one input without modifying or migrating away its exact pending work',async()=>{
  const {operation}=await fixture(),current=fillTo({...emptyInboxRecovery(scope),pending:operation},INBOX_RECOVERY_BYTES-64);
  const {parked:_empty,...legacy}=current,before=vendorCanonical(legacy);
  await expect(validateInboxRecovery(legacy,scope)).rejects.toThrow();expect(vendorCanonical(legacy)).toBe(before);expect(Object.hasOwn(legacy,'parked')).toBe(false);
});

it.each(['pending','parked'] as const)('accepts legitimate near-bound %s not_found input without reserving its existing proof twice',async place=>{
  const {operation,missing}=await fixture();
  const seed:InboxRecoveryRecord=place==='pending'?{...emptyInboxRecovery(scope),pending:operation,receipt:missing}:{...emptyInboxRecovery(scope),parked:[{operation,receipt:missing}]};
  const record=fillTo(seed,INBOX_RECOVERY_BYTES-growth(missing)-64),before=vendorCanonical(record);
  const restored=await validateInboxRecovery(record,scope);expect(restored).toEqual(record);
  expect(withInboxDraft(restored,restored.drafts.at(-1)!)).toEqual(record);
  const changed={...restored.drafts.at(-1)!,instructions:restored.drafts.at(-1)!.instructions+'x'};
  expect(()=>withInboxDraft(restored,changed)).toThrow();expect(vendorCanonical(record)).toBe(before);
});

it.each(['review','rejected'] as const)('keeps unknown → not_found → exact %s proof → history at the admission boundary',async kind=>{
  const {operation,receipt,missing}=await fixture(kind);
  const pending=fillTo({...emptyInboxRecovery(scope),pending:operation},INBOX_RECOVERY_BYTES-growth(null)-64);
  const record=withInboxCommand({...pending,pending:null},operation);
  expect(record).toEqual(pending);expect(await validateInboxRecovery(record,scope)).toEqual(record);
  const resolved=await validateInboxRecovery({...record,receipt:missing},scope);
  expect(withInboxDraft(resolved,resolved.drafts.at(-1)!)).toEqual(resolved);
  const terminal=await validateInboxRecovery({...resolved,receipt},scope),history=continueInboxReview(terminal);
  expect(vendorBytes(history)).toBeLessThanOrEqual(INBOX_RECOVERY_BYTES);expect(await validateInboxRecovery(history,scope)).toEqual(history);
  expect(vendorCanonical(history.history[0].operation)).toBe(vendorCanonical(operation));expect(vendorCanonical(history.history[0].receipt)).toBe(vendorCanonical(receipt));
  expect(history.pending).toBeNull();expect(history.receipt).toBeNull();
});

it('blocks parking at the reserved capacity boundary without changing the original request, proof or editor text',async()=>{
  const {operation}=await fixture(),record=fillTo({...emptyInboxRecovery(scope),pending:operation},INBOX_RECOVERY_BYTES-growth(null)-64),before=vendorCanonical(record);
  expect(await validateInboxRecovery(record,scope)).toEqual(record);
  expect(()=>parkInboxCommand(record)).toThrow();expect(vendorCanonical(record)).toBe(before);expect(record.pending).toEqual(operation);expect(record.parked).toEqual([]);
});

it('preserves exact work across near-bound park → restore → resume → not_found → park → terminal history',async()=>{
  const {operation,receipt,missing}=await fixture(),record=fillTo({...emptyInboxRecovery(scope),pending:operation},INBOX_RECOVERY_BYTES-growth(null)-128);
  const parked=parkInboxCommand(record),restored=await validateInboxRecovery(parked,scope),resumed=resumeInboxCommand(restored,operation.request.item_id);
  expect(resumed.pending).toEqual(operation);expect(resumed.receipt).toBeNull();expect(resumed.drafts).toEqual(record.drafts);
  const absent=await validateInboxRecovery({...resumed,receipt:missing},scope);
  const parkedAgain=await validateInboxRecovery(parkInboxCommand(absent),scope);
  expect(parkedAgain.parked).toEqual([{operation,receipt:missing}]);
  const terminal=await validateInboxRecovery({...resumeInboxCommand(parkedAgain,operation.request.item_id),receipt},scope);
  const history=continueInboxReview(terminal);expect(await validateInboxRecovery(history,scope)).toEqual(history);expect(history.history).toEqual([{operation,receipt}]);
});

it('retains terminal wrapper space and does not reserve future proof growth for historical work',async()=>{
  const {operation,receipt}=await fixture();
  const terminal=fillTo({...emptyInboxRecovery(scope),pending:operation,receipt},INBOX_RECOVERY_BYTES-64);
  expect(await validateInboxRecovery(terminal,scope)).toEqual(terminal);
  const archived=continueInboxReview(terminal);expect(vendorBytes(archived)).toBeLessThanOrEqual(INBOX_RECOVERY_BYTES);expect(await validateInboxRecovery(archived,scope)).toEqual(archived);
  const fullHistory=fillTo({...emptyInboxRecovery(scope),history:[{operation,receipt}]},INBOX_RECOVERY_BYTES);
  expect(await validateInboxRecovery(fullHistory,scope)).toEqual(fullHistory);expect(withInboxDraft(fullHistory,fullHistory.drafts.at(-1)!)).toEqual(fullHistory);
});
