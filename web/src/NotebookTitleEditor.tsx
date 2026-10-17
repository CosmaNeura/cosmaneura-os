import {useEffect,useRef,useState} from 'react';
import type {AccountRecoveryAccess} from './account-recovery';
import {editorAddress} from './draft-journal';
import {validateTitleRecovery,type NotebookRename,type NotebookTitleReceipt} from './notebook-metadata-contract';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

/** A failed rename keeps one encrypted request and checks it before replacement. */
export function NotebookTitleEditor({identity,recovery,workspaceId,title,titleRevision,onSaved,onClose,onAccessLost}: {
  identity:AuthenticatedWorkspaceIdentity;recovery:AccountRecoveryAccess|null;workspaceId:string;title:string;titleRevision:number;
  onSaved:(receipt:NotebookTitleReceipt)=>void;onClose:()=>void;onAccessLost:(cause:unknown)=>void;
}){
  const [value,setValue]=useState(title),[pending,setPending]=useState<NotebookRename|null>(null),[ready,setReady]=useState(false),[busy,setBusy]=useState(false),[retry,setRetry]=useState(false),[stale,setStale]=useState<{title:string;revision:number}|null>(null),[baseRevision,setBaseRevision]=useState(titleRevision),[error,setError]=useState('');
  const live=useRef({identity,recovery,workspaceId,epoch:0,alive:true}),flight=useRef(false);
  if(live.current.identity!==identity||live.current.recovery!==recovery||live.current.workspaceId!==workspaceId)live.current={identity,recovery,workspaceId,epoch:live.current.epoch+1,alive:true};
  const current=(epoch:number)=>live.current.alive&&live.current.epoch===epoch&&live.current.identity===identity;
  const address=editorAddress(workspaceId,'notebook-title');
  useEffect(()=>{live.current.alive=true;const epoch=++live.current.epoch;setReady(false);setPending(null);setValue(title);setError('');setRetry(false);setStale(null);setBaseRevision(titleRevision);
    if(recovery)void(async()=>{await recovery.authorize();const saved=await recovery.journal.load(address);if(!current(epoch))return;
      if(saved){if(saved.kind!=='editor'||saved.editor!=='notebook-title')throw new Error();const data=validateTitleRecovery(saved.data,workspaceId);setPending(data.pending);setValue(data.pending.title);}setReady(true);
    })().catch(cause=>{if(current(epoch)){setError('Rename recovery could not be checked. The retained request is kept.');deny(cause);}});
    return()=>{live.current.alive=false;live.current.epoch++;};
  },[identity,recovery,workspaceId]);
  function deny(cause:unknown){if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status))onAccessLost(cause);}
  async function persist(body:NotebookRename|null){if(!recovery)throw new Error();await recovery.journal.persist(address,body?{kind:'editor',workspaceId,editor:'notebook-title',data:{contract:'notebook-title-recovery.v1',workspace_id:workspaceId,pending:body},pending:body.idempotency_key}:null);}
  async function save(){if(!recovery||!ready||flight.current||busy||pending&&!retry||!value.trim())return;
    const epoch=live.current.epoch,body=pending??{title:value.trim(),expected_title_revision:baseRevision,idempotency_key:crypto.randomUUID()};flight.current=true;setBusy(true);setError('');setRetry(false);
    try{await recovery.authorize();if(!current(epoch))return;await persist(body);if(!current(epoch))return;setPending(body);
      const receipt=await workspaceApi.renameNotebook(identity,workspaceId,body);if(!current(epoch))return;await recovery.authorize();if(!current(epoch))return;
      await persist(null);if(current(epoch)){setPending(null);onSaved(receipt);}}
    catch(cause){if(current(epoch)){setError(cause instanceof WorkspaceApiError&&cause.code==='notebook_title_conflict'?'The title changed elsewhere. This request was rejected. Check its saved result, then refresh the notebook before a new rename.':'Rename is unconfirmed. Check the saved result before submitting another title.');deny(cause);}}
    finally{flight.current=false;if(current(epoch))setBusy(false);}
  }
  async function resolve(){if(!recovery||!ready||busy||flight.current||!pending)return;const epoch=live.current.epoch;flight.current=true;setBusy(true);setError('');
    try{await recovery.authorize();if(!current(epoch))return;const result=await workspaceApi.resolveNotebookTitle(identity,workspaceId,pending);if(!current(epoch))return;
      if(result.outcome==='saved'&&result.receipt){await recovery.authorize();if(!current(epoch))return;await persist(null);if(current(epoch)){setPending(null);onSaved(result.receipt);}}
      else{
        const latest=await workspaceApi.read(identity,workspaceId);if(!current(epoch))return;
        const metadata=latest.notebook;if(metadata&&(typeof metadata.title!=='string'||metadata.title.length>160||!Number.isSafeInteger(metadata.title_revision)||metadata.title_revision<0))throw new Error();
        if(metadata&&metadata.title_revision>pending.expected_title_revision){setStale({title:metadata.title,revision:metadata.title_revision});setRetry(false);setError(`The current title is “${metadata.title}”. Your earlier rename was not saved. Use this version before editing again.`);}
        else{setRetry(true);setError('No saved rename was found. Retry the same title and request, or keep working and check later.');}
      }}
    catch(cause){if(current(epoch)){setError('The rename result could not be checked. No rename was repeated.');deny(cause);}}
    finally{flight.current=false;if(current(epoch))setBusy(false);}
  }
  async function useCurrentTitle(){if(!recovery||!stale||!pending||busy)return;const epoch=live.current.epoch;setBusy(true);
    try{await recovery.authorize();if(!current(epoch))return;await persist(null);if(current(epoch)){setBaseRevision(stale.revision);setPending(null);setStale(null);setRetry(false);setError('Your unsent title is ready to edit against the current version.');}}
    catch(cause){if(current(epoch)){setError('The retained rename could not be updated on this device.');deny(cause);}}
    finally{if(current(epoch))setBusy(false);}
  }
  return <form className="notebook-title-editor" aria-label="Rename notebook" onSubmit={event=>{event.preventDefault();void save();}}>
    <label>Notebook title<input autoFocus maxLength={160} value={value} disabled={!ready||!!pending} onChange={event=>setValue(event.target.value)}/></label>
    {pending?<><p>The original rename request is retained on this device.</p><button type="button" disabled={!ready||busy} onClick={()=>void resolve()}>Check saved rename</button>{retry&&<button type="submit" disabled={busy}>Retry same rename</button>}{stale&&<button type="button" disabled={busy} onClick={()=>void useCurrentTitle()}>Use current title version</button>}</>:<button type="submit" disabled={!ready||busy||!value.trim()||value.trim()===title}>Save title</button>}
    <button type="button" onClick={onClose}>Close rename</button>{error&&<p role="alert">{error}</p>}
  </form>;
}
