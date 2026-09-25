import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {actual,processActual,processR3,revisionPending,revisionApproved,actualFinanceProposal,actualFinanceApproval,actualFinanceOptions} from './finance-test-fixture';
import {validateFinance,normalizeFinance,verifyFinanceView,verifyFinanceReceipt} from './finance-contract';
import {prepareFinanceOperation,validateFinanceOperation,verifyFinanceOperationReceipt,type FinanceKind,type FinanceRequests} from './finance-operation';
import {completeFinanceEvidence,financeCents,financeProposalIssue} from './FinanceWorkPanel';
import {emptyFinanceDraft} from './finance-recovery';
import {vendorDigest} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('actual private finance public contract',()=>{
  it('validates current options, catalog, result and actual process payment states with their hashes',async()=>{
    await verifyFinanceView('FinanceOptions',actual.options);await verifyFinanceView('FinanceCatalog',actual.catalog);await verifyFinanceView('FinanceObservations',actual.observations);
    for(const value of [actual.pending_detail,actual.result_detail,...Object.entries(processActual).filter(([k])=>k.endsWith('_detail')).map(([,v])=>v)])await verifyFinanceView('FinanceDetail',value);
    for(const value of [actual.proposal_receipt,actual.approval_receipt,actual.result_receipt,processActual.result_receipt,processActual.verify_receipt])await verifyFinanceReceipt(value,{scope:{kind:'workspace',id:value.scope.id},kind:value.command_kind,key:value.idempotency_key,sha256:value.request_sha256});
  });
  it('reconstructs exact actual proposal and approval request digests and resolves their same receipts',async()=>{
    const p=await actualFinanceProposal(),a=await actualFinanceApproval();expect(p.request_sha256).toBe(actual.proposal_receipt.request_sha256);expect(a.request_sha256).toBe(actual.approval_receipt.request_sha256);
    expect(await verifyFinanceOperationReceipt(p,actual.proposal_resolved)).toMatchObject({effect:actual.proposal_receipt.effect,receipt_sha256:actual.proposal_receipt.receipt_sha256});await verifyFinanceOperationReceipt(a,actual.approval_receipt);expect(await validateFinanceOperation(p)).toEqual(p);
  });
  it('rejects changed selections, current evidence, review and receipt rather than trusting labels',async()=>{
    const o=structuredClone(actual.options);o.customers[0].label+=' changed';await expect(verifyFinanceView('FinanceOptions',o)).rejects.toThrow();
    const d=structuredClone(actual.pending_detail);d.review.amount++;await expect(verifyFinanceView('FinanceDetail',d)).rejects.toThrow();const e=structuredClone(actual.result_detail);e.latest_result.evidence='changed';e.summary.evidence_sha256='0'.repeat(64);await expect(verifyFinanceView('FinanceDetail',e)).rejects.toThrow();
    const receipt=structuredClone(actual.proposal_receipt);receipt.effect.operation_id=crypto.randomUUID();await expect(verifyFinanceOperationReceipt(await actualFinanceProposal(),receipt)).rejects.toThrow();
  });
  it('strictly validates USD cents and required proposal fields',()=>{
    for(const [text,cents] of [['0.50',50],['125.01',12501],['1',100],['1.2',120],['999999.99',99999999]] as const)expect(financeCents(text)).toBe(cents);
    for(const text of ['0.49','1000000','1e2','1.001','NaN','-12','1,234','01.00',' 12'])expect(financeCents(text)).toBeNull();
    const o=actualFinanceOptions(),d={...emptyFinanceDraft(),connection_id:o.connections[0].id,customer_id:o.customers[0].id,source:o.source,amount:'125.00',due_date:'2026-10-01',expected_outcome:'Invented payment goal'};expect(financeProposalIssue(o,d)).toBeNull();expect(financeProposalIssue(o,{...d,due_date:''})).toBe('Choose a due date.');expect(financeProposalIssue(o,{...d,due_date:'2026-02-30'})).toBe('Choose a valid calendar date.');expect(financeProposalIssue(o,{...d,customer_id:''})).toContain('reviewed patient');expect(financeProposalIssue(o,{...d,source:null})).toContain('reviewed note');
  });
  it('rejects unknown fields, null command fields, fractional cents and incoherent receipt/payment unions',async()=>{
    const op=await actualFinanceProposal();for(const request of [{...op.request,secret:'forbidden'},{...op.request,amount:125.5},{...op.request,source:null}])expect(()=>validateFinance('FinanceProposal',request)).toThrow();
    expect(()=>validateFinance('FinanceResponse',{...actual.proposal_receipt,outcome:'not_found'})).toThrow();expect(()=>validateFinance('FinanceResponse',{...actual.proposal_receipt,command_kind:'verify'})).toThrow();
    const row={id:crypto.randomUUID(),sequence:1,operation_id:actual.pending_detail.summary.operation_id,recorded_at:actual.proposal_receipt.observed_at,sha256:'a'.repeat(64),kind:'payment',payment_state:'succeeded',amount:100,currency:'usd',amount_received:50};expect(()=>validateFinance('FinancePayment',row)).toThrow();
    const normalized=normalizeFinance('FinanceProposal',{...op.request,expected_outcome:'Line one\r\nLine two 🩺'});expect(normalized.expected_outcome).toBe('Line one\nLine two 🩺');expect(()=>validateFinance('FinanceProposal',{...op.request,expected_outcome:'Line one\r\nLine two'})).toThrow();
  });
  it('does not confuse an empty reviewed evidence chain with payment or completion',async()=>{
    const page=validateFinance('FinanceObservations',actual.observations),summary=validateFinance('FinanceDetail',actual.result_detail).summary;expect(await completeFinanceEvidence(page,summary)).toBe(true);expect(summary.payment_state).toBe('not_observed');expect(summary.verification).toBe('pending');
    expect(await completeFinanceEvidence({...page,observation_head:{...page.observation_head,sequence:1}},summary)).toBe(false);
  });
  it('verifies all six exact actual signed-process commands and the complete paid evidence chain',async()=>{
    for(const command of processR3.commands){const kind=command.kind as FinanceKind,scope={kind:'workspace' as const,id:command.response.scope.id};const op=await prepareFinanceOperation(scope,kind,kind==='propose'?null:command.response.effect.ticket_id,command.request as FinanceRequests[FinanceKind]);expect(op.request_sha256).toBe(command.response.request_sha256);await verifyFinanceOperationReceipt(op,command.response);}
    const page=await verifyFinanceView('FinanceObservations',processR3.observations),detail=await verifyFinanceView('FinanceDetail',processR3.paid_detail);expect(page.observations).toHaveLength(3);expect(await completeFinanceEvidence(page,detail.summary)).toBe(true);
    expect(await completeFinanceEvidence({...page,observations:page.observations.slice(1)},detail.summary)).toBe(false);expect(await completeFinanceEvidence({...page,observations:[...page.observations].reverse()},detail.summary)).toBe(false);
  });
  it('binds a revision receipt to its original ticket and a newly created revision instead of reusing approval',async()=>{
    const prior=await actualFinanceProposal(),d=validateFinance('FinanceDetail',actual.pending_detail),r=d.summary;
    const op=await prepareFinanceOperation(prior.scope,'propose',null,{...prior.request,idempotency_key:'new-finance-revision',proposed_operation_id:crypto.randomUUID(),amount:15025,revises:{ticket_id:r.ticket_id,expected_version:r.version,revision_id:r.revision_id,payload_hash:r.payload_hash}});
    const receipt={...structuredClone(actual.proposal_receipt),idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,effect:{...structuredClone(actual.proposal_receipt.effect),revision_id:crypto.randomUUID() as string,operation_id:op.request.proposed_operation_id,payload_hash:'c'.repeat(64),effect_version:r.version+1}};
    const sign=async(value:typeof receipt)=>{value.receipt_sha256=await vendorDigest('cosmas-finance-public-receipt.v1',{scope:value.scope,command_kind:value.command_kind,idempotency_key:value.idempotency_key,request_sha256:value.request_sha256,effect:value.effect});return value;};await verifyFinanceOperationReceipt(op,await sign(receipt));
    for(const patch of [{ticket_id:crypto.randomUUID()},{revision_id:r.revision_id},{payload_hash:r.payload_hash},{effect_version:r.version}])await expect(verifyFinanceOperationReceipt(op,await sign({...receipt,effect:{...receipt.effect,...patch}}))).rejects.toThrow();
    expect(()=>validateFinance('FinanceProposal',{...op.request,revises:null})).toThrow();
  });
  it.each([['pending',revisionPending],['approved',revisionApproved]] as const)('validates the exact actual %s revision, retained old receipt and fresh approval',async(_state,fixture)=>{
    const prior=await verifyFinanceView('FinanceDetail',fixture.prior_detail),pending=await verifyFinanceView('FinanceDetail',fixture.pending_detail);
    const request=validateFinance('FinanceProposal',fixture.revision_request),scope={kind:'workspace' as const,id:prior.workspace_id};
    const op=await prepareFinanceOperation(scope,'propose',null,request);
    expect(op.request_sha256).toBe(fixture.revision_receipt.request_sha256);
    expect(op.request.revises).toEqual({ticket_id:prior.summary.ticket_id,expected_version:prior.summary.version,revision_id:prior.summary.revision_id,payload_hash:prior.summary.payload_hash});
    const receipt=await verifyFinanceOperationReceipt(op,fixture.revision_receipt),replay=await verifyFinanceOperationReceipt(op,fixture.revision_replayed);
    expect(replay.effect).toEqual(receipt.effect);expect(replay.receipt_sha256).toBe(receipt.receipt_sha256);
    expect(pending.summary).toMatchObject({ticket_id:prior.summary.ticket_id,version:prior.summary.version+1,state:'pending_approval',submit_claimed:false,verification:'pending'});
    expect(pending.summary.revision_id).not.toBe(prior.summary.revision_id);expect(pending.summary.operation_id).not.toBe(prior.summary.operation_id);expect(pending.summary.payload_hash).not.toBe(prior.summary.payload_hash);
    expect(pending.review.amount).toBe(request.amount);expect(pending.review.due_date).toBe(request.due_date);expect(pending.review.expected_outcome).toBe(request.expected_outcome);
    const old=fixture.old_resolved;await verifyFinanceReceipt(old,{scope,kind:old.command_kind,key:old.idempotency_key,sha256:old.request_sha256,ticketId:prior.summary.ticket_id,revisionId:prior.summary.revision_id,operationId:prior.summary.operation_id,payloadHash:prior.summary.payload_hash});
    const approval=await prepareFinanceOperation(scope,'decide',pending.summary.ticket_id,validateFinance('FinanceDecision',fixture.approval_request));
    expect(approval.request_sha256).toBe(fixture.approval_receipt.request_sha256);expect(approval.request.review_sha256).toBe(pending.review_sha256);expect(approval.request.revision_id).toBe(pending.summary.revision_id);
    expect((await verifyFinanceOperationReceipt(approval,fixture.approval_receipt)).effect?.effect).toBe('approved');
  });
});
