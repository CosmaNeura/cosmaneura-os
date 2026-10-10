import {useEffect,useRef,useState} from 'react';
import type {AccountRecoveryAccess} from './account-recovery';
import {loadPrivateDraftRecovery,persistPrivateDraftRecovery,type PrivateDraftCreate,type PrivateDraftRecovery} from './private-draft-recovery';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
import type {PrivateNotebookResult} from './PrivateRecordingPanel';
import type {PrivateRecordingSnapshot} from './private-recording-runtime';
import './practice-home.css';

function recordingDetails(recording:PrivateRecordingSnapshot):string {
  const status=recording.phase==='sealed'?(recording.recordedChunks?'Saved on this device; not yet synced':'Stopped · no audio captured'):recording.phase==='paused'?'Paused · not yet synced':recording.phase==='interrupted'?'Interrupted · check retained audio':'Check recording status';
  const seconds=Math.floor(recording.elapsedSeconds),duration=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  return `${duration} · ${status} · Private`;
}

export type StartPrivateRecording={title:string;prepareNotebook:()=>Promise<PrivateNotebookResult>};
export function PracticeHome({identity,recovery,team,teamUnchanged=true,locked,onUseTeam,onSettings,onVisits,onConnections,onPracticeWork,onOpened,onAccessLost,onBusyChange,onRecord,recordings,onReopenRecording,openRecordingRequest=0}:{
  identity:AuthenticatedWorkspaceIdentity;recovery:AccountRecoveryAccess|null;team:ProviderTeam|null;teamUnchanged?:boolean;locked:boolean;
  onUseTeam:()=>void;onSettings:()=>void;onVisits:()=>void;onConnections:()=>void;onPracticeWork:()=>void;
  onOpened:(value:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam})=>Promise<void>;
  onAccessLost:(cause:unknown)=>void;onBusyChange:(busy:boolean)=>void;
  onRecord?:(value:StartPrivateRecording)=>void;recordings?:PrivateRecordingSnapshot[];onReopenRecording?:(recordingId:string)=>void;
  openRecordingRequest?:number;
}){
  const [title,setTitle]=useState('Private note'),[pending,setPending]=useState<PrivateDraftCreate|null>(null),[ready,setReady]=useState(false);
  const [busy,setBusy]=useState(false),[retryAllowed,setRetryAllowed]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [drafts,setDrafts]=useState<Awaited<ReturnType<typeof workspaceApi.privateDrafts>>|null>(null);
  const live=useRef({identity,recovery,epoch:0,alive:true});
  if(live.current.identity!==identity||live.current.recovery!==recovery)live.current={identity,recovery,epoch:live.current.epoch+1,alive:true};
  const current=(epoch:number)=>live.current.alive&&live.current.epoch===epoch&&live.current.identity===identity&&live.current.recovery===recovery;
  const callback=useRef(onBusyChange);callback.current=onBusyChange;
  const creating=useRef(false);
  const initialRecovery=useRef<{epoch:number;promise:ReturnType<typeof loadPrivateDraftRecovery>}|null>(null);
  const recordingRequest=useRef({identity,seen:0});
  useEffect(()=>{callback.current(busy);},[busy]);
  useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;};},[]);
  useEffect(()=>{
    const epoch=++live.current.epoch;setReady(false);setPending(null);setDrafts(null);setBusy(false);setRetryAllowed(false);setError('');setMessage('');setTitle('Private note');
    if(!recovery)return;
    const promise=loadPrivateDraftRecovery(recovery);initialRecovery.current={epoch,promise};
    void(async()=>{const saved=await promise;if(!current(epoch))return;
      if(saved){setTitle(saved.title);setPending(saved.pending);}setReady(true);
      const list=await workspaceApi.privateDrafts(identity);if(current(epoch))setDrafts(list);
    })().catch(cause=>{if(current(epoch)){setError('Private notes could not be checked. Refresh Home before starting a new draft.');deny(cause);}});
  },[identity,recovery]);
  function deny(cause:unknown){if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status)){setDrafts(null);setReady(false);onAccessLost(cause);}}
  async function refresh(){
    if(!recovery||busy||creating.current||locked)return;const epoch=live.current.epoch;setBusy(true);setError('');
    try{const promise=loadPrivateDraftRecovery(recovery);initialRecovery.current={epoch,promise};const saved=await promise;if(!current(epoch))return;
      setPending(saved?.pending??null);if(saved)setTitle(saved.title);setReady(true);
      const list=await workspaceApi.privateDrafts(identity);if(current(epoch))setDrafts(list);
    }catch(cause){if(current(epoch)){setError('Private notes could not be checked. No new draft was started.');deny(cause);}}
    finally{if(current(epoch))setBusy(false);}
  }
  async function create(retry=false){
    if(!recovery||!ready||busy||creating.current||locked||pending&&(!retry||!retryAllowed)||retry&&!pending||!title.trim())return;
    creating.current=true;
    const epoch=live.current.epoch,body=pending??{title:title.trim(),idempotency_key:crypto.randomUUID()};let sent=false;
    setBusy(true);setRetryAllowed(false);setError('');setMessage('');
    try{await recovery.authorize();if(!current(epoch))return;
      const saved:PrivateDraftRecovery={contract:'private-draft-recovery.v1',title:body.title,pending:body};
      await persistPrivateDraftRecovery(recovery,saved);if(!current(epoch))return;setPending(body);sent=true;
      const opened=await workspaceApi.createPrivateDraft(identity,body);if(!current(epoch))return;
      await recovery.authorize();if(!current(epoch))return;
      await persistPrivateDraftRecovery(recovery,null);if(!current(epoch))return;setPending(null);await onOpened(opened);
    }catch(cause){if(current(epoch)){setError(sent?'The note creation is unconfirmed. Its exact request is retained. Check the saved result before starting another.':'The note was not sent. Check private recovery storage before starting.');deny(cause);}}
    finally{creating.current=false;if(current(epoch))setBusy(false);}
  }
  function record(){
    if(!onRecord||!recovery||busy||creating.current||locked)return;
    const epoch=live.current.epoch,recordingTitle=title.trim()==='Private note'?'Private recording':title.trim()||'Private recording';
    let flight:Promise<PrivateNotebookResult>|null=null;
    // Opening consent never waits for HTTP. The panel calls this independent, exactly-once preparation.
    onRecord({title:recordingTitle,prepareNotebook:()=>flight??(flight=(async()=>{
      if(!current(epoch)||creating.current)throw new WorkspaceApiError(503);
      creating.current=true;setBusy(true);let sent=false;
      try{
        // The initial editor read must settle before another read can update its CAS baseline.
        if(initialRecovery.current?.epoch===epoch)await initialRecovery.current.promise;
        const retained=await loadPrivateDraftRecovery(recovery);
        if(!current(epoch))throw new WorkspaceApiError(401);
        if(retained?.pending){setPending(retained.pending);setTitle(retained.title);throw new WorkspaceApiError(503);}
        const body={title:recordingTitle,idempotency_key:crypto.randomUUID()};
        await persistPrivateDraftRecovery(recovery,{contract:'private-draft-recovery.v1',title:body.title,pending:body});
        if(!current(epoch))throw new WorkspaceApiError(401);setPending(body);sent=true;
        const opened=await workspaceApi.createPrivateDraft(identity,body);
        await recovery.authorize();if(!current(epoch))throw new WorkspaceApiError(401);
        await persistPrivateDraftRecovery(recovery,null);if(!current(epoch))throw new WorkspaceApiError(401);
        setPending(null);return opened;
      }catch(cause){if(current(epoch))setError(sent?'The notebook creation is unconfirmed. Its exact request is retained. Local recording can continue independently.':'No new notebook was sent. Check retained note recovery; local recording can continue independently.');throw cause;}
      finally{creating.current=false;if(current(epoch))setBusy(false);}
    })())});
  }
  useEffect(()=>{
    if(recordingRequest.current.identity!==identity){recordingRequest.current={identity,seen:openRecordingRequest};return;}
    if(!Number.isSafeInteger(openRecordingRequest)||openRecordingRequest<=recordingRequest.current.seen||!onRecord||!recovery||busy||creating.current||locked)return;
    recordingRequest.current.seen=openRecordingRequest;record();
  },[identity,openRecordingRequest,onRecord,recovery,busy,locked]);
  async function resolve(){
    if(!recovery||!pending||!ready||busy||creating.current||locked)return;const epoch=live.current.epoch,body=pending;
    setBusy(true);setError('');setMessage('');
    try{await recovery.authorize();if(!current(epoch))return;
      const result=await workspaceApi.resolvePrivateDraft(identity,body);if(!current(epoch))return;
      await recovery.authorize();if(!current(epoch))return;
      if(result.outcome==='saved'&&result.workspace){
        const opened=await workspaceApi.openPrivateDraft(identity,result.workspace.id);if(!current(epoch))return;
        await persistPrivateDraftRecovery(recovery,null);if(!current(epoch))return;setPending(null);await onOpened(opened);
      }else{setRetryAllowed(true);setMessage('No saved result was found. The original request is retained; retry that same request only when ready.');}
    }catch(cause){if(current(epoch)){setError('The saved result remains unconfirmed. The exact request is retained; no creation was repeated.');deny(cause);}}
    finally{if(current(epoch))setBusy(false);}
  }
  async function reopen(id:string){
    if(!recovery||!ready||busy||locked||pending)return;const epoch=live.current.epoch;setBusy(true);setError('');
    try{await recovery.authorize();if(!current(epoch))return;const value=await workspaceApi.openPrivateDraft(identity,id);if(current(epoch))await onOpened(value);}
    catch(cause){if(current(epoch)){setError('This private note could not be opened. Check current access and try again.');deny(cause);}}
    finally{if(current(epoch))setBusy(false);}
  }
  const names=team?.configuration.bots.filter(bot=>bot.enabled&&!bot.retired).map(bot=>bot.name)??[];
  return <section className="practice-home" aria-label="Practice Home">
    <p className="team-kicker">YOUR PRACTICE</p><h1>{team?.revision?'Your workspace':'Let’s get you ready.'}</h1>
    <p className="practice-home-lead">Record with Scribe or start a private note. Choose a patient or visit later.</p>
    {onRecord&&<section className="practice-home-scribe" aria-label="Start with Scribe"><div><p className="team-kicker">SCRIBE</p><h2>Record first. Organize later.</h2><p>Private audio stays encrypted on this device. Everyone’s consent is required before the microphone starts.</p></div><button className="team-primary" disabled={!recovery||busy||locked} onClick={record}>Start recording</button></section>}
    {recordings&&onReopenRecording&&<section tabIndex={-1} className="practice-home-notes practice-home-recordings" aria-label="Saved private recordings"><h2>Recordings on this device</h2>{recordings.map(recording=><button className="practice-home-note" key={recording.recordingId} disabled={locked||busy} onClick={()=>onReopenRecording(recording.recordingId)}><strong>{recording.title}</strong>{recording.createdAt&&<time dateTime={recording.createdAt}>{new Date(recording.createdAt).toLocaleString()}</time>}<span>{recordingDetails(recording)}</span></button>)}{!recordings.length&&<p>No private recordings on this device yet.</p>}</section>}
    <form className="practice-quick-start" onSubmit={event=>{event.preventDefault();void create();}}>
      <label>Note title<input maxLength={160} value={title} disabled={!ready||busy||locked||!!pending} onChange={event=>setTitle(event.target.value)}/></label>
      <div className="practice-home-team"><h2>Your provider team</h2><p>{names.length?names.join(' · '):'Checking your team…'}</p>
        <p>Private drafts first. External actions need separate human review.</p>
        {team?.revision===0&&<button type="button" disabled={locked||busy||!ready||!!pending} onClick={onUseTeam}>{teamUnchanged?'Use this team':'Review team changes'}</button>}
        <button type="button" className="team-subtle" disabled={locked||busy} onClick={onSettings}>Personalize later in Settings</button>
      </div>
      <button type="submit" className="team-primary" disabled={!ready||busy||locked||!!pending||!title.trim()}>{busy?'Checking…':'Start a private note'}</button>
      <p className="team-fine">No appointment, email, calendar or patient portal is needed. Patient-linked work and external actions need separate review.</p>
    </form>
    {pending&&<div className="team-recovery"><p>An earlier note creation is unconfirmed. Check its saved result to avoid a duplicate.</p><button disabled={!ready||busy||locked} onClick={()=>void resolve()}>Check saved note creation</button>{retryAllowed&&<button disabled={!ready||busy||locked} onClick={()=>void create(true)}>Retry same note creation</button>}</div>}
    {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    <section className="practice-home-notes" aria-label="Saved private notes"><h2>Your private notes</h2>
      <button disabled={!recovery||busy||locked} onClick={()=>void refresh()}>Refresh private notes</button>
      {drafts?.drafts.map(draft=><button className="practice-home-note" disabled={!ready||busy||locked||!!pending} key={draft.workspace_id} onClick={()=>void reopen(draft.workspace_id)}><strong>{draft.title}</strong><span>{draft.link_state==='linked'?'Linked to a visit':'Private draft'} · Open saved notes</span></button>)}
      {drafts&&!drafts.drafts.length&&<p>No private notes yet.</p>}{drafts?.has_more&&<p>The latest 50 private notes are shown.</p>}
    </section>
    <nav className="practice-home-next" aria-label="Other ways to start"><button disabled={locked||busy} onClick={onVisits}>Visits and notes</button><button disabled={locked||busy} onClick={onPracticeWork}>Practice work</button><button disabled={locked||busy} onClick={onConnections}>Connect an account later</button></nav>
  </section>;
}
