import {coreConnectionApi} from './core-connection-api';
import {googleConnectionRequest,type GoogleStatus} from './google-connection-api';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {schedulingLoginRequest} from './scheduling-login-api';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {ConnectionId} from './connection-catalog-api';
import {observeConnectionStatus,connectionHealth,connectionServices,type ConnectionHealth,type ConnectionService,type PersonalConnection} from './connection-operation-health';
import {readFaxReadiness,type FaxReadiness} from './fax-readiness-api';

export type ConnectionSummary = {
  label:string; reason:string; action:string; tone:'neutral'|'ready'|'attention'; checkedAt?:number;checkKind?:'account'|'availability';services?:ConnectionService[];accountVersion?:number|null;faxReadiness?:FaxReadiness;
};
export function personalConnectionSummary(provider:PersonalConnection,health:ConnectionHealth,accountLabel:string):ConnectionSummary{
  const services=connectionServices(provider,health),missing=services.find(row=>row.label==='Permission needed'),failed=services.find(row=>row.label==='Last read failed');
  const verified=services.every(row=>row.tone==='ready'),next=services.find(row=>row.tone!=='ready');
  return {label:!health.accountCurrent?'Needs account check':!health.connected?'Not connected':missing?'Partly connected':failed?'Needs attention':verified?'Reads verified':'Account connected',
    reason:!health.accountCurrent?'Check which account is connected.':!health.connected?'Sign in to connect your account.':accountLabel,
    action:!health.accountCurrent?'Check account':!health.connected?'Connect account':missing?'Add calendar access':failed?`Check ${failed.name.toLowerCase()} access`:next?`Check ${next.name.toLowerCase()}`:'View connection',
    tone:health.accountCurrent&&(!health.connected||missing||failed)?'attention':verified&&health.accountCurrent?'ready':'neutral',checkedAt:health.checkedAt??undefined,services,accountVersion:health.accountVersion};
}
export function faxConnectionSummary(readiness:FaxReadiness):ConnectionSummary{
  const total=(key:'installed_accounts'|'active_accounts'|'review_required_accounts'|'unavailable_accounts'|'prepare_enabled_accounts')=>readiness.providers.reduce((sum,row)=>sum+row[key],0);
  const base={checkedAt:Date.now(),checkKind:'account' as const,faxReadiness:readiness};
  if(!readiness.enabled)return {...base,label:'Admin setup',reason:'Your practice administrator needs to enable fax setup.',action:'View requirements',tone:'attention'};
  if(!total('installed_accounts'))return {...base,label:'Choose a fax provider',reason:'Spruce, SRFax, Documo and eFax are supported. A practice account must be installed before use.',action:'Compare fax options',tone:'neutral'};
  if(!total('prepare_enabled_accounts'))return {...base,
    label:total('active_accounts')?'Fax permission needed':total('unavailable_accounts')?'Account needs attention':'Account review needed',
    reason:total('active_accounts')?'An account is active, but fax preparation permission still needs review.':'Review and activate an installed fax account for this practice.',
    action:'Review fax setup',tone:'attention'};
  const missing=[!readiness.work_enabled&&'fax work',!readiness.credential_access_configured&&'service access',!readiness.document_storage_configured&&'private PDF storage',!readiness.delivery_enabled&&'sending'].filter(Boolean);
  if(missing.length)return {...base,label:'Finish fax setup',reason:`Administrator setup needed: ${missing.join(', ')}. No fax delivery or receiving was checked.`,action:'View requirements',tone:'attention'};
  return {...base,label:'Ready to prepare',reason:'Each fax needs a reviewed recipient, document and approval. Delivery and receiving have not been verified.',action:'View fax options',tone:'neutral'};
}
export const accountStatusSupported=(id:ConnectionId)=>['core','google','microsoft','scheduling','messaging'].includes(id);
export async function readConnectionSummary(identity:AuthenticatedWorkspaceIdentity,id:ConnectionId,signal:AbortSignal):Promise<ConnectionSummary>{
  if(id==='messaging')return faxConnectionSummary(await readFaxReadiness(identity,signal));
  if(id==='core'){
    const result=await coreConnectionApi.read(identity,{action:'connection',request_nonce:crypto.randomUUID()},signal);
    return result.connection_status==='connected'
      ?{label:'Connected',reason:result.discovery.connection.practice_label,action:'View connection',tone:'ready',checkedAt:Date.now()}
      :{label:result.connection_status==='review_required'?'Needs review':'Confirm practice',
        reason:result.connection_status==='review_required'?'Your practice administrator needs to confirm access.':'Confirm the practice matched to your account.',
        action:'Review connection',tone:'attention',checkedAt:Date.now()};
  }
  const result=id==='google'?await googleConnectionRequest(identity,'status',signal)
    :id==='microsoft'?await microsoftConnectionRequest(identity,'status',signal)
    :id==='scheduling'?await schedulingLoginRequest(identity,'status',signal):null;
  if(!result||!('state'in result)||result.state==='disconnected')throw new WorkspaceApiError(502);
  const checkedAt=Date.now();
  if(id==='google'||id==='microsoft'){
    const personal=result as GoogleStatus;
    observeConnectionStatus(identity,id,personal);
    if(personal.state==='connected')return personalConnectionSummary(id,connectionHealth(identity,id),personal.account?.email??'Account connected.');
  }
  if(result.state==='connected')return {label:'Connected',reason:'account'in result?result.account?.email||'Account connected.':'label'in result?result.label:'Account connected.',action:'View connection',tone:'ready',checkedAt};
  if(result.state==='completing_sign_in')return {label:'Finishing sign-in',reason:'The account connection is being verified.',action:'Check sign-in',tone:'neutral',checkedAt};
  if(result.state==='sign_in_pending')return {label:'Sign-in pending',reason:'Continue sign-in, then return to check the result.',action:'Continue setup',tone:'attention',checkedAt};
  return {label:'Not connected',reason:'Sign in to connect your account.',action:'Connect account',tone:'attention',checkedAt};
}
