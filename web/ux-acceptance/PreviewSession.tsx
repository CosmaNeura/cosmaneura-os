import {useSyncExternalStore,type ReactNode} from 'react';
import type {AuthenticatedWorkspaceIdentity} from '../src/workspace-api';
import {previewSession} from './preview-session';

export function PreviewSession({children,session=previewSession}:{
  children:(identity:AuthenticatedWorkspaceIdentity,controls:ReactNode)=>ReactNode;
  session?:typeof previewSession;
}){
  const state=useSyncExternalStore(session.subscribe,session.getSnapshot);
  function enter(){
    // Re-entry starts at the inbox, not the previous account's settings/task URL.
    window.history.replaceState(window.history.state,'','#cosmas/home');
    session.enter();
  }
  if(state.open)return children(state.identity,<button className="button secondary" onClick={()=>session.close()}>Log out</button>);
  return <main className="shell"><section className="panel" aria-label="Preview session">
    <h1>Preview is closed</h1>
    <p>This preview uses invented information. No real account is signed in.</p>
    <p>Continue when you are ready to use the preview again. Saved draft recovery is kept separate from this choice.</p>
    {state.storageError&&<p role="alert">This device could not remember your preview session choice. The workspace is closed here. Close this window before leaving the device, or try again.</p>}
    <button className="button" style={{minHeight:44,whiteSpace:'normal'}} onClick={enter}>Continue preview</button>
  </section></main>;
}
