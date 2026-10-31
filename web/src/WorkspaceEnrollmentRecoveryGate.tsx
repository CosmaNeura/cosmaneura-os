import {useEffect,useState,useSyncExternalStore,type ReactNode} from 'react';
import {usePracticeAccessTask} from './PracticeAccessGate';
import {practiceAccessApi} from './practice-access-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import {permittedWorkspaceApi} from './workspace-origin';
import {admitWorkspaceProtocol,workspaceFetch,workspaceProtocolGeneration} from './workspace-protocol';
import {WORKSPACE_ENROLLMENT_HEADER,releaseWorkspaceEnrollment,subscribeWorkspaceEnrollment,workspaceEnrollmentHold,workspaceEnrollmentRevision} from './workspace-enrollment-state';
import {WorkspaceStartupShell} from './WorkspaceStartupShell';
import './workspace-enrollment.css';
import {hostedWorkspaceConfiguration} from './hosted-workspace';

export function enrollmentRecoveryDestination(value:unknown,apiBase=hostedWorkspaceConfiguration()?.apiOrigin??import.meta.env.VITE_API_BASE,accountOrigin?:unknown):string|null{
  try{
    if(typeof apiBase!=='string')return null;const api=new URL(apiBase);
    if(apiBase!==api.origin||api.protocol!=='https:'||api.username||api.password||api.port||api.search||api.hash||api.pathname!=='/')return null;
    const staging=['staging.cosmas.ai','api.staging.cosmas.ai'].includes(api.hostname)||/^api\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.staging\.cosmas\.ai$/.test(api.hostname);
    const production=api.hostname==='api.cosmas.ai'||/^api\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.workspace\.cosmas\.ai$/.test(api.hostname);
    if(!staging&&!production)return null;
    // The runtime supplies its validated immutable account binding. Never infer
    // a destination from an API hostname or accept a browser-provided redirect.
    const allowed=staging?['https://staging.cosmas.ai','https://onboarding.staging.cosmas.ai']:['https://app.cosmas.ai'];
    if(typeof accountOrigin!=='string'||!allowed.includes(accountOrigin))return null;
    const expected=accountOrigin+'/onboarding';return value===expected?expected:null;
  }catch{return null;}
}
async function bounded<T>(signal:AbortSignal|undefined,work:(signal:AbortSignal)=>Promise<T>):Promise<T>{
  const controller=new AbortController(),abort=()=>controller.abort();
  const interrupted=new Promise<never>((_,reject)=>controller.signal.addEventListener('abort',()=>reject(new WorkspaceApiError(504)),{once:true}));
  const timer=setTimeout(abort,15000);signal?.addEventListener('abort',abort,{once:true});if(signal?.aborted)abort();
  try{return await Promise.race([work(controller.signal),interrupted]);}finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);controller.abort();}
}
async function request(identity:AuthenticatedWorkspaceIdentity,path:string,signal:AbortSignal):Promise<Response>{
  const base=import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||'http://127.0.0.1:8000';
  if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href))throw new WorkspaceApiError(503);
  const headers=await workspaceAuthHeaders(identity,base);signal.throwIfAborted();assertCurrentDesktopSession(identity);
  const response=await workspaceFetch(identity,base+path,{headers,signal,method:'GET',credentials:'omit',cache:'no-store',redirect:'error',referrerPolicy:'no-referrer'},true);
  assertCurrentDesktopSession(identity);signal.throwIfAborted();
  if(response.status!==200||response.redirected||response.type==='opaque'||response.url&&response.url!==base+path||
    response.headers.get(WORKSPACE_ENROLLMENT_HEADER)!==null||response.headers.get('content-type')?.split(';')[0].trim().toLowerCase()!=='application/json'||
    !response.headers.get('cache-control')?.split(',').some(value=>value.trim().toLowerCase()==='no-store')){void response.body?.cancel().catch(()=>{});throw new WorkspaceApiError(response.status===403?403:503);}
  return response;
}
async function recoveryLink(identity:AuthenticatedWorkspaceIdentity,signal:AbortSignal):Promise<string|null>{
  const response=await request(identity,'/config',signal),reader=response.body?.getReader();if(!reader)throw new WorkspaceApiError(503);
  const bytes=new Uint8Array(65536);let size=0;
  const cancel=()=>{void reader.cancel().catch(()=>{});};signal.addEventListener('abort',cancel,{once:true});
  try{for(;;){signal.throwIfAborted();const part=await reader.read();signal.throwIfAborted();if(part.done)break;
    if(part.value.length>bytes.length-size)throw new WorkspaceApiError(503);bytes.set(part.value,size);size+=part.value.length;}
    const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(0,size)));
    return value?.enrollment_managed===true?enrollmentRecoveryDestination(value?.enrollment_recovery_url,undefined,value?.enrollment_account_origin):null;
  }finally{signal.removeEventListener('abort',cancel);cancel();}
}
export function WorkspaceEnrollmentRecoveryGate({identity,accountControls,children}:{identity:AuthenticatedWorkspaceIdentity;accountControls?:ReactNode;children:ReactNode}){
  const observedRevision=useSyncExternalStore(listener=>subscribeWorkspaceEnrollment(identity,listener),()=>workspaceEnrollmentRevision(identity),()=>0);
  const hold=workspaceEnrollmentHold(identity);
  const [destination,setDestination]=useState<{identity:AuthenticatedWorkspaceIdentity;url:string|null}|null>(null),[message,setMessage]=useState('');
  const {busy,run}=usePracticeAccessTask(identity);
  useEffect(()=>{setDestination(null);setMessage('');if(!hold)return;
    const controller=new AbortController();let current=true;
    void bounded(controller.signal,signal=>recoveryLink(identity,signal)).then(url=>{if(current)setDestination({identity,url});}).catch(()=>{if(current)setDestination({identity,url:null});});
    return()=>{current=false;controller.abort();};
  },[identity,hold,observedRevision]);
  const recheck=()=>{setMessage('');const revision=workspaceEnrollmentRevision(identity);
    void run(signal=>bounded(signal,async signal=>{const generation=workspaceProtocolGeneration(identity);await practiceAccessApi.compatibility(identity,signal);signal.throwIfAborted();admitWorkspaceProtocol(identity,generation);
      const response=await request(identity,'/account/identity',signal);void response.body?.cancel().catch(()=>{});return revision;
    }),checked=>releaseWorkspaceEnrollment(identity,checked),()=>setMessage('Practice access is still paused. Review the existing account and billing setup, then check again.'));
  };
  if(!hold)return <>{children}</>;
  const link=destination?.identity===identity?destination.url:null;
  return <WorkspaceStartupShell status="Practice access paused"><section className="workspace-enrollment-recovery" role="alert" aria-label="Practice account recovery">
    <nav aria-label="Account">{accountControls}</nav><h1>Practice access is paused</h1>
    <p>{hold==='workspace_enrollment_access_required'?'Your practice account needs an enrollment or billing review.':'The service could not confirm your practice account and billing access.'}</p>
    <p>Saved work is retained. Already submitted requests may still finish; check their saved results after access returns.</p>
    <div>{link&&<a className="button" href={link} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Review account and billing</a>}
      <button disabled={busy} onClick={recheck}>{busy?'Checking access…':'Check practice access'}</button></div>
    {!link&&<p>Use your practice’s account service or contact the practice owner for help.</p>}
    {message&&<p role="status">{message}</p>}
  </section></WorkspaceStartupShell>;
}
