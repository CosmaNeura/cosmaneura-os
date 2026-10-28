import {coreDigest} from './core-connection-contract';
import {validateAthenaVisitLinkCommand,validateAthenaVisitLinkResult,type AthenaVisitLinkCommand,type AthenaVisitLinkObservation} from './athena-visit-link-api';
import {vendorCanonical,vendorObject,vendorUuid} from './vendor-contract';

export const ATHENA_VISIT_RECOVERY_BYTES=8192;
export type AthenaVisitRecoveryScope={box_id:string;owner_id:string;recovery_scope:string};
export type AthenaVisitRecoveryTarget={operation:'link';appointment_ref:string;patient_ref:string}|{operation:'unlink';link_ref:string};
export type AthenaVisitRecoveryResolution={state:'linked'|'removed'|'review_required'|'not_found';checked_at:string;link_ref:string|null};
export type AthenaVisitRecoveryRecord={version:1;scope:AthenaVisitRecoveryScope;binding:{actor_ref:string;tenant_ref:string};
 request:AthenaVisitLinkCommand;command_sha256:string;target:AthenaVisitRecoveryTarget;metadata_sha256:string;resolution:AthenaVisitRecoveryResolution|null};
/** The host rechecks its signed account scope and journal generation on every authorization. */
export type AthenaVisitRecoveryAccess={authorize():Promise<void>;current():boolean;load():Promise<unknown>;persist(value:AthenaVisitRecoveryRecord):Promise<void>};
/** Inject the existing signed Core read client. This module has no default or live transport. */
export type AthenaVisitRecoveryRead=(command:AthenaVisitLinkCommand)=>Promise<unknown>;
type ErrorCode='invalid'|'scope_changed'|'storage_unavailable'|'pending'|'fresh_review_required'|'busy'|'unavailable'|'result_unverified';
export class AthenaVisitRecoveryError extends Error{
 constructor(readonly code:ErrorCode){super(`Athena visit recovery ${code}`);}
}
const fail=(code:ErrorCode='invalid'):never=>{throw new AthenaVisitRecoveryError(code);};
const sha=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const ref=(v:unknown,prefix:string):v is string=>typeof v==='string'&&new RegExp('^'+prefix+'_[0-7][0-9a-hjkmnp-tv-z]{25}$').test(v);
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>vendorObject(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
const same=(a:unknown,b:unknown)=>vendorCanonical(a)===vendorCanonical(b);
function bounded(value:unknown,maximum=ATHENA_VISIT_RECOVERY_BYTES){
 try{if(new TextEncoder().encode(vendorCanonical(value)).length>maximum)fail();}
 catch{fail();}
}
export function validAthenaVisitRecoveryScope(value:unknown):value is AthenaVisitRecoveryScope{
 try{bounded(value);return closed(value,'box_id,owner_id,recovery_scope')&&vendorUuid(value.box_id)&&vendorUuid(value.owner_id)&&sha(value.recovery_scope);}
 catch{return false;}
}
function stamp(value:unknown):value is string{
 return typeof value==='string'&&value.length<=40&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
}
async function commandHash(request:AthenaVisitLinkCommand,binding:AthenaVisitRecoveryRecord['binding']){
 const {request_nonce:_nonce,action,...fields}=request;
 return coreDigest({...fields,action:action==='athena_visit_link'?'link':'unlink',expected_actor_ref:binding.actor_ref,expected_tenant_ref:binding.tenant_ref});
}
async function seal(value:Omit<AthenaVisitRecoveryRecord,'metadata_sha256'>):Promise<AthenaVisitRecoveryRecord>{
 return {...value,metadata_sha256:await coreDigest({kind:'cosmas-athena-visit-recovery.v1',...value})};
}

/** Checksums detect corruption; the authorized encrypted journal supplies custody, not this hash. */
export async function validateAthenaVisitRecovery(value:unknown,scope:AthenaVisitRecoveryScope):Promise<AthenaVisitRecoveryRecord>{
 bounded(value);
 if(!validAthenaVisitRecoveryScope(scope)||!closed(value,'version,scope,binding,request,command_sha256,target,metadata_sha256,resolution')||value.version!==1||
  !validAthenaVisitRecoveryScope(value.scope)||!same(value.scope,scope)||!closed(value.binding,'actor_ref,tenant_ref')||
  !ref(value.binding.actor_ref,'authority_actor')||!ref(value.binding.tenant_ref,'authority_tenant')||!sha(value.command_sha256)||!sha(value.metadata_sha256)||!vendorObject(value.request))return fail();
 // Clone before hashing: a caller cannot change the command during an asynchronous digest.
 const record=structuredClone(value) as AthenaVisitRecoveryRecord,request=record.request,target=record.target;
 try{validateAthenaVisitLinkCommand(request);}catch{return fail();}
 if(request.action!=='athena_visit_link'&&request.action!=='athena_visit_unlink')return fail();
 if(request.action==='athena_visit_link'){
  if(!closed(target,'operation,appointment_ref,patient_ref')||target.operation!=='link'||target.appointment_ref!==request.appointment_ref||!ref(target.patient_ref,'patient'))return fail();
 }else if(!closed(target,'operation,link_ref')||target.operation!=='unlink'||target.link_ref!==request.link_ref)return fail();
 const resolution=record.resolution;
 if(resolution!==null){
  if(!closed(resolution,'state,checked_at,link_ref')||!stamp(resolution.checked_at))return fail();
  if(resolution.state==='not_found'){if(resolution.link_ref!==null)return fail();}
  else if(!['linked','removed','review_required'].includes(resolution.state)||!ref(resolution.link_ref,'athena_visit_link')||
   target.operation==='unlink'&&(resolution.state!=='removed'||resolution.link_ref!==target.link_ref))return fail();
 }
 if(await commandHash(request,record.binding)!==record.command_sha256)return fail();
 const {metadata_sha256,...body}=record;
 if((await seal(body)).metadata_sha256!==metadata_sha256)return fail();
 return record;
}

/** Called only by an explicit human confirmation of a fully validated fresh preview. */
export async function prepareAthenaVisitRecovery(scope:AthenaVisitRecoveryScope,previewCommand:AthenaVisitLinkCommand,previewValue:unknown,confirmed:boolean):Promise<AthenaVisitRecoveryRecord>{
 if(confirmed!==true||!validAthenaVisitRecoveryScope(scope))return fail();
 bounded(previewCommand);bounded(previewValue,16384);
 const owner=structuredClone(scope),preview=structuredClone(previewCommand),previewSnapshot=structuredClone(previewValue);
 if(preview.action!=='athena_visit_preview'&&preview.action!=='athena_visit_unlink_preview')return fail();
 let observation:AthenaVisitLinkObservation;
 try{
  validateAthenaVisitLinkCommand(preview);
  observation=(await validateAthenaVisitLinkResult(previewSnapshot,preview)).athena_visit_link;
 }catch{return fail('result_unverified');}
 if(observation.state!=='ready'||!observation.plan_sha256||!observation.command_sha256)return fail('fresh_review_required');
 const request:AthenaVisitLinkCommand={...preview,action:preview.action==='athena_visit_preview'?'athena_visit_link':'athena_visit_unlink',
  request_nonce:crypto.randomUUID(),plan_sha256:observation.plan_sha256,confirmed:true};
 let target:AthenaVisitRecoveryTarget;
 if(request.action==='athena_visit_link'){
  if(!observation.encounter||!request.appointment_ref)return fail('result_unverified');
  target={operation:'link',appointment_ref:request.appointment_ref,patient_ref:observation.encounter.patient.patient_ref};
 }else{
  if(!request.link_ref)return fail('result_unverified');
  target={operation:'unlink',link_ref:request.link_ref};
 }
 const record=await seal({version:1,scope:owner,binding:{actor_ref:observation.connection.actor_ref,tenant_ref:observation.connection.tenant_ref},
  request,command_sha256:observation.command_sha256,target,resolution:null});
 return validateAthenaVisitRecovery(record,owner);
}

export async function athenaVisitStatusCommand(value:AthenaVisitRecoveryRecord,scope:AthenaVisitRecoveryScope):Promise<AthenaVisitLinkCommand>{
 const r=await validateAthenaVisitRecovery(value,scope);
 return {action:'athena_visit_status',request_nonce:crypto.randomUUID(),connection_sha256:r.request.connection_sha256,
  account_sha256:r.request.account_sha256,command_key:r.request.command_key,command_sha256:r.command_sha256};
}
function exactTarget(observation:AthenaVisitLinkObservation,record:AthenaVisitRecoveryRecord){
 if(observation.connection.actor_ref!==record.binding.actor_ref||observation.connection.tenant_ref!==record.binding.tenant_ref||
  observation.connection.connection_sha256!==record.request.connection_sha256||observation.account.account_sha256!==record.request.account_sha256)return fail('result_unverified');
 if(!observation.applied)return;
 const target=record.target;
 if(observation.operation!==target.operation)return fail('result_unverified');
 if(target.operation==='unlink'){
  if(observation.state!=='removed'||observation.link_ref!==target.link_ref)return fail('result_unverified');
 }else if(observation.encounter&&(observation.encounter.appointment.appointment_ref!==target.appointment_ref||observation.encounter.patient.patient_ref!==target.patient_ref))return fail('result_unverified');
}

/** One mounted owner, one operation at a time; restored records can only issue status reads. */
export class AthenaVisitRecoverySession{
 private active=true;
 private running=false;
 private record:AthenaVisitRecoveryRecord|null=null;
 private readonly scope:AthenaVisitRecoveryScope;
 constructor(scope:AthenaVisitRecoveryScope,private readonly access:AthenaVisitRecoveryAccess,private readonly read:AthenaVisitRecoveryRead){
  if(!validAthenaVisitRecoveryScope(scope))fail();this.scope=structuredClone(scope);
 }
 close(){this.active=false;this.record=null;}
 snapshot():AthenaVisitRecoveryRecord|null{this.current();return structuredClone(this.record);}
 private current(){if(!this.active||!this.access.current())fail('scope_changed');}
 private async authorize(){this.current();try{await this.access.authorize();}catch{fail('scope_changed');}this.current();}
 private async owned<T>(work:()=>Promise<T>):Promise<T>{
  this.current();if(this.running)fail('busy');this.running=true;
  try{return await work();}finally{this.running=false;}
 }
 private async load(){
  await this.authorize();let value:unknown;
  try{value=await this.access.load();}catch{this.current();return fail('storage_unavailable');}
  await this.authorize();const record=value===null?null:await validateAthenaVisitRecovery(value,this.scope);this.current();
  this.record=record;return record;
 }
 private async persist(record:AthenaVisitRecoveryRecord){
  await this.authorize();const checked=await validateAthenaVisitRecovery(record,this.scope);this.current();
  try{await this.access.persist(structuredClone(checked));}catch{this.current();return fail('storage_unavailable');}
  await this.authorize();this.record=checked;
 }
 /** No provider call, even for a pending or previously resolved command. */
 restore(){return this.owned(async()=>structuredClone(await this.load()));}
 submit(previewCommand:AthenaVisitLinkCommand,previewValue:unknown,confirmed:boolean){
  return this.owned(async()=>{
   bounded(previewCommand);bounded(previewValue,16384);
   const reviewedCommand=structuredClone(previewCommand),reviewedValue=structuredClone(previewValue);
   const existing=await this.load();if(existing?.resolution===null)fail('pending');
   const record=await prepareAthenaVisitRecovery(this.scope,reviewedCommand,reviewedValue,confirmed);this.current();
   if(existing?.request.command_key===record.request.command_key)fail('fresh_review_required');
   await this.persist(record);
   return this.execute(record,record.request);
  });
 }
 check(){return this.owned(async()=>{
  const record=await this.load();if(!record)return fail('fresh_review_required');
  const command=await athenaVisitStatusCommand(record,this.scope);this.current();return this.execute(record,command);
 });}
 private async execute(record:AthenaVisitRecoveryRecord,command:AthenaVisitLinkCommand){
  await this.authorize();let value:unknown;
  try{value=await this.read(structuredClone(command));}catch{this.current();return fail('unavailable');}
  await this.authorize();let observation:AthenaVisitLinkObservation;
  try{bounded(value,16384);observation=(await validateAthenaVisitLinkResult(structuredClone(value),command)).athena_visit_link;exactTarget(observation,record);}
  catch{this.current();return fail('result_unverified');}
  this.current();
  if(!['linked','removed','review_required','not_found'].includes(observation.state))return fail('result_unverified');
  const resolution:AthenaVisitRecoveryResolution={state:observation.state as AthenaVisitRecoveryResolution['state'],checked_at:observation.checked_at,link_ref:observation.link_ref};
  const {metadata_sha256:_old,...body}=record;
  await this.persist(await seal({...body,resolution}));
  // Only this fresh, authorized projection is returned. Restore exposes metadata alone.
  this.current();return structuredClone(observation);
 }
}
