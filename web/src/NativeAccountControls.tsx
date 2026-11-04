import './native-account-controls.css';
import {useUnsavedWorkPresent} from './unsaved-work';

/** Names come only from the current authenticated practice-access response. */
export function NativeAccountControls({displayName,practiceName,onSignOut,onConnectPractice}:{
  displayName?:string|null;practiceName?:string|null;onSignOut:()=>void;onConnectPractice?:()=>void;
}) {
  const workPending=useUnsavedWorkPresent();
  return <details className="native-account-controls">
    <summary><strong>Account</strong>{practiceName&&<span>{practiceName}</span>}</summary>
    <div className="native-account-actions" role="group" aria-label="Signed-in account">
      <p>{displayName?<strong>{displayName}</strong>:'Signed in to your workspace'}</p>
      {practiceName&&<p>{practiceName}</p>}
      <button className="button secondary" onClick={onSignOut}>Log out</button>
      {onConnectPractice&&<><button className="button secondary" disabled={workPending} onClick={onConnectPractice}>Connect practice</button>
        {workPending&&<p role="status">Save your edits and finish pending work before connecting a practice.</p>}</>}
    </div>
  </details>;
}
