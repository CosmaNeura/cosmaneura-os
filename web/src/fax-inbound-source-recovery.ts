import {teamClosed} from './team-setup-request';
import {vendorCanonical} from './vendor-contract';
import {faxSourceRequestHash,validFaxSourceScope,validFaxSourceOffer,validFaxSourceVisit,validFaxSourceReviewRequest,verifyFaxSourceReceipt,
 type FaxSourceScope,type FaxSourceOffer,type FaxSourceVisit,type FaxSourceReviewRequest,type FaxSourceReceipt} from './fax-inbound-source-api';

export type FaxSourcePending={request:FaxSourceReviewRequest;request_sha256:string};
export type FaxSourceRecovery={version:1;scope:FaxSourceScope;offered:FaxSourceOffer;visit:FaxSourceVisit;passage:string;page_numbers:number[];pending:FaxSourcePending|null;saved:FaxSourceReceipt|null;saved_request:FaxSourceReviewRequest|null};
export type FaxSourceRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(value:FaxSourceRecovery|null):Promise<void>;denied?(error:unknown):void};
export const emptyFaxSourceRecovery=(scope:FaxSourceScope,offered:FaxSourceOffer,visit:FaxSourceVisit):FaxSourceRecovery=>({
 version:1,scope:structuredClone(scope),offered:structuredClone(offered),visit:structuredClone(visit),passage:'',page_numbers:[],pending:null,saved:null,saved_request:null});
const bad=():never=>{throw new Error('Private fax passage recovery could not be verified.');};
export async function validateFaxSourceRecovery(value:unknown,scope:FaxSourceScope,offered?:FaxSourceOffer):Promise<FaxSourceRecovery>{
 if(!validFaxSourceScope(scope)||!teamClosed(value,'version,scope,offered,visit,passage,page_numbers,pending,saved,saved_request')||value.version!==1||
 !validFaxSourceScope(value.scope)||vendorCanonical(scope)!==vendorCanonical(value.scope)||!validFaxSourceOffer(value.offered)||
 offered&&(value.offered.operation_id!==offered.operation_id||value.offered.document_sha256!==offered.document_sha256||value.offered.pages!==offered.pages)||
 !validFaxSourceVisit(value.visit)||value.visit.id!==scope.workspace_id||typeof value.passage!=='string'||Array.from(value.passage).length>12000||
 /[\u0000-\u0008\u000b-\u001f\u007f]/.test(value.passage)||!Array.isArray(value.page_numbers)||value.page_numbers.length>50||
 !value.page_numbers.every((p,i,a)=>Number.isInteger(p)&&p>=1&&p<=Number((value.offered as FaxSourceOffer).pages)&&(i===0||p>a[i-1])))return bad();
 try{if(new TextEncoder().encode(vendorCanonical(value)).length>131072)return bad();}catch{return bad();}
 const v=value as FaxSourceRecovery;
 const bind=(r:FaxSourceReviewRequest)=>r.operation_id===v.offered.operation_id&&r.document_sha256===v.offered.document_sha256&&r.expected_revision===v.visit.revision&&
 r.passage===v.passage&&vendorCanonical(r.page_numbers)===vendorCanonical(v.page_numbers)&&Math.max(...r.page_numbers)<=v.offered.pages;
 if(v.pending!==null){
  if(!teamClosed(v.pending,'request,request_sha256')||!validFaxSourceReviewRequest(v.pending.request)||!bind(v.pending.request)||
  v.pending.request_sha256!==await faxSourceRequestHash(scope,v.pending.request)||v.saved!==null||v.saved_request!==null)return bad();
 }
 if(v.saved!==null){
  if(!validFaxSourceReviewRequest(v.saved_request)||!bind(v.saved_request))return bad();
  await verifyFaxSourceReceipt(v.saved,scope,v.saved_request);
 }else if(v.saved_request!==null)return bad();
 return structuredClone(v);
}
