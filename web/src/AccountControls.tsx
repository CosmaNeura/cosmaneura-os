import {useState,type ReactNode} from 'react';
import {ACCOUNT_DELETE_CONFIRM,accountDeletionApi} from './account-deletion-api';
import {AccountPublicLinks} from './AccountPublicLinks';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {WorkspaceDialog} from './WorkspaceDialog';

type Props={
  identity:AuthenticatedWorkspaceIdentity;
  onSignOut:()=>void|Promise<void>;
  /** Optional native Keychain wipe after the server deletes the Clerk login. */
  clearNativeCredentials?:()=>Promise<void>;
  /** Extra controls kept next to Log out (for example Clerk UserButton). */
  extras?:ReactNode;
};

export function AccountControls({identity,onSignOut,clearNativeCredentials,extras}:Props){
  const [confirming,setConfirming]=useState(false);
  const [busy,setBusy]=useState(false);
  const [failed,setFailed]=useState(false);

  async function confirmDelete(){
    if(busy)return;
    setBusy(true);setFailed(false);
    try{
      await accountDeletionApi.deleteAccount(identity,ACCOUNT_DELETE_CONFIRM);
      setConfirming(false);
      if(clearNativeCredentials)await clearNativeCredentials();
      else await onSignOut();
    }catch{
      setFailed(true);
    }finally{
      setBusy(false);
    }
  }

  return <>
    <div className="row account-controls" aria-label="Account">
      {extras}
      <AccountPublicLinks/>
      <button type="button" className="button secondary" disabled={busy} onClick={()=>void onSignOut()}>Log out</button>
      <button type="button" className="button secondary" disabled={busy} onClick={()=>{setFailed(false);setConfirming(true);}}>Delete account</button>
    </div>
    {confirming&&<WorkspaceDialog title="Delete your account?" onClose={()=>{if(!busy)setConfirming(false);}} canRestoreFocus={()=>!busy}>
      <p>This permanently deletes your CosmaBot login and your personal connection data on this account. Practice records shared with teammates stay in place. This cannot be undone.</p>
      {failed&&<p role="alert">Your account could not be deleted. Nothing was removed. Try again, or contact your practice administrator if you are the practice owner with teammates.</p>}
      <div className="row account-controls">
        <button type="button" className="button secondary" disabled={busy} onClick={()=>setConfirming(false)}>Cancel</button>
        <button type="button" className="button" disabled={busy} onClick={()=>void confirmDelete()}>{busy?'Deleting…':'Delete account'}</button>
      </div>
    </WorkspaceDialog>}
  </>;
}
