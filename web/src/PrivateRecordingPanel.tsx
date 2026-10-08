import {useEffect,useRef,useState} from 'react';
import {PrivateRecordingRuntime,openPrivateRecordingStore,prewarmPrivateRecordingNative,consumePrivateRecordingNativeReceipt,type PrivateRecordingNativeReceipt,type PrivateRecordingOptions,type PrivateRecordingSnapshot,type PrivateRecordingStore} from './private-recording-runtime';
import {PrivateRecordingLedgerController,type PrivateRecordingLedger} from './private-recording-ledger';
import {readPrivateRecordingLanguage,savePrivateRecordingLanguage} from './recording-preferences';
import type {CaptureAttestation,CaptureLanguage} from './capture-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace} from './workspace-api';
import './practice-home.css';

export type PrivateNotebookResult={identity:AuthenticatedWorkspaceIdentity;workspace:Workspace;team:ProviderTeam};
type Consent=CaptureAttestation&{language:CaptureLanguage};
type Controller=Pick<PrivateRecordingRuntime,'snapshot'|'subscribe'|'start'|'pause'|'stop'|'close'|'attachWorkspace'|'exportWav'|'snapshotForLedger'>;
export type PrivateRecordingPanelProps={
  identity:AuthenticatedWorkspaceIdentity;scope:string;platform:'ios'|'desktop';isCurrent:()=>boolean;authorize?:()=>Promise<void>;
  title?:string;recordingId?:string;prepareNotebook?:()=>Promise<PrivateNotebookResult>;
  onClose:()=>void;onNotebook?:(value:PrivateNotebookResult)=>Promise<void>;onAccessLost?:(cause:unknown)=>void;
  /** Closed-panel result finalizer; caller verifies the original owner and reopens only this saved recording. */
  onNotebookPrepared?:(value:PrivateNotebookResult,recordingId:string)=>Promise<void>;
  onBusyChange?:(busy:boolean)=>void;onSaved?:(snapshot:PrivateRecordingSnapshot)=>void;
  runtimeFactory?:(options:PrivateRecordingOptions,input:{recordingId?:string;title:string;consent?:Consent})=>Promise<Controller>;
  prepareStore?:()=>Promise<PrivateRecordingStore>;prepareNative?:(input:{scope:string;revision:string})=>Promise<PrivateRecordingNativeReceipt>;
  consumeNative?:(receipt:PrivateRecordingNativeReceipt)=>Promise<Pick<PrivateRecordingNativeReceipt,'receiptId'|'revision'>|null>;
};
const elapsed=(seconds:number)=>`${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
/** Local recording has no patient authority, upload or transcription admission. */
export function PrivateRecordingPanel(props:PrivateRecordingPanelProps){
  const {identity,scope,platform,recordingId}=props;
  const [title,setTitle]=useState(props.title?.trim()||'Private recording');
  const [language,setLanguage]=useState<CaptureLanguage>(()=>readPrivateRecordingLanguage(scope));
  const [modality,setModality]=useState<CaptureAttestation['modality']>('in_person');
  const [consented,setConsented]=useState(false),[prepared,setPrepared]=useState(false),[working,setWorking]=useState(false);
  const [nativeReady,setNativeReady]=useState(platform!=='ios'),[nativeEpoch,setNativeEpoch]=useState(0);
  const [preparationError,setPreparationError]=useState(''),[nativeError,setNativeError]=useState('');
  const preparationRetry=useRef(false);
  const [snapshot,setSnapshot]=useState<PrivateRecordingSnapshot|null>(null),[error,setError]=useState(''),[notebookError,setNotebookError]=useState('');
  const [notebook,setNotebook]=useState<PrivateNotebookResult|null>(null),[audio,setAudio]=useState<string|null>(null);
  const live=useRef(props);live.current=props;
  const owner=useRef<{alive:boolean;identity:AuthenticatedWorkspaceIdentity;scope:string;store:PrivateRecordingStore|null;runtime:Controller|null;closed:Promise<void>|null;unsubscribe?:()=>void}|null>(null);
  const audioRef=useRef<string|null>(null),notebookRef=useRef<PrivateNotebookResult|null>(null);
  const starting=useRef(false);
  const [ledger,setLedger]=useState<PrivateRecordingLedger|null>(null),[ledgerBusy,setLedgerBusy]=useState(false),[ledgerError,setLedgerError]=useState('');
  const ledgerOwner=useRef<{selected:NonNullable<typeof owner.current>;id:string;store:PrivateRecordingStore|null;controller:PrivateRecordingLedgerController|null;chain:Promise<void>;attachAttempted:boolean;finishAttempted:boolean;loaded:boolean}|null>(null);
  const nativeReceipt=useRef<PrivateRecordingNativeReceipt|null>(null),nativeConsumed=useRef(false);
  const consumedReceipt=useRef<Pick<PrivateRecordingNativeReceipt,'receiptId'|'revision'>|null>(null);
  const accessStopped=useRef(false);
  const current=()=>!!owner.current?.alive&&owner.current.identity===live.current.identity&&owner.current.scope===live.current.scope&&live.current.isCurrent();
  const clearAudio=()=>{if(audioRef.current)URL.revokeObjectURL(audioRef.current);audioRef.current=null;setAudio(null);};
  function closeRuntime(selected:NonNullable<typeof owner.current>):Promise<void>{return selected.closed??(selected.closed=selected.runtime?.close()??Promise.resolve());}
  useEffect(()=>{
    const selected={alive:true,identity,scope,store:null as PrivateRecordingStore|null,runtime:null as Controller|null,closed:null as Promise<void>|null,unsubscribe:undefined as (()=>void)|undefined};owner.current=selected;
    setPrepared(false);setPreparationError('');setSnapshot(null);setConsented(false);setError('');setNotebookError('');setNotebook(null);setLedger(null);setLedgerError('');setLedgerBusy(false);clearAudio();setTitle(props.title?.trim()||'Private recording');setLanguage(readPrivateRecordingLanguage(scope));notebookRef.current=null;accessStopped.current=false;nativeReceipt.current=null;consumedReceipt.current=null;nativeConsumed.current=false;setNativeReady(platform!=='ios');
    void(async()=>{
      const authorization=props.authorize?.()??Promise.resolve();
      const [storage,authority]=await Promise.allSettled([props.prepareStore?.()??openPrivateRecordingStore(scope,platform),authorization]);
      if(authority.status==='rejected'){if(storage.status==='fulfilled')storage.value.close();throw authority.reason;}
      if(storage.status==='rejected')throw storage.reason;
      const store=storage.value;
      if(!selected.alive||owner.current!==selected||!current()){store.close();return;}selected.store=store;
      if(recordingId){
        const runtime=await(props.runtimeFactory??PrivateRecordingRuntime.open)({scope,platform,isCurrent:()=>owner.current===selected&&current(),openStore:async()=>store,...(platform==='ios'?{nativePreparation:()=>owner.current===selected?takeNativeReceipt():null}:{})},{recordingId,title});
        if(!selected.alive||owner.current!==selected){await runtime.close();return;}
        selected.runtime=runtime;selected.unsubscribe=runtime.subscribe(value=>{if(selected.alive&&owner.current===selected)setSnapshot(value);});
      }
      setPrepared(true);
    })().catch(cause=>{if(selected.alive&&owner.current===selected){setPreparationError(recordingId?'Saved recording recovery could not be confirmed. Its encrypted audio is retained. Check microphone status before starting another recording.':'Recording is not ready: current access or encrypted storage could not be prepared. Check your connection and try again.');if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status))live.current.onAccessLost?.(cause);}});
    return()=>{selected.alive=false;const binding=ledgerOwner.current;if(binding?.selected===selected){ledgerOwner.current=null;void binding.chain.finally(()=>binding.store?.close()).catch(()=>{});}selected.unsubscribe?.();if(selected.runtime)void closeRuntime(selected).catch(()=>{});else selected.store?.close();if(audioRef.current)URL.revokeObjectURL(audioRef.current);audioRef.current=null;};
  },[identity,scope,platform,recordingId]);
  function takeNativeReceipt(){
    const receipt=consumedReceipt.current;consumedReceipt.current=null;
    return current()?receipt:null;
  }
  useEffect(()=>{
    if(platform!=='ios'){setNativeReady(true);return;}
    const selected=owner.current,revision=identity.mode==='clerk_jwt'?identity.nativeSession?.revision:undefined;
    let active=true,timer:ReturnType<typeof setTimeout>|undefined;nativeReceipt.current=null;setNativeReady(false);setNativeError('');
    if(!revision){setNativeError('Recording is not ready: sign in again to restore this device’s recording access.');return;}
    void(props.prepareNative??prewarmPrivateRecordingNative)({scope,revision}).then(receipt=>{
      if(!active||owner.current!==selected||!current())return;
      if(receipt.revision!==revision||Date.parse(receipt.expiresAt)<=Date.now())throw new WorkspaceApiError(403);
      nativeReceipt.current=receipt;setNativeReady(true);
      timer=setTimeout(()=>{nativeReceipt.current=null;setNativeReady(false);if(!nativeConsumed.current)setNativeError('Recording access check expired. Try preparing recording again.');},Math.max(0,Date.parse(receipt.expiresAt)-Date.now()));
    }).catch(()=>{if(active&&owner.current===selected)setNativeError('Recording is not ready: this device’s recording access could not be checked. Try preparing recording again.');});
    return()=>{active=false;if(timer)clearTimeout(timer);};
  },[identity,scope,platform,nativeEpoch]);
  async function retryPreparation(){
    const selected=owner.current;
    if(!selected?.alive||selected.runtime||preparationRetry.current||!current())return;
    if(!preparationError){setNativeEpoch(value=>value+1);return;}
    preparationRetry.current=true;setPreparationError('');
    try{
      const [storage,authority]=await Promise.allSettled([props.prepareStore?.()??openPrivateRecordingStore(scope,platform),props.authorize?.()??Promise.resolve()]);
      if(authority.status==='rejected'){if(storage.status==='fulfilled')storage.value.close();throw authority.reason;}
      if(storage.status==='rejected')throw storage.reason;
      if(owner.current!==selected||!current()){storage.value.close();return;}
      selected.store?.close();selected.store=storage.value;
      if(recordingId){
        const runtime=await(props.runtimeFactory??PrivateRecordingRuntime.open)({scope,platform,isCurrent:()=>owner.current===selected&&current(),openStore:async()=>storage.value,...(platform==='ios'?{nativePreparation:()=>owner.current===selected?takeNativeReceipt():null}:{})},{recordingId,title});
        if(owner.current!==selected||!current()){await runtime.close();return;}
        selected.runtime=runtime;selected.unsubscribe=runtime.subscribe(value=>{if(selected.alive&&owner.current===selected)setSnapshot(value);});
      }
      setPrepared(true);
      if(platform==='ios'&&!nativeReady)setNativeEpoch(value=>value+1);
    }catch(cause){if(owner.current===selected&&current()){setPreparationError('Recording is not ready: current access or encrypted storage could not be prepared. Check your connection and try again.');if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status))live.current.onAccessLost?.(cause);}}
    finally{preparationRetry.current=false;}
  }
  useEffect(()=>{
    const selected=owner.current;
    if(!selected?.alive||current()||accessStopped.current)return;
    accessStopped.current=true;setConsented(false);setNotebook(null);notebookRef.current=null;setLedger(null);clearAudio();
    void(async()=>{try{await selected.runtime?.pause();live.current.onAccessLost?.(new WorkspaceApiError(401));}catch{setError('Access changed and the microphone stop is unconfirmed. Keep this panel open and check Stop.');}})();
  });
  useEffect(()=>{
    if(!props.prepareNotebook)return;
    const selected=owner.current,finalize=props.onNotebookPrepared;let active=true;
    void props.prepareNotebook().then(async value=>{
      if(value.identity!==identity||!value.workspace.private_draft)throw new WorkspaceApiError(403);
      if(!active||!selected?.alive||owner.current!==selected||selected.closed){
        const savedId=selected?.runtime?.snapshot.recordingId;
        if(savedId&&selected&&finalize){await closeRuntime(selected);await finalize(value,savedId);}
        return;
      }
      if(!current())return;
      notebookRef.current=value;setNotebook(value);
      await selected.runtime?.attachWorkspace(value.workspace.id,true);
    }).catch(async cause=>{
      if(!active||!selected?.alive||owner.current!==selected)return;
      setNotebookError('The private notebook is unconfirmed. Its exact request is retained; your local audio does not depend on that request.');
      if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status)){
        try{await selected.runtime?.pause();live.current.onAccessLost?.(cause);}catch{setError('Access changed and the microphone stop is unconfirmed. Keep this panel open and check Stop.');}
      }
    });
    return()=>{active=false;};
  },[identity,scope,recordingId]);
  // Metadata synchronization uses a separate encrypted-store handle and never
  // gates microphone start, Stop, playback or closing the recording.
  function synchronizeLedger(action:'automatic'|'check'|'retry'|'finish'='automatic'){
    const selected=owner.current,mapping=notebookRef.current,runtime=selected?.runtime;
    if(!selected?.alive||!runtime||!mapping||!current())return;
    const id=runtime.snapshot.recordingId;
    let binding=ledgerOwner.current;
    if(!binding){binding={selected,id,store:null,controller:null,chain:Promise.resolve(),attachAttempted:false,finishAttempted:false,loaded:false};ledgerOwner.current=binding;}
    if(binding.selected!==selected||binding.id!==id)return;
    const owned=binding;
    owned.chain=owned.chain.catch(()=>{}).then(async()=>{
      if(!current()||ledgerOwner.current!==owned)return;
      setLedgerBusy(true);
      try{
        if(!owned.controller){
          const store=await(props.prepareStore?.()??openPrivateRecordingStore(scope,platform));
          if(!current()||ledgerOwner.current!==owned){store.close();return;}
          owned.store=store;owned.controller=new PrivateRecordingLedgerController({identity,team:mapping.team,workspace:mapping.workspace,store,scope,isCurrent:()=>current()&&ledgerOwner.current===owned});
        }
        let saved=await owned.controller.readCurrent(id);owned.loaded=true;
        if(action==='check'&&saved)saved=await owned.controller.checkSaved(id);
        if(action==='retry')saved=await owned.controller.retryExact(id);
        // Reopening only reads retained metadata. A pending result is checked
        // explicitly; no effect repeats an unknown POST.
        const audioState=await runtime.snapshotForLedger();
        if(action==='automatic'&&!recordingId&&!saved&&!owned.attachAttempted&&audioState.startedAt&&
            (audioState.phase==='recording'||['sealed','interrupted'].includes(audioState.phase)&&audioState.chunks>0)){
          owned.attachAttempted=true;saved=await owned.controller.attach(audioState);
        }
        const latest=await runtime.snapshotForLedger();
        if((!recordingId||action==='finish')&&saved?.state==='attached'&&!owned.finishAttempted&&
            ['sealed','interrupted'].includes(latest.phase)&&latest.chunks>0){
          owned.finishAttempted=true;saved=await owned.controller.finish(latest);
        }
        if(current()&&ledgerOwner.current===owned){setLedger(saved);setLedgerError('');}
      }catch{
        if(current()&&ledgerOwner.current===owned){
          // The exact request was sealed before transmission; read it locally
          // even when the response or its local receipt write was lost.
          try{setLedger(await owned.controller?.readCurrent(id)??null);}catch{}
          setLedgerError('Notebook recording status is unconfirmed. Local audio is retained. Check the saved result before retrying.');
        }
      }finally{if(current()&&ledgerOwner.current===owned)setLedgerBusy(false);}
    });
  }
  useEffect(()=>{synchronizeLedger();},[notebook,snapshot?.recordingId,snapshot?.phase]);
  const activeAudio=!!snapshot&&['starting','recording','pausing','stopping','stop_unconfirmed'].includes(snapshot.phase);
  useEffect(()=>{live.current.onBusyChange?.(working||activeAudio);},[working,activeAudio]);
  useEffect(()=>{if(snapshot&&['sealed','paused','interrupted'].includes(snapshot.phase))live.current.onSaved?.(snapshot);},[snapshot]);
  useEffect(()=>{if(platform==='ios'&&nativeConsumed.current&&snapshot&&['paused','interrupted'].includes(snapshot.phase)){nativeConsumed.current=false;setNativeEpoch(value=>value+1);}},[snapshot?.phase,platform]);
  async function start(){
    if(!prepared||!nativeReady||working||starting.current||!current()||!consented||activeAudio||snapshot?.phase==='sealed')return;
    starting.current=true;
    const consent:Consent={modality,participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:new Date().toISOString(),language};
    const selected=owner.current!;setWorking(true);setConsented(false);setError('');clearAudio();
    try{
      let runtime=selected.runtime;
      if(!runtime){runtime=await(props.runtimeFactory??PrivateRecordingRuntime.open)({scope,platform,isCurrent:()=>owner.current===selected&&current(),openStore:async()=>selected.store!,...(platform==='ios'?{nativePreparation:()=>owner.current===selected?takeNativeReceipt():null}:{})},{title:title.trim()||'Private recording',consent});selected.runtime=runtime;selected.unsubscribe=runtime.subscribe(value=>{if(selected.alive&&owner.current===selected)setSnapshot(value);});}
      if(!current())throw new WorkspaceApiError(401);
      if(platform==='ios'){
        const receipt=nativeReceipt.current;nativeReceipt.current=null;setNativeReady(false);nativeConsumed.current=true;
        const claimed=receipt&&Date.parse(receipt.expiresAt)>Date.now()?await(props.consumeNative??consumePrivateRecordingNativeReceipt)(receipt):null;
        if(!claimed||!current()){setNativeEpoch(value=>value+1);throw new WorkspaceApiError(403);}
        consumedReceipt.current=claimed;
      }
      // Notebook creation/mapping is independent and never gates microphone start.
      const mapping=notebookRef.current;if(mapping)void runtime.attachWorkspace(mapping.workspace.id,true).catch(()=>setNotebookError('The notebook mapping could not be confirmed. Local audio is retained.'));
      await runtime.start(consent);setConsented(false);
      savePrivateRecordingLanguage(scope,language);
    }catch{if(selected.alive&&owner.current===selected)setError('Recording did not start cleanly. Check the microphone and saved recording status before trying again.');}
    finally{consumedReceipt.current=null;starting.current=false;if(selected.alive&&owner.current===selected)setWorking(false);}
  }
  async function halt(seal:boolean){
    const selected=owner.current;if(!selected?.runtime)return;setWorking(true);setError('');setConsented(false);
    try{await(seal?selected.runtime.stop():selected.runtime.pause());}
    catch{setError('The microphone stop is unconfirmed. Keep this panel open and check Stop again; retained audio has not been discarded.');}
    finally{if(selected.alive&&owner.current===selected)setWorking(false);}
  }
  async function playback(){
    const selected=owner.current;if(!selected?.runtime||working||activeAudio||!current())return;setWorking(true);setError('');clearAudio();
    try{const saved=await selected.runtime.exportWav();if(!current())return;const url=URL.createObjectURL(saved.blob);audioRef.current=url;setAudio(url);}
    catch{setError('Saved audio could not be verified for playback. The encrypted recording is retained.');}
    finally{if(selected.alive&&owner.current===selected)setWorking(false);}
  }
  async function close(){
    const selected=owner.current;if(activeAudio||working)return;
    setWorking(true);
    if(selected?.runtime)try{await closeRuntime(selected);}catch{selected.closed=null;setError('The microphone stop remains unconfirmed. Keep the recording open.');setWorking(false);return;}
    clearAudio();props.onClose();
  }
  async function openNotebook(){
    if(!notebook||!props.onNotebook||working||activeAudio||!current())return;
    setWorking(true);setError('');
    try{await owner.current?.runtime?.attachWorkspace(notebook.workspace.id,true);if(!current())return;await props.onNotebook(notebook);}
    catch(cause){setError('The private notebook could not be opened. Your local recording is retained.');if(cause instanceof WorkspaceApiError&&[401,403,426].includes(cause.status))props.onAccessLost?.(cause);}
    finally{if(owner.current?.alive)setWorking(false);}
  }
  const mayResume=snapshot&&['paused','interrupted'].includes(snapshot.phase);
  if(owner.current&&!current())return <section className="private-recording-panel" aria-label="Private Scribe recording">
    <h1>Recording access changed</h1><p>Private recording details are hidden. Retained audio remains encrypted for its original account.</p>
    <p role="status">{activeAudio?'Checking microphone stop':'Microphone stopped'}</p>
    {activeAudio&&<button className="team-primary" onClick={()=>void halt(true)}>Stop and save recording</button>}
    {!activeAudio&&<button disabled={working} onClick={()=>void close()}>Close recording</button>}
  </section>;
  return <section className="private-recording-panel" aria-label="Private Scribe recording">
    <header><div><p className="team-kicker">SCRIBE</p><h1>{snapshot?'Private recording':'Start a private recording'}</h1></div><button className="team-subtle" disabled={activeAudio||working} onClick={()=>void close()}>Close recording</button></header>
    <p>Record now. Choose a patient or confirmed visit later. This recording stays encrypted on this device and is not synced to another device.</p>
    <div role="status" className="private-recording-status"><strong>{snapshot?.phase==='recording'?'Recording':snapshot?.phase==='sealed'?snapshot.recordedChunks?'Saved on this device':'Stopped · no audio captured':snapshot?.phase==='paused'?'Paused':snapshot?.phase==='interrupted'?'Interrupted · retained audio':snapshot?.phase==='stop_unconfirmed'?'Microphone stop unconfirmed':snapshot?.busy?'Updating recording':preparationError||nativeError?'Recording not ready':!prepared?'Checking access and encrypted storage':!nativeReady?'Checking this device’s recording access':'Ready for consent'}</strong>
      {snapshot&&<span>{elapsed(snapshot.elapsedSeconds)} · {snapshot.recordedChunks} saved audio chunks</span>}<span>{snapshot?.recordedChunks?'Saved on this device; not yet synced':'Private · not synced'} · transcription not requested</span></div>
    {(!snapshot||mayResume||snapshot.phase==='ready')&&<div className="private-recording-consent">
      <details><summary>Recording options · {language==='en-US'?'English':'English and Spanish'} · {modality==='in_person'?'In person':modality==='virtual'?'Video visit':'Phone'}</summary>
      <label>Title <span>optional</span><input maxLength={160} value={title} disabled={working||!!snapshot} onChange={event=>setTitle(event.target.value)}/></label>
      <div className="private-recording-options"><label>Conversation<select value={modality} disabled={working} onChange={event=>setModality(event.target.value as CaptureAttestation['modality'])}><option value="in_person">In person</option><option value="virtual">Video visit</option><option value="phone">Phone</option></select></label>
      <label>Language<select value={language} disabled={working} onChange={event=>setLanguage(event.target.value as CaptureLanguage)}><option value="en-US">English</option><option value="en-US+es-US">English and Spanish</option></select></label></div></details>
      <label className="private-recording-check"><input type="checkbox" checked={consented} disabled={working} onChange={event=>setConsented(event.target.checked)}/>I informed everyone that this conversation will be recorded and every party gave consent for this recording.</label>
      <p className="team-fine">Consent is required each time you start or resume. Your language preference is remembered.</p>
      {!nativeReady&&platform==='ios'&&!nativeError&&<p role="status">Checking this device’s recording access…</p>}
      <button className="team-primary" disabled={!prepared||!nativeReady||working||!consented||!current()} onClick={()=>void start()}>{mayResume?'Resume recording':'Start recording'}</button>
      {(preparationError||nativeError)&&!working&&!snapshot&&<button onClick={()=>void retryPreparation()}>Try preparing recording again</button>}
      {nativeError&&snapshot&&!working&&<button onClick={()=>setNativeEpoch(value=>value+1)}>Try preparing recording again</button>}
    </div>}
    {activeAudio&&<div className="private-recording-actions"><button disabled={snapshot?.phase!=='recording'} onClick={()=>void halt(false)}>Pause recording</button><button className="team-primary" onClick={()=>void halt(true)}>Stop and save recording</button></div>}
    {snapshot&&!activeAudio&&<div className="private-recording-actions">{snapshot.phase!=='sealed'&&<button disabled={working} onClick={()=>void halt(true)}>Finish and save recording</button>}<button disabled={working||!snapshot.recordedChunks||!current()} onClick={()=>void playback()}>Play saved recording</button>
      {notebook&&props.onNotebook&&<button disabled={working||!current()} onClick={()=>void openNotebook()}>Open private notebook</button>}</div>}
    {notebook&&<aside aria-label="Notebook recording status"><p role="status">{ledger?.state==='finished'?'Recording details saved to your private notebook':ledger?.state==='attached'?'Recording linked to your private notebook':ledger?'Notebook recording status unconfirmed':'Checking notebook recording status'} · audio remains on this device; not synced or transcribed.</p>
      {recordingId&&ledger?.state==='attached'&&snapshot&&['sealed','interrupted'].includes(snapshot.phase)&&snapshot.recordedChunks>0&&<button disabled={ledgerBusy} onClick={()=>synchronizeLedger('finish')}>Save recording details to notebook</button>}
      {ledger&&['attach_pending','finish_pending'].includes(ledger.state)&&<button disabled={ledgerBusy} onClick={()=>synchronizeLedger('check')}>Check saved recording result</button>}
      {ledger?.retry_ready&&<button disabled={ledgerBusy} onClick={()=>synchronizeLedger('retry')}>Retry original recording request</button>}
      {ledgerError&&<p role="status">{ledgerError}</p>}</aside>}
    {audio&&current()&&<audio controls src={audio} aria-label="Saved private recording playback"/>}
    {preparationError&&<p role="alert">{preparationError}</p>}{nativeError&&<p role="alert">{nativeError}</p>}{error&&<p role="alert">{error}</p>}{notebookError&&<p role="status">{notebookError}</p>}
  </section>;
}
