import {useCallback,useEffect,useState,type ReactNode} from 'react';
import {practiceAccessApi} from './practice-access-api';
import {usePracticeAccessTask} from './PracticeAccessGate';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {admitWorkspaceProtocol,subscribeWorkspaceProtocol,workspaceProtocolGeneration,workspaceProtocolPhase} from './workspace-protocol';
import './workspace-compatibility.css';

export function WorkspaceCompatibilityGate({identity,accountControls,children}:{identity:AuthenticatedWorkspaceIdentity;accountControls:ReactNode;children:ReactNode}) {
  const [admitted,setAdmitted]=useState<AuthenticatedWorkspaceIdentity|null>(null);
  const [phase,setPhase]=useState(()=>workspaceProtocolPhase(identity));
  const [error,setError]=useState('');
  const {busy,run}=usePracticeAccessTask(identity);
  useEffect(()=>{
    setAdmitted(null);setError('');setPhase(workspaceProtocolPhase(identity));
    return subscribeWorkspaceProtocol(identity,()=>setPhase(workspaceProtocolPhase(identity)));
  },[identity]);
  const check=useCallback(()=>{
    setError('');
    const generation=workspaceProtocolGeneration(identity);
    return run(async signal=>{
      await practiceAccessApi.compatibility(identity,signal);
    },()=>{admitWorkspaceProtocol(identity,generation);setAdmitted(identity);},cause=>setError(cause instanceof WorkspaceApiError && cause.status===426
      ? 'An update is needed before this workspace can connect. On desktop, use CosmaBot → Update CosmaBot for installation steps. If the app is current, the practice service needs a compatible update. Then check the connection again.'
      : cause instanceof WorkspaceApiError && [401,403].includes(cause.status)
      ? 'Your secure session could not be checked. Sign in again to continue.'
      : 'The workspace connection could not be checked. Reconnect and try again.'));
  },[identity,run]);
  useEffect(()=>{void check();},[check]);
  const opened=admitted===identity;
  return <>
    {(!opened || phase!=='ready') && <section className="workspace-compatibility" aria-label="Workspace connection" role={busy?'status':'alert'}>
      {!opened && <nav aria-label="Account and organization">{accountControls}</nav>}
      <h1>{busy?'Checking workspace connection':opened?'Workspace connection paused':'Connect to your workspace'}</h1>
      <p>{error || (phase==='blocked'?'The app and workspace service need a compatible update. Check the connection before sending or syncing more work.':'Checking that this app can work with your practice service.')}</p>
      <p>{opened?'Keep this workspace open. You can keep editing or stop a recording; sending and syncing new work are paused. Already-sent requests may still finish; check their saved results.':'Saved drafts and recordings stay on this device.'}</p>
      <button disabled={busy} onClick={()=>void check()}>Check connection</button>
    </section>}
    {/* Keep editors and the recorder mounted after admission, including uncertain writes. */}
    {opened && children}
  </>;
}
