import {teamClosed} from './team-setup-request';
import {vendorCanonical} from './vendor-contract';
import {efaxSourceRequestHash,validEFaxSourceScope,validEFaxSourceOffer,validEFaxSourceVisit,validEFaxSourceReviewRequest,verifyEFaxSourceReceipt,
 type EFaxSourceScope,type EFaxSourceOffer,type EFaxSourceVisit,type EFaxSourceReviewRequest,type EFaxSourceReceipt} from './efax-inbound-source-api';

export type EFaxSourcePending={request:EFaxSourceReviewRequest;request_sha256:string};
export type EFaxSourceRecovery={version:1;scope:EFaxSourceScope;offered:EFaxSourceOffer;visit:EFaxSourceVisit;passage:string;page_numbers:number[];pending:EFaxSourcePending|null;saved:EFaxSourceReceipt|null;saved_request:EFaxSourceReviewRequest|null};
export type EFaxSourceRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(value:EFaxSourceRecovery|null):Promise<void>;denied?(error:unknown):void};
export const emptyEFaxSourceRecovery=(scope:EFaxSourceScope,offered:EFaxSourceOffer,visit:EFaxSourceVisit):EFaxSourceRecovery=>({
 version:1,scope:structuredClone(scope),offered:structuredClone(offered),visit:structuredClone(visit),passage:'',page_numbers:[],pending:null,saved:null,saved_request:null});
const bad=():never=>{throw new Error('Private fax passage recovery could not be verified.');};
export async function validateEFaxSourceRecovery(value:unknown,scope:EFaxSourceScope,offered?:EFaxSourceOffer):Promise<EFaxSourceRecovery>{
 if(!validEFaxSourceScope(scope)||!teamClosed(value,'version,scope,offered,visit,passage,page_numbers,pending,saved,saved_request')||value.version!==1||
 !validEFaxSourceScope(value.scope)||vendorCanonical(scope)!==vendorCanonical(value.scope)||!validEFaxSourceOffer(value.offered)||
 offered&&(value.offered.operation_id!==offered.operation_id||value.offered.document_sha256!==offered.document_sha256||value.offered.pages!==offered.pages)||
 !validEFaxSourceVisit(value.visit)||value.visit.id!==scope.workspace_id||typeof value.passage!=='string'||Array.from(value.passage).length>12000||
 /[\u0000-\u0008\u000b-\u001f\u007f]/.test(value.passage)||!Array.isArray(value.page_numbers)||value.page_numbers.length>50||
 !value.page_numbers.every((p,i,a)=>Number.isInteger(p)&&p>=1&&p<=Number((value.offered as EFaxSourceOffer).pages)&&(i===0||p>a[i-1])))return bad();
 try{if(new TextEncoder().encode(vendorCanonical(value)).length>131072)return bad();}catch{return bad();}
 const v=value as EFaxSourceRecovery;
 const bind=(r:EFaxSourceReviewRequest)=>r.operation_id===v.offered.operation_id&&r.document_sha256===v.offered.document_sha256&&r.expected_revision===v.visit.revision&&
 r.passage===v.passage&&vendorCanonical(r.page_numbers)===vendorCanonical(v.page_numbers)&&Math.max(...r.page_numbers)<=v.offered.pages;
 if(v.pending!==null){
  if(!teamClosed(v.pending,'request,request_sha256')||!validEFaxSourceReviewRequest(v.pending.request)||!bind(v.pending.request)||
  v.pending.request_sha256!==await efaxSourceRequestHash(scope,v.pending.request)||v.saved!==null||v.saved_request!==null)return bad();
 }
 if(v.saved!==null){
  if(!validEFaxSourceReviewRequest(v.saved_request)||!bind(v.saved_request))return bad();
  await verifyEFaxSourceReceipt(v.saved,scope,v.saved_request);
 }else if(v.saved_request!==null)return bad();
 return structuredClone(v);
}
