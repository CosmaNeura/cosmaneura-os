import {WorkspaceApiError} from './workspace-api';
import {parseVendorJson, vendorObject, vendorUuid} from './vendor-contract';

export type CoreRecordLocation={contract_version:1;workspace_id:string;appointment_ref:string;href:string;checked_at:string};
export const RECORD_LOCATION_BYTES=2048;
export const RECORD_LOCATION_DEADLINE_MS=35000;
export const RECORD_LOCATION_MAX_AGE_MS=30000;
export const RECORD_NAVIGATION_EVENT='cosmas-cosmaneura-record-navigation';
export type RecordNavigationRequest={schemaVersion:1;requestId:string;expectedRevision:string;href:string};
export type RecordNavigationResult={schemaVersion:1;requestId:string;status:'opened'|'unavailable'};
declare global {
  interface Window {
    cosmasCosmaneuraNavigation?:{version:1;available:boolean;mode:'trusted-click'};
  }
}

export function validCoreWebOrigin(value:unknown):value is string {
  if(typeof value!=='string'||value.length>255||!value.startsWith('https://'))return false;
  const host=value.slice(8);
  if(!host.includes('.')||!/[a-z]/.test(host.split('.').at(-1)?.[0]??'')||
    !/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/.test(host)||
    !host.split('.').every(label=>/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)))return false;
  try{return new URL(value).origin===value;}catch{return false;}
}
export const configuredCoreWebOrigin=()=>import.meta.env.VITE_COSMANEURA_WEB_ORIGIN??'';
const closed=(value:unknown,keys:string):value is Record<string,unknown>=>vendorObject(value)&&
  Object.keys(value).sort().join(',')===keys&&Reflect.ownKeys(value).length===Object.keys(value).length;

export function validateRecordLocation(value:unknown,workspace:string,origin:string,now=Date.now()):CoreRecordLocation {
  if(!validCoreWebOrigin(origin)||!closed(value,'appointment_ref,checked_at,contract_version,href,workspace_id')||
    value.contract_version!==1||!vendorUuid(value.workspace_id)||value.workspace_id!==workspace||
    typeof value.appointment_ref!=='string'||!/^appointment_[0-7][0-9a-hjkmnp-tv-z]{25}$/.test(value.appointment_ref)||
    value.href!==origin+'/notes/'+value.appointment_ref||typeof value.checked_at!=='string'||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?(?:Z|[+-]\d\d:\d\d)$/.test(value.checked_at))throw new WorkspaceApiError(502);
  const checked=Date.parse(value.checked_at);
  if(!Number.isFinite(checked)||checked<now-RECORD_LOCATION_MAX_AGE_MS||checked>now+5000)throw new WorkspaceApiError(502);
  return {contract_version:1,workspace_id:value.workspace_id,appointment_ref:value.appointment_ref,href:value.href as string,checked_at:value.checked_at};
}

export function parseRecordNavigationResult(detail:unknown,requestId:string):RecordNavigationResult|null {
  if(typeof detail!=='string'||new TextEncoder().encode(detail).byteLength>512)return null;
  try {
    const value=parseVendorJson(detail);
    return closed(value,'requestId,schemaVersion,status')&&value.schemaVersion===1&&vendorUuid(value.requestId)&&
      value.requestId===requestId&&(value.status==='opened'||value.status==='unavailable')?value as RecordNavigationResult:null;
  }catch{return null;}
}
