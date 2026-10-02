import {useEffect, useRef, useState} from 'react';
import {WorkspaceApiError, type DraftHandoff, type Workspace, type WorkspaceIdentity} from './workspace-api';
import {saveHandoffReview, prepareHandoffRevision, verifiedHandoffResult, validHandoffReviewReceipt, HandoffReviewRefusal, refusalProvesNoCommit, refusalNeedsFreshAssignment,
  type HandoffReviewInput, type HandoffRevisionInput, type HandoffReviewReceipt,
  type ReviewableHandoff, type VerifiedHandoffResult} from './handoff-review-api';
import {teamText} from './team-setup-request';
import {useUnsavedWork} from './unsaved-work';
import {editorDraft,EditorRecoveryNotice,useEditorRecovery} from './editor-recovery';
import {handoffRecoveryAnchor,handoffRecoveryMatches,handoffRevisionHash,validateHandoffReviewRecovery,
  type HandoffReviewRecovery,type HandoffRecoveryPending} from './handoff-review-recovery';
import {handoffReviewHash} from './handoff-review-api';

export type HandoffReviewPanelProps = {workspace:Workspace;handoff:DraftHandoff;identity:WorkspaceIdentity;locked:boolean;
  onSaved:(workspace:Workspace)=>void;onClose?:()=>void;onPendingChange?:(pending:boolean)=>void;onRevisionPrepared?:(handoffId:string)=>void;
  onAccessLost?:(error:WorkspaceApiError)=>void;onRefresh?:()=>Promise<void>;recoveryLocked?:boolean;onFreshAssignment?:(feedback:string)=>void};
type PendingReview={kind:'review';workspaceId:string;handoffId:string;recipientName:string;identity:WorkspaceIdentity;body:HandoffReviewInput;result:VerifiedHandoffResult};
type PendingRevision={kind:'revision';workspaceId:string;handoffId:string;recipientName:string;identity:WorkspaceIdentity;body:HandoffRevisionInput;result:VerifiedHandoffResult;feedback:string};
type Pending=PendingReview|PendingRevision;

export function HandoffReviewPanel({workspace,handoff,identity,locked,recoveryLocked,onSaved,onClose,onPendingChange,onRevisionPrepared,onAccessLost,onRefresh,onFreshAssignment}:HandoffReviewPanelProps) {
  const [checked,setChecked]=useState<{workspace:Workspace;handoff:DraftHandoff;result:VerifiedHandoffResult|null}|null>(null),[checking,setChecking]=useState(true);
  const [feedback,setFeedback]=useState(''),[askingChanges,setAskingChanges]=useState(false),[pending,setPending]=useState<Pending|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState<HandoffReviewReceipt|null>(null);
  const [accessLost,setAccessLost]=useState(false),[refusal,setRefusal]=useState<{code:string;workspace:Workspace;freshAssignment:boolean}|null>(null);
  const [withheldReceipt,setWithheldReceipt]=useState<{workspaceId:string;handoffId:string;review:HandoffReviewReceipt}|null>(null);
  const uncertain=useRef(false);
  const [recoveryRecord,setRecoveryRecord]=useState<HandoffReviewRecovery|null>(null),[replayCompared,setReplayCompared]=useState(true);
  const refreshed=useRef<Workspace|null>(null);
  const mounted=useRef(true),inFlight=useRef(false),controller=useRef<AbortController|null>(null);
  const originalIdentity=useRef(identity),identityChanged=originalIdentity.current!==identity;
  const anchor=handoffRecoveryAnchor(workspace,handoff);
  const localRecord:HandoffReviewRecovery|null=recoveryRecord?{...recoveryRecord,feedback,asking_changes:askingChanges}:anchor&&feedback?
    {...anchor,version:1,feedback,asking_changes:askingChanges,pending:null}:null;
  const editor=`handoff-review:${handoff.id}` as const;
  const recovery=useEditorRecovery(workspace.id,editor,localRecord?editorDraft(workspace.id,editor,localRecord,localRecord.pending?.body.idempotency_key??null):null,
    busy||pending!==null,{identity,required:'mode'in identity});
  const originalJournal=useRef(recovery.access?.journal);if(!originalJournal.current&&recovery.access)originalJournal.current=recovery.access.journal;
  const journalChanged=!!originalJournal.current&&!!recovery.access&&originalJournal.current!==recovery.access.journal;
  const live=useRef({identity,workspaceId:workspace.id,handoffId:handoff.id,journal:recovery.access?.journal});
  live.current={identity,workspaceId:workspace.id,handoffId:handoff.id,journal:recovery.access?.journal};
  const recoveryUnresolved=recovery.blocked;
  useUnsavedWork(pending!==null||feedback.length>0||busy);
  useEffect(()=>{onPendingChange?.(pending!==null||feedback.length>0||busy||!!recovery.offer||recovery.phase==='failed');},[onPendingChange,pending,feedback,busy,recovery.offer,recovery.phase]);
  useEffect(()=>()=>onPendingChange?.(false),[onPendingChange]);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;controller.current?.abort();};},[]);
  useEffect(()=>{
    let active=true;setChecked(null);setChecking(true);
    void verifiedHandoffResult(workspace,handoff as ReviewableHandoff).then(result=>{if(active){setChecked({workspace,handoff,result});setChecking(false);}})
      .catch(()=>{if(active){setChecked({workspace,handoff,result:null});setChecking(false);}});
    return()=>{active=false;};
  },[workspace,handoff]);
  useEffect(()=>{if(!pending&&!refusal&&(!recoveryRecord||recovery.access===undefined)){setFeedback('');setAskingChanges(false);if(recovery.access===undefined)setRecoveryRecord(null);}},[workspace.id,handoff.id,handoff.attempt_id,handoff.result_entry_id]);
  const proof=checked?.workspace===workspace&&checked.handoff===handoff?checked.result:null;
  useEffect(()=>{if(proof&&refusal&&!refusal.freshAssignment&&refreshed.current&&workspace!==refreshed.current){setRefusal(null);refreshed.current=null;uncertain.current=false;}},[proof,refusal,workspace]);
  const retained=(handoff as ReviewableHandoff).review;
  const confirmedWithheld=withheldReceipt?.workspaceId===workspace.id&&withheldReceipt.handoffId===handoff.id?withheldReceipt:null;
  const sourceWithheld=identityChanged||journalChanged||recovery.access===null||!!confirmedWithheld||workspace.entries.some(entry=>(entry.id===handoff.result_entry_id||entry.id===pending?.result.entryId||entry.id===recoveryRecord?.result.result_entry_id)&&
    (entry.google_source_state==='unavailable'||entry.calendar_source_state==='unavailable'));
  const restoredChanged=!!recoveryRecord&&!handoffRecoveryMatches(recoveryRecord,workspace,handoff);
  const stale=handoff.review_status==='stale'||refusal?.freshAssignment===true||sourceWithheld||restoredChanged;
  const receipt=proof&&!stale?[saved,retained].find(value=>validHandoffReviewReceipt(value)&&value.attempt_id===proof.attemptId&&
    value.result_entry_id===proof.entryId&&value.result_sha256===proof.sha256):undefined;
  const result=sourceWithheld?null:pending?.result.content?pending.result:restoredChanged?null:proof;
  const revision=receipt?.decision==='changes_requested'?(workspace.handoffs?.find(value=>value.id===receipt.revision_handoff_id)||
    workspace.handoffs?.find(value=>(value as ReviewableHandoff).revision_request?.parent_handoff_id===handoff.id&&
      (value as ReviewableHandoff).revision_request?.review_id===receipt.id)):undefined;
  const revisionPrepared=!!receipt?.revision_handoff_id||!!revision;
  const validFeedback=teamText(feedback,2000)&&!feedback.includes('\0');
  const disabled=locked||busy||checking||!proof||pending!==null||!!receipt||accessLost||stale||refusal!==null||recoveryUnresolved||restoredChanged;
  function editFeedback(value:string){
    if(!recoveryRecord&&anchor)setRecoveryRecord({...anchor,version:1,feedback:value,asking_changes:true,pending:null});
    setFeedback(value);
  }
  async function recordRequest(request:Pending):Promise<HandoffReviewRecovery>{
    const original=handoffRecoveryAnchor(workspace,handoff);
    if(!original)throw new Error('The saved result could not be retained.');
    const command:HandoffRecoveryPending=request.kind==='review'?{kind:'review',body:request.body,request_sha256:await handoffReviewHash(request.workspaceId,request.handoffId,request.body)}:
      {kind:'revision',body:request.body,request_sha256:await handoffRevisionHash(request.workspaceId,request.handoffId,request.body),review:receipt!};
    const record={...original,version:1 as const,feedback:request.kind==='review'?request.body.feedback:request.feedback,asking_changes:request.kind==='review'&&request.body.decision==='changes_requested',pending:command};
    return validateHandoffReviewRecovery(record,request.workspaceId,request.handoffId);
  }
  async function persist(request:Pending) {
    if((recoveryLocked??locked)||inFlight.current||recovery.blocked||!replayCompared||identityChanged||journalChanged||request.identity!==identity)return;
    inFlight.current=true;setBusy(true);setError('');const current=new AbortController();controller.current=current;
    let dispatched=false,commandRecord:HandoffReviewRecovery|null=null;
    const same=()=>mounted.current&&live.current.identity===request.identity&&live.current.workspaceId===request.workspaceId&&live.current.handoffId===request.handoffId&&
      (!originalJournal.current||live.current.journal===originalJournal.current);
    try {
      const record=recoveryRecord?.pending?.body.idempotency_key===request.body.idempotency_key?recoveryRecord:await recordRequest(request);
      commandRecord=record;
      setRecoveryRecord(record);
      await recovery.commit(editorDraft(request.workspaceId,editor,record,request.body.idempotency_key));
      if(!same()||current.signal.aborted)return;
      setRecoveryRecord(record);dispatched=true;
      const response=request.kind==='review'?await saveHandoffReview(request.identity,request.workspaceId,request.handoffId,request.body,current.signal):
        await prepareHandoffRevision(request.identity,request.workspaceId,request.handoffId,request.body,current.signal);
      if(!same())return;
      const recorded=(response.workspace.handoffs?.find(value=>value.id===request.handoffId) as ReviewableHandoff).review!;
      await recovery.commit(null);if(!same())return;
      uncertain.current=false;setRecoveryRecord(null);setSaved(recorded);setPending(null);setFeedback('');setAskingChanges(false);setRefusal(null);
      setWithheldReceipt('feedback_withheld'in response&&response.feedback_withheld?{workspaceId:request.workspaceId,handoffId:request.handoffId,review:recorded}:null);
      onSaved(response.workspace);
      if('revision_handoff_id' in response&&typeof response.revision_handoff_id==='string')onRevisionPrepared?.(response.revision_handoff_id);
    }catch(cause){if(same()){
      if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)){
        setAccessLost(true);setError(cause.message);recovery.denied(cause);onAccessLost?.(cause);
      }else if(cause instanceof HandoffReviewRefusal&&(!uncertain.current||refusalProvesNoCommit(cause))){
        if(!commandRecord){setError('The request recovery record could not be verified. Existing work is retained.');return;}
        const retainedRecord={...commandRecord,pending:null,feedback:request.kind==='review'?request.body.feedback:request.feedback};
        try{await recovery.commit(retainedRecord.feedback?editorDraft(workspace.id,editor,retainedRecord):null);}catch{setError('Local recovery could not record the refusal. The original request is retained.');return;}
        setRecoveryRecord(retainedRecord.feedback?retainedRecord:null);
        setPending(null);setFeedback(request.kind==='review'?request.body.feedback:request.feedback);setAskingChanges(request.kind==='review'&&request.body.decision==='changes_requested');
        setRefusal({code:cause.code!,workspace,freshAssignment:refusalNeedsFreshAssignment(cause.code)});setError('This request was not saved. Your change request is retained.');
      }else{if(dispatched){uncertain.current=true;if(recovery.access)setReplayCompared(false);}setError(!dispatched?'The request was not submitted because its private recovery copy could not be saved. Recheck local recovery before continuing.':
        cause instanceof WorkspaceApiError?cause.message:'The save could not be confirmed. Retry the same review save.');}
    }}
    finally{inFlight.current=false;if(mounted.current)setBusy(false);if(controller.current===current)controller.current=null;}
  }
  function decide(decision:HandoffReviewInput['decision']) {
    if(disabled||!proof||inFlight.current||decision==='changes_requested'&&(!validFeedback||!feedback.trim()))return;
    const request:PendingReview={kind:'review',workspaceId:workspace.id,handoffId:handoff.id,recipientName:handoff.recipient_name,identity,result:proof,body:{expected_revision:workspace.revision,
      idempotency_key:crypto.randomUUID(),attempt_id:proof.attemptId,result_entry_id:proof.entryId,result_sha256:proof.sha256,
      decision,feedback:decision==='changes_requested'?feedback:''}};
    setPending(request);void persist(request);
  }
  function prepareRevision() {
    if(locked||busy||pending||!proof||!receipt||receipt.decision!=='changes_requested'||revisionPrepared||inFlight.current||accessLost||stale||refusal||recoveryUnresolved||restoredChanged)return;
    const request:PendingRevision={kind:'revision',workspaceId:workspace.id,handoffId:handoff.id,recipientName:handoff.recipient_name,identity,
      result:proof,feedback:receipt.feedback,body:{expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),review_id:receipt.id}};
    setPending(request);void persist(request);
  }
  async function refreshForReview(){
    if(!onRefresh||busy||pending||accessLost||(recoveryLocked??locked))return;
    setBusy(true);setError('');
    try{refreshed.current=workspace;await onRefresh();}
    catch(cause){refreshed.current=null;if(mounted.current){if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)){setAccessLost(true);onAccessLost?.(cause);}
      setError(cause instanceof WorkspaceApiError?cause.message:'The latest draft could not be loaded. Your feedback is retained.');}}
    finally{if(mounted.current)setBusy(false);}
  }
  async function comparePending(){
    if(!pending||busy||!recovery.access||(recoveryLocked??locked))return;
    setBusy(true);setError('');
    try{const latest=await recovery.access.authorize();if(!mounted.current)return;
      if(latest.id!==workspace.id||latest.appointment_id!==workspace.appointment_id)throw new WorkspaceApiError(403);
      onSaved(latest);setReplayCompared(true);setError('Saved history checked. Retry the same save to confirm its exact receipt. No new decision was created.');
    }catch(cause){if(mounted.current){setReplayCompared(false);recovery.denied(cause);
      if(cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status)){setAccessLost(true);onAccessLost?.(cause);}
      setError('Current access and saved history could not be confirmed. The private request is retained.');}}
    finally{if(mounted.current)setBusy(false);}
  }
  async function discardRetainedFeedback(){
    if(pending||busy||!restoredChanged||sourceWithheld||(recoveryLocked??locked)||recovery.blocked)return;
    setBusy(true);setError('');
    try{await recovery.commit(null);if(!mounted.current)return;setRecoveryRecord(null);setFeedback('');setAskingChanges(false);}
    catch{if(mounted.current)setError('The retained feedback could not be cleared from private storage. It remains available for recovery.');}
    finally{if(mounted.current)setBusy(false);}
  }
  if(accessLost||identityChanged||journalChanged)return <section className="handoff-review" aria-label="Review completed draft"><p role="alert">Workspace access is unavailable. The draft is withheld from this view.</p></section>;
  return <section className="handoff-review" aria-label="Review completed draft" aria-busy={checking||busy||recovery.phase==='checking'}>
    <h3 tabIndex={-1}>{pending?.recipientName??handoff.recipient_name} draft</h3>
    <EditorRecoveryNotice recovery={recovery} label="Handoff review" onRestore={async(draft,latest,isCurrent)=>{
      const restored=await validateHandoffReviewRecovery(draft.data,workspace.id,handoff.id);
      if(latest.id!==restored.workspace_id||latest.appointment_id!==restored.appointment_id)throw new WorkspaceApiError(403);
      const selected=latest.handoffs?.find(h=>h.id===restored.handoff_id);if(!selected)throw new WorkspaceApiError(404);
      const currentResult=await verifiedHandoffResult(latest,selected);
      if(!isCurrent())return;
      onSaved(latest);setRecoveryRecord(restored);setFeedback(restored.feedback);setAskingChanges(restored.asking_changes);
      if(restored.pending){const base={workspaceId:restored.workspace_id,handoffId:restored.handoff_id,recipientName:restored.recipient.name,identity,
        result:currentResult&&handoffRecoveryMatches(restored,latest,selected)?currentResult:{attemptId:restored.result.attempt_id,entryId:restored.result.result_entry_id,sha256:restored.result.result_sha256,content:''}};
        setPending(restored.pending.kind==='review'?{...base,kind:'review',body:restored.pending.body}:{...base,kind:'revision',body:restored.pending.body,feedback:restored.pending.review.feedback});
        uncertain.current=true;setReplayCompared(false);
      }
    }}/>
    <p>Read the saved draft, then accept it for next work or request changes.</p>
    {restoredChanged&&!sourceWithheld&&<p role="alert">This retained change request belongs to an earlier draft. Keep its text for fresh work; it cannot approve the current result.</p>}
    {restoredChanged&&!sourceWithheld&&!pending&&<button type="button" disabled={busy||(recoveryLocked??locked)||recoveryUnresolved} onClick={()=>void discardRetainedFeedback()}>Discard retained feedback</button>}
    {checking&&!pending&&<p role="status">Checking the saved draft…</p>}
    {handoff.status!=='completed'&&!pending&&<p role="status">{handoff.status==='queued'?'Draft queued':handoff.status==='running'?'Preparing draft…':'Draft needs attention. Check the assignment before trying again.'}</p>}
    {handoff.status==='completed'&&!checking&&!proof&&!pending&&<p role="alert">The complete saved draft could not be verified. Refresh the encounter before reviewing it.</p>}
    {stale&&!pending&&<p role="alert">{sourceWithheld?'Source access is unavailable. The draft and its feedback are withheld; check source access before next work.':'The saved sources or assignment changed after this draft. Ask Chief for a fresh assignment before next work.'}</p>}
    {confirmedWithheld&&!pending&&<p role="status">The exact saved review is confirmed. Its draft and feedback are unavailable; check source access before next work.</p>}
    {stale&&!sourceWithheld&&!pending&&onFreshAssignment&&<button type="button" disabled={busy||(recoveryLocked??locked)} onClick={()=>{
      if(busy||pending||(recoveryLocked??locked))return;
      onFreshAssignment(feedback||(validHandoffReviewReceipt(retained)&&retained.decision==='changes_requested'?retained.feedback:''));
    }}>Ask Chief for fresh work</button>}
    {result&&<div aria-label="Complete saved draft" style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{result.content}</div>}
    {receipt&&!pending&&<div role="status"><strong>{receipt.decision==='accepted'?'Draft accepted':'Changes requested'}</strong>
      {receipt.decision==='changes_requested'&&<><p>{receipt.feedback}</p>
        <p>{revisionPrepared?'Revised assignment saved.':'The change request is saved. Prepare a revised draft to get an updated result.'}</p>
        {!revisionPrepared&&<button type="button" disabled={locked||busy||checking||pending!==null||refusal!==null||recoveryUnresolved||restoredChanged} onClick={prepareRevision}>Prepare revised draft</button>}
        {revision&&<><p role="status">{revision.status==='completed'?'Revised draft ready':revision.status==='queued'?'Revised draft queued':revision.status==='running'?'Preparing revised draft':'Revised draft needs attention'}</p>
          {onRevisionPrepared&&<button type="button" disabled={locked||busy||pending!==null} onClick={()=>onRevisionPrepared(revision.id)}>{revision.status==='completed'?'Review revised draft':'Open revised assignment'}</button>}</>}
      </>}
      {receipt.decision==='accepted'&&<p>This draft is ready for next work. Clinical sign-off and any delivery remain separate.</p>}</div>}
    {receipt&&feedback&&!pending&&!sourceWithheld&&<div><label>Retained unsaved change request<textarea aria-label="Retained change request" value={feedback}
      disabled={busy||recoveryUnresolved} onChange={event=>editFeedback(event.target.value)}/></label><p>This text was not saved as a review. Copy it or clear it before leaving.</p></div>}
    {!receipt&&<div>
      <button type="button" disabled={disabled} onClick={()=>decide('accepted')}>Accept draft for next work</button>
      <button type="button" disabled={disabled} onClick={()=>setAskingChanges(true)}>Request changes</button>
      {askingChanges&&!sourceWithheld&&<div><label>What should change?<textarea aria-label="Change request" value={pending?.kind==='review'?pending.body.feedback:feedback}
        disabled={locked||busy||pending!==null||recoveryUnresolved} onChange={event=>editFeedback(event.target.value)}/></label>
        {!validFeedback&&<p role="alert">Use valid text with no more than 2,000 characters.</p>}
        <button type="button" disabled={disabled||!feedback.trim()||!validFeedback} onClick={()=>decide('changes_requested')}>Save change request</button></div>}
    </div>}
    {pending&&<><p role="status">{busy?(pending.kind==='review'?'Saving review…':'Saving revised assignment…'):
      pending.kind==='review'?'Review save unconfirmed. Keep this exact decision until the same save is confirmed.':'Revised assignment save unconfirmed. Retry this exact request before starting another.'}</p>
      {pending.kind==='review'&&<><p>{pending.body.decision==='accepted'?'Pending decision: accept draft for next work':'Pending decision: request changes'}</p>
        {!sourceWithheld&&pending.body.feedback&&<p>{pending.body.feedback}</p>}</>}
      {pending.kind==='revision'&&!sourceWithheld&&<p>{pending.feedback}</p>}
      {sourceWithheld&&<p>The draft and change request are withheld. The exact saved request is retained for confirmation.</p>}</>}
    {error&&<p role="alert">{error}</p>}
    {refusal&&!pending&&!refusal.freshAssignment&&<p role="status">Load the current saved draft before reviewing another decision. Your feedback will stay here.</p>}
    {refusal&&!pending&&onRefresh&&<button type="button" disabled={(recoveryLocked??locked)||busy} onClick={()=>void refreshForReview()}>Refresh draft to review</button>}
    {pending&&!busy&&!replayCompared&&<button type="button" disabled={(recoveryLocked??locked)||recovery.blocked} onClick={()=>void comparePending()}>Check saved review status</button>}
    {pending&&!busy&&<button type="button" disabled={(recoveryLocked??locked)||recoveryUnresolved||!replayCompared} onClick={()=>void persist(pending)}>{pending.kind==='review'?'Retry same review save':'Retry same revised assignment'}</button>}
    {onClose&&<button type="button" disabled={busy||pending!==null||feedback.length>0||recoveryUnresolved} onClick={onClose}>Close draft review</button>}
  </section>;
}
