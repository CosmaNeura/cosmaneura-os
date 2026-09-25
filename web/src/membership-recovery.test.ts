import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {process,membershipFixtureScope as scope,membershipHistoryOperations} from './membership-test-fixture';
import {validateMembership} from './membership-contract';
import {prepareMembershipOperation} from './membership-operation';
import {emptyMembershipRecovery,validateMembershipRecovery,withMembershipCommand,hasUnresolvedMembershipCommand,persistMembershipRecovery,type MembershipRecoveryAccess} from './membership-recovery';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('exact bounded membership recovery',()=>{
 it('retains complete original commands and immutable receipts as the next action starts',async()=>{
  const h=validateMembership('History',process.history),ops=await membershipHistoryOperations(h);let r=emptyMembershipRecovery(scope);
  for(let i=0;i<ops.length;i++){r=withMembershipCommand(r,ops[i]);r={...r,receipt:h.items[i].receipt};r=await validateMembershipRecovery(r,scope);}
  expect(r.history).toHaveLength(3);expect(r.pending).toEqual(ops[3]);expect(r.history[2].operation.request).toEqual(h.items[2].request);expect(hasUnresolvedMembershipCommand(r)).toBe(false);
 });
 it('never clears an unknown or rejected exact request in favor of a new command',async()=>{
  const ops=await membershipHistoryOperations(validateMembership('History',process.history)),r=withMembershipCommand(emptyMembershipRecovery(scope),ops[0]);
  expect(()=>withMembershipCommand(r,ops[1])).toThrow();const notFound={contract_version:1 as const,scope,command_kind:ops[0].kind,idempotency_key:ops[0].request.idempotency_key,request_sha256:ops[0].request_sha256,outcome:'not_found' as const,effect:null,receipt_sha256:null};
  const retained=await validateMembershipRecovery({...r,receipt:notFound},scope);expect(hasUnresolvedMembershipCommand(retained)).toBe(true);expect(()=>withMembershipCommand(retained,ops[1])).toThrow();
 });
 it('rejects crossscope, forged receipts, unknown draft fields and inconsistent duplicate keys',async()=>{
  const h=validateMembership('History',process.history),ops=await membershipHistoryOperations(h),r={...emptyMembershipRecovery(scope),pending:ops[0],receipt:h.items[0].receipt};
  await expect(validateMembershipRecovery(r,{...scope,owner_id:crypto.randomUUID()})).rejects.toThrow();await expect(validateMembershipRecovery({...r,receipt:{...r.receipt,receipt_sha256:'0'.repeat(64)}},scope)).rejects.toThrow();await expect(validateMembershipRecovery({...r,draft:{...r.draft,consent:true}},scope)).rejects.toThrow();await expect(validateMembershipRecovery({...r,history:[{operation:ops[0],receipt:h.items[0].receipt}]},scope)).rejects.toThrow();
 });
 it('fails at the whole-record bound without clearing old pending proof or edited text',async()=>{
  const h=validateMembership('History',process.history),ops=await membershipHistoryOperations(h),r={...emptyMembershipRecovery(scope),pending:ops[2],receipt:h.items[2].receipt};r.draft.result_evidence='Retain this edited result';
  const before=structuredClone(r);const huge={...r,history:Array.from({length:100},()=>({operation:{...ops[0],request:{...ops[0].request,instructions:'🧪'.repeat(2000)}},receipt:h.items[0].receipt}))};
  expect(()=>withMembershipCommand(huge,ops[3])).toThrow();expect(r).toEqual(before);
  const access:MembershipRecoveryAccess={load:async()=>r,persist:vi.fn(async()=>{throw new Error('CAS');}),authorize:vi.fn(async()=>{})};await expect(persistMembershipRecovery(access,r)).rejects.toThrow('CAS');expect(r.pending).toEqual(ops[2]);expect(r.receipt).toEqual(h.items[2].receipt);expect(r.draft.result_evidence).toBe('Retain this edited result');
 });
 it('keeps local draft writes separate from fresh authorization at command admission',async()=>{
  const access:MembershipRecoveryAccess={load:async()=>null,persist:vi.fn(async()=>{}),authorize:vi.fn(async()=>{})},r=emptyMembershipRecovery(scope);r.draft.instructions='Unsent notes';await persistMembershipRecovery(access,r,{local:true});expect(access.authorize).not.toHaveBeenCalled();await persistMembershipRecovery(access,r);expect(access.authorize).toHaveBeenCalledOnce();
  const op=await prepareMembershipOperation(scope,'propose',validateMembership('Proposal',process.proposal_request));expect(op.request.idempotency_key).toBe(process.proposal_request.idempotency_key);
 });
});
