import type {Scope,ReviewedSource,Document,FinanceProof} from './membership-schema';
import type {ArtifactMetadata} from './vendor-schema';
import type {FinanceDetail,FinanceResponse} from './finance-schema';
import type {FinanceOperation} from './finance-operation';
import {validateFinanceOperation,verifyFinanceOperationReceipt} from './finance-operation';
import {verifyFinanceView} from './finance-contract';
import {MembershipContractError,validateMembership,sameMembershipScope} from './membership-contract';
import {validateVendor,vendorBytes,vendorCanonical,vendorObject} from './vendor-contract';
import {requirePdf} from './vendor-api';

export type MembershipDocumentChoice={label:string;metadata:ArtifactMetadata};
export type MembershipFinanceChoice={operation:FinanceOperation;receipt:FinanceResponse};
export type MembershipEvidenceInventory={scope:Scope;documents:MembershipDocumentChoice[];finance:MembershipFinanceChoice[]};
/** Root derives these from the current private custody and encrypted finance journal.
 * Every call reauthorizes this owner/workspace through the existing server route.
 * FinanceDetail has no patient ID field; its current workspace authorization and
 * membership backend admission enforce the confirmed-patient association.
 * No provider reconciliation/sending is performed by any method. */
export type MembershipEvidenceAccess={
 load(scope:Scope,signal?:AbortSignal):Promise<MembershipEvidenceInventory>;
 preview(scope:Scope,document:Document,signal?:AbortSignal):Promise<Uint8Array>;
 financeDetail(scope:Scope,ticketId:string,signal?:AbortSignal):Promise<FinanceDetail>;
};
const fail=():never=>{throw new MembershipContractError();};
export async function verifyMembershipEvidenceInventory(value:unknown,scope:Scope,source:ReviewedSource):Promise<MembershipEvidenceInventory>{
 if(!vendorObject(value)||Object.keys(value).sort().join(',')!=='documents,finance,scope'||vendorBytes(value)>131072)fail();
 const v=value as MembershipEvidenceInventory;validateMembership('Scope',v.scope);if(!sameMembershipScope(v.scope,scope)||!Array.isArray(v.documents)||v.documents.length>100||!Array.isArray(v.finance)||v.finance.length>100)fail();
 const artifacts=new Set<string>(),receipts=new Set<string>();const documents:MembershipDocumentChoice[]=[],finance:MembershipFinanceChoice[]=[];
 for(const item of v.documents){if(!vendorObject(item)||Object.keys(item).sort().join(',')!=='label,metadata'||typeof item.label!=='string'||!item.label.trim()||Array.from(item.label).length>120)fail();const metadata=validateVendor('ArtifactMetadata',item.metadata);if(artifacts.has(metadata.artifact_id))fail();artifacts.add(metadata.artifact_id);if(metadata.state==='ready'&&vendorCanonical(metadata.source)===vendorCanonical(source))documents.push({label:item.label,metadata});}
 for(const item of v.finance){if(!vendorObject(item)||Object.keys(item).sort().join(',')!=='operation,receipt')fail();const operation=await validateFinanceOperation(item.operation,{kind:'workspace',id:scope.workspace_id});if(operation.kind!=='verify')fail();const receipt=await verifyFinanceOperationReceipt(operation,item.receipt);if(receipt.outcome!=='recorded'||!receipt.effect||receipt.effect.effect!=='verified'||receipts.has(receipt.effect.receipt_id))fail();receipts.add(receipt.effect!.receipt_id);finance.push({operation,receipt});}
 return {scope:structuredClone(scope),documents,finance};
}
export async function membershipFinanceProof(choice:MembershipFinanceChoice,value:unknown,scope:Scope):Promise<{proof:FinanceProof;detail:FinanceDetail}>{
 const op=await validateFinanceOperation(choice.operation,{kind:'workspace',id:scope.workspace_id}),receipt=await verifyFinanceOperationReceipt(op,choice.receipt),d=await verifyFinanceView('FinanceDetail',value);
 if(op.kind!=='verify'||receipt.outcome!=='recorded'||!receipt.effect||receipt.effect.effect!=='verified'||d.workspace_id!==scope.workspace_id||d.summary.state!=='closed'||d.summary.verification!=='verified'||d.summary.conflicting_evidence)fail();
 const e=receipt.effect!,q=op.request as import('./finance-schema').FinanceVerify,s=d.summary;
 if(e.effect_version!==q.expected_version+1||e.effect_version!==s.version||e.ticket_id!==s.ticket_id||e.operation_id!==s.operation_id||e.revision_id!==s.revision_id||e.payload_hash!==s.payload_hash||q.evidence_sha256!==s.evidence_sha256||vendorCanonical(q.observation_head)!==vendorCanonical(s.observation_head))fail();
 return {proof:validateMembership('FinanceProof',{ticket_id:s.ticket_id,verification_receipt_id:e.receipt_id,verification_receipt_sha256:receipt.receipt_sha256,evidence_sha256:s.evidence_sha256}),detail:d};
}
export async function membershipDocumentPreview(access:MembershipEvidenceAccess,scope:Scope,document:Document,signal?:AbortSignal){validateMembership('Document',document);const bytes=await access.preview(scope,document,signal);await requirePdf(document,bytes);return bytes;}
