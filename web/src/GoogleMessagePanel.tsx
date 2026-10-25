import {useEffect,useRef,useState} from 'react';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type Workspace} from './workspace-api';
import {useUnsavedWork} from './unsaved-work';
import {modelCanonical} from './model-work-request';
import {useConnectionHealth,connectionReadScope,type ConnectionReadScope} from './connection-operation-health';
import {useGoogleNativeForeground} from './use-google-native-foreground';
import {googleMessageApi,googleReviewProvesNoCommit,type GoogleMessageStatus,type GoogleMessageReceipt,type GoogleMessageResolve,
  type GoogleMessageReviewResponse} from './google-message-api';
import {emptyGoogleMessageRecovery,validateGoogleMessageRecovery,type GoogleMessagePending,type GoogleMessageRecoveryAccess,
  type GoogleMessageRecoveryScope,type GoogleMessageRecoveryRecord,type GoogleMessageVisit,type GoogleMessageSaved} from './google-message-recovery';
import './google-message.css';

export type GoogleMessagePanelProps={identity:AuthenticatedWorkspaceIdentity;scope:GoogleMessageRecoveryScope;recovery:GoogleMessageRecoveryAccess|null;
  workspace:GoogleMessageVisit|null;locked?:boolean;recoveryLocked?:boolean;onSaved:(workspace:Workspace)=>void;onBusyChange?:(busy:boolean)=>void;
  currentSources?:Array<{entry_id:string;state:'current'|'unavailable'}>;
  onAuthenticationLost:(cause:unknown)=>void;onRequestFullMailAccess?:()=>void;fullMailAccessBusy?:boolean;
  onChooseVisit?:()=>void;onAskChief?:(source:GoogleMessageSaved)=>void;onRefreshVisit?:()=>Promise<void>};
const reasons={attachment:'This email contains an attachment. Review the whole message in Gmail before using it for work.',
  html_only:'This email has no supported plain text. Review it in Gmail.',unsupported_mime:'This email format needs a person to review it in Gmail.',
  oversize:'This email exceeds the supported size. Review the whole message in Gmail.',ambiguous:'This message has conflicting contents. Review it in Gmail.',
  invalid_encoding:'This email could not be read reliably. Review it in Gmail.'};
const when=(value:string)=>new Date(value).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
const authority=(cause:unknown)=>cause instanceof WorkspaceApiError&&[401,403,404,426].includes(cause.status);
const same=(a:unknown,b:unknown)=>modelCanonical(a)===modelCanonical(b);
export function GoogleMessagePanel({identity,scope,recovery,workspace,locked=false,recoveryLocked,onSaved,onBusyChange,onAuthenticationLost,
  onRequestFullMailAccess,fullMailAccessBusy=false,onChooseVisit,onAskChief,onRefreshVisit,currentSources}:GoogleMessagePanelProps){
  const [record,setRecord]=useState(()=>emptyGoogleMessageRecovery(scope)),[offer,setOffer]=useState<GoogleMessageRecoveryRecord|null>(null),
    [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState<GoogleMessageStatus|null>(null),
    [reviewed,setReviewed]=useState(false),[resolved,setResolved]=useState<GoogleMessageResolve|null>(null),[sourceStale,setSourceStale]=useState(false),[loadEpoch,setLoadEpoch]=useState(0),
    [sourceWithheld,setSourceWithheld]=useState(false),[connectionStamp,setConnectionStamp]=useState<ConnectionReadScope|null>(null);
  const health=useConnectionHealth(identity,'google'),healthScope=connectionReadScope(identity,'google');
  const latest=useRef(record);latest.current=record;
  const current=useRef({identity,recovery,scopeKey:modelCanonical(scope),alive:true,generation:0});
  const shownOwner=useRef({identity,recovery,scopeKey:modelCanonical(scope)});
  const scopeKey=modelCanonical(scope);
  if(current.current.identity!==identity||current.current.recovery!==recovery||current.current.scopeKey!==scopeKey)
    current.current={identity,recovery,scopeKey,alive:true,generation:current.current.generation+1};
  const active=useRef(false),controller=useRef<AbortController|null>(null),callbacks=useRef({onBusyChange,onAuthenticationLost,onSaved});callbacks.current={onBusyChange,onAuthenticationLost,onSaved};
  const reloadAfterResume=useRef(false),requiresNativeCheck=useRef(false);
  const nativeForeground=useGoogleNativeForeground(identity,{
    suspended:()=>{
      reloadAfterResume.current=active.current||!ready;
      if(reloadAfterResume.current)setReady(false);
      requiresNativeCheck.current=true;
      current.current.generation++;controller.current?.abort();setBusy(false);
      setReviewed(false);setStatus(null);setSourceWithheld(true);setSourceStale(true);
    },
    resumed:()=>{
      requiresNativeCheck.current=true;
      setReviewed(false);setStatus(null);setSourceWithheld(true);setSourceStale(true);
      if(reloadAfterResume.current&&!active.current){reloadAfterResume.current=false;setLoadEpoch(n=>n+1);}
    },
  });
  const owned=shownOwner.current.identity===identity&&shownOwner.current.recovery===recovery&&shownOwner.current.scopeKey===scopeKey;
  const valid=(gen:number)=>nativeForeground.foreground.current&&current.current.alive&&current.current.generation===gen&&current.current.identity===identity&&current.current.recovery===recovery&&current.current.scopeKey===scopeKey;
  useEffect(()=>{current.current.alive=true;return()=>{current.current.alive=false;current.current.generation++;controller.current?.abort();callbacks.current.onBusyChange?.(false);};},[]);
  useEffect(()=>{
    const gen=++current.current.generation;controller.current?.abort();shownOwner.current={identity,recovery,scopeKey};setReady(false);setOffer(null);setRecord(emptyGoogleMessageRecovery(scope));setStatus(null);setError('');setReviewed(false);setResolved(null);setSourceStale(false);setSourceWithheld(false);setConnectionStamp(null);
    if(recovery&&nativeForeground.foreground.current)void(async()=>{await recovery.authorize();const saved=await recovery.load();if(!valid(gen))return;
      if(saved!==null&&saved!==undefined){const checked=await validateGoogleMessageRecovery(saved,scope);if(valid(gen))setOffer(checked);}else setReady(true);
    })().catch(cause=>{if(!valid(gen))return;setError('Private saved email work is unavailable. Your earlier work is retained.');if(authority(cause))callbacks.current.onAuthenticationLost(cause);});
    return()=>{current.current.generation++;controller.current?.abort();};
  },[identity,recovery,scopeKey,loadEpoch]);
  const checkedDisconnected=health.checkedAt!==null&&!health.connected;
  const connectionChanged=checkedDisconnected||!!record.list&&healthScope!==connectionStamp||connectionStamp!==null&&(!health.accountCurrent||!health.connected);
  const projectedSourceUnavailable=workspace?.id===record.saved?.workspace_id&&!!record.saved&&
    currentSources?.some(source=>source.entry_id===record.saved!.entry_id&&source.state==='unavailable')===true;
  const showSource=owned&&!nativeForeground.suspended&&!sourceWithheld&&!connectionChanged&&!record.saved?.source_withheld&&!projectedSourceUnavailable;
  const pending=owned?record.pending:null,message=showSource?record.message?.message:null;
  const sourceAllowed=showSource&&status?.state==='connected'&&status.full_mail_read&&!sourceStale;
  const blocked=nativeForeground.suspended||!owned||!ready||busy||!!offer||!!pending||locked||fullMailAccessBusy;
  const unsaved=owned&&(!!offer||!!pending||busy||reviewed);
  useUnsavedWork(unsaved);
  useEffect(()=>{callbacks.current.onBusyChange?.(unsaved);},[unsaved,onBusyChange]);
  useEffect(()=>{setReviewed(false);},[workspace?.id,workspace?.revision,record.message?.source_sha256,locked]);
  useEffect(()=>{if(connectionChanged){setReviewed(false);setSourceStale(true);setStatus(null);setSourceWithheld(true);controller.current?.abort();}},[connectionChanged]);
  async function persist(value:GoogleMessageRecoveryRecord,gen:number){
    if(!recovery||!valid(gen))throw new WorkspaceApiError(403);const checked=await validateGoogleMessageRecovery(value,scope);
    await recovery.authorize();if(!valid(gen))throw new WorkspaceApiError(403);await recovery.persist(checked);if(!valid(gen))throw new WorkspaceApiError(403);
    latest.current=checked;setRecord(checked);return checked;
  }
  async function run(action:(gen:number,signal:AbortSignal)=>Promise<void>){
    if(!nativeForeground.foreground.current||active.current||!recovery)return;active.current=true;setBusy(true);setError('');const gen=current.current.generation,c=new AbortController();controller.current=c;
    try{await recovery.authorize();if(!valid(gen))return;await action(gen,c.signal);}catch(cause){
      if(!valid(gen))return;
      if(authority(cause)){setStatus(null);setReviewed(false);setRecord(emptyGoogleMessageRecovery(scope));setReady(false);recovery.denied?.(cause);callbacks.current.onAuthenticationLost(cause);setError('Email access is unavailable. Sign in and reopen your saved work.');}
      else {if(cause instanceof WorkspaceApiError&&cause.code?.startsWith('google_message_')&&!cause.code.includes('unconfirmed')){
        setSourceStale(true);setReviewed(false);if(cause.code.includes('grant_')||cause.code.includes('source_'))setSourceWithheld(true);}
        setError(cause instanceof WorkspaceApiError&&cause.code==='google_mail_consent_required'?'Full email access is needed. Add access before reading a message.':
        cause instanceof WorkspaceApiError&&cause.code?.includes('superseded')?'This email source changed. Load and review the current message before new work.':
        'The result could not be confirmed. Your exact saved request is retained; check its saved result before starting another request.');}
    }finally{if(valid(gen)){controller.current=null;setBusy(false);}active.current=false;
      if(current.current.alive&&current.current.identity===identity&&nativeForeground.foreground.current&&reloadAfterResume.current){reloadAfterResume.current=false;setLoadEpoch(n=>n+1);}}
  }
  async function settle(receipt:GoogleMessageReceipt,p:GoogleMessagePending,gen:number){
    if(p.kind==='review')throw new WorkspaceApiError(502);
    if(receipt.read_key!==p.request.idempotency_key||receipt.kind!==p.kind||p.kind==='message'&&(
      receipt.observation_id!==p.request.observation_id||receipt.message!.message_id!==p.request.message_id||p.request.thread_id&&receipt.message!.thread_id!==p.request.thread_id))throw new WorkspaceApiError(502);
    const next=p.kind==='list'?{...latest.current,pending:null,list:receipt,message:null,selected_message_id:null,selected_visit:null,saved:null}:
      {...latest.current,pending:null,list:p.list_anchor,message:receipt,selected_message_id:receipt.message!.message_id,selected_visit:null,saved:null};
    await persist(next,gen);setResolved(null);setReviewed(false);setSourceStale(false);
    setSourceWithheld(false);setConnectionStamp(connectionReadScope(identity,'google'));
  }
  async function execute(p:GoogleMessagePending,gen:number,signal:AbortSignal){
    if(p.kind==='list')await settle(await googleMessageApi.list(identity,p.request,signal),p,gen);
    else if(p.kind==='message')await settle(await googleMessageApi.read(identity,p.request,signal),p,gen);
    else {
      let receipt:GoogleMessageReviewResponse;
      try{receipt=await googleMessageApi.review(identity,p.workspace!.id,p.request,p.message_anchor!,signal);}catch(cause){
        if(googleReviewProvesNoCommit(cause)&&valid(gen)){await persist({...latest.current,pending:null,selected_visit:null},gen);setReviewed(false);setSourceStale(true);}throw cause;
      }
      const saved:GoogleMessageSaved={workspace_id:p.workspace!.id,entry_id:receipt.entry_id,entry_revision:receipt.entry_revision,
        source_sha256:receipt.source.source_sha256,content_sha256:receipt.source.content_sha256,request_sha256:receipt.request_sha256,source_withheld:receipt.source_withheld};
      await persist({...latest.current,pending:null,saved},gen);setReviewed(false);setResolved(null);
      if(receipt.source_withheld){setSourceWithheld(true);setSourceStale(true);setStatus(null);}
      callbacks.current.onSaved(receipt.workspace);
    }
  }
  function submit(p:GoogleMessagePending){if(blocked)return;void run(async(gen,signal)=>{await persist({...latest.current,pending:p},gen);setReviewed(false);setResolved(null);await execute(p,gen,signal);});}
  const list=()=>submit({kind:'list',request:{action:'list',idempotency_key:crypto.randomUUID()},workspace:null,list_anchor:null,message_anchor:null});
  const read=()=>{const r=record.list,item=r?.observation?.items.find(i=>i.id===record.selected_message_id);if(!r||!item||status?.full_mail_read!==true)return;
    submit({kind:'message',request:{action:'read',idempotency_key:crypto.randomUUID(),observation_id:r.read_id,observation_sha256:r.source_sha256,message_id:item.id,
      ...(item.thread_id?{thread_id:item.thread_id}:{})},workspace:null,list_anchor:r,message_anchor:null});};
  const review=()=>{if(!workspace||!record.selected_visit||!same(workspace,record.selected_visit)||!record.message||record.message.status!=='complete'||!reviewed||!sourceAllowed)return;
    submit({kind:'review',request:{expected_revision:workspace.revision,idempotency_key:crypto.randomUUID(),read_id:record.message.read_id,source_sha256:record.message.source_sha256,
      reviewed_patient:true,reviewed_exact_message:true,reviewed_untrusted_source:true},workspace:structuredClone(workspace),list_anchor:record.list,message_anchor:record.message});};
  const recover=()=>{if(!pending||busy||(recoveryLocked??locked))return;void run(async(gen,signal)=>{
    if(pending.kind==='review'){await execute(pending,gen,signal);return;}
    const result=await googleMessageApi.resolve(identity,pending.request.idempotency_key,pending.kind,signal);
    if('source_sha256'in result)await settle(result,pending,gen);else {if(!valid(gen))return;setResolved(result);setError(result.status==='not_found'?
      'No saved reservation was found. You can explicitly send this same saved request.':'This read was reserved, but its result is unconfirmed. A saved-result check will not repeat the Google read.');}
  });};
  const restore=()=>void run(async(gen)=>{if(!offer)return;const checked=await validateGoogleMessageRecovery(offer,scope);await recovery!.authorize();if(!valid(gen))return;
    const accountChecked=health.checkedAt!==null||requiresNativeCheck.current;
    latest.current=checked;setRecord(checked);setOffer(null);setReady(true);setReviewed(false);setStatus(null);setSourceStale(accountChecked);setSourceWithheld(accountChecked);setConnectionStamp(connectionReadScope(identity,'google'));setError('Saved email work restored. Check email access and compare the visit before continuing; nothing was sent.');});
  const stopWaiting=()=>{if(!busy)return;controller.current?.abort();};
  const choose=(id:string)=>{if(blocked)return;void run(async(gen)=>{await persist({...latest.current,selected_message_id:id,message:null,selected_visit:null,saved:null},gen);setReviewed(false);});};
  const selectVisit=()=>{if(blocked||!sourceAllowed||!workspace||!message||message.status!=='complete')return;void run(async(gen)=>{await persist({...latest.current,selected_visit:structuredClone(workspace)},gen);setReviewed(false);});};
  return <section className="google-message-panel" aria-label="Work with Gmail">
    <h3 tabIndex={-1}>Work with email</h3><p>Read one message, confirm its visit, then make it available for Chief’s work.</p>
    <p className="google-message-notice">Full email access allows CosmaBot to read message bodies. A message is read only when you choose it below. Attachments and unsupported contents need a person to review them in Gmail. CosmaBot cannot send email.</p>
    {nativeForeground.suspended&&<p role="status">Email contents are hidden while the app is inactive. Your private saved work is retained.</p>}
    {!recovery&&<p role="alert">Private saved-work storage is required. Email work is unavailable.</p>}
    {owned&&offer&&<div className="google-message-recovery"><p>Email work is saved on this device.{offer.pending?' Its exact request is still unresolved.':''}</p>
      <button disabled={busy||(recoveryLocked??locked)} onClick={restore}>Restore saved email work</button>
      {!offer.pending&&<button disabled={busy||locked} onClick={()=>void run(async(gen)=>{await recovery!.persist(null);if(valid(gen)){setOffer(null);setReady(true);setRecord(emptyGoogleMessageRecovery(scope));}})}>Discard local email draft</button>}</div>}
    {(!owned||!ready)&&!offer&&recovery&&<><p role="status">{error&&owned?'Email work could not be opened.':'Checking private saved-work storage…'}</p>{error&&owned&&<button disabled={busy} onClick={()=>setLoadEpoch(n=>n+1)}>Reopen saved email work</button>}</>}
    {busy&&<div role="status"><p>Waiting for the current email operation…</p><p>This request has a 50-second limit.</p><button onClick={stopWaiting}>Stop waiting</button></div>}
    {error&&owned&&<p role={pending?'status':'alert'}>{error}</p>}
    {owned&&ready&&<>
      <button disabled={blocked} onClick={()=>void run(async(gen,signal)=>{
        const value=await googleMessageApi.status(identity,signal);if(!valid(gen))return;setStatus(value);
        if(value.state!=='connected'){setSourceStale(true);setSourceWithheld(true);setReviewed(false);return;}
        if(!value.full_mail_read&&latest.current.message){setSourceStale(true);setSourceWithheld(true);setReviewed(false);return;}
        if(latest.current.list&&value.account?.email!==latest.current.list.observation!.account.email){setSourceStale(true);setSourceWithheld(true);setReviewed(false);setError('The connected account changed. Load and review its current email before new work.');return;}
        if(latest.current.message){await googleMessageApi.inspect(identity,latest.current.message,signal);if(!valid(gen))return;}
        requiresNativeCheck.current=false;
        setSourceStale(false);setSourceWithheld(false);setConnectionStamp(connectionReadScope(identity,'google'));
      })}>Check email access</button>
      {status&&!connectionChanged&&<p role="status">{status.state==='connected'?`${status.account!.email} · ${status.full_mail_read?'Full email access granted':'Full email permission needed'}`:'Connect Google again to continue.'}</p>}
      {(sourceWithheld||connectionChanged||projectedSourceUnavailable)&&<p role="alert">Saved email contents are withheld until account access and this source are checked. The private recovery record is retained.</p>}
      {record.saved?.source_withheld&&<p role="status">The exact email source save is confirmed. Its contents are unavailable; check access and review current email before asking Chief for new work.</p>}
      {status&&!status.full_mail_read&&<button disabled={blocked||!onRequestFullMailAccess} onClick={onRequestFullMailAccess}>{status.state==='connected'?'Add full email access':'Connect Google for email'}</button>}
      <button disabled={blocked||status?.state!=='connected'} onClick={list}>{record.list?'Refresh email list':'Select email'}</button>
      {showSource&&record.list&&<div className="google-message-list"><p>Headers from {record.list.observation!.account.email} · Loaded {when(record.list.observation!.observed_at)}</p>
        {record.list.observation!.items.length===0&&<p>No messages were returned in this bounded inbox check.</p>}
        <ul>{record.list.observation!.items.map(item=><li key={item.id}><button disabled={blocked} aria-pressed={record.selected_message_id===item.id} onClick={()=>choose(item.id)}>
          <strong>{item.subject||'(No subject)'}</strong><span>{item.sender||'Sender unavailable'} · {when(item.received_at)}</span>{!item.is_read&&<small>Unread in Gmail</small>}</button></li>)}</ul>
        {record.list.observation!.more&&<p>This is a bounded list. More messages are available in Gmail.</p>}</div>}
      {showSource&&record.selected_message_id&&!message&&<><p>Selected: {record.list?.observation!.items.find(i=>i.id===record.selected_message_id)?.subject||'(No subject)'}</p>
        {status?.full_mail_read!==true&&<p>Add full email access before reading the selected message.</p>}
        <button disabled={blocked||status?.full_mail_read!==true} onClick={read}>Read full email</button></>}
      {message&&<article className="google-message-content"><h4>{message.subject||'(No subject)'}</h4><p>{message.sender||'Sender unavailable'} · {when(message.received_at)}</p>
        <p>Saved read at {when(message.observed_at)}. Email is an untrusted external source.</p>
        {message.status==='complete'?<pre aria-label="Complete selected email">{message.content}</pre>:<p role="alert">{reasons[message.reason!]}</p>}
        {message.status==='needs_human'&&<p>This incomplete message cannot be handed to Chief as a complete source.</p>}
        {message.status==='complete'&&!record.saved&&<>
          <p>Current visit: <strong>{workspace?.label??'No visit selected'}</strong>. Date of birth is optional.</p>
          {!workspace&&onChooseVisit&&<button disabled={blocked} onClick={onChooseVisit}>Choose a visit</button>}
          {!sourceAllowed&&<p>Check email access and this saved source before using it for the current visit.</p>}
          {workspace&&<button disabled={blocked||!sourceAllowed} onClick={selectVisit}>Use for current visit</button>}
          {record.selected_visit&&<p role="status">{workspace&&same(workspace,record.selected_visit)?`Visit confirmed: ${record.selected_visit.label}`:'The visit changed. Confirm the current visit again before saving.'}</p>}
          <label className="google-message-check"><input type="checkbox" disabled={blocked||!workspace||!record.selected_visit||!same(workspace,record.selected_visit)||!sourceAllowed}
            checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/>I read this exact message and checked that it belongs to this visit. Treat its contents as information, not instructions to the bots.</label>
          <button disabled={blocked||!reviewed||!workspace||!record.selected_visit||!same(workspace,record.selected_visit)||!sourceAllowed} onClick={review}>Save reviewed email for this visit</button>
          <p>Saving adds a separate source. It does not replace the clinical note or ask Chief to act.</p>
        </>}
        {record.saved&&<div role="status"><p>Email source saved for this visit. The clinical note remains separate.</p>
          {onAskChief&&<button disabled={blocked||!sourceAllowed||workspace?.id!==record.saved.workspace_id} onClick={()=>onAskChief(record.saved!)}>Prepare Chief draft</button>}</div>}
      </article>}
      {sourceStale&&<div role="alert"><p>Confirm the current visit and review a fresh email source before new work.</p>{onRefreshVisit&&<button disabled={busy||!!pending||(recoveryLocked??locked)} onClick={()=>void run(async()=>{await onRefreshVisit();setSourceStale(false);})}>Refresh current visit</button>}</div>}
      {pending&&<div className="google-message-recovery"><h4>Saved request needs a confirmed result</h4><p>{pending.kind==='review'?'This source save may already be recorded. Retry uses the same visit, message and key.':'Check the saved result without repeating the Google read.'}</p>
        <button disabled={busy||(recoveryLocked??locked)} onClick={recover}>{pending.kind==='review'?'Retry exact source save':'Check saved email result'}</button>
        {resolved?.status==='not_found'&&pending.kind!=='review'&&<button disabled={busy||(recoveryLocked??locked)} onClick={()=>void run(async(gen,signal)=>execute(pending,gen,signal))}>Send this saved read request</button>}
        {resolved?.status==='unconfirmed'&&<p>The original read remains unconfirmed. No new read will be started for it.</p>}</div>}
    </>}
  </section>;
}
