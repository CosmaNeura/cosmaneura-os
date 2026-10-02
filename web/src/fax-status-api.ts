import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';
import {readVendorSavedFaxStatus} from './vendor-api';
import {vendorDigest,vendorUuid} from './vendor-contract';

type Recorded={id:string;sha256:string;sequence:number;observed_at:string;recorded_at:string};
export type FaxStatus={
  contract_version:1;scope:{box_id:string;owner_id:string;workspace_id:string};ticket_id:string;operation_id:string;
  revision_id:string;payload_hash:string;provider:'spruce'|'srfax'|'documo'|'efax';state:string;version:number;
  acceptance:'not_observed'|'accepted'|'rejected'|'unconfirmed';dispatch:'not_started'|'invocation_started'|'proved_not_dispatched'|'unconfirmed'|'response_observed';
  transport:'not_observed'|'pending'|'delivered'|'failed'|'unknown';result:'none'|'recorded_success'|'recorded_exception';
  verification:'pending'|'verified'|'exception_unresolved';conflicting_evidence:boolean;source_current:boolean|null;
  original_account_available:boolean;responsible_id:string;status_label:string;
  next_step:{code:string;label:string;requires_human:boolean};
  external_outcome:'not_established'|'unconfirmed'|'provider_transport_delivered'|'provider_transport_failed'|'spruce_posted_delivery_unconfirmed';
  observation_head:{sequence:number;sha256:string};evidence_sha256:string;last_recorded:Recorded|null;
  pages:{observation:Recorded;total:number;delivered:number}|null;observed_at:string;sha256:string;
};
const keys=(value:unknown,expected:string):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===expected;
const hash=(value:unknown)=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
const counter=(value:unknown,max=2147483647)=>Number.isInteger(value)&&Number(value)>=0&&Number(value)<=max;
const timestamp=(value:unknown)=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}T/.test(value)&&/(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value));
const recorded=(value:unknown)=>keys(value,'id,observed_at,recorded_at,sequence,sha256')&&vendorUuid(value.id)&&hash(value.sha256)&&counter(value.sequence)&&Number(value.sequence)>0&&timestamp(value.observed_at)&&timestamp(value.recorded_at);
const one=(value:unknown,allowed:string[])=>typeof value==='string'&&allowed.includes(value);
export async function parseFaxStatus(value:unknown):Promise<FaxStatus>{
  if(!keys(value,'acceptance,conflicting_evidence,contract_version,dispatch,evidence_sha256,external_outcome,last_recorded,next_step,observation_head,observed_at,operation_id,original_account_available,pages,payload_hash,provider,responsible_id,result,revision_id,scope,sha256,source_current,state,status_label,ticket_id,transport,verification,version')||value.contract_version!==1||
    !keys(value.scope,'box_id,owner_id,workspace_id')||!Object.values(value.scope).every(vendorUuid)||
    !['ticket_id','operation_id','revision_id','responsible_id'].every(k=>vendorUuid(value[k]))||
    !['payload_hash','evidence_sha256','sha256'].every(k=>hash(value[k]))||!counter(value.version)||Number(value.version)<1||
    !one(value.provider,['spruce','srfax','documo','efax'])||!one(value.acceptance,['not_observed','accepted','rejected','unconfirmed'])||
    !one(value.dispatch,['not_started','invocation_started','proved_not_dispatched','unconfirmed','response_observed'])||
    !one(value.transport,['not_observed','pending','delivered','failed','unknown'])||!one(value.result,['none','recorded_success','recorded_exception'])||
    !one(value.verification,['pending','verified','exception_unresolved'])||!one(value.external_outcome,['not_established','unconfirmed','provider_transport_delivered','provider_transport_failed','spruce_posted_delivery_unconfirmed'])||
    typeof value.conflicting_evidence!=='boolean'||typeof value.original_account_available!=='boolean'||!(value.source_current===null||typeof value.source_current==='boolean')||
    !one(value.state,['pending_approval','approved','rejected','withdrawn','superseded','closed'])||typeof value.status_label!=='string'||value.status_label.length<1||value.status_label.length>160||
    !keys(value.next_step,'code,label,requires_human')||typeof value.next_step.code!=='string'||!/^[a-z_]{1,64}$/.test(value.next_step.code)||typeof value.next_step.label!=='string'||value.next_step.label.length<1||value.next_step.label.length>240||typeof value.next_step.requires_human!=='boolean'||
    !keys(value.observation_head,'sequence,sha256')||!counter(value.observation_head.sequence)||!hash(value.observation_head.sha256)||
    !(value.last_recorded===null||recorded(value.last_recorded))||!timestamp(value.observed_at)||
    !(value.pages===null||keys(value.pages,'delivered,observation,total')&&recorded(value.pages.observation)&&counter(value.pages.total,1000000)&&counter(value.pages.delivered,1000000)&&Number(value.pages.delivered)<=Number(value.pages.total)))throw new WorkspaceApiError(502);
  const checked=value as FaxStatus;
  if((checked.last_recorded===null)!==(checked.observation_head.sequence===0)||checked.last_recorded&&checked.last_recorded.sequence!==checked.observation_head.sequence||checked.pages&&checked.pages.observation.sequence>checked.observation_head.sequence||checked.provider==='spruce'&&checked.external_outcome.startsWith('provider_transport_'))throw new WorkspaceApiError(502);
  const commitment=Object.fromEntries(Object.entries(value).filter(([key])=>!['sha256','observed_at'].includes(key)));
  if(await vendorDigest('cosmas-fax-status.v1',commitment)!==value.sha256)throw new WorkspaceApiError(502);
  return checked;
}
export function readFaxStatus(identity:WorkspaceIdentity,wid:string,tid:string,signal?:AbortSignal):Promise<FaxStatus>{
  return readVendorSavedFaxStatus(identity,wid,tid,async value=>{
    const result=await parseFaxStatus(value);
    if(result.scope.workspace_id!==wid||result.ticket_id!==tid||!('mode'in identity)&&(result.scope.box_id!==identity.boxId||result.scope.owner_id!==identity.actorId))throw new WorkspaceApiError(502);
    return result;
  },signal);
}
