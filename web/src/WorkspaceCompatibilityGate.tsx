import {useCallback,useEffect,useState,type ReactNode} from 'react';
import {practiceAccessApi} from './practice-access-api';
import {usePracticeAccessTask,WorkspaceConnectionRecoveryContext} from './PracticeAccessGate';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {admitWorkspaceProtocol,subscribeWorkspaceProtocol,workspaceProtocolGeneration,workspaceProtocolPhase} from './workspace-protocol';
import './workspace-compatibility.css';

export function WorkspaceCompatibilityGate({identity,accountControls,children}:{identity:AuthenticatedWorkspaceIdentity;accountControls:ReactNode;children:ReactNode}) {
  const [admitted,setAdmitted]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const [phase,setPhase]=useState(()=>workspaceProtocolPhase(identity));
  const [error,setError]=useState('');
  const [recovery,setRecovery]=useState<{identity:AuthenticatedWorkspaceIdentity;sequence:number;generation:number}|null>(null);
  const {busy,run}=usePracticeAccessTask(identity);
  useEffect(()=>{
    setAdmitted(null);setError('');setRecovery(null);setPhase(workspaceProtocolPhase(identity));
    return subscribeWorkspaceProtocol(identity,()=>setPhase(workspaceProtocolPhase(identity)));
  },[identity]);
  const check=useCallback((reconnecting=false)=>{
    setError('');
    const generation=workspaceProtocolGeneration(identity);
    return run(async signal=>{
      await practiceAccessApi.compatibility(identity,signal);
    },()=>{admitWorkspaceProtocol(identity,generation);setAdmitted(identity);
      if(reconnecting)setRecovery(previous=>({identity,generation,sequence:previous?.identity===identity?previous.sequence+1:1}));
    },cause=>setError(cause instanceof WorkspaceApiError && cause.status===426
      ? 'The app and practice service could not confirm a compatible version. Retry after the app or service is updated.'
      : cause instanceof WorkspaceApiError && [401,403].includes(cause.status)
      ? 'Your secure session could not be checked. Sign in again to continue.'
      : 'The practice service could not be reached or its reply could not be checked. Reconnect and retry.'));
  },[identity,run]);
  useEffect(()=>{void check();},[check]);
  const opened=admitted===identity;
  const compact=opened&&identity.mode==='clerk_jwt'&&!!identity.nativeSession&&
    (window.matchMedia?.('(max-width: 600px)').matches??false);
  return <WorkspaceConnectionRecoveryContext.Provider value={{identity,sequence:recovery?.identity===identity?recovery.sequence:0,
    generation:recovery?.identity===identity?recovery.generation:workspaceProtocolGeneration(identity),phase,busy,retry:()=>void check(true)}}>
    {(!opened || phase!=='ready') && <section className={`workspace-compatibility${opened?' workspace-compatibility-paused':''}${compact?' workspace-compatibility-native':''}`} aria-label="Workspace connection" role={busy?'status':'alert'}>
      {!opened && <nav aria-label="Account and organization">{accountControls}</nav>}
      <header><h1>{compact?(busy?'Reconnecting…':'Connection paused'):busy?'Checking workspace connection':opened?'Workspace connection paused':'Connect to your workspace'}</h1>
        <button disabled={busy} onClick={()=>void check(true)}>{busy?'Retrying…':'Retry'}</button></header>
      {!compact&&<p>{error || (phase==='blocked'?'The service connection is paused. Retry checks the connection and your practice access.':'Checking that this app can work with your practice service.')}</p>}
      {compact&&<p>{error||'Sending is paused. Your saved work stays on this device.'}</p>}
      {opened?<details><summary>{compact?'Connection details':'Your saved work is retained'}</summary>
        {compact&&!error&&<p>Retry checks the service connection and your practice access.</p>}
        <p>You can keep editing or stop a recording. Sending and syncing are paused. Already-sent requests may still finish; their saved results need to be checked separately.</p></details>
        :<p>Saved drafts and recordings stay on this device.</p>}
    </section>}
    {/* Keep editors and the recorder mounted after admission, including uncertain writes. */}
    {opened && children}
  </WorkspaceConnectionRecoveryContext.Provider>;
}
