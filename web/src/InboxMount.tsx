import {useContext,useEffect,useMemo,useRef} from 'react';
import {AccountRecoveryContext} from './account-recovery';
import {accountEditorAddress} from './draft-journal';
import {DraftStoreError} from './draft-store';
import type {InboxDraftSelection} from './inbox-analysis-contract';
import {InboxPanel} from './InboxPanel';
import {validateInbox} from './inbox-contract';
import {validateInboxRecovery,type InboxRecoveryAccess} from './inbox-recovery';
import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';

export const INBOX_BUILD = import.meta.env.VITE_INBOX_ENABLED === 'true';

export function InboxMount({identity,onDenied,onBusyChange,onOpenHandoff,onDraftInbox,enabled=INBOX_BUILD}:{
  identity:WorkspaceIdentity; onDenied:(cause:unknown)=>void;
  onBusyChange?:(busy:boolean)=>void; onOpenHandoff?:(itemId:string)=>void; onDraftInbox?:(selection:InboxDraftSelection)=>void; enabled?:boolean;
}) {
  const context=useContext(AccountRecoveryContext),denied=useRef(onDenied);
  const live=useRef({identity,context,enabled,active:true,generation:0});
  denied.current=onDenied;
  if(live.current.identity!==identity||live.current.context!==context||live.current.enabled!==enabled) {
    live.current={identity,context,enabled,active:true,generation:live.current.generation+1};
  }
  useEffect(()=>{live.current.active=true;return()=>{live.current.active=false;};},[]);
  const recovery=useMemo<InboxRecoveryAccess|null>(()=>{
    if(!context)return null;
    const generation=live.current.generation;
    const current=()=>live.current.active&&live.current.enabled&&live.current.generation===generation&&
      live.current.identity===identity&&live.current.context===context;
    const check=()=>{if(!current())throw new WorkspaceApiError(403);};
    const editor='inbox-work',address=accountEditorAddress(editor);
    return {
      async load(){
        check();const draft=await context.journal.load(address);check();
        if(!draft)return null;
        if(draft.kind!=='account-editor'||draft.editor!==editor||draft.pending!==null)throw new DraftStoreError('integrity');
        const scope=validateInbox('Scope',(draft.data as {scope?:unknown}).scope);
        const record=await validateInboxRecovery(draft.data,scope);check();return record;
      },
      async persist(value){
        check();
        // This editor never discards retained commands or history as a navigation action.
        if(!value)throw new DraftStoreError('invalid');
        const checked=await validateInboxRecovery(value,validateInbox('Scope',value.scope));check();
        if(!('mode' in identity)&&(checked.scope.box_id!==identity.boxId||checked.scope.owner_id!==identity.actorId))throw new WorkspaceApiError(403);
        await context.journal.persist(address,{kind:'account-editor',editor,data:checked,pending:null});check();
      },
      async authorize(){check();await context.authorize();check();},
      denied:cause=>{if(current())denied.current(cause);},
    };
  },[context,identity,enabled]);
  if(!enabled)return null;
  if(!recovery)return <section aria-label="Private Inbox"><h2>Inbox</h2><p role="status">Checking private account access and saved work…</p></section>;
  return <InboxPanel identity={identity} recovery={recovery} enabled presentation="focused" onOpenHandoff={onOpenHandoff} onDraftInbox={onDraftInbox} onBusyChange={onBusyChange}/>;
}
