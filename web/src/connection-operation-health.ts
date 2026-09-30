import {useSyncExternalStore} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

export type PersonalConnection = 'google'|'microsoft';
export type ConnectionRead = 'mail'|'calendar';
export type ReadHealth = {lastSuccessAt:string|null;latest:'unverified'|'succeeded'|'failed'|'cancelled'};
export type ConnectionHealth = {
  checkedAt:number|null;accountCurrent:boolean;connected:boolean;accountVersion:number|null;
  permissions:{mail:boolean|null;calendar:boolean|null};mail:ReadHealth;calendar:ReadHealth;
};
type Status = {state:string;account:{email:string}|null;connected_at:string|null;capabilities?:{mail:boolean;calendar:boolean}};
type ReadResult = {kind:ConnectionRead;account:{email:string};observed_at:string};
export type ConnectionReadScope = Readonly<{serial:number}>;
type Stored = {value:ConnectionHealth;binding:string|null;account:string|null;connectedAt:number;scope:ConnectionReadScope|null;listeners:Set<()=>void>};
const emptyRead=():ReadHealth=>({lastSuccessAt:null,latest:'unverified'});
const empty=():ConnectionHealth=>({checkedAt:null,accountCurrent:false,connected:false,accountVersion:null,permissions:{mail:null,calendar:null},mail:emptyRead(),calendar:emptyRead()});
const EMPTY=empty();
const owners=new WeakMap<AuthenticatedWorkspaceIdentity,Partial<Record<PersonalConnection,Stored>>>();
let serial=0;
function stored(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection):Stored{
  let item=owners.get(owner);if(!item){item={};owners.set(owner,item);}
  return item[provider]??= {value:empty(),binding:null,account:null,connectedAt:0,scope:null,listeners:new Set()};
}
function publish(item:Stored,value:ConnectionHealth){item.value=value;item.listeners.forEach(listener=>listener());}
export function connectionHealth(owner:AuthenticatedWorkspaceIdentity|undefined,provider:PersonalConnection):ConnectionHealth{
  return owner?stored(owner,provider).value:EMPTY;
}
export function useConnectionHealth(owner:AuthenticatedWorkspaceIdentity|undefined,provider:PersonalConnection){
  return useSyncExternalStore(listener=>{if(!owner)return()=>{};const item=stored(owner,provider);item.listeners.add(listener);return()=>{item.listeners.delete(listener);};},
    ()=>connectionHealth(owner,provider),()=>EMPTY);
}
// Session-only observations. No source contents, tokens, identifiers from mail or
// calendar, or browser persistence. A fresh identity starts without proof.
export function observeConnectionStatus(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection,status:Status){
  const item=stored(owner,provider),connected=status.state==='connected';
  const permissions=provider==='google'?{mail:status.capabilities?.mail??null,calendar:status.capabilities?.calendar??null}:{mail:null,calendar:null};
  const account=status.account?.email.trim().toLowerCase()??null,connectedAt=Date.parse(status.connected_at??'');
  const binding=connected&&account&&Number.isFinite(connectedAt)?JSON.stringify([account,status.connected_at,permissions]):null;
  const changed=!binding||binding!==item.binding;
  if(changed){item.scope=binding?{serial:++serial}:null;item.binding=binding;item.account=account;item.connectedAt=connectedAt;}
  publish(item,{checkedAt:Date.now(),accountCurrent:true,connected,accountVersion:item.scope?.serial??null,permissions,
    mail:changed?emptyRead():item.value.mail,calendar:changed?emptyRead():item.value.calendar});
}
export function invalidateConnectionHealth(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection){
  const item=stored(owner,provider);item.binding=null;item.account=null;item.scope=null;publish(item,empty());
}
export function connectionCheckFailed(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection){
  const item=stored(owner,provider);publish(item,{...item.value,accountCurrent:false});
}
export function connectionReadScope(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection){
  const item=stored(owner,provider);return item.value.accountCurrent&&item.value.connected?item.scope:null;
}
export function observeConnectionRead(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection,scope:ConnectionReadScope|null,result:ReadResult):boolean{
  const item=stored(owner,provider),when=Date.parse(result.observed_at);
  if(!scope||scope!==item.scope||!item.value.accountCurrent||item.value.permissions[result.kind]===false||
    result.account.email.trim().toLowerCase()!==item.account||!Number.isFinite(when)||when<item.connectedAt||when>Date.now()+300000)return false;
  publish(item,{...item.value,[result.kind]:{lastSuccessAt:result.observed_at,latest:'succeeded'}});return true;
}
export function connectionReadFailed(owner:AuthenticatedWorkspaceIdentity,provider:PersonalConnection,scope:ConnectionReadScope|null,kind:ConnectionRead,cancelled=false){
  const item=stored(owner,provider);if(!scope||scope!==item.scope)return;
  publish(item,{...item.value,[kind]:{...item.value[kind],latest:cancelled?'cancelled':'failed'}});
}
export type ConnectionService = {kind:ConnectionRead;name:string;label:string;detail:string;tone:'neutral'|'ready'|'attention';lastSuccessAt:string|null};
export function connectionServices(provider:PersonalConnection,health:ConnectionHealth):ConnectionService[]{
  return (['mail','calendar'] as const).map(kind=>{
    const read=health[kind],permission=health.permissions[kind],name=kind==='mail'?'Email':'Calendar';
    let label='Not verified',detail=provider==='microsoft'?'A Microsoft sign-in does not confirm an Outlook mailbox.':'Read once to check this account.',tone:ConnectionService['tone']='neutral';
    if(!health.accountCurrent){label='Needs account check';detail='Check the connected account before reading.';}
    else if(!health.connected){label='Not connected';detail='Connect an account to continue.';}
    else if(permission===false){label='Permission needed';detail='Add calendar access to view your week.';tone='attention';}
    else if(read.latest==='failed'){label='Last read failed';detail=provider==='microsoft'?'Check that this account has Outlook or Exchange. Google-hosted email uses Google Workspace.':'Check Google access, then try this read again.';tone='attention';}
    else if(read.latest==='cancelled'){label='Read cancelled';detail='No result was accepted. Read again when ready.';}
    else if(read.latest==='succeeded'){label='Verified in this session';detail='A bounded read succeeded for this account.';tone='ready';}
    else if(permission===true){detail='Permission granted; a read has not been verified.';}
    else if(provider==='google'){detail='Permission not checked; a read has not been verified.';}
    return {kind,name,label,detail,tone,lastSuccessAt:read.lastSuccessAt};
  });
}
export const PERSONAL_CONNECTION_DEADLINE_MS=50000;
export const personalConnectionProgress=(provider:PersonalConnection,action:string)=>({
  status:`Checking ${provider==='google'?'Google':'Microsoft'} account and permissions…`,
  mail:`Reading up to ${provider==='google'?10:25} email headers…`,calendar:'Reading calendar summaries for the next 7 days…',
  start:'Preparing secure sign-in…',disconnect:'Disconnecting this account…',recovery:'The read did not finish. Checking account access only…',
}[action]??'Checking connection…');
