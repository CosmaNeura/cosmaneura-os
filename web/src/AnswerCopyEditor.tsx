import {useContext,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {CopyAnswer} from './CopyAnswer';
import {canEditAnswerCopy,parseAnswerCopy,validateAnswerCopySource,validAnswerCopyText,type AnswerCopyData} from './answer-copy-contract';
import {EditorRecoveryContext,EditorRecoveryNotice,editorDraft,useEditorRecovery} from './editor-recovery';
import {DraftStoreError} from './draft-store';
import {useUnsavedWork} from './unsaved-work';
import type {EditorDraft} from './draft-journal';
import type {Workspace,WorkspaceEntry} from './workspace-api';
import './answer-copy-editor.css';

/** Only encrypted device storage is written. The saved reply and notebook remain immutable. */
export function AnswerCopyEditor({workspaceId,entry,scope,locked,isCurrent,onBusyChange,onDone}:{workspaceId:string;entry:WorkspaceEntry;scope:object;locked:boolean;isCurrent:()=>boolean;onBusyChange:(blocked:boolean)=>void;onDone:()=>void}){
  const access=useContext(EditorRecoveryContext);
  const [binding]=useState(()=>({workspaceId,entryId:entry.id,scope,access,originalContent:entry.reply!.content,contextRevision:entry.reply!.context_revision}));
  const [content,setContent]=useState(binding.originalContent),[persisted,setPersisted]=useState<string|null>(null),[writing,setWriting]=useState(false);
  const volatile=useRef(false),inFlight=useRef(false),alive=useRef(true);
  const current=useRef({access,workspaceId,entry,scope,locked,isCurrent,content});current.current={access,workspaceId,entry,scope,locked,isCurrent,content};
  const ownsStorage=()=>{const now=current.current;return alive.current&&now.access===binding.access&&now.scope===binding.scope&&now.workspaceId===binding.workspaceId&&now.entry.id===binding.entryId&&now.isCurrent();};
  const owns=()=>{const now=current.current;return ownsStorage()&&canEditAnswerCopy(now.workspaceId,now.entry)&&now.entry.reply!.content===binding.originalContent&&now.entry.reply!.context_revision===binding.contextRevision;};
  const data:AnswerCopyData={contract:'chief-answer-copy.v1',entryId:binding.entryId,originalContent:binding.originalContent,contextRevision:binding.contextRevision,content};
  const draft=editorDraft(binding.workspaceId,`answer-copy:${binding.entryId}`,data);
  const contentValid=validAnswerCopyText(content);
  // Explicit serialized autosaves below retain the latest input while a prior write settles.
  const recovery=useEditorRecovery(binding.workspaceId,`answer-copy:${binding.entryId}`,draft,true,{required:true,scopeKey:binding.access?.recoveryScope,identity:binding.scope});
  const unsafe=recovery.blocked||recovery.phase==='saving'||writing||persisted!==content||!contentValid;
  const blocked=useRef(unsafe);blocked.current=unsafe;
  useUnsavedWork(unsafe);
  useLayoutEffect(()=>{onBusyChange(unsafe);},[unsafe,onBusyChange]);
  useLayoutEffect(()=>{alive.current=true;return()=>{alive.current=false;onBusyChange(false);};},[onBusyChange]);
  useEffect(()=>{
    if(!ownsStorage()||locked||recovery.blocked||inFlight.current||persisted===content||!contentValid)return;
    const savedContent=content;inFlight.current=true;setWriting(true);
    void recovery.commit(draft).then(()=>{if(ownsStorage())setPersisted(savedContent);}).catch(()=>{/* Recovery retains both the failed local record and current input. */}).finally(()=>{
      inFlight.current=false;if(alive.current)setWriting(false);
    });
  },[content,persisted,writing,locked,recovery.blocked,recovery.phase,contentValid]);
  async function restore(saved:EditorDraft,workspace:Workspace,fresh:()=>boolean){
    if(!owns()||current.current.locked||saved.workspaceId!==binding.workspaceId||saved.editor!==`answer-copy:${binding.entryId}`||saved.pending!==null)throw new DraftStoreError('integrity');
    const recovered=parseAnswerCopy(saved.data,binding.entryId);
    validateAnswerCopySource(recovered,workspace,binding.workspaceId);
    if(recovered.originalContent!==binding.originalContent||recovered.contextRevision!==binding.contextRevision||!fresh()||!owns()||current.current.locked)throw new DraftStoreError('integrity');
    // Rechecking a failed write must not replace newer volatile edits with an older local offer.
    if(!volatile.current)setContent(recovered.content);
    setPersisted(recovered.content);
  }
  if(!owns())return <section aria-label="Retained answer copy"><EditorRecoveryNotice recovery={recovery} label="Answer copy" onRestore={restore}/><p role="status">The answer or current access changed. Your local copy is retained; it cannot be used with this answer.</p></section>;
  return <section className="answer-copy-editor" aria-label="Edit a private answer copy" aria-busy={unsafe}>
    <h3>Edit a copy</h3><p>Saved only on this device. The original answer and notes stay unchanged.</p>
    <EditorRecoveryNotice recovery={recovery} label="Answer copy" onRestore={restore}/>
    {volatile.current&&recovery.offer&&<p>Your current edits are retained while you check the earlier saved copy.</p>}
    {!contentValid&&<p role="alert">This copy is too long to save on this device. Shorten it before copying or closing; your current text is retained.</p>}
    <label>Editable answer copy<textarea value={content} maxLength={65536} disabled={locked||recovery.blocked} onChange={event=>{
      if(!owns()||current.current.locked||recovery.blocked)return;
      volatile.current=true;blocked.current=true;onBusyChange(true);setContent(event.target.value);
    }}/></label>
    <CopyAnswer content={content} scope={binding} edited disabled={locked||unsafe} isCurrent={()=>owns()&&!blocked.current&&!current.current.locked}/>
    <button type="button" disabled={locked||unsafe} onClick={()=>{if(owns()&&!blocked.current&&!current.current.locked)onDone();}}>Finish editing</button>
  </section>;
}
