import {useState} from 'react';
import './native-account-controls.css';
import {ACCOUNT_DELETE_CONFIRM,accountDeletionApi} from './account-deletion-api';
import {AccountPublicLinks} from './AccountPublicLinks';
import {useUnsavedWorkPresent} from './unsaved-work';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {WorkspaceDialog} from './WorkspaceDialog';

/** Names come only from the current authenticated practice-access response. */
export function NativeAccountControls({displayName,practiceName,onSignOut,onConnectPractice,identity,clearNativeCredentials}:{
  displayName?:string|null;practiceName?:string|null;onSignOut:()=>void;onConnectPractice?:()=>void;
  identity?:AuthenticatedWorkspaceIdentity;clearNativeCredentials?:()=>Promise<void>;
}) {
  const workPending=useUnsavedWorkPresent();
  const [confirming,setConfirming]=useState(false);
  const [busy,setBusy]=useState(false);
  const [failed,setFailed]=useState(false);

  async function confirmDelete(){
    if(busy||!identity)return;
    setBusy(true);setFailed(false);
    try{
      await accountDeletionApi.deleteAccount(identity,ACCOUNT_DELETE_CONFIRM);
      setConfirming(false);
      if(clearNativeCredentials)await clearNativeCredentials();
      else onSignOut();
    }catch{
      setFailed(true);
    }finally{
      setBusy(false);
    }
  }

  return <><details className="native-account-controls">
    <summary><strong>Account</strong>{practiceName&&<span>{practiceName}</span>}</summary>
    <div className="native-account-actions" role="group" aria-label="Signed-in account">
      <p>{displayName?<strong>{displayName}</strong>:'Signed in to your workspace'}</p>
      {practiceName&&<p>{practiceName}</p>}
      <AccountPublicLinks/>
      <button type="button" className="button secondary" disabled={busy} onClick={onSignOut}>Log out</button>
      {identity&&<button type="button" className="button secondary" disabled={busy} onClick={()=>{setFailed(false);setConfirming(true);}}>Delete account</button>}
      {onConnectPractice&&<><button type="button" className="button secondary" disabled={workPending||busy} onClick={onConnectPractice}>Connect practice</button>
        {workPending&&<p role="status">Save your edits and finish pending work before connecting a practice.</p>}</>}
    </div>
  </details>
  {confirming&&identity&&<WorkspaceDialog title="Delete your account?" onClose={()=>{if(!busy)setConfirming(false);}} canRestoreFocus={()=>!busy}>
    <p>This permanently deletes your CosmaBot login and your personal connection data on this account. Practice records shared with teammates stay in place. This cannot be undone.</p>
    {failed&&<p role="alert">Your account could not be deleted. Nothing was removed. Try again, or contact your practice administrator if you are the practice owner with teammates.</p>}
    <div className="row account-controls">
      <button type="button" className="button secondary" disabled={busy} onClick={()=>setConfirming(false)}>Cancel</button>
      <button type="button" className="button" disabled={busy} onClick={()=>void confirmDelete()}>{busy?'Deleting…':'Delete account'}</button>
    </div>
  </WorkspaceDialog>}</>;
}
