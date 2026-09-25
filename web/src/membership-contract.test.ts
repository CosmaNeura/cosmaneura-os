import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {http,process,manual,membershipFixture} from './membership-test-fixture';
import integrated from './__fixtures__/membership/actual-membership-integrated-private-http.json';
import {validateMembership,verifyMembershipView} from './membership-contract';
import {prepareMembershipOperation,verifyMembershipOperationReceipt,verifyMembershipBundle} from './membership-operation';
import {vendorCanonical,vendorDigest} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('actual membership public R2 wire',()=>{
 it('validates the frozen combined-app private route proposal and current owner detail',async()=>{
  const d=await verifyMembershipView('Detail',integrated.detail),q=validateMembership('Proposal',integrated.request),op=await prepareMembershipOperation(d.scope,'propose',q);
  expect(await verifyMembershipOperationReceipt(op,integrated.receipt)).toEqual(integrated.receipt);expect(d.review.proposal).toEqual(q);expect(d.latest_result).toBeNull();expect(d.summary.state).toBe('pending_approval');
 });
 it('validates actual HTTP options and proposal receipt without operation creation or membership authority',async()=>{
  const o=await verifyMembershipView('Options',http.options),op=await prepareMembershipOperation(o.scope,'propose',validateMembership('Proposal',http.proposal_request));
  expect(await verifyMembershipOperationReceipt(op,http.receipt)).toEqual(http.receipt);expect((await verifyMembershipView('Detail',http.detail)).review.automatic_membership_changes).toBe(false);
 });
 it.each([process,manual])('verifies actual complete history and original saved result text',async actual=>{
  const bundle=await verifyMembershipBundle(actual.detail,actual.history);expect(bundle.detail.summary.external_service_verified).toBe(false);expect(bundle.detail.summary.membership_authority).toBe('not_established');
  for(const item of bundle.history.items){const op=await prepareMembershipOperation(bundle.history.scope,item.receipt.command_kind,item.request);expect(await verifyMembershipOperationReceipt(op,item.receipt)).toEqual(item.receipt);}
 });
 it.each(['missing','duplicate','text','result_id','receipt_sha','scope','revision','classification','forged_authority','wrong_state'])('rejects %s before private result disclosure',async mode=>{
  const d=structuredClone(process.detail) as any,h=structuredClone(process.history) as any;
  if(mode==='missing')h.items.splice(1,1);if(mode==='duplicate')h.items[1]=h.items[0];if(mode==='text')d.latest_result.request.evidence='Never recorded';if(mode==='result_id')d.latest_result.receipt_id=crypto.randomUUID();if(mode==='receipt_sha')h.items[2].receipt.receipt_sha256='0'.repeat(64);if(mode==='scope')h.scope.owner_id=crypto.randomUUID();if(mode==='revision')d.summary.revision_id=crypto.randomUUID();if(mode==='classification')d.summary.evidence_classification='manual_ledger_record';if(mode==='forged_authority')d.summary.external_service_verified=true;if(mode==='wrong_state')d.summary.state='approved';
  await expect(verifyMembershipBundle(d,h)).rejects.toThrow();
 });
 it('requires exact result receipt correspondence even after an attacker recomputes its request hash',async()=>{
  const h=structuredClone(process.history),r=h.items[2];(r.request as {evidence:string}).evidence='Altered text';r.receipt.request_sha256=await vendorDigest('cosmas-membership-request.v1',{scope:h.scope,command_kind:'result',request:r.request});
  await expect(verifyMembershipBundle(process.detail,h)).rejects.toThrow();
 });
 it('normalizes request text before hashing but rejects noncanonical stored requests and explicit null evidence',async()=>{
  const q=validateMembership('Proposal',http.proposal_request),scope=validateMembership('Scope',http.options.scope),op=await prepareMembershipOperation(scope,'propose',{...q,instructions:'one\r\ntwo'});expect(op.request.instructions).toBe('one\ntwo');
  expect(()=>validateMembership('Proposal',{...q,instructions:'one\r\ntwo'})).toThrow();
  const r=process.history.items[2].request;expect(()=>validateMembership('Result',{...r,ledger:null})).toThrow();expect(()=>validateMembership('Result',{...r,disposition:'record_reviewed'})).toThrow();
 });
 it('rejects source/command extras and an otherwise bounded text request over8KiB',async()=>{
  const q=validateMembership('Proposal',http.proposal_request),scope=validateMembership('Scope',http.options.scope);
  await expect(prepareMembershipOperation(scope,'propose',{...q,instructions:'🧪'.repeat(2000)})).rejects.toThrow();
  expect(()=>validateMembership('Proposal',{...q,url:'https://unknown.invalid'})).toThrow();expect(()=>validateMembership('Scope',{...scope,actor_id:scope.owner_id})).toThrow();
 });
 it('keeps manual and local derived UI states distinct and never restores service authority',async()=>{
  const local=await membershipFixture(3),ledger=await membershipFixture(3,true);expect(local.detail.summary.evidence_classification).toBe('local_unreconciled');expect(ledger.detail.summary.evidence_classification).toBe('manual_ledger_record');expect(ledger.detail.summary.can_verify).toBe(true);
  expect(vendorCanonical(local.detail)).not.toContain('external_service_verified":true');
 });
});
