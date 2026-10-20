import {useEffect,useRef,useState} from 'react';
import {PrivateRecordingRuntime,openPrivateRecordingStore,type PrivateRecordingStore} from './private-recording-runtime';
import {PrivateRecordingLedgerController} from './private-recording-ledger';
import {privateRecordingApi,type RecordingVisitBinding,type RecordingVisitRequest} from './private-recording-api';
import {workspaceApi,WorkspaceApiError,botAddress,type AuthenticatedWorkspaceIdentity,type ProviderTeam,type Workspace,type WorkspaceEncounter,type CaptureTaskBot} from './workspace-api';
import {parseVisitTranscriptionIntent,visitTranscriptionCommand,visitTranscriptionIntentHash,requireVisitTranscriptionSource,requireVisitTranscriptionConsent,type RecordingTranscriptionGesture,type SavedRecordingEntry} from './SavedRecordingTranscriptionPanel';
import {vendorCanonical} from './vendor-contract';

/** Visit association and transcription have separate exact requests under one explicit consent gesture. */
export function RecordingVisitPanel({entry,identity,origin,team,locked,isCurrent,onSelected,taskBot}:{entry:SavedRecordingEntry;
  identity:AuthenticatedWorkspaceIdentity;origin:Workspace;team:ProviderTeam;locked:boolean;isCurrent:()=>boolean;taskBot?:CaptureTaskBot;
  onSelected:(workspace:Workspace,binding:RecordingVisitBinding|null,gesture?:RecordingTranscriptionGesture)=>Promise<void>}){
  const [choices,setChoices]=useState<WorkspaceEncounter[]|null>(null),[choice,setChoice]=useState(''),[confirmed,setConfirmed]=useState(false);
  const [busy,setBusy]=useState(true),[error,setError]=useState(''),[pending,setPending]=useState(false),[reload,setReload]=useState(0),[targetLabel,setTargetLabel]=useState('');
  const [clip,setClip]=useState<{title:string;startedAt:string|null;seconds:number}|null>(null);
  const store=useRef<PrivateRecordingStore|null>(null),flight=useRef<symbol|null>(null),generation=useRef<symbol|null>(null);
  const live=useRef({identity,isCurrent,locked,entry,origin,team,taskBot});live.current={identity,isCurrent,locked,entry,origin,team,taskBot};
  const alive=useRef(false),key='visit-binding:'+entry.recordingId;
  const current=()=>alive.current&&live.current.identity===identity&&live.current.entry.recordingId===entry.recordingId&&live.current.entry.scope===entry.scope&&
    live.current.origin.id===origin.id&&live.current.team.revision===team.revision&&live.current.team.recovery_scope===team.recovery_scope&&live.current.isCurrent();
  function need(v:unknown):asserts v{if(!v)throw new WorkspaceApiError(409,'private_recording_visit_changed');}
  function sameAuthority(returned:ProviderTeam){
    need(returned.revision===team.revision&&returned.recovery_scope===team.recovery_scope);
    if(taskBot){const bot=returned.configuration?.bots.find(bot=>botAddress(bot)===taskBot.selection.address);
      need(taskBot.enabled&&taskBot.selection.team_revision===returned.revision&&bot?.role==='scribe'&&bot.enabled&&!bot.retired);}
  }
  async function readClip(receipt:Awaited<ReturnType<typeof privateRecordingApi.read>>,check=current){
    const recording=await PrivateRecordingRuntime.open({scope:entry.scope,platform:entry.platform,isCurrent:check},{recordingId:entry.recordingId,title:'Saved recording'});
    try{const audio=await recording.snapshotForLedger();need(check()&&receipt.finish&&audio.phase==='sealed'&&audio.recordingId===entry.recordingId&&recording.snapshot.workspaceId===origin.id&&
      audio.manifestSHA256===receipt.finish.manifest_sha256&&audio.chunks===receipt.finish.chunks&&audio.frames===receipt.finish.frames);
      return {audio,title:recording.snapshot.title,startedAt:audio.startedAt??null,seconds:recording.snapshot.elapsedSeconds};
    }finally{await recording.close();}
  }
  function failure(cause:unknown){if(current())setError(cause instanceof WorkspaceApiError&&cause.code==='private_recording_visit_in_use'
    ?'This visit already has a saved recording transfer. Your original audio is retained.'
    :cause instanceof WorkspaceApiError&&cause.code==='private_recording_visit_changed'
    ?'The recording, consent or visit changed. Reopen the original recording to check its saved connection before transcribing.'
    :'The visit connection could not be confirmed. Your recording and exact request are saved. Check the saved connection before continuing.');}
  async function original(check=current){if(!store.current||!check())throw new WorkspaceApiError(403);
    const ledger=new PrivateRecordingLedgerController({identity,team,workspace:origin,store:store.current,scope:entry.scope,isCurrent:check});
    const record=await ledger.readCurrent(entry.recordingId);if(record?.state!=='finished'||!record.receipt)throw new WorkspaceApiError(409);
    const receipt=await privateRecordingApi.read(identity,record.attach,team,record.receipt.recording_id);
    if(!check())throw new WorkspaceApiError(403);return {record,receipt};}
  async function retained(value:unknown){
    if(value!==null&&typeof value==='object'&&'contract'in value&&value.contract==='cosmas.visit-transcription.intent.v1'){
      const intent=await parseVisitTranscriptionIntent(value);return {command:intent.request,intent};
    }
    return {command:visitTranscriptionCommand(value),intent:null};
  }
  async function selected(binding:RecordingVisitBinding,check=current,gesture?:RecordingTranscriptionGesture){
    const result=await workspaceApi.openExisting(identity,{workspace_id:binding.target_workspace_id,appointment_id:binding.appointment_id});
    need(result.identity===identity&&result.workspace.id===binding.target_workspace_id&&result.workspace.appointment_id===binding.appointment_id);sameAuthority(result.team);if(gesture)need(result.workspace.revision===binding.request.expected_target_revision);
    if(check())await onSelected(result.workspace,binding,gesture);
  }
  useEffect(()=>{alive.current=true;const selectedGeneration=Symbol('recording-visit');generation.current=selectedGeneration;flight.current=null;let mounted=true,opened:PrivateRecordingStore|null=null;const check=()=>mounted&&generation.current===selectedGeneration&&current();
    setClip(null);setConfirmed(false);setPending(false);setChoices(null);setChoice('');setTargetLabel('');setBusy(true);setError('');
    void(async()=>{opened=await openPrivateRecordingStore(entry.scope,entry.platform);if(!check()){opened.close();return;}store.current=opened;
      const {record,receipt}=await original(check);const details=await readClip(receipt,check);if(!check())return;setClip(details);
      const saved=await opened.read(key);if(!check())return;
      const stored=saved===null?null:await retained(saved);if(!check())return;
      if(stored?.intent)requireVisitTranscriptionSource(stored.intent,receipt,entry,team);
      const binding=await privateRecordingApi.readVisitBinding(identity,record.attach,team,receipt);if(!check())return;
      // Ordinary reopening recovers a saved visit, but never creates a send gesture.
      if(binding){if(stored&&vendorCanonical(stored.command)!==vendorCanonical(binding.request))throw new WorkspaceApiError(409);await selected(binding,check);return;}
      if(origin.appointment_id&&await opened.read('transfer:'+entry.recordingId)!==null){if(check())await onSelected(origin,null);return;}
      if(stored){const target=await workspaceApi.openExisting(identity,{workspace_id:stored.command.target_workspace_id,appointment_id:stored.command.appointment_id});
        need(target.identity===identity&&target.workspace.id===stored.command.target_workspace_id&&target.workspace.appointment_id===stored.command.appointment_id);sameAuthority(target.team);
        if(check()){setPending(true);setChoice(stored.command.appointment_id);setTargetLabel(target.workspace.label);}return;}
      const rows=await workspaceApi.catalog(identity);if(check())setChoices(rows);
    })().catch(cause=>{if(check())failure(cause);}).finally(()=>{if(check())setBusy(false);});
    return()=>{mounted=false;alive.current=false;generation.current=null;store.current=null;opened?.close();};
  },[identity,entry.scope,entry.recordingId,origin.id,team.revision,team.recovery_scope,taskBot?.selection.address,taskBot?.selection.team_revision,taskBot?.enabled,reload]);
  async function confirm(){if(!current()||!store.current||flight.current||busy||live.current.locked||!confirmed||!choice||!taskBot?.enabled)return;
    const ticket=Symbol('confirm-visit'),selectedGeneration=generation.current;flight.current=ticket;setBusy(true);setError('');
    const expectedBot=vendorCanonical(taskBot.selection);
    const check=()=>generation.current===selectedGeneration&&current()&&live.current.taskBot?.enabled===true&&vendorCanonical(live.current.taskBot.selection)===expectedBot;
    try{const storage=store.current,saved=await storage.read(key);if(!check())return;
      const prior=saved===null?null:await retained(saved);
      const target=prior?await workspaceApi.openExisting(identity,{workspace_id:prior.command.target_workspace_id,appointment_id:prior.command.appointment_id}):await workspaceApi.open(identity,choice);
      need(check()&&target.identity===identity&&target.workspace.appointment_id===choice&&(!prior||target.workspace.id===prior.command.target_workspace_id));sameAuthority(target.team);
      const command:RecordingVisitRequest=prior?.command??{idempotency_key:crypto.randomUUID(),target_workspace_id:target.workspace.id,appointment_id:choice,expected_target_revision:target.workspace.revision,visit_confirmed:true};
      const {record,receipt}=await original(check);need(check()&&receipt.finish);
      const {audio}=await readClip(receipt,check);need(check());
      let intent=prior?.intent;
      if(!intent){const {language,...consent}=audio.consent;
        intent=await parseVisitTranscriptionIntent({contract:'cosmas.visit-transcription.intent.v1',scope:entry.scope,owner_id:receipt.owner_id,box_id:receipt.box_id,recovery_scope:receipt.recovery_scope,
          recording_id:receipt.recording_id,local_recording_id:entry.recordingId,origin_workspace_id:origin.id,request:command,
          request_sha256:await visitTranscriptionIntentHash({contract:'cosmas.private-recording.visit-binding.v1',request:command}),
          finish_request_sha256:receipt.finish.request_sha256,manifest_sha256:audio.manifestSHA256,chunks:audio.chunks,frames:audio.frames,audio_consent_sha256:await visitTranscriptionIntentHash(audio.consent),
          admission:{key:crypto.randomUUID(),language,attestation:{...consent,granted_at:new Date().toISOString()},bot:taskBot.selection}});
        requireVisitTranscriptionSource(intent,receipt,entry,team);need(check());
        await storage.write(key,saved,intent);need(check());setPending(true);setTargetLabel(target.workspace.label);
      }
      requireVisitTranscriptionSource(intent,receipt,entry,team);requireVisitTranscriptionConsent(intent,audio.consent);
      need(intent.audio_consent_sha256===await visitTranscriptionIntentHash(audio.consent)&&vendorCanonical(intent.admission.bot)===expectedBot&&check());
      // A retained or lost request is observed before any POST. An unconfirmed GET cannot authorize retry.
      let binding=await privateRecordingApi.readVisitBinding(identity,record.attach,team,receipt);need(check());
      if(!binding){need(target.workspace.revision===command.expected_target_revision);
        try{binding=await privateRecordingApi.bindVisit(identity,record.attach,team,receipt,command);}
        catch(cause){binding=await privateRecordingApi.readVisitBinding(identity,record.attach,team,receipt);need(check());if(!binding)throw cause;}
      }
      need(binding&&check()&&vendorCanonical(binding.request)===vendorCanonical(command)&&binding.request_sha256===intent.request_sha256);
      const intentHash=await visitTranscriptionIntentHash(intent);need(check());let claimed=false;
      const gesture:RecordingTranscriptionGesture={identity,scope:entry.scope,recordingId:entry.recordingId,intent_sha256:intentHash,
        claim:()=>{if(claimed||live.current.identity!==identity||live.current.entry.recordingId!==entry.recordingId||live.current.entry.scope!==entry.scope||live.current.team.revision!==team.revision||live.current.team.recovery_scope!==team.recovery_scope||vendorCanonical(live.current.taskBot?.selection??null)!==expectedBot||!live.current.taskBot?.enabled||!live.current.isCurrent())return false;claimed=true;return true;}};
      await selected(binding,check,gesture);
    }catch(cause){if(check())failure(cause);}finally{if(flight.current===ticket)flight.current=null;if(check())setBusy(false);}
  }
  return <section className="capture-panel saved-visit-selection" aria-label="Choose a visit for this recording">
    <h2>Choose a visit and transcribe</h2><p>Your saved recording stays in its original private notebook. Choose the patient and visit, then send this exact recording to Scribe.</p>
    <p>{origin.label} · <strong>{clip?.title??'Saved recording'}</strong></p>
    {clip&&<p>{clip.startedAt&&<time dateTime={clip.startedAt}>{new Date(clip.startedAt).toLocaleString()} · </time>}{Math.floor(clip.seconds/60)}:{String(Math.floor(clip.seconds%60)).padStart(2,'0')} saved recording</p>}
    {busy&&<p role="status">Checking your saved recording and visit…</p>}
    {pending?<p><strong>{targetLabel}</strong> · saved visit selection</p>:choices&&<label>Patient and visit<select value={choice} disabled={busy||locked} onChange={e=>{setChoice(e.target.value);setConfirmed(false);}}>
      <option value="">Choose a visit…</option>{choices.map(row=><option key={row.appointment_id} value={row.appointment_id} disabled={!!origin.appointment_id&&origin.appointment_id!==row.appointment_id}>{row.label}</option>)}
    </select></label>}
    {(pending||choices)&&<><label className="private-recording-check"><input type="checkbox" checked={confirmed} disabled={busy||locked||!choice} onChange={e=>setConfirmed(e.target.checked)}/>I checked that this saved recording belongs to this patient and visit, and everyone agreed to send it to Scribe for transcription.</label>
      <button className="team-primary" disabled={busy||locked||!choice||!confirmed||!taskBot?.enabled} onClick={()=>void confirm()}>Confirm visit and transcribe</button>
      {!taskBot?.enabled&&<p role="status">Enable Scribe to transcribe this recording. Your saved audio is retained.</p>}
      {choices&&!choices.length&&<p role="status">No confirmed visits are available. Your recording remains saved on this device.</p>}</>}
    {error&&<><p role="alert">{error}</p>{!pending&&!choices&&<button disabled={busy||locked} onClick={()=>setReload(v=>v+1)}>Check saved visit connection</button>}</>}
  </section>;
}
