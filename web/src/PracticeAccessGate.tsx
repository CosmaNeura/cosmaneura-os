import {useCallback,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {practiceAccessApi} from './practice-access-api';
import {accessCode,accessName,type AccessStatus} from './practice-access-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import './practice-access.css';

export type PracticeAccessContext={role:'owner'|'member';onAccessLost:()=>void};
export const accessDenied=(error:unknown)=>error instanceof WorkspaceApiError && [401,403,404,426].includes(error.status);
export const accessFailure=(error:unknown)=>error instanceof WorkspaceApiError && error.status===426
  ? 'Update CosmasOS before continuing.' : accessDenied(error)
  ? 'Practice access is unavailable for this session. Check the selected organization or sign in again.'
  : error instanceof WorkspaceApiError && error.status===429
  ? 'The practice has reached its access-request limit. Try again later or contact the owner.'
  : 'The result could not be confirmed. Check your access before trying again.';

/** One bounded operation per mounted identity; no late result can enter another session. */
export function usePracticeAccessTask(identity:AuthenticatedWorkspaceIdentity) {
  const current=useRef(identity);current.current=identity;
  const scope=useRef<{identity:AuthenticatedWorkspaceIdentity;active:boolean;request:AbortController|null}|null>(null);
  const [busy,setBusy]=useState(false);
  useLayoutEffect(()=>{
    const next={identity,active:true,request:null as AbortController|null};scope.current=next;setBusy(false);
    return ()=>{next.active=false;next.request?.abort();};
  },[identity]);
  const run=useCallback(async <T,>(operation:(signal:AbortSignal)=>Promise<T>,accept:(value:T)=>void,fail:(error:unknown)=>void)=>{
    const started=scope.current;
    if(!started?.active || started.identity!==identity || current.current!==identity || started.request)return;
    const controller=new AbortController();started.request=controller;setBusy(true);
    const live=()=>started.active && scope.current===started && current.current===identity && !controller.signal.aborted;
    try {const value=await operation(controller.signal);if(live())accept(value);}
    catch(error){if(live())fail(error);}
    finally {if(live())setBusy(false);if(started.request===controller)started.request=null;}
  },[identity]);
  return {busy,run};
}

export function PracticeAccessGate({identity,accountControls,children}:{identity:AuthenticatedWorkspaceIdentity;accountControls:ReactNode;children:(access:PracticeAccessContext)=>ReactNode}) {
  const [observed,setObserved]=useState<{identity:AuthenticatedWorkspaceIdentity;status:AccessStatus}|null>(null);
  const [name,setName]=useState(''),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false);
  const requestKey=useRef<{name:string;key:string}|null>(null);
  const {busy,run}=usePracticeAccessTask(identity);
  const status=observed?.identity===identity?observed.status:null;
  const accept=useCallback((value:AccessStatus)=>{
    if(['cancelled','declined','expired','connected'].includes(value.state))requestKey.current=null;
    setObserved({identity,status:value});setUncertain(false);setError('');
  },[identity]);
  const fail=useCallback((cause:unknown)=>{if(accessDenied(cause))setObserved(null);setError(accessFailure(cause));},[]);
  const check=useCallback(()=>run(signal=>practiceAccessApi.read(identity,signal),accept,fail),[identity,run,accept,fail]);
  useEffect(()=>{setObserved(null);setName('');setError('');setUncertain(false);requestKey.current=null;void check();},[check]);
  useEffect(()=>{
    if(status?.state!=='pending')return;
    const refresh=()=>{if(document.visibilityState==='visible')void check();};
    const timer=window.setInterval(refresh,15000);document.addEventListener('visibilitychange',refresh);
    return ()=>{clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
  },[status?.state,check]);
  const onAccessLost=useCallback(()=>{setObserved(null);setError('Practice access changed. Check your access to continue.');},[]);
  if(status?.state==='connected' && status.role)return children({role:status.role,onAccessLost});
  const request=status?.request;
  const mayRequest=status && ['request_required','cancelled','declined','expired'].includes(status.state);
  async function submit(){
    if(busy||uncertain)return;
    const displayName=name.trim();if(!accessName(displayName))return;
    if(requestKey.current?.name!==displayName)requestKey.current={name:displayName,key:crypto.randomUUID()};
    const command={idempotency_key:requestKey.current.key,display_name:displayName};
    setError('');setUncertain(true);
    await run(signal=>practiceAccessApi.request(identity,command,signal),accept,fail);
  }
  async function cancel(){
    if(!request||busy||uncertain)return;
    setError('');setUncertain(true);
    await run(signal=>practiceAccessApi.cancel(identity,{request_id:request.request_id,review_sha256:request.review_sha256,confirm:true},signal),accept,fail);
  }
  return <main className="practice-access-gate">
    <nav aria-label="Account and organization">{accountControls}</nav>
    <h1>Join your practice</h1>
    <p>Your practice owner approves access to this workspace.</p>
    {error && <p role="alert">{error}</p>}
    {busy && <p role="status">Checking practice access…</p>}
    {request && <section aria-label="Your access request">
      <p><strong>{request.display_name}</strong></p>
      <p>Matching code: <strong className="practice-access-code">{accessCode(request)}</strong></p>
      {status?.state==='pending' && <><p>Waiting for your practice owner. Share your name and this code with them so they can match your request in Settings → Practice access.</p>
        <p>Request expires {new Date(request.expires_at).toLocaleString()}.</p>
        <button disabled={busy||uncertain} onClick={()=>void cancel()}>Cancel access request</button></>}
      {status?.state==='declined' && <p>The owner declined this request. Contact them before requesting access again.</p>}
      {status?.state==='expired' && <p>This request expired. You can send a new request.</p>}
      {status?.state==='cancelled' && <p>This request was cancelled.</p>}
      {status?.state==='approved' && <p>Your request was approved. Check access to open the workspace.</p>}
    </section>}
    {mayRequest && <form onSubmit={event=>{event.preventDefault();void submit();}}>
      <label>Your name<input autoComplete="name" maxLength={120} value={name} disabled={busy||uncertain} onChange={event=>setName(event.target.value)}/></label>
      <p>Use the name your practice owner knows. They will see this name and your matching code.</p>
      <button type="submit" disabled={busy||uncertain||!accessName(name.trim())}>Request practice access</button>
    </form>}
    <button disabled={busy} onClick={()=>void check()}>Check access</button>
  </main>;
}
