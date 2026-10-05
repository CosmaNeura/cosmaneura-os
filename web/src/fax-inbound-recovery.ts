import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical} from './vendor-contract';
import {faxObject,faxHash,validFaxScope,validateFaxPending,validateFaxReceipt,validateFaxProposal,type FaxScope,type FaxPending,type FaxReceipt,type FaxProposal} from './fax-inbound-api';
export type FaxRecovery={version:1;scope:FaxScope;pending:FaxPending|null;observation:FaxReceipt|null;selected_source_sha256:string|null;proposal:FaxProposal|null;approval:FaxReceipt|null;acquisition:FaxReceipt|null;acquire_request:FaxPending|null};
export type FaxRecoveryAccess={authorize:()=>Promise<void>;load:()=>Promise<unknown>;persist:(v:FaxRecovery|null)=>Promise<void>;denied?:(e:unknown)=>void};
export const emptyFaxRecovery=(scope:FaxScope):FaxRecovery=>({version:1,scope,pending:null,observation:null,selected_source_sha256:null,proposal:null,approval:null,acquisition:null,acquire_request:null});
export async function validateFaxRecovery(v:unknown,scope:FaxScope):Promise<FaxRecovery>{
 const bad=():never=>{throw new WorkspaceApiError(502,'fax_inbound_recovery_invalid');};
 if(!validFaxScope(scope)||!faxObject(v,'version,scope,pending,observation,selected_source_sha256,proposal,approval,acquisition,acquire_request')||v.version!==1||vendorCanonical(v.scope)!==vendorCanonical(scope)||new TextEncoder().encode(vendorCanonical(v)).length>131072)return bad();
 const r=v as unknown as FaxRecovery;
 if(r.pending!==null)validateFaxPending(r.pending);
 if(r.observation!==null){await validateFaxReceipt(r.observation,scope);if(r.observation.kind!=='observe'||r.observation.state!=='observed')return bad();}
 if(r.selected_source_sha256!==null&&(!faxHash(r.selected_source_sha256)||!r.observation?.items?.some(f=>f.source_sha256===r.selected_source_sha256)))return bad();
 if(r.proposal!==null){await validateFaxProposal(r.proposal,scope,r.proposal.ticket_id,r.proposal.revision_id);if(r.proposal.source_sha256!==r.selected_source_sha256)return bad();}
 if(r.approval!==null){await validateFaxReceipt(r.approval,scope);if(r.approval.kind!=='decide'||r.approval.ticket_id!==r.proposal?.ticket_id||r.approval.revision_id!==r.proposal?.revision_id||!['approved','rejected'].includes(r.approval.state))return bad();}
 if(r.acquire_request!==null){validateFaxPending(r.acquire_request);if(r.acquire_request.kind!=='acquire'||r.approval?.state!=='approved'||r.acquire_request.request.ticket_id!==r.proposal?.ticket_id||r.acquire_request.request.revision_id!==r.proposal?.revision_id||r.acquire_request.request.expected_version!==r.approval.version||r.acquire_request.request.approval_sha256!==r.approval.approval_sha256)return bad();}
 if(r.acquisition!==null){if(!r.acquire_request)return bad();await validateFaxReceipt(r.acquisition,scope,r.acquire_request);if(r.acquisition.kind!=='acquire')return bad();}
 if(r.pending?.kind==='propose'&&(r.pending.request.grant_id!==r.observation?.grant_id||r.pending.request.observation_id!==r.observation?.observation_id||r.pending.request.observation_sha256!==r.observation?.source_sha256||r.pending.request.source_sha256!==r.selected_source_sha256))return bad();
 if(r.pending?.kind==='decide'&&(r.pending.request.ticket_id!==r.proposal?.ticket_id||r.pending.request.revision_id!==r.proposal?.revision_id||r.pending.request.expected_version!==r.proposal?.version))return bad();
 if(r.pending?.kind==='acquire'&&vendorCanonical(r.pending)!==vendorCanonical(r.acquire_request))return bad();
 return r;
}
