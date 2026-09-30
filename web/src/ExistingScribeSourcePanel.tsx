import {useEffect,useRef,useState} from 'react';
import {BffResponseError} from '../../clients/capture/src/bff/http-client';
import {EditorRecoveryNotice,editorDraft,useEditorRecovery} from './editor-recovery';
import {DraftStoreError} from './draft-store';
import {useUnsavedWork} from './unsaved-work';
import {readExistingScribeSource,saveScribeSourcePacket,validScribeSourceRequest,type ExistingScribeSource,type ScribeSourceRequest} from './scribe-source-api';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';

export function ExistingScribeSourcePanel({workspace,identity,locked,onSaved,onBusyChange,onAccessLost}:{
  workspace:Workspace;identity:AuthenticatedWorkspaceIdentity;locked:boolean;
  onSaved:(workspace:Workspace)=>void;onBusyChange?:(busy:boolean)=>void;onAccessLost?:(error:WorkspaceApiError)=>void;
}){
  const [preview,setPreview]=useState<{owner:AuthenticatedWorkspaceIdentity;workspaceId:string;value:ExistingScribeSource}|null>(null);
  const [pendingState,setPendingState]=useState<{owner:AuthenticatedWorkspaceIdentity;workspaceId:string;request:ScribeSourceRequest}|null>(null);
  const [busy,setBusy]=useState(false),[reviewed,setReviewed]=useState(false);
  const [message,setMessage]=useState(''),[saved,setSaved]=useState(false);
  const generation=useRef(0),active=useRef<AbortController|null>(null),live=useRef({identity,workspaceId:workspace.id});
  live.current={identity,workspaceId:workspace.id};
  const value=preview?.owner===identity&&preview.workspaceId===workspace.id?preview.value:null;
  const pending=pendingState?.owner===identity&&pendingState.workspaceId===workspace.id?pendingState.request:null;
  const setPending=(request:ScribeSourceRequest|null)=>setPendingState(request?{owner:identity,workspaceId:workspace.id,request}:null);
  const recovery=useEditorRecovery(workspace.id,'scribe-source',pending?editorDraft(workspace.id,'scribe-source',pending,pending.idempotency_key):null,
    busy||pending!==null,{required:true,identity});
  useUnsavedWork(!!pending||busy);
  useEffect(()=>{generation.current++;active.current?.abort();setPreview(null);setPending(null);setBusy(false);setReviewed(false);setMessage('');setSaved(false);
    return()=>{generation.current++;active.current?.abort();};},[identity,workspace.id]);
  useEffect(()=>{onBusyChange?.(busy||!!pending||!!recovery.offer);return()=>onBusyChange?.(false);},[busy,pending,recovery.offer,onBusyChange]);
  const current=(version:number,controller:AbortController)=>version===generation.current&&!controller.signal.aborted&&live.current.identity===identity&&live.current.workspaceId===workspace.id;
  function failure(cause:unknown,saveUnconfirmed=false){
    const status=cause instanceof BffResponseError||cause instanceof WorkspaceApiError?cause.status:undefined;
    const code=cause instanceof BffResponseError?cause.code:undefined;
    if(status===401||status===403){setPreview(null);setReviewed(false);recovery.suspend();onAccessLost?.(new WorkspaceApiError(status));setMessage('Access to this encounter could not be confirmed. The saved request is retained.');}
    else if(status===404)setMessage('This Scribe recording connection is not available in this app environment yet.');
    else if(code==='scribe_source_packet_too_large')setMessage('This transcript is too long to share as one complete source packet.');
    else if(code==='scribe_source_already_saved')setMessage('This reviewed transcript is already shared with your team. Open saved sources to see it.');
    else if(code==='scribe_source_changed')setMessage('Scribe has a newer version. Check the recording again and review that version before sharing.');
    else if(code==='workspace_revision_conflict')setMessage('The encounter changed. Refresh the encounter, then check the recording again.');
    else if(code==='workspace_history_limit')setMessage('This encounter’s saved-source limit has been reached. Keep the transcript in Scribe and ask your practice administrator for help.');
    else if(cause instanceof DraftStoreError)setMessage('The request could not be saved securely on this device. Recheck recovery before continuing.');
    else setMessage(saveUnconfirmed?'The save could not be confirmed. Keep this screen open and check the saved result.':'The recording could not be loaded. Check the Scribe recording again.');
  }
  async function lookup(){
    if(locked||busy||pending||recovery.blocked)return;
    const controller=new AbortController(),version=++generation.current;active.current?.abort();active.current=controller;
    setBusy(true);setMessage('');setPreview(null);setReviewed(false);setSaved(false);
    try{const result=await readExistingScribeSource(workspace.id,identity,controller.signal);if(current(version,controller))setPreview({owner:identity,workspaceId:workspace.id,value:result});}
    catch(cause){if(current(version,controller))failure(cause);}
    finally{if(current(version,controller))setBusy(false);}
  }
  async function submit(){
    if(locked||busy||recovery.blocked||!pending&&(!reviewed||!value?.selection))return;
    const request=pending??{idempotency_key:crypto.randomUUID(),expected_revision:workspace.revision,selection:value!.selection!,reviewed:true,share_with_team:true};
    const retry=!!pending,controller=new AbortController(),version=++generation.current;active.current?.abort();active.current=controller;
    setBusy(true);setMessage('');setPending(request);
    try{
      // Only immutable request metadata is journaled. The private transcript
      // stays in this authorized preview and the server's saved source packet.
      await recovery.commit(editorDraft(workspace.id,'scribe-source',request,request.idempotency_key));
      if(!current(version,controller))return;
      let currentWorkspace:Workspace|undefined;
      if(retry){currentWorkspace=await workspaceApi.read(identity,workspace.id,controller.signal);if(!current(version,controller))return;}
      const receipt=await saveScribeSourcePacket(workspace.id,identity,request,controller.signal);
      if(!current(version,controller))return;
      await recovery.commit(null);if(!current(version,controller))return;
      setPending(null);setReviewed(false);setSaved(true);setMessage('Saved to this encounter’s sources. Chief of Staff can use this version for team handoffs.');
      onSaved(currentWorkspace&&currentWorkspace.revision>receipt.workspace.revision?currentWorkspace:receipt.workspace);
    }catch(cause){if(current(version,controller)){
      // These exact server rejections occur before saving and after recovery
      // checked for the same request. Unknown replies always keep the request.
      if(cause instanceof BffResponseError&&[409,422].includes(cause.status)&&
        ['scribe_source_changed','scribe_source_packet_too_large','scribe_source_already_saved','workspace_revision_conflict','workspace_history_limit'].includes(cause.code??'')){
        try{await recovery.commit(null);if(!current(version,controller))return;setPending(null);setReviewed(false);setPreview(null);}
        catch(error){failure(error);return;}
      }
      failure(cause,true);
    }}
    finally{if(current(version,controller))setBusy(false);}
  }
  const disabled=locked||busy||recovery.blocked;
  return <section className="team-prep" aria-label="Existing Scribe recording">
    <div className="capture-actions"><button className="team-subtle" disabled={disabled||!!pending} onClick={()=>void lookup()}>
      <span aria-hidden="true">📄 </span>{busy&&!pending?'Finding recording…':value?'Check Scribe recording':'Use a Scribe recording'}</button></div>
    <EditorRecoveryNotice recovery={recovery} label="Scribe source" onRestore={async(draft,_latest,isCurrent)=>{
      if(!validScribeSourceRequest(draft.data)||draft.pending!==draft.data.idempotency_key)throw new DraftStoreError('integrity');
      if(isCurrent()){setPending(draft.data);setPreview(null);setReviewed(false);setMessage('Restored the exact request. Check its saved result; no new version has been shared.');}
    }}/>
    {value?.status==='not_prepared'&&<p>No Scribe recording is linked to this encounter yet. Check that you opened the same visit in Scribe.</p>}
    {value?.review&&<>
      <p>{workspace.label} · Source version {value.review.source?.source_transcript_version??'not ready'}{value.review.working?` · Transcript version ${value.review.working.working_transcript_version}`:''}</p>
      {value.review.capture_continuity&&<p role="alert">Recording continuity is unconfirmed. Speech may be missing; gap lengths are unknown. Review this before sharing.</p>}
      {value.review.working&&<details open><summary>Review the complete saved transcript</summary>
        <div style={{maxHeight:'22rem',overflowY:'auto',whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>
          <p>{value.review.working.segments.map(segment=>`${segment.speaker_role}: ${segment.content??'This passage still needs review.'}`).join('\n\n')}</p>
        </div></details>}
      {!value.selection&&<p>Scribe has not finished preparing this transcript for use. Finish processing or transcript review in Scribe, then check again.</p>}
      {value.selection&&<p>This saves a copy for the team. It will not update automatically when Scribe changes.</p>}
      {value.selection&&!saved&&!pending&&<>
        <label><input type="checkbox" checked={reviewed} disabled={disabled} onChange={event=>setReviewed(event.target.checked)}/> I reviewed this transcript and any recording gaps.</label>
        <div className="capture-actions"><button className="team-primary" disabled={disabled||!reviewed} onClick={()=>void submit()}>Use this version with my team</button></div>
      </>}
    </>}
    {pending&&<div className="team-recovery"><p>Keep this request for checking. Checking it uses the same version and request.</p>
      <button disabled={disabled} onClick={()=>void submit()}>{busy?'Checking saved result…':'Check saved result'}</button></div>}
    {message&&<p role="status">{message}</p>}
  </section>;
}
