import {beforeEach,afterEach,describe,expect,it,vi} from 'vitest';
import {portalFixture,actualPortalCatalog,actualPortalProposal} from './portal-setup-test-fixture';
import {preparePortalOperation,verifyPortalReceipt,verifyPortalDetail,verifyPortalCatalog} from './portal-setup-contract';
import {emptyPortalRecovery,validatePortalRecovery} from './portal-setup-recovery';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('portal setup closed contracts from signed HTTP and real PostgreSQL',()=>{
  it('verifies actual proposal, activation, mapping digests and contiguous history after process restart',async()=>{
    await actualPortalCatalog();const op=await actualPortalProposal();await verifyPortalReceipt(portalFixture.proposal_receipt,op);
    const active=await preparePortalOperation(op.scope,'activate',portalFixture.activation as Parameters<typeof preparePortalOperation>[2]);
    await verifyPortalReceipt(portalFixture.activation_receipt,active);await verifyPortalDetail(portalFixture.detail_active);
    for(const receipt of portalFixture.history.receipts)await verifyPortalReceipt(receipt);
    expect(portalFixture.history.receipts.map(r=>r.effect.version)).toEqual([1,2,3,4]);
  });
  it.each([false,'true',1,null])('rejects nonliteral activation confirmation %s',async value=>{
    await expect(preparePortalOperation(portalFixture.proposal_receipt.scope,'activate',{...portalFixture.activation,reviewed_patient:value} as never)).rejects.toThrow();
  });
  it.each(['https://portal.example.invalid','../path','*',12345678])('rejects an endpoint, path, wildcard or nontext mapping %s',async value=>{
    await expect(preparePortalOperation(portalFixture.proposal_receipt.scope,'propose',{...portalFixture.proposal,mappings:{...portalFixture.proposal.mappings,patient_reference:value}} as never)).rejects.toThrow();
  });
  it('binds receipt to exact scope, key and persisted request hash',async()=>{
    const op=await actualPortalProposal();await expect(verifyPortalReceipt({...portalFixture.proposal_receipt,idempotency_key:'changed-key'},op)).rejects.toThrow();
    await expect(verifyPortalReceipt(portalFixture.proposal_receipt,{...op,request_sha256:'0'.repeat(64)})).rejects.toThrow();
  });
  it('rejects unsupported profile claims and mismatched mapping hashes',async()=>{
    const cat=structuredClone(portalFixture.catalog_pending);cat.live_portals_configured=true;
    await expect(verifyPortalCatalog(cat)).rejects.toThrow();
    const detail=structuredClone(portalFixture.detail_pending);detail.review.mappings_sha256='0'.repeat(64);
    await expect(verifyPortalDetail(detail)).rejects.toThrow();
  });
  it('validates a closed encrypted recovery value and refuses scope/receipt forgery or oversized content',async()=>{
    const op=await actualPortalProposal(),record={...emptyPortalRecovery(op.scope),pending:op,receipt:await verifyPortalReceipt(portalFixture.proposal_receipt,op)};
    expect(await validatePortalRecovery(record,op.scope)).toEqual(record);
    await expect(validatePortalRecovery({...record,access_token:'invented'})).rejects.toThrow();
    await expect(validatePortalRecovery(record,{...op.scope,owner_id:crypto.randomUUID()})).rejects.toThrow();
    await expect(validatePortalRecovery({...record,draft:{...record.draft,practice_label:'x'.repeat(20000)}})).rejects.toThrow();
  });
});
