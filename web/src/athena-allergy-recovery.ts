import {modelCanonical} from './model-work-request';
import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {ehrContentHash,ehrHash} from './ehr-read-api';
import type {EhrReadSaved} from './ehr-read-recovery';
import {ATHENA_CORE,athenaChildMatches,athenaReviewHash,athenaSourceHash,validAthenaCommand,validAthenaReceipt,validAthenaReview,type AthenaCoreCommand,type AthenaCoreReceipt,type AthenaCoreReview,type AthenaCoreResolve} from './athena-allergy-api';
export type AthenaAllergyScope=typeof ATHENA_CORE&{box_id:string;owner_id:string;workspace_id:string};
export type AthenaAllergyPending={kind:'read';request:AthenaCoreCommand;anchor:AthenaCoreReceipt|null}|{kind:'review';request:AthenaCoreReview;anchor:AthenaCoreReceipt};
export type AthenaAllergyRecovery={version:1;scope:AthenaAllergyScope;binding:{connection_id:string;binding_sha256:string}|null;patients:AthenaCoreReceipt|null;allergies:AthenaCoreReceipt|null;pending:AthenaAllergyPending|null;saved:EhrReadSaved|null;saved_request:AthenaCoreReview|null;superseded_reads:{request:AthenaCoreCommand;resolution:AthenaCoreResolve}[]};
export type AthenaAllergyRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(value:AthenaAllergyRecovery|null):Promise<void>;denied?(error:unknown):void};
export const emptyAthenaRecovery=(scope:AthenaAllergyScope):AthenaAllergyRecovery=>({version:1,scope:structuredClone(scope),binding:null,patients:null,allergies:null,pending:null,saved:null,saved_request:null,superseded_reads:[]});
const same=(a:unknown,b:unknown)=>modelCanonical(a)===modelCanonical(b);
const bad=():never=>{throw new Error('Saved Athena allergy work could not be verified.');};
export const validAthenaAllergyScope=(v:unknown):v is AthenaAllergyScope=>teamClosed(v,'provider,protocol,box_id,owner_id,workspace_id')&&v.provider==='athena'&&v.protocol==='core'&&teamUuid(v.box_id)&&teamUuid(v.owner_id)&&teamUuid(v.workspace_id);
export async function validateAthenaRecovery(value:unknown,scope:AthenaAllergyScope):Promise<AthenaAllergyRecovery>{
 if(!validAthenaAllergyScope(scope)||!teamClosed(value,'version,scope,binding,patients,allergies,pending,saved,saved_request,superseded_reads')||value.version!==1||!validAthenaAllergyScope(value.scope)||!same(scope,value.scope)||new TextEncoder().encode(modelCanonical(value)).length>131072)return bad();
 const v=value as AthenaAllergyRecovery;
 if(v.binding!==null&&(!teamClosed(v.binding,'connection_id,binding_sha256')||!teamUuid(v.binding.connection_id)||!teamHash(v.binding.binding_sha256)))return bad();
 if(v.patients!==null&&(!await validAthenaReceipt(v.patients)||v.patients.observation.kind!=='core_patients'))return bad();
 if(v.allergies!==null&&(!v.patients||!await validAthenaReceipt(v.allergies)||!athenaChildMatches(v.allergies,v.patients)))return bad();
 for(const a of [v.patients,v.allergies])if(a&&(a.observation.workspace_id!==scope.workspace_id||a.connection_id!==v.binding?.connection_id||a.binding_sha256!==v.binding?.binding_sha256))return bad();
 if(!v.binding&&(v.patients||v.allergies||v.pending||v.saved))return bad();
 if(!Array.isArray(v.superseded_reads)||v.superseded_reads.length>3||new Set(v.superseded_reads.map(x=>x?.request?.idempotency_key)).size!==v.superseded_reads.length)return bad();
 for(const old of v.superseded_reads)if(!teamClosed(old,'request,resolution')||!validAthenaCommand(old.request)||old.request.workspace_id!==scope.workspace_id||old.request.connection_id!==v.binding?.connection_id||old.request.binding_sha256!==v.binding?.binding_sha256||!teamClosed(old.resolution,'provider,protocol,status,observation_id,observation_key')||old.resolution.provider!=='athena'||old.resolution.protocol!=='core'||old.resolution.status!=='unconfirmed'||!teamUuid(old.resolution.observation_id)||old.resolution.observation_key!==old.request.idempotency_key||old.request.idempotency_key===v.pending?.request.idempotency_key)return bad();
 const matchesReview=(r:AthenaCoreReview,a:AthenaCoreReceipt)=>a.observation.kind==='core_allergies'&&validAthenaReview(r)&&r.observation_id===a.observation_id&&r.observation_sha256===a.source_sha256&&r.item_handle===a.observation.item.handle&&r.item_sha256===a.observation.item.sha256;
 if(v.pending!==null){const p=v.pending;if(!teamClosed(p,'kind,request,anchor')||v.saved!==null||v.saved_request!==null)return bad();
  if(p.kind==='read'){if(!validAthenaCommand(p.request)||p.request.workspace_id!==scope.workspace_id||p.request.connection_id!==v.binding?.connection_id||p.request.binding_sha256!==v.binding?.binding_sha256||v.allergies!==null)return bad();if(p.request.action==='core_patients'){if(p.anchor!==null||v.patients!==null)return bad();}else{const a=v.patients,r=p.request;if(!a||a.observation.kind!=='core_patients'||!same(p.anchor,a)||a.observation_id!==r.observation_id||a.source_sha256!==r.observation_sha256||!a.observation.items.some(i=>i.handle===r.item_handle&&i.sha256===r.item_sha256))return bad();}}
  else if(p.kind!=='review'||!v.allergies||!same(p.anchor,v.allergies)||!matchesReview(p.request,p.anchor))return bad();
 }
 if(v.saved!==null){const s=v.saved,r=v.saved_request,a=v.allergies;if(!a||a.observation.kind!=='core_allergies'||!r||!matchesReview(r,a)||!teamClosed(s,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||s.workspace_id!==scope.workspace_id||!teamUuid(s.entry_id)||!teamNatural(s.entry_revision)||s.entry_revision!==r.expected_revision+1||typeof s.source_withheld!=='boolean'||s.content_sha256!==a.observation.item.content_sha256||s.content_sha256!==await ehrContentHash(a.observation.item.source_content)||s.source_sha256!==await athenaSourceHash(a)||s.request_sha256!==await athenaReviewHash(scope.workspace_id,r))return bad();}else if(v.saved_request!==null)return bad();
 await ehrHash(v);return structuredClone(v);
}
