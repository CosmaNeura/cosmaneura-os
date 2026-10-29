import {modelCanonical} from './model-work-request';
import {teamClosed,teamHash,teamNatural,teamUuid} from './team-setup-request';
import {ehrContentHash,ehrHash} from './ehr-read-api';
import type {EhrReadSaved} from './ehr-read-recovery';
import {TEBRA_FHIR,tebraChildMatches,tebraReviewHash,tebraSourceHash,validTebraCommand,validTebraReceipt,validTebraReview,type TebraFhirCommand,type TebraFhirReceipt,type TebraFhirReview,type TebraFhirResolve} from './tebra-medication-api';
export type TebraMedicationScope=typeof TEBRA_FHIR&{box_id:string;owner_id:string;workspace_id:string};
export type TebraMedicationPending={kind:'read';request:TebraFhirCommand;anchor:TebraFhirReceipt|null}|{kind:'review';request:TebraFhirReview;anchor:TebraFhirReceipt};
export type TebraMedicationRecovery={version:1;scope:TebraMedicationScope;binding:{connection_id:string;binding_sha256:string}|null;patients:TebraFhirReceipt|null;medications:TebraFhirReceipt|null;pending:TebraMedicationPending|null;saved:EhrReadSaved|null;saved_request:TebraFhirReview|null;superseded_reads:{request:TebraFhirCommand;resolution:TebraFhirResolve}[]};
export type TebraMedicationRecoveryAccess={authorize():Promise<void>;load():Promise<unknown>;persist(value:TebraMedicationRecovery|null):Promise<void>;denied?(error:unknown):void};
export const emptyTebraRecovery=(scope:TebraMedicationScope):TebraMedicationRecovery=>({version:1,scope:structuredClone(scope),binding:null,patients:null,medications:null,pending:null,saved:null,saved_request:null,superseded_reads:[]});
const same=(a:unknown,b:unknown)=>modelCanonical(a)===modelCanonical(b);
const bad=():never=>{throw new Error('Saved Tebra medication work could not be verified.');};
export const validTebraMedicationScope=(v:unknown):v is TebraMedicationScope=>teamClosed(v,'provider,protocol,box_id,owner_id,workspace_id')&&v.provider==='tebra'&&v.protocol==='fhir'&&teamUuid(v.box_id)&&teamUuid(v.owner_id)&&teamUuid(v.workspace_id);
export async function validateTebraRecovery(value:unknown,scope:TebraMedicationScope):Promise<TebraMedicationRecovery>{
 if(!validTebraMedicationScope(scope)||!teamClosed(value,'version,scope,binding,patients,medications,pending,saved,saved_request,superseded_reads')||value.version!==1||!validTebraMedicationScope(value.scope)||!same(scope,value.scope)||new TextEncoder().encode(modelCanonical(value)).length>131072)return bad();
 const v=value as TebraMedicationRecovery;
 if(v.binding!==null&&(!teamClosed(v.binding,'connection_id,binding_sha256')||!teamUuid(v.binding.connection_id)||!teamHash(v.binding.binding_sha256)))return bad();
 if(v.patients!==null&&(!await validTebraReceipt(v.patients)||v.patients.observation.kind!=='fhir_patients'))return bad();
 if(v.medications!==null&&(!v.patients||!await validTebraReceipt(v.medications)||!tebraChildMatches(v.medications,v.patients)))return bad();
 for(const a of [v.patients,v.medications])if(a&&(a.observation.workspace_id!==scope.workspace_id||a.connection_id!==v.binding?.connection_id||a.binding_sha256!==v.binding?.binding_sha256))return bad();
 if(!v.binding&&(v.patients||v.medications||v.pending||v.saved))return bad();
 if(!Array.isArray(v.superseded_reads)||v.superseded_reads.length>3||new Set(v.superseded_reads.map(x=>x?.request?.idempotency_key)).size!==v.superseded_reads.length)return bad();
 for(const old of v.superseded_reads)if(!teamClosed(old,'request,resolution')||!validTebraCommand(old.request)||old.request.workspace_id!==scope.workspace_id||old.request.connection_id!==v.binding?.connection_id||old.request.binding_sha256!==v.binding?.binding_sha256||!teamClosed(old.resolution,'provider,protocol,status,observation_id,observation_key')||old.resolution.provider!=='tebra'||old.resolution.protocol!=='fhir'||old.resolution.status!=='unconfirmed'||!teamUuid(old.resolution.observation_id)||old.resolution.observation_key!==old.request.idempotency_key||old.request.idempotency_key===v.pending?.request.idempotency_key)return bad();
 const matchesReview=(r:TebraFhirReview,a:TebraFhirReceipt)=>a.observation.kind==='fhir_medications'&&validTebraReview(r)&&r.observation_id===a.observation_id&&r.observation_sha256===a.source_sha256&&r.item_handle===a.observation.item.handle&&r.item_sha256===a.observation.item.sha256;
 if(v.pending!==null){const p=v.pending;if(!teamClosed(p,'kind,request,anchor')||v.saved!==null||v.saved_request!==null)return bad();
  if(p.kind==='read'){if(!validTebraCommand(p.request)||p.request.workspace_id!==scope.workspace_id||p.request.connection_id!==v.binding?.connection_id||p.request.binding_sha256!==v.binding?.binding_sha256||v.medications!==null)return bad();if(p.request.action==='fhir_patients'){if(p.anchor!==null||v.patients!==null)return bad();}else{const a=v.patients,r=p.request;if(!a||a.observation.kind!=='fhir_patients'||!same(p.anchor,a)||a.observation_id!==r.observation_id||a.source_sha256!==r.observation_sha256||!a.observation.items.some(i=>i.handle===r.item_handle&&i.sha256===r.item_sha256))return bad();}}
  else if(p.kind!=='review'||!v.medications||!same(p.anchor,v.medications)||!matchesReview(p.request,p.anchor))return bad();
 }
 if(v.saved!==null){const s=v.saved,r=v.saved_request,a=v.medications;if(!a||a.observation.kind!=='fhir_medications'||!r||!matchesReview(r,a)||!teamClosed(s,'workspace_id,entry_id,entry_revision,source_sha256,content_sha256,request_sha256,source_withheld')||s.workspace_id!==scope.workspace_id||!teamUuid(s.entry_id)||!teamNatural(s.entry_revision)||s.entry_revision!==r.expected_revision+1||typeof s.source_withheld!=='boolean'||s.content_sha256!==a.observation.item.content_sha256||s.content_sha256!==await ehrContentHash(a.observation.item.source_content)||s.source_sha256!==await tebraSourceHash(a)||s.request_sha256!==await tebraReviewHash(scope.workspace_id,r))return bad();}else if(v.saved_request!==null)return bad();
 await ehrHash(v);return structuredClone(v);
}
