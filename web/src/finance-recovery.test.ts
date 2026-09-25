import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {actual,actualFinanceProposal,actualFinanceApproval} from './finance-test-fixture';
import {emptyFinanceRecovery,validateFinanceRecovery,withFinanceCommand,persistFinanceRecovery} from './finance-recovery';
import {validateFinance} from './finance-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
it('retains exact pending command and compact immutable prior receipts without restoring consent',async()=>{
  const op=await actualFinanceProposal(),approval=await actualFinanceApproval(),r={...emptyFinanceRecovery(op.scope),pending:op,receipt:validateFinance('FinanceResponse',actual.proposal_receipt)};
  const next=withFinanceCommand(r,approval);expect(next.receipts).toEqual([actual.proposal_receipt]);expect((await validateFinanceRecovery(next,op.scope)).pending).toEqual(approval);expect('reviewed'in next.draft).toBe(false);
});
it('refuses replacing an unresolved command or crossing workspace/command/hash scope',async()=>{
  const op=await actualFinanceProposal(),r={...emptyFinanceRecovery(op.scope),pending:op};
  const next=await actualFinanceApproval();expect(()=>withFinanceCommand(r,next)).toThrow();await expect(validateFinanceRecovery(r,{kind:'workspace',id:crypto.randomUUID()})).rejects.toThrow();
  await expect(validateFinanceRecovery({...r,pending:{...op,request_sha256:'0'.repeat(64)}},op.scope)).rejects.toThrow();await expect(validateFinanceRecovery({...r,draft:{...r.draft,approved:true}},op.scope)).rejects.toThrow();
});
it('rejects damaged or excessive receipt histories instead of silently discarding them',async()=>{
  const op=await actualFinanceProposal(),r=emptyFinanceRecovery(op.scope),receipt=structuredClone(actual.proposal_receipt);receipt.effect.effect='approved';await expect(validateFinanceRecovery({...r,receipts:[receipt]},op.scope)).rejects.toThrow();
  await expect(validateFinanceRecovery({...r,receipts:Array(101).fill(actual.proposal_receipt)},op.scope)).rejects.toThrow();
});
it('uses the supplied encrypted journal and leaves its old saved value on CAS failure',async()=>{
  const op=await actualFinanceProposal(),old=emptyFinanceRecovery(op.scope),persist=vi.fn().mockRejectedValue(new Error('CAS conflict')),authorize=vi.fn(async()=>{});const access={load:async()=>old,persist,authorize};
  await expect(persistFinanceRecovery(access,{...old,pending:op})).rejects.toThrow('CAS conflict');expect(await access.load()).toEqual(old);expect(authorize).toHaveBeenCalledTimes(1);
  persist.mockResolvedValue(undefined);await persistFinanceRecovery(access,{...old,draft:{...old.draft,amount:'1'}},{local:true});expect(authorize).toHaveBeenCalledTimes(1);
});
it('migrates only the exact old editable shape and keeps its saved command unchanged',async()=>{
  const op=await actualFinanceProposal(),r={...emptyFinanceRecovery(op.scope),pending:op};const {revises:_,...oldDraft}=r.draft;
  const restored=await validateFinanceRecovery({...r,draft:oldDraft},op.scope);expect(restored.draft.revises).toBeNull();expect(restored.pending).toEqual(op);await expect(validateFinanceRecovery({...r,draft:{...oldDraft,unknown:null}},op.scope)).rejects.toThrow();await expect(validateFinanceRecovery({...r,draft:{...oldDraft,revises:{ticket_id:'not-a-uuid'}}},op.scope)).rejects.toThrow();
});
