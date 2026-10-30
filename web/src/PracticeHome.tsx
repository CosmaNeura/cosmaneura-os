import {SampleVisit} from './SampleVisit';
import {NotebookTitleEditor} from './NotebookTitleEditor';
import {useContext,useEffect,useLayoutEffect,useRef,useState} from 'react';
import {WorkspaceConnectionRecoveryContext} from './PracticeAccessGate';
import {workspaceProtocolGeneration} from './workspace-protocol';
import type {AccountRecoveryAccess} from './account-recovery';
import {loadPrivateDraftRecovery,persistPrivateDraftRecovery,readStoredPrivateDraftRecovery,type PrivateDraftCreate,type PrivateDraftRecovery} from './private-draft-recovery';
import {workspaceApi,WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
import {WorkspaceHomeStartup} from './workspace-home-startup';
import type {PrivateNotebookResult} from './PrivateRecordingPanel';
import type {PrivateRecordingSnapshot} from './private-recording-runtime';
import './practice-home.css';

function recordingDetails(recording:PrivateRecordingSnapshot):string {
  const status=recording.phase==='sealed'?(recording.recordedChunks?'Saved on this device':'Stopped · no audio captured'):recording.phase==='paused'?'Paused':recording.phase==='interrupted'?'Interrupted · check retained audio':'Check recording status';
  const seconds=Math.floor(recording.elapsedSeconds),duration=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  return `${duration} · ${status} · Private`;
}

export type StartPrivateRecording={title:string;prepareNotebook:(title?:string)=>Promise<PrivateNotebookResult>};
export function PracticeHome({conversationContext,onPendingChange,identity,recovery,team,teamUnchanged=true,locked,onUseTeam,onSettings,onVisits,onOpenVisit,onConnections,onPracticeWork,onOpened,onNoteOpened,onAccessLost,onBusyChange,onRecord,recordings,onReopenRecording,openRecordingRequest=0,recordingActive=false,nativeCompact=false,teamError='',onRetryTeam,suspended=false}:{
  conversationContext?:{name:string;scribe:boolean};onPendingChange?:(pending:boolean)=>void;
  identity:AuthenticatedWorkspaceIdentity;recovery:AccountRecoveryAccess|null;team:ProviderTeam|null;teamUnchanged?:boolean;locked:boolean;
  onUseTeam:()=>void;onSettings:()=>void;onVisits:()=>void;onOpenVisit?:(appointmentId:string)=>void;onConnections:()=>void;onPracticeWork:()=>void;
  onOpened:(value:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam})=>Promise<void>;
  onNoteOpened?:(value:{identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam})=>Promise<void>;
  onAccessLost:(cause:unknown)=>void;onBusyChange:(busy:boolean)=>void;
  onRecord?:(value:StartPrivateRecording)=>void;recordings?:PrivateRecordingSnapshot[];onReopenRecording?:(recordingId:string)=>void;
  openRecordingRequest?:number;recordingActive?:boolean;nativeCompact?:boolean;teamError?:string;onRetryTeam?:()=>void;suspended?:boolean;
}){
  const connection=useContext(WorkspaceConnectionRecoveryContext),connectionLive=useRef(connection);connectionLive.current=connection;
  const recoveredLists=useRef({identity,recovery,sequence:connection?.identity===identity?connection.sequence:0});
  const listRead=useRef<{epoch:number;promise:Promise<void>}|null>(null);
  const [sample,setSample]=useState(false);
  const [title,setTitle]=useState('Private note'),[pending,setPending]=useState<PrivateDraftCreate|null>(null),[ready,setReady]=useState(false);
  const [busy,setBusy]=useState(false),[retryAllowed,setRetryAllowed]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  const [opening,setOpening]=useState<{identity:AuthenticatedWorkspaceIdentity;recovery:AccountRecoveryAccess;epoch:number;workspaceId:string}|null>(null);
  const openingFlight=useRef<typeof opening>(null);
  const [drafts,setDrafts]=useState<Awaited<ReturnType<typeof workspaceApi.privateDraftSummaries>>|null>(null);
  const [listError,setListError]=useState('');
  const [search,setSearch]=useState(''),[needsReview,setNeedsReview]=useState(false),[renaming,setRenaming]=useState<string|null>(null),[slowCheck,setSlowCheck]=useState(false);
  const [visits,setVisits]=useState<Awaited<ReturnType<typeof workspaceApi.catalog>>|null>(null),[visitError,setVisitError]=useState('');
  const live=useRef({identity,recovery,epoch:0,alive:true});
  if(live.current.identity!==identity)live.current={identity,recovery,epoch:live.current.epoch+1,alive:true};
  else if(live.current.recovery!==recovery)live.current={...live.current,recovery};
  const current=(epoch:number)=>live.current.alive&&live.current.epoch===epoch&&live.current.identity===identity&&live.current.recovery===recovery;
  const sameAccount=(epoch:number)=>live.current.alive&&live.current.epoch===epoch&&live.current.identity===identity;
  useEffect(()=>{onPendingChange?.(!!pending);},[pending,onPendingChange]);
  const callback=useRef(onBusyChange);callback.current=onBusyChange;
  const creating=useRef(false);
  const initialRecovery=useRef<{epoch:number;promise:ReturnType<typeof loadPrivateDraftRecovery>}|null>(null);
  const recordingRequest=useRef({identity,seen:0});
  useEffect(()=>{callback.current(busy);},[busy]);
  useEffect(()=>{live.current.alive=true;return()=>{live.current.alive=false;};},[]);
  useLayoutEffect(()=>{recoveredLists.current={identity,recovery,sequence:connection?.identity===identity?connection.sequence:0};},[identity,recovery]);
  function readLists(epoch:number){
    const flight={epoch,promise:Promise.resolve()};
    const notesRead=workspaceApi.privateDraftSummaries,catalogRead=workspaceApi.catalog;
    flight.promise=(async()=>{
      const [notes,schedule]=await Promise.allSettled([
        typeof notesRead==='function'?notesRead(identity):Promise.reject(new Error('unavailable')),
        typeof catalogRead==='function'?catalogRead(identity):Promise.reject(new Error('unavailable')),
      ]);
      if(!sameAccount(epoch))return;
      // Background list reads never clear Start readiness or tear down access.
      // Start still authorizes on submit; lists are status-only.
      if(notes.status==='fulfilled'){setDrafts(notes.value);setListError('');}
      else setListError('Recent notes could not be loaded. You can still start recording or write a note.');
      if(schedule.status==='fulfilled'){setVisits(schedule.value);setVisitError('');}
      else setVisitError('Today’s visits could not be loaded. Recording and private notes remain available.');
    })().catch(()=>{}).finally(()=>{if(listRead.current===flight)listRead.current=null;});
    listRead.current=flight;return flight.promise;
  }
  const listsFor=useRef<AuthenticatedWorkspaceIdentity|null>(null);
  useEffect(()=>{
    if(suspended)return;
    // Returning to Home reuses the lists already read for this account.
    if(listsFor.current===identity)return;
    listsFor.current=identity;
    const epoch=++live.current.epoch;openingFlight.current=null;setOpening(null);setReady(false);setPending(null);setDrafts(null);setListError('');setBusy(false);setRetryAllowed(false);setError('');setMessage('');setTitle('Private note');setSearch('');setRenaming(null);setVisits(null);setVisitError('');setSlowCheck(false);
    // Visit and note lists do not decide whether Start is safe.
    void readLists(epoch);
  },[identity,suspended]);
  useEffect(()=>{
    if(suspended||ready){setSlowCheck(false);return;}
    const timer=setTimeout(()=>setSlowCheck(true),3000);
    return()=>clearTimeout(timer);
  },[ready,identity,suspended]);
  useEffect(()=>{
    if(suspended)return;
    if(!recovery){setReady(false);return;}
    // The journal was opened only after the signed team scope check. This read stays on device.
    // Submitting Start still calls authorize(), which reads the team again.
    const epoch=live.current.epoch,promise=readStoredPrivateDraftRecovery(recovery.journal);initialRecovery.current={epoch,promise};
    void(async()=>{const saved=await promise;if(!current(epoch))return;
      if(saved){setTitle(saved.title);setPending(saved.pending);}setReady(true);
    })().catch(cause=>{if(current(epoch)){setError('Private recovery could not be checked. Refresh Home before starting a new draft.');deny(cause);}});
  },[identity,recovery,suspended]);
  useEffect(()=>{
    if(!recovery||!ready||connection?.identity!==identity||recoveredLists.current.identity!==identity||recoveredLists.current.recovery!==recovery||
      connection.sequence<=recoveredLists.current.sequence||connection.phase!=='ready'||connection.busy||workspaceProtocolGeneration(identity)!==connection.generation)return;
    const epoch=live.current.epoch,sequence=connection.sequence,protocolGeneration=connection.generation;
    recoveredLists.current.sequence=sequence;
    const prior=listRead.current?.epoch===epoch?listRead.current.promise:null;
    // Read lists once after an explicit reconnect. Do not reload the journal,
    // change the private-create request, or resolve/submit any operation.
    void(async()=>{
      await prior;
      const latest=connectionLive.current;
      if(!current(epoch)||latest?.identity!==identity||latest.sequence!==sequence||latest.generation!==protocolGeneration||latest.phase!=='ready'||latest.busy||
        workspaceProtocolGeneration(identity)!==protocolGeneration)return;
      await readLists(epoch);
    })();
  },[identity,recovery,ready,connection?.identity,connection?.sequence,connection?.generation,connection?.phase,connection?.busy]);
  function deny(cause:unknown){if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status)){setDrafts(null);setReady(false);onAccessLost(cause);}}
  async function refresh(){
    if(!recovery||busy||creating.current||locked)return;const epoch=live.current.epoch;setBusy(true);setError('');setMessage('');
    try{const promise=loadPrivateDraftRecovery(recovery);initialRecovery.current={epoch,promise};const saved=await promise;if(!current(epoch))return;
      setPending(saved?.pending??null);if(saved)setTitle(saved.title);setReady(true);
      const list=await workspaceApi.privateDraftSummaries(identity);if(current(epoch)){setDrafts(list);setListError('');}
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
    const epoch=live.current.epoch,recordingTitle=title.trim()==='Private note'||!title.trim()?`Visit recording · ${new Date().toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}`:title.trim();
    let flight:Promise<PrivateNotebookResult>|null=null;
    // Opening consent never waits for HTTP. The panel calls this independent, exactly-once preparation.
    onRecord({title:recordingTitle,prepareNotebook:(chosenTitle=recordingTitle)=>flight??(flight=(async()=>{
      if(!current(epoch)||creating.current)throw new WorkspaceApiError(503);
      creating.current=true;setBusy(true);let sent=false;
      try{
        // The initial editor read must settle before another read can update its CAS baseline.
        if(initialRecovery.current?.epoch===epoch)await initialRecovery.current.promise;
        const retained=await loadPrivateDraftRecovery(recovery);
        if(!current(epoch))throw new WorkspaceApiError(401);
        if(retained?.pending){setPending(retained.pending);setTitle(retained.title);throw new WorkspaceApiError(503);}
        const body={title:chosenTitle.trim()||recordingTitle,idempotency_key:crypto.randomUUID()};
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
    if(!recovery||!ready||busy||locked||openingFlight.current)return;const epoch=live.current.epoch;
    const request={identity,recovery,epoch,workspaceId:id};openingFlight.current=request;setOpening(request);setBusy(true);setError('');
    try{await recovery.authorize();if(!current(epoch))return;const value=await workspaceApi.openPrivateDraft(identity,id);if(current(epoch))await (onNoteOpened??onOpened)(value);}
    catch(cause){if(current(epoch)){setError('This private note could not be opened. Check current access and try again.');deny(cause);}}
    finally{if(openingFlight.current===request)openingFlight.current=null;if(current(epoch)){setOpening(previous=>previous===request?null:previous);setBusy(false);}}
  }
  const openingNoteId=opening&&opening.identity===identity&&opening.recovery===recovery&&current(opening.epoch)?opening.workspaceId:null;
  const query=search.trim().toLocaleLowerCase(),today=new Date().toDateString();
  const todaysVisits=visits?.filter(visit=>visit.start_at&&new Date(visit.start_at).toDateString()===today)??[];
  const names=team?.configuration.bots.filter(bot=>bot.enabled&&!bot.retired).map(bot=>bot.name)??[];
  const chiefAvailable=team?.configuration.bots.some(bot=>bot.role==='chief'&&bot.enabled&&!bot.retired)??false;
  const nativeStartLabel=!team?'Start conversation':chiefAvailable?'Start with Chief':'Start a private note';
  const nativeTitleLabel=!team||chiefAvailable?'Name this conversation':'Name this note';
  const startEnabled=WorkspaceHomeStartup.startEnabled({recoveryReady:ready,busy,locked,pending:!!pending,title});
  const startupStatus=WorkspaceHomeStartup.status({recoveryReady:ready,teamListed:!!team,visitsLoaded:visits!==null||!!visitError,notesLoaded:drafts!==null||!!listError,teamError});
  const showStartupRetry=(!ready&&slowCheck)||!!visitError||!!listError||!!teamError;
  function retryChecks(){if(!ready||teamError)onRetryTeam?.();void readLists(live.current.epoch);}
  const titleField=<label>Note title<input maxLength={160} value={title} disabled={busy||locked||!!pending} onChange={event=>setTitle(event.target.value)}/></label>;
  const todayVisits=<section className="practice-home-notes" aria-label="Today's visits"><h2>Today's visits</h2>
      {todaysVisits.map(visit=><button className="practice-home-note" key={visit.appointment_id} disabled={locked||busy} onClick={()=>onOpenVisit?onOpenVisit(visit.appointment_id):onVisits()}><strong>{visit.label}</strong><time dateTime={visit.start_at}>{new Date(visit.start_at!).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'})}</time><span>{visit.workspace_id?'Open visit notes':'Open visit'}</span></button>)}
      {visitError?<p role="status">{visitError}</p>:visits&&!todaysVisits.length?<p>No supported visits are scheduled today. You can record or write a private note.</p>:null}
    </section>;
  const recordingList=recordings&&onReopenRecording?<section tabIndex={-1} className="practice-home-notes practice-home-recordings" aria-label="Saved private recordings"><h2>Recordings on this device</h2>{recordings.map(recording=><button className="practice-home-note" key={recording.recordingId} disabled={locked||busy} onClick={()=>onReopenRecording(recording.recordingId)}><strong>{recording.title}</strong>{recording.createdAt&&<time dateTime={recording.createdAt}>{new Date(recording.createdAt).toLocaleString()}</time>}<span>{recordingDetails(recording)}</span></button>)}{!recordings.length&&<p>No private recordings on this device yet.</p>}</section>:null;
  const quickStart=<form className="practice-quick-start" onSubmit={event=>{event.preventDefault();void create();}}>
      {nativeCompact&&!conversationContext&&<><h2>{!team?"Conversation":chiefAvailable?"Chief":"Private note"}</h2><p>Plan your next step privately.</p></>}
      {!nativeCompact&&titleField}
      {(!nativeCompact||team?.revision===0)&&!conversationContext&&<div className="practice-home-team"><h2>Your provider team</h2><p>{names.length?names.join(' · '):team?'No teammates are on yet.':'Your team list will appear here.'}</p>
        <p>Private drafts first. External actions need separate human review.</p>
        {team?.revision===0&&<button type="button" disabled={locked||busy||!ready||!!pending} onClick={onUseTeam}>{teamUnchanged?'Use this team':'Review team changes'}</button>}
        <button type="button" className="team-subtle" onClick={onSettings}>Personalize later in Settings</button>
      </div>}
      <button type="submit" className="team-primary" disabled={!startEnabled}>{busy?'Checking…':nativeCompact?nativeStartLabel:'Start a private note'}</button>
      {nativeCompact&&<details className="practice-home-title"><summary>{title==='Private note'?nativeTitleLabel:title}</summary>{titleField}</details>}
      {!nativeCompact&&<p className="team-fine">No appointment, email, calendar or patient portal is needed. Patient-linked work and external actions need separate review.</p>}
    </form>;
  return <section className="practice-home" data-native-compact={nativeCompact} data-conversation-context={!!conversationContext} data-context-scribe={!!conversationContext?.scribe} aria-label="Practice Home">
    {nativeCompact?<h1 className="team-sr-only">Home</h1>:<><p className="team-kicker">YOUR PRACTICE</p><h1>{team?.revision?'Your workspace':'Let’s get you ready.'}</h1></>}
    <p className="practice-home-lead">{nativeCompact?'Private notes, recordings and next steps.':'Record with Scribe or start a private note. Choose a patient or visit later.'}</p>
    {startupStatus&&<div className="practice-home-status" role="status">{startupStatus}{showStartupRetry&&<button type="button" onClick={retryChecks}>Retry</button>}</div>}
    {nativeCompact&&quickStart}
    {onRecord&&<section className="practice-home-scribe" aria-label="Start with Scribe"><div>{!nativeCompact&&<p className="team-kicker">SCRIBE</p>}<h2>{nativeCompact?'Record privately':'Record first. Organize later.'}</h2><p>{nativeCompact?'Original audio is encrypted on this iPhone. Confirm consent before recording.':'Private audio stays encrypted on this device. Everyone’s consent is required before the microphone starts.'}</p></div><button className="team-primary" disabled={!recovery||busy||locked} onClick={record}>Start recording</button></section>}
    {recordings&&onReopenRecording&&(nativeCompact?<details className="practice-home-recordings-disclosure"><summary>Saved recordings · {recordings.length}</summary>{recordingList}</details>:recordingList)}
    {!nativeCompact&&quickStart}
    {pending&&<div className="team-recovery"><p>An earlier note creation is unconfirmed. Check its saved result to avoid a duplicate.</p><button disabled={!ready||busy||locked} onClick={()=>void resolve()}>Check saved note creation</button>{retryAllowed&&<button disabled={!ready||busy||locked} onClick={()=>void create(true)}>Retry same note creation</button>}</div>}
    {error&&<p role="alert">{error}</p>}{listError&&<p role="alert">{listError}</p>}{message&&<p role="status">{message}</p>}
    {!nativeCompact&&todayVisits}
    <section className="practice-home-notes" aria-label="Saved private notes"><h2>{nativeCompact?'Saved notes':'Recent notes'}</h2>
      <div className="notebook-list-tools"><label>Search notes<input type="search" value={search} onChange={event=>setSearch(event.target.value)} placeholder="Title or patient"/></label>
        <label><input type="checkbox" checked={needsReview} onChange={event=>setNeedsReview(event.target.checked)}/>Needs review</label>
        <button disabled={!recovery||busy} onClick={()=>void refresh()}>Refresh private notes</button></div>
      {drafts?.drafts.filter(draft=>(!query||`${draft.title} ${draft.patient_label??''}`.toLocaleLowerCase().includes(query))&&(!needsReview||draft.note_state==='needs_review')).map(draft=><article className="notebook-list-row" key={draft.workspace_id}>
        <button className="practice-home-note" disabled={!ready||busy||locked} onClick={()=>void reopen(draft.workspace_id)}><strong>{draft.title}</strong>
          <span>{draft.patient_label??'No patient yet'} · {draft.note_state==='reviewed'?'Reviewed':draft.note_state==='needs_review'?'Needs review':'Draft notes'}</span>
          <time dateTime={draft.updated_at}>{new Date(draft.updated_at).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})}</time>
          <span>{draft.duration_seconds!==null?`${Math.floor(draft.duration_seconds/60)}:${String(Math.floor(draft.duration_seconds)%60).padStart(2,'0')} recording · `:''}Notebook saved · {draft.link_state==='linked'?'Linked to a visit':'Unlinked note'}</span></button>
        <div className="notebook-row-actions"><button disabled={busy||locked} onClick={()=>void reopen(draft.workspace_id)}>{openingNoteId===draft.workspace_id?'Opening…':'Open note'}</button><button onClick={()=>setRenaming(draft.workspace_id)}>Rename</button>{draft.link_state==='unlinked'&&<button disabled={busy||locked} onClick={()=>void reopen(draft.workspace_id)}>Link a visit</button>}</div>
        {openingNoteId===draft.workspace_id&&<p className="team-fine" role="status">Opening note…</p>}
        {renaming===draft.workspace_id&&<NotebookTitleEditor identity={identity} recovery={recovery} workspaceId={draft.workspace_id} title={draft.title} titleRevision={draft.title_revision} onClose={()=>setRenaming(null)} onAccessLost={onAccessLost}
          onSaved={receipt=>{setDrafts(current=>current?{...current,drafts:current.drafts.map(row=>row.workspace_id===receipt.workspace_id?{...row,title:receipt.title,title_revision:receipt.title_revision}:row)}:current);setRenaming(null);setMessage('Notebook title saved. Audio and original notes are retained.');}}/>}
      </article>)}
      {drafts&&!drafts.drafts.length&&<p>No private notes yet.</p>}{drafts&&drafts.drafts.length>0&&!drafts.drafts.some(draft=>(!query||`${draft.title} ${draft.patient_label??''}`.toLocaleLowerCase().includes(query))&&(!needsReview||draft.note_state==='needs_review'))&&<p>No notes match these filters.</p>}{drafts?.has_more&&<p>The latest 50 private notes are shown.</p>}
    </section>
    {nativeCompact&&todayVisits}
    {sample&&<SampleVisit onClose={()=>setSample(false)}/>}
    <nav className="practice-home-next" aria-label="Other ways to start"><button onClick={onVisits}>Visits and notes</button><button onClick={onPracticeWork}>Practice work</button><button onClick={onConnections}>Connect an account later</button><button disabled={recordingActive} onClick={()=>setSample(true)}>Try a sample</button></nav>
  </section>;
}
