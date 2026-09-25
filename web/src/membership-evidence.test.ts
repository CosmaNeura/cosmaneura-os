import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {processR3} from './finance-test-fixture';
import {prepareFinanceOperation} from './finance-operation';
import {validateFinance} from './finance-contract';
import {membershipFinanceProof,membershipDocumentPreview,verifyMembershipEvidenceInventory,type MembershipEvidenceAccess,type MembershipFinanceChoice} from './membership-evidence';
import {membershipFixtureScope,manual} from './membership-test-fixture';
import {validateMembership} from './membership-contract';
import {vendorSha256} from './vendor-contract';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
async function financial(){const d=validateFinance('FinanceDetail',processR3.verified_detail),command=processR3.commands.find(c=>c.kind==='verify')!,op=await prepareFinanceOperation({kind:'workspace',id:d.workspace_id},'verify',d.summary.ticket_id,validateFinance('FinanceVerify',command.request)),choice:MembershipFinanceChoice={operation:op,receipt:validateFinance('FinanceResponse',command.response)};return {scope:{...membershipFixtureScope,workspace_id:d.workspace_id},detail:d,choice};}
describe('membership evidence from existing exact custody/finance proofs',()=>{
 it('accepts the actual recorded finance verification pair and fresh current detail as manual review evidence',async()=>{
  const f=await financial(),checked=await membershipFinanceProof(f.choice,f.detail,f.scope);expect(checked.proof.verification_receipt_id).toBe(f.choice.receipt.effect!.receipt_id);expect(checked.proof.evidence_sha256).toBe(f.detail.summary.evidence_sha256);
  const inventory=await verifyMembershipEvidenceInventory({scope:f.scope,documents:[],finance:[f.choice]},f.scope,f.detail.review.source);expect(inventory.finance).toHaveLength(1);
 });
 it.each(['creation','wrong_scope','conflicting','changed_evidence','wrong_version'])('rejects %s as current finance review proof',async mode=>{
  const f=await financial();let scope=f.scope;
  if(mode==='creation'){const c=processR3.commands.find(c=>c.kind==='submit')!;f.choice.operation=await prepareFinanceOperation({kind:'workspace',id:f.detail.workspace_id},'submit',f.detail.summary.ticket_id,validateFinance('BoundCommand',c.request));f.choice.receipt=validateFinance('FinanceResponse',c.response);}
  if(mode==='wrong_scope')scope={...scope,workspace_id:crypto.randomUUID()};if(mode==='conflicting')f.detail.summary.conflicting_evidence=true;if(mode==='changed_evidence')f.detail.summary.evidence_sha256='0'.repeat(64);if(mode==='wrong_version')f.detail.summary.version++;
  await expect(membershipFinanceProof(f.choice,f.detail,scope)).rejects.toThrow();
 });
 it('keeps document choices scope/source-bound and rehashes all PDF bytes before showing them',async()=>{
  const d=validateMembership('Detail',manual.detail),source=d.review.proposal.source,bytes=new TextEncoder().encode('%PDF-1.4\nInvented private evidence\n%%EOF\n'),document={...d.latest_result!.request.ledger!.document,sha256:await vendorSha256(bytes),byte_length:bytes.length};
  const metadata={artifact_id:document.artifact_id,version:2,source,document,intent_sha256:'1'.repeat(64),state:'ready',generation:1,lease_until:null};
  const inventory=await verifyMembershipEvidenceInventory({scope:d.scope,documents:[{label:'Private ledger PDF',metadata}],finance:[]},d.scope,source);expect(inventory.documents).toHaveLength(1);
  expect((await verifyMembershipEvidenceInventory({scope:d.scope,documents:[{label:'Old source PDF',metadata:{...metadata,source:{...source,note_id:crypto.randomUUID()}}}],finance:[]},d.scope,source)).documents).toHaveLength(0);
  const access:MembershipEvidenceAccess={load:vi.fn(),financeDetail:vi.fn(),preview:vi.fn(async()=>bytes)};expect(await membershipDocumentPreview(access,d.scope,document)).toEqual(bytes);
  vi.mocked(access.preview).mockResolvedValueOnce(new Uint8Array(bytes.length));await expect(membershipDocumentPreview(access,d.scope,document)).rejects.toThrow();
  await expect(verifyMembershipEvidenceInventory({scope:{...d.scope,owner_id:crypto.randomUUID()},documents:[],finance:[]},d.scope,source)).rejects.toThrow();
 });
});
