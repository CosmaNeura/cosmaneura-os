import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {readVendorSetupReadiness} from './vendor-setup-api';
import {vendorUuid} from './vendor-contract';

export const FAX_PROVIDERS = ['spruce','srfax','documo','efax'] as const;
export type FaxProvider = typeof FAX_PROVIDERS[number];
export type FaxProviderReadiness = {
  id:FaxProvider; installed_accounts:number; active_accounts:number;
  review_required_accounts:number; unavailable_accounts:number; prepare_enabled_accounts:number;
};
export type FaxReadiness = {
  contract_version:1; scope:{box_id:string;owner_id:string}; enabled:boolean;
  work_enabled:boolean; delivery_enabled:boolean; credential_access_configured:boolean;
  document_storage_configured:boolean; providers:FaxProviderReadiness[];
};
const keys=(value:unknown,expected:string):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===expected;
export function parseFaxReadiness(value:unknown):FaxReadiness{
  if(!keys(value,'contract_version,credential_access_configured,delivery_enabled,document_storage_configured,enabled,providers,scope,work_enabled')||value.contract_version!==1||
    !keys(value.scope,'box_id,owner_id')||!vendorUuid(value.scope.box_id)||!vendorUuid(value.scope.owner_id)||
    !['enabled','work_enabled','delivery_enabled','credential_access_configured','document_storage_configured'].every(name=>typeof value[name]==='boolean')||
    !Array.isArray(value.providers)||value.providers.length!==FAX_PROVIDERS.length)throw new WorkspaceApiError(502);
  const seen=new Set<unknown>();
  for(const row of value.providers){
    if(!keys(row,'active_accounts,id,installed_accounts,prepare_enabled_accounts,review_required_accounts,unavailable_accounts')||
      !FAX_PROVIDERS.includes(row.id as FaxProvider)||seen.has(row.id)||
      !['installed_accounts','active_accounts','review_required_accounts','unavailable_accounts','prepare_enabled_accounts'].every(name=>Number.isInteger(row[name])&&Number(row[name])>=0&&Number(row[name])<=50)||
      Number(row.prepare_enabled_accounts)>Number(row.active_accounts)||Number(row.active_accounts)>Number(row.installed_accounts)||
      Number(row.active_accounts)+Number(row.review_required_accounts)+Number(row.unavailable_accounts)>50)throw new WorkspaceApiError(502);
    seen.add(row.id);
  }
  return value as FaxReadiness;
}

/** Reads only account setup counts. Does not retrieve patients, destinations or provider data. */
export function readFaxReadiness(identity:AuthenticatedWorkspaceIdentity,signal:AbortSignal):Promise<FaxReadiness>{
  return readVendorSetupReadiness(identity,parseFaxReadiness,signal);
}
