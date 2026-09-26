import {beforeEach,it,expect,vi} from 'vitest';
import actual from './__fixtures__/inbox-handoff/actual-owner-review-http.json';
import {prepareInboxHandoffOperation,validateInboxHandoff,verifyInboxHandoffOperationReceipt,verifyInboxHandoffView} from './inbox-handoff-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));
const ownerScope=()=>({...validateInboxHandoff('Scope',actual.receipt.scope),kind:'ticket' as const,id:actual.detail.ticket_id});
it('validates the byte-preserved actual local HTTP owner review and exact proposal receipt',async()=>{const op=await prepareInboxHandoffOperation(validateInboxHandoff('Scope',actual.receipt.scope),'propose',validateInboxHandoff('Propose',actual.request));expect(op.request_sha256).toBe(actual.receipt.request_sha256);expect(await verifyInboxHandoffOperationReceipt(op,actual.receipt)).toEqual(actual.receipt);const d=await verifyInboxHandoffView('Detail',actual.detail,ownerScope());expect(d.due_date).toBe(actual.request.due_date);expect(d.expected_outcome).toBe(actual.request.expected_outcome);expect(d.publication_active).toBe(false);});
it('refuses altered due date or outcome in a fresh unpublished owner review',async()=>{await expect(verifyInboxHandoffView('Detail',{...actual.detail,due_date:'2026-10-03'},ownerScope())).rejects.toThrow();await expect(verifyInboxHandoffView('Detail',{...actual.detail,expected_outcome:'Changed outcome'},ownerScope())).rejects.toThrow();});
it('does not accept this owner-private unpublished review as a staff disclosure',async()=>{await expect(verifyInboxHandoffView('Detail',actual.detail,{...ownerScope(),actor_id:crypto.randomUUID()})).rejects.toThrow();});
