/** Invented renderer fixtures. Actual HTTP qualification is kept separate. */
import {vendorDigest} from './vendor-contract';
import {prepareFinanceSetupOperation,type FinanceSetupOperation,type FinanceSetupDetail,type FinanceSetupCatalog,type FinanceSetupSummary} from './finance-setup-contract';
import type {Receipt,AccountReview,CustomerReview} from './finance-setup-schema';
export const setupId=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
export const setupScope={box_id:setupId(1),owner_id:setupId(2)};
export async function setupReceipt(op:FinanceSetupOperation,review:AccountReview|CustomerReview):Promise<Receipt>{
  const states={propose_account:'pending_review',propose_customer:'pending_review',activate:'active',disable:'disabled',revoke:'revoked'} as const;
  const unsigned={contract_version:1 as const,outcome:'recorded' as const,scope:op.scope,command_kind:op.kind,idempotency_key:op.request.idempotency_key,request_sha256:op.request_sha256,receipt_id:crypto.randomUUID(),recorded_at:'2026-09-21T15:00:00.000000Z',effect:{setup_id:op.request.setup_id,kind:review.kind,version:op.request.expected_version+1,revision_id:review.revision_id,review_sha256:await vendorDigest('cosmas-finance-setup-review.v1',review),state:states[op.kind]}};
  return {...unsigned,receipt_sha256:await vendorDigest('cosmas-finance-setup-receipt.v1',unsigned)};
}
export async function setupFixture(){
  const installed={installation_id:setupId(3),installation_sha256:'a'.repeat(64),label:'Invented practice Stripe',environment:'sandbox' as const,account_reference:'acct_InventedPractice'};
  const accountRequest={setup_id:setupId(4),expected_version:0,idempotency_key:'invented-account-01',installation_id:installed.installation_id,installation_sha256:installed.installation_sha256,label:'Practice sandbox',permissions:{read_status:true,create_unconfirmed_intents:true}};
  const accountReview:AccountReview={kind:'account',setup_id:accountRequest.setup_id,revision_id:setupId(5),revision:1,installed,label:accountRequest.label,permissions:accountRequest.permissions,connection_version_id:setupId(6)};
  const accountOp=await prepareFinanceSetupOperation(setupScope,'propose_account',accountRequest),accountReceipt=await setupReceipt(accountOp,accountReview);
  const detail=(review:AccountReview|CustomerReview,last_receipt:Receipt):FinanceSetupDetail=>({contract_version:1,scope:setupScope,summary:{...last_receipt.effect,target:review.kind==='account'?{kind:'account',installation_id:review.installed.installation_id}:{kind:'customer',account_setup_id:review.account.setup_id,patient_link_id:review.patient.patient_link_id},label:review.label,usable_locally:last_receipt.effect.state==='active',availability:'available'},review,last_receipt});
  const accountPending=detail(accountReview,accountReceipt),b={setup_id:accountReview.setup_id,expected_version:1,revision_id:accountReview.revision_id,review_sha256:accountReceipt.effect.review_sha256};
  const activateOp=await prepareFinanceSetupOperation(setupScope,'activate',{...b,idempotency_key:'invented-activate-01',reviewed_account:true,reviewed_environment:true,confirm_local_activation:true}),activateReceipt=await setupReceipt(activateOp,accountReview),accountActive=detail(accountReview,activateReceipt);
  const patient={patient_link_id:setupId(7),label:'Invented Avery'};
  const customerRequest={setup_id:setupId(8),expected_version:0,idempotency_key:'invented-customer-01',account:{...b,expected_version:2},patient_link_id:patient.patient_link_id,customer_id:'cus_InventedAvery',label:'Avery billing'};
  const customerReview:CustomerReview={kind:'customer',setup_id:customerRequest.setup_id,revision_id:setupId(9),revision:1,installed,label:customerRequest.label,account:customerRequest.account,account_label:accountReview.label,connection_version_id:accountReview.connection_version_id,customer_version_id:setupId(10),patient,customer_id:customerRequest.customer_id};
  const customerOp=await prepareFinanceSetupOperation(setupScope,'propose_customer',customerRequest),customerReceipt=await setupReceipt(customerOp,customerReview),customerPending=detail(customerReview,customerReceipt);
  const catalog=(setups:FinanceSetupSummary[]):FinanceSetupCatalog=>({contract_version:1,scope:setupScope,enabled:true,installed_accounts:[installed],patients:[patient],setups});
  return {installed,patient,accountOp,accountReceipt,accountPending,activateOp,activateReceipt,accountActive,customerOp,customerReceipt,customerPending,accountReview,customerReview,catalogPending:catalog([accountPending.summary]),catalogActive:catalog([accountActive.summary,customerPending.summary]),emptyCatalog:catalog([])};
}
