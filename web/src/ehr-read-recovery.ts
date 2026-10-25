import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {modelCanonical} from './model-work-request';
import {ehrHash,ehrContentHash,ehrSourceContent,ehrReviewHash,ehrSourceHash,ehrTransport,validEhrInstall,validEhrCommand,validEhrReceipt,validEhrReview,type EhrTransport,type EhrInstallRequest,type EhrCommand,type EhrReceipt,type EhrReviewRequest,type EhrResolve} from './ehr-read-api';
export type EhrReadScope={box_id:string;owner_id:string;workspace_id:string};
export type EhrReadVisit={id:string;label:string;revision:number};
export type EhrReadSaved={workspace_id:string;entry_id:string;entry_revision:number;source_sha256:string;content_sha256:string;request_sha256:string;source_withheld:boolean};
export type EhrPending={kind:'install';request:EhrInstallRequest;anchor:null}|{kind:'read';request:EhrCommand;anchor:EhrReceipt|null;transport?:EhrTransport}|{kind:'review';request:EhrReviewRequest;anchor:EhrReceipt};
export type EhrSupersededRead={request:EhrCommand;resolution:EhrResolve};
export type EhrReadRecovery={version:1;superseded_reads:EhrSupersededRead[];scope:EhrReadScope;binding:{connection_id:string;binding_sha256:string}|null;window:EhrReceipt|null;verified:EhrReceipt|null;pending:EhrPending|null;saved:EhrReadSaved|null;saved_request:EhrReviewRequest|null};
export type EhrReadRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(value:EhrReadRecovery|null):Promise<void>;denied?(error:unknown):void};
export const validEhrScope=(v:unknown):v is EhrReadScope=>teamClosed(v,'box_id,owner_id,workspace_id')&&teamUuid(v.box_id)&&teamUuid(v.owner_id)&&teamUuid(v.workspace_id);
export const emptyEhrReadRecovery=(scope:EhrReadScope):EhrReadRecovery=>({version:1,superseded_reads:[],scope:structuredClone(scope),binding:null,window:null,verified:null,pending:null,saved:null,saved_request:null});
const bad=():never=>{throw new Error('Saved Elation work could not be verified.');};
const same=(a:unknown,b:unknown)=>modelCanonical(a)===modelCanonical(b);
export async function validateEhrReadRecovery(value:unknown,scope:EhrReadScope):Promise<EhrReadRecovery>{
 if(!validEhrScope(scope)||!teamClosed(value,'version,superseded_reads,scope,binding,window,verified,pending,saved,saved_request')||value.version!==1||!validEhrScope(value.scope)||!same(value.scope,scope))return bad();
 if(new TextEncoder().encode(modelCanonical(value)).length>131072)return bad();
 const v=value as EhrReadRecovery;
 if(!Array.isArray(v.superseded_reads)||v.superseded_reads.length>3||new Set(v.superseded_reads.map(old=>old?.request?.idempotency_key)).size!==v.superseded_reads.length)return bad();
 for(const old of v.superseded_reads)if(!teamClosed(old,'request,resolution')||!validEhrCommand(old.request)||!teamClosed(old.resolution,'status,observation_id,observation_key')||old.resolution.status!=='unconfirmed'||!teamUuid(old.resolution.observation_id)||old.resolution.observation_key!==old.request.idempotency_key||old.request.connection_id!==v.binding?.connection_id||old.request.binding_sha256!==v.binding?.binding_sha256||old.request.idempotency_key===v.pending?.request.idempotency_key)return bad();
 if(v.binding!==null&&(!teamClosed(v.binding,'connection_id,binding_sha256')||!teamUuid(v.binding.connection_id)||!teamHash(v.binding.binding_sha256)))return bad();
 if(v.window!==null&&(!await validEhrReceipt(v.window)||v.window.observation.kind!=='window'))return bad();
 if(v.verified!==null){
  if(!v.window||!await validEhrReceipt(v.verified)||v.verified.observation.kind!=='verified_visit'||v.window.observation.kind!=='window')return bad();
  const o=v.verified.observation,item=v.window.observation.items.find(i=>i.handle===o.item.handle&&i.selectable);
  if(!item||item.starts_at!==o.item.starts_at||item.ends_at!==o.item.ends_at||item.status!==o.item.status||ehrTransport(v.window)!==ehrTransport(v.verified)||!same(v.window.observation.practice,o.practice)||!same(v.window.observation.window,o.window)||v.window.observation.coverage!==o.coverage)return bad();
 }
 if(!v.binding&&(v.window||v.verified||v.pending&&v.pending.kind!=='install'||v.saved))return bad();
 for(const r of [v.window,v.verified])if(r&&(r.connection_id!==v.binding?.connection_id||r.binding_sha256!==v.binding?.binding_sha256))return bad();
 const reviewMatches=(r:EhrReviewRequest,a:EhrReceipt)=>a.observation.kind==='verified_visit'&&r.observation_id===a.observation_id&&r.observation_sha256===a.source_sha256&&r.item_handle===a.observation.item.handle&&r.item_sha256===a.observation.item.sha256;
 if(v.pending!==null){
  const p=v.pending;if(!teamClosed(p,'kind,request,anchor',p.kind==='read'?'transport':'')||v.saved!==null||v.saved_request!==null)return bad();
  if(p.kind==='install'){
   if(!validEhrInstall(p.request)||p.anchor!==null||v.binding||v.window||v.verified||v.superseded_reads.length)return bad();
  }else if(p.kind==='read'){
   if(p.transport!==undefined&&p.transport!=='mock'&&p.transport!=='vendor_sandbox'||p.anchor&&ehrTransport(p)!==ehrTransport(p.anchor))return bad();
   if(!validEhrCommand(p.request)||p.request.connection_id!==v.binding?.connection_id||p.request.binding_sha256!==v.binding?.binding_sha256)return bad();
   if(p.request.action==='observe'){if(p.anchor!==null||v.window!==null||v.verified!==null)return bad();}
   else {const r=p.request;if(!v.window||!same(p.anchor,v.window)||v.window.observation.kind!=='window'||r.observation_id!==v.window.observation_id||r.observation_sha256!==v.window.source_sha256||!v.window.observation.items.some(i=>i.handle===r.item_handle&&i.sha256===r.item_sha256&&i.selectable)||v.verified!==null)return bad();}
  }else if(p.kind!=='review'||!validEhrReview(p.request)||!v.verified||!same(p.anchor,v.verified)||!reviewMatches(p.request,p.anchor))return bad();
 }
 if(v.saved!==null){
  const s=v.saved,r=v.saved_request,a=v.verified;
  if(!a||a.observation.kind!=='verified_visit'||!validEhrReview(r)||!reviewMatches(r,a)||!teamClosed(s,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||s.workspace_id!==scope.workspace_id||!teamUuid(s.entry_id)||!teamNatural(s.entry_revision)||s.entry_revision!==r.expected_revision+1||!teamHash(s.content_sha256)||s.content_sha256!==await ehrContentHash(ehrSourceContent(a.observation))||typeof s.source_withheld!=='boolean'||s.source_sha256!==await ehrSourceHash(a,a.observation.item)||s.request_sha256!==await ehrReviewHash(scope.workspace_id,r))return bad();
 }else if(v.saved_request!==null)return bad();
 // Canonicalizing once also rejects values the encrypted journal cannot retain.
 await ehrHash(v);return structuredClone(v);
}
