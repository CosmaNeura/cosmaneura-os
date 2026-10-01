// Isolated UI fixtures. No authentication, provider calls or saved user data.
import {faxConnectionSummary,type ConnectionSummary} from '../src/connection-summary';
import type {FaxReadiness} from '../src/fax-readiness-api';
export {personalConnectionSummary} from '../src/connection-summary';

export let scenario='mixed';
export const setScenario=(value:string)=>{scenario=value;};
export const faxScenarios={
  'fax-empty':'Fax · no installed account (synthetic)',
  'fax-draft':'Fax · eFax draft setup, sending and storage missing (synthetic)',
  'fax-ready':'Fax · ready configuration (simulated, not provider verified)',
  'fax-failure':'Fax · status check fails (synthetic)',
};
export const accountStatusSupported=(id:string)=>['core','google','microsoft','scheduling','messaging'].includes(id);
function faxReadiness():FaxReadiness{
  const configured=scenario==='fax-draft'||scenario==='fax-ready',ready=scenario==='fax-ready';
  return {contract_version:1,scope:{box_id:'00000000-0000-4000-8000-000000000001',owner_id:'00000000-0000-4000-8000-000000000002'},
    enabled:true,work_enabled:true,delivery_enabled:ready,credential_access_configured:configured,document_storage_configured:ready,
    providers:(['spruce','srfax','documo','efax'] as const).map(id=>({id,installed_accounts:id==='efax'&&configured?1:0,
      active_accounts:id==='efax'&&configured?1:0,review_required_accounts:0,unavailable_accounts:0,
      prepare_enabled_accounts:id==='efax'&&configured?1:0}))};
}
const wait=(signal:AbortSignal)=>new Promise<void>((resolve,reject)=>{
  const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},scenario==='slow'?5000:350);
  const abort=()=>{clearTimeout(timer);reject(new Error('aborted'));};
  signal.addEventListener('abort',abort,{once:true});if(signal.aborted)abort();
});
export async function readConnectionCatalog(_identity:unknown,signal:AbortSignal){
  await wait(signal);if(scenario==='offline')throw new Error('Synthetic offline fixture');
  return {core:true,google:true,microsoft:true,scheduling:false,messaging:scenario in faxScenarios,payments:false,portals:false};
}
export async function readConnectionSummary(_identity:unknown,id:string,signal:AbortSignal):Promise<ConnectionSummary>{
  await wait(signal);
  if(id==='messaging'){
    if(scenario==='fax-failure')throw new Error('Synthetic fax status failure');
    return faxConnectionSummary(faxReadiness());
  }
  if(scenario==='failure'&&id==='microsoft')throw new Error('Synthetic status failure');
  if(scenario==='new')return {label:'Not connected',reason:'Sign in to connect your account.',action:'Connect account',tone:'attention',checkedAt:Date.now()};
  if(id==='microsoft')return {label:'Sign-in pending',reason:'Continue sign-in, then return to check the result.',action:'Continue setup',tone:'attention',checkedAt:Date.now()};
  return {label:'Connected',reason:id==='core'?'Cedar synthetic practice':'provider@example.invalid',action:'View connection',tone:'ready',checkedAt:Date.now()};
}
