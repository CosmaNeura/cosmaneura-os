import {WorkspaceApiError} from './workspace-api';
import {vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';
import {validateEFaxPending,validateEFaxReceipt,validateEFaxProposal,efaxFaxHash,type EFaxScope,type EFaxPending,type EFaxReceipt,type EFaxProposal} from './efax-inbound-api';

export type EFaxInboundRecovery={version:1;scope:EFaxScope;pending:EFaxPending|null;observation:EFaxReceipt|null;selected_fax_id:string|null;proposal:EFaxProposal|null;approval:EFaxReceipt|null;acquisition:EFaxReceipt|null;acquire_request:EFaxPending|null};
export type EFaxInboundRecoveryAccess={authorize:()=>Promise<void>;load:()=>Promise<unknown>;persist:(v:EFaxInboundRecovery|null)=>Promise<void>;denied?:(e:unknown)=>void};
export const emptyEFaxRecovery=(scope:EFaxScope):EFaxInboundRecovery=>({version:1,scope,pending:null,observation:null,selected_fax_id:null,proposal:null,approval:null,acquisition:null,acquire_request:null});
export async function validateEFaxRecovery(v:unknown,scope:EFaxScope):Promise<EFaxInboundRecovery>{
 const bad=():never=>{throw new WorkspaceApiError(502,'efax_inbound_recovery_invalid');};
 if(!vendorObject(v)||Object.keys(v).sort().join(',')!=='acquire_request,acquisition,approval,observation,pending,proposal,scope,selected_fax_id,version'||v.version!==1||vendorCanonical(v.scope)!==vendorCanonical(scope)||!vendorUuid(scope.box_id)||!vendorUuid(scope.owner_id)||new TextEncoder().encode(vendorCanonical(v)).length>131072)return bad();
 const r=v as unknown as EFaxInboundRecovery;
 if(r.pending!==null)validateEFaxPending(r.pending);
 if(r.observation!==null){validateEFaxReceipt(r.observation,scope);if(r.observation.kind!=='observe'||r.observation.state!=='observed')return bad();}
 if(r.selected_fax_id!==null&&(!vendorUuid(r.selected_fax_id)||!r.observation?.snapshot?.items.some(f=>f.fax_id===r.selected_fax_id)))return bad();
 if(r.proposal!==null){await validateEFaxProposal(r.proposal,scope,r.proposal.ticket_id);if(!r.proposal.source_withheld&&(r.proposal.fax?.fax_id!==r.selected_fax_id||r.proposal.observation_id!==r.observation?.observation_id||r.proposal.observation_sha256!==r.observation?.source_sha256))return bad();}
 if(r.approval!==null){validateEFaxReceipt(r.approval,scope);if(r.approval.kind!=='decide'||r.approval.ticket_id!==r.proposal?.ticket_id||r.approval.revision_id!==r.proposal?.revision_id)return bad();}
 if(r.acquire_request!==null){validateEFaxPending(r.acquire_request);if(r.acquire_request.kind!=='acquire'||r.approval?.state!=='approved'||r.acquire_request.request.ticket_id!==r.proposal?.ticket_id||r.acquire_request.request.revision_id!==r.proposal?.revision_id||r.acquire_request.request.expected_version!==r.approval.version||r.acquire_request.request.approval_sha256!==r.approval.approval_sha256)return bad();}
 if(r.acquisition!==null){validateEFaxReceipt(r.acquisition,scope);if(r.acquisition.kind!=='acquire'||r.acquisition.ticket_id!==r.proposal?.ticket_id||r.acquisition.revision_id!==r.proposal?.revision_id||r.acquisition.idempotency_key!==r.acquire_request?.request.idempotency_key||r.acquire_request?.kind!=='acquire'||r.acquisition.version!==r.acquire_request.request.expected_version+1)return bad();}
 if(r.pending?.kind==='propose'&&(r.pending.request.grant_id!==r.observation?.grant_id||r.pending.request.fax_id!==r.selected_fax_id||r.pending.request.observation_id!==r.observation?.observation_id||r.pending.request.observation_sha256!==r.observation?.source_sha256))return bad();
 if(r.pending?.kind==='propose'){const selected=r.observation?.snapshot?.items.find(f=>f.fax_id===r.selected_fax_id);if(!selected||r.pending.request.fax_sha256!==await efaxFaxHash(selected))return bad();}
 if(r.pending?.kind==='decide'&&(r.pending.request.ticket_id!==r.proposal?.ticket_id||r.pending.request.revision_id!==r.proposal?.revision_id))return bad();
 if(r.pending?.kind==='acquire'&&vendorCanonical(r.pending)!==vendorCanonical(r.acquire_request))return bad();
 return r;
}
