import actual from './__fixtures__/finance-work/actual-finance-http-fixtures.json';
import processActual from './__fixtures__/finance-work/actual-finance-process-fixtures.json';
import processR3 from './__fixtures__/finance-work/actual-finance-process-r3.json';
import revisionPending from './__fixtures__/finance-work/actual-finance-revision-0.json';
import revisionApproved from './__fixtures__/finance-work/actual-finance-revision-1.json';
import {validateFinance} from './finance-contract';
import {prepareFinanceOperation} from './finance-operation';
export {actual,processActual,processR3,revisionPending,revisionApproved};
export const actualFinanceOptions=()=>validateFinance('FinanceOptions',actual.options);
export const actualFinanceDetail=()=>validateFinance('FinanceDetail',actual.pending_detail);
export const actualFinanceCatalog=()=>validateFinance('FinanceCatalog',actual.catalog);
const selection=(v:{id:string;revision:number;public_sha256:string})=>({id:v.id,revision:v.revision,public_sha256:v.public_sha256});
export function actualFinanceProposal(){const o=actualFinanceOptions(),r=actualFinanceDetail().review;return prepareFinanceOperation({kind:'workspace',id:o.workspace_id},'propose',null,{expected_workspace_revision:o.expected_workspace_revision,idempotency_key:actual.proposal_receipt.idempotency_key,proposed_operation_id:r.operation_id,source:r.source,connection:selection(r.connection),customer:selection(r.customer),amount:r.amount,currency:'usd',due_date:r.due_date,expected_outcome:r.expected_outcome});}
export function actualFinanceApproval(){const d=actualFinanceDetail(),s=d.summary;return prepareFinanceOperation({kind:'workspace',id:d.workspace_id},'decide',s.ticket_id,{expected_version:s.version,idempotency_key:actual.approval_receipt.idempotency_key,operation_id:s.operation_id,revision_id:s.revision_id,payload_hash:s.payload_hash,choice:'approve',review_sha256:d.review_sha256});}
