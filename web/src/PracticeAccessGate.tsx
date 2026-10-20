import {invitationFromHash} from './practice-invitation-contract';
import {createContext,useCallback,useContext,useEffect,useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {practiceAccessApi} from './practice-access-api';
import {accessCode,accessName,type AccessStatus,type PracticeSetupStatus,type CompletePracticeSetup} from './practice-access-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {workspaceProtocolGeneration,workspaceProtocolPhase} from './workspace-protocol';
import type {WorkspaceStartupTeam} from './workspace-team-read';
import './practice-access.css';

export type PracticeAccessContext={role:'owner'|'member';onAccessLost:()=>void;startupTeam?:WorkspaceStartupTeam};
export const WorkspaceConnectionRecoveryContext=createContext<{
  identity:AuthenticatedWorkspaceIdentity;sequence:number;generation:number;phase:'pending'|'ready'|'blocked';busy:boolean;retry:()=>void;
}|null>(null);
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

export function PracticeAccessGate({identity,accountControls,children}:{identity:AuthenticatedWorkspaceIdentity;accountControls:ReactNode;children:(access:PracticeAccessContext)=>ReactNode;prefetchTeam?:boolean}) {
  const connection=useContext(WorkspaceConnectionRecoveryContext);
  const recovery=connection?.identity===identity?connection:null;
  const recoveredRead=useRef({identity,sequence:recovery?.sequence??0});
  const [observed,setObserved]=useState<{identity:AuthenticatedWorkspaceIdentity;status:AccessStatus}|null>(null);
  const [name,setName]=useState(''),[error,setError]=useState(''),[uncertain,setUncertain]=useState(false);
  const [setup,setSetup]=useState<{identity:AuthenticatedWorkspaceIdentity;value:PracticeSetupStatus}|null>(null);
  const [practiceName,setPracticeName]=useState(''),[specialty,setSpecialty]=useState('');
  const [inviteToken,setInviteToken]=useState(()=>invitationFromHash(window.location.hash));
  const [entry,setEntry]=useState<'choose'|'solo'|'join'>(()=>invitationFromHash(window.location.hash)?'join':'choose');
  useEffect(()=>{const change=()=>{const token=invitationFromHash(window.location.hash);setInviteToken(token);if(token)setEntry('join');};window.addEventListener?.('hashchange',change);return()=>window.removeEventListener?.('hashchange',change);},[]);
  const setupCommand=useRef<CompletePracticeSetup|null>(null);
  const requestKey=useRef<{name:string;key:string}|null>(null);
  const {busy:taskBusy,run}=usePracticeAccessTask(identity);
  const busy=taskBusy||!!recovery&&(recovery.busy||recovery.phase!=='ready');
  const status=observed?.identity===identity?observed.status:null;
  const accept=useCallback((value:AccessStatus)=>{
    if(['cancelled','declined','expired','connected'].includes(value.state))requestKey.current=null;
    setObserved({identity,status:value});setUncertain(false);setError('');
  },[identity]);
  const fail=useCallback((cause:unknown)=>{if(accessDenied(cause)){setObserved(null);setSetup(null);}setError(accessFailure(cause));},[]);
  const acceptSetup=useCallback((value:PracticeSetupStatus,preserveFields=false)=>{
    const pending=value.state==='owner_ready'?null:setupCommand.current;
    setSetup({identity,value});
    if(!preserveFields){
      setPracticeName(pending?.practice_name??value.practice?.display_name??'My practice');
      if(pending?.display_name??value.display_name)setName(pending?.display_name??value.display_name??'');
      setSpecialty(pending?.specialty??value.practice?.specialty??'');
    }
    if(value.state==='owner_ready'){setupCommand.current=null;setUncertain(false);}
    else if(setupCommand.current)setUncertain(false);
  },[identity]);
  const check=useCallback((preserveFields=false)=>run(async signal=>{
    // Practice admission depends only on its authenticated access and setup
    // reads. The mounted encounter loads its optional team independently.
    const generation=workspaceProtocolGeneration(identity),expiresAt=performance.now()+15000;
    const [status,profile]=await Promise.all([practiceAccessApi.read(identity,signal),practiceAccessApi.setup(identity,signal)]);
    signal.throwIfAborted();
    if(performance.now()>=expiresAt||workspaceProtocolGeneration(identity)!==generation)throw new WorkspaceApiError(503);
    return {status,profile};
  },value=>{accept(value.status);acceptSetup(value.profile,preserveFields);},fail),[identity,run,accept,acceptSetup,fail]);
  useEffect(()=>{setObserved(null);setSetup(null);setName('');setPracticeName('');setSpecialty('');setEntry(invitationFromHash(window.location.hash)?'join':'choose');setError('');setUncertain(false);requestKey.current=null;setupCommand.current=null;void check();},[check]);
  useLayoutEffect(()=>{recoveredRead.current={identity,sequence:recovery?.sequence??0};},[identity]);
  useEffect(()=>{
    if(!recovery||recoveredRead.current.identity!==identity||recovery.sequence<=recoveredRead.current.sequence||
      recovery.phase!=='ready'||recovery.busy||taskBusy||workspaceProtocolGeneration(identity)!==recovery.generation)return;
    // One explicit successful connection retry, one read. Existing form keys and
    // unconfirmed writes are never submitted by this recovery path.
    recoveredRead.current.sequence=recovery.sequence;void check(true);
  },[identity,recovery?.sequence,recovery?.generation,recovery?.phase,recovery?.busy,taskBusy,check]);
  useEffect(()=>{
    if(status?.state!=='pending')return;
    const refresh=()=>{if(document.visibilityState==='visible'&&workspaceProtocolPhase(identity)==='ready')void check();};
    const timer=window.setInterval(refresh,15000);document.addEventListener('visibilitychange',refresh);
    return ()=>{clearInterval(timer);document.removeEventListener('visibilitychange',refresh);};
  },[status?.state,check,identity]);
  const onAccessLost=useCallback(()=>{setObserved(null);setSetup(null);setError('Practice access changed. Check your access to continue.');},[]);
  const profile=setup?.identity===identity?setup.value:null;
  if(status?.state==='connected' && status.role&&profile&&(profile.state==='owner_ready'||profile.state==='member_ready'))return children({role:status.role,onAccessLost});
  if(recovery&&recovery.phase!=='ready')return <section className="workspace-access-paused" aria-label="Practice access paused">
    <nav aria-label="Account and organization">{accountControls}</nav>
    <p>Practice access will be checked after Retry.{uncertain?' Your unconfirmed request is retained; nothing will be sent again.':''}</p>
  </section>;
  const request=status?.request;
  const mayRequest=status && ['request_required','cancelled','declined','expired'].includes(status.state);
  async function submit(){
    if(busy||uncertain)return;
    const displayName=name.trim();if(!accessName(displayName))return;
    if(requestKey.current?.name!==displayName)requestKey.current={name:displayName,key:crypto.randomUUID()};
    const command={idempotency_key:requestKey.current.key,display_name:displayName};
    setError('');setUncertain(true);
    await run(signal=>inviteToken?practiceAccessApi.joinInvitation(identity,{...command,token:inviteToken},signal):practiceAccessApi.request(identity,command,signal),accept,cause=>{if(cause instanceof WorkspaceApiError&&cause.code==='practice_invitation_unavailable'){setUncertain(false);setError('This invitation expired or was revoked. Ask your practice owner for a new link.');}else fail(cause);});
  }
  async function cancel(){
    if(!request||busy||uncertain)return;
    setError('');setUncertain(true);
    await run(signal=>practiceAccessApi.cancel(identity,{request_id:request.request_id,review_sha256:request.review_sha256,confirm:true},signal),accept,fail);
  }
  async function finishSetup(){
    if(busy||uncertain||!profile||!['owner_setup','solo_setup_available'].includes(profile.state))return;
    const practice=practiceName.trim(),display=name.trim(),choice=specialty.trim()||null;
    if(!accessName(practice)||!accessName(display)||choice!==null&&!accessName(choice))return;
    const command=setupCommand.current??{idempotency_key:crypto.randomUUID(),practice_name:practice,display_name:display,specialty:choice,confirm:true};
    setupCommand.current=command;setUncertain(true);setError('');
    await run(signal=>practiceAccessApi.confirmSetup(identity,command,signal),value=>{
      acceptSetup(value);setObserved({identity,status:{contract_version:1,state:'connected',role:'owner',request:null}});
    },fail);
  }
  const showSetup=profile?.state==='owner_setup'||entry==='solo'&&profile?.can_start_practice;
  if(showSetup)return <main className="practice-access-gate practice-quick-setup">
    <nav aria-label="Account and organization">{accountControls}</nav>
    <p className="practice-setup-kicker">YOUR PRACTICE · QUICK SETUP</p><h1>Let's get you ready.</h1>
    <p>Confirm your practice. Your provider team and first private note are next.</p>
    {error&&<p role="alert">{error}</p>}
    <div className="practice-setup-fields">
      <label>Practice name<input maxLength={120} value={practiceName} disabled={busy||uncertain||setupCommand.current!==null} onChange={event=>setPracticeName(event.target.value)}/></label>
      <label>Your name<input autoComplete="name" maxLength={120} value={name} disabled={busy||uncertain||setupCommand.current!==null} onChange={event=>setName(event.target.value)}/></label>
      <label>Specialty <span>optional</span><input maxLength={120} value={specialty} disabled={busy||uncertain||setupCommand.current!==null} placeholder="General practice" onChange={event=>setSpecialty(event.target.value)}/></label>
    </div>
    <p>No email, calendar or patient portal is needed to start a private note.</p>
    <button className="practice-setup-primary" disabled={busy||uncertain||!accessName(practiceName.trim())||!accessName(name.trim())} onClick={()=>void finishSetup()}>Continue to my workspace</button>
    {uncertain&&<p role="status">Setup may have finished. Check setup before trying again.</p>}
    <button disabled={busy} onClick={()=>recovery?recovery.retry():void check()}>{recovery?'Retry':'Check setup'}</button>
  </main>;
  return <main className="practice-access-gate">
    <nav aria-label="Account and organization">{accountControls}</nav>
    <h1>{entry==='join'||request?'Join your practice':'Welcome to your practice workspace'}</h1>
    {entry==='choose'&&!request&&profile&&<div className="practice-entry-choices">
      <button onClick={()=>setEntry('solo')}>Set up my practice</button><button onClick={()=>setEntry('join')}>Join an existing practice</button>
    </div>}
    {entry==='solo'&&!profile?.can_start_practice&&<section><h2>Set up my practice</h2><p>This sign-in belongs to an existing practice or has no reserved owner workspace. A new practice must be authorized before setup; joining this practice does not make you its owner.</p><button onClick={()=>setEntry('choose')}>Back</button></section>}
    {(entry==='join'||request)&&<p>Your practice owner approves access to this workspace.</p>}
    {inviteToken&&<p>This invitation is for the practice organization selected in your signed-in account. Choose that organization first. The owner will still review your request and matching code.</p>}
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
    {mayRequest&&entry==='join' && <form onSubmit={event=>{event.preventDefault();void submit();}}>
      <label>Your name<input autoComplete="name" maxLength={120} value={name} disabled={busy||uncertain} onChange={event=>setName(event.target.value)}/></label>
      <p>Use the name your practice owner knows. They will see this name and your matching code.</p>
      <button type="submit" disabled={busy||uncertain||!accessName(name.trim())}>Request practice access</button>
    </form>}
    <button disabled={busy} onClick={()=>recovery?recovery.retry():void check()}>{recovery?'Retry':'Check access'}</button>
  </main>;
}
