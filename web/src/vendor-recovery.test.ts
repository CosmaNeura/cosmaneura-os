import {describe,it,expect,vi} from 'vitest';
import {actual,artifact,shared,actualContent,actualProposal,actualAcceptance} from './vendor-test-fixture';
import {validateVendor,vendorCanonical} from './vendor-contract';
import {emptyVendorRecovery,validateVendorRecovery,recordVendorCommand,recordVendorReceipt} from './vendor-recovery';
import {prepareVendorOperation,validateVendorOperation,verifyOperationReceipt,vendorOperationPath} from './vendor-operation';

describe('exact metadata-only delivery recovery',()=>{
  it('crosses actual proposal, content, acceptance and immutable replay HTTP receipts',async()=>{
    const proposal=await actualProposal();expect(proposal.request_sha256).toBe(actual.proposal_receipt.request_sha256);await verifyOperationReceipt(proposal,actual.proposal_receipt);
    const content=await actualContent();expect(content.request_sha256).toBe(artifact.artifact_content_receipt.request_sha256);await verifyOperationReceipt(content,artifact.artifact_replay_receipt);
    const acceptance=await actualAcceptance();expect(acceptance.request_sha256).toBe(shared.shared_accept_receipt.request_sha256);await verifyOperationReceipt(acceptance,shared.shared_accept_receipt);expect(vendorOperationPath(acceptance)).toBe(`/practice-work/${acceptance.scope.id}/handoffs`);
  });
  it('persists the exact command before any caller can dispatch; refuses replacement while unknown',async()=>{
    const op=await actualProposal();const access={load:async()=>null,persist:vi.fn().mockResolvedValue(undefined),authorize:vi.fn().mockResolvedValue(undefined)};
    const saved=await recordVendorCommand(access,emptyVendorRecovery(op.scope),op);expect(access.persist).toHaveBeenCalledWith(saved);expect(saved.pending).toEqual(op);
    const changed=await prepareVendorOperation(op.scope,'propose',null,{...op.request,idempotency_key:'different-exact-key'});
    await expect(recordVendorCommand(access,saved,changed)).rejects.toThrow();expect(access.persist).toHaveBeenCalledTimes(1);
    const confirmed=await recordVendorReceipt(access,saved,actual.proposal_receipt);await expect(recordVendorCommand(access,confirmed,changed)).resolves.toMatchObject({pending:changed});
  });
  it('retains the original content key independently from the next known command',async()=>{
    const op=await actualContent(),metadata=validateVendor('ArtifactResponse',artifact.artifact_content_receipt).artifact!;
    const record={...emptyVendorRecovery(op.scope),artifact:metadata,artifact_write:op,pending:op,receipt:validateVendor('ArtifactResponse',artifact.artifact_content_receipt)};
    expect((await validateVendorRecovery(record,op.scope)).artifact_write).toEqual(op);
    const wrong={...record,artifact_write:{...op,request:{...op.request,sha256:'a'.repeat(64)}}};await expect(validateVendorRecovery(wrong,op.scope)).rejects.toThrow();
  });
  it('rejects other scopes, wire mutations, raw bytes and private fields in staff recovery',async()=>{
    const op=await actualProposal();await expect(validateVendorOperation({...op,request:{...op.request,message:'changed'}})).rejects.toThrow();
    await expect(validateVendorRecovery({...emptyVendorRecovery(op.scope),pdf:new Uint8Array([1])},op.scope)).rejects.toThrow();
    const staff=await actualAcceptance(),r=emptyVendorRecovery(staff.scope);await expect(validateVendorRecovery({...r,draft:{...r.draft,message:'private content'}},staff.scope)).rejects.toThrow();
    await expect(validateVendorRecovery(emptyVendorRecovery(op.scope),staff.scope)).rejects.toThrow();
    expect(vendorCanonical(r)).not.toContain('request_bytes');
  });
  it('rejects over-sized partial drafts and unauthorized staff dispositions',async()=>{
    const op=await actualProposal(),r=emptyVendorRecovery(op.scope);await expect(validateVendorRecovery({...r,draft:{...r.draft,message:'😀'.repeat(4001)}},r.scope)).rejects.toThrow();
    const s=await actualAcceptance();await expect(prepareVendorOperation(s.scope,'submit',s.scope.id,{expected_version:1,operation_id:s.scope.id,revision_id:s.scope.id,payload_hash:'a'.repeat(64),idempotency_key:'invalid-staff-send'})).rejects.toThrow();
  });
  it('migrates only the exact old R1 shape and verifies retained receipt history without truncation',async()=>{
    const op=await actualProposal(),r=emptyVendorRecovery(op.scope);const old=structuredClone(r) as any;delete old.receipts;delete old.retired_commands;delete old.draft.revises;delete old.draft.supersedes;expect(await validateVendorRecovery(old,op.scope)).toEqual(r);
    const r2=structuredClone(r) as any;delete r2.retired_commands;delete r2.draft.supersedes;expect(await validateVendorRecovery(r2,op.scope)).toEqual(r);
    const r4=structuredClone(r) as any;delete r4.retired_commands;expect(await validateVendorRecovery(r4,op.scope)).toEqual(r);await expect(validateVendorRecovery({...old,retired_commands:[]},op.scope)).rejects.toThrow();
    await expect(validateVendorRecovery({...old,unexpected:1},op.scope)).rejects.toThrow();await expect(validateVendorRecovery({...old,receipts:[]},op.scope)).rejects.toThrow();
    const valid={...r,receipts:[validateVendor('CommandResponse',actual.proposal_receipt)]};expect((await validateVendorRecovery(valid,op.scope)).receipts).toEqual(valid.receipts);
    const bad=structuredClone(valid);bad.receipts[0].request_sha256='a'.repeat(64);await expect(validateVendorRecovery(bad,op.scope)).rejects.toThrow();
    await expect(validateVendorRecovery({...valid,receipts:[...valid.receipts,...valid.receipts]},op.scope)).rejects.toThrow();
  });
});
