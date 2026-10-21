import {useEffect,useRef,useState} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {openPrivateRecordingStore} from './private-recording-runtime';
import {PrivateTranscriptionController,type PrivateTranscript,type PrivateTranscriptAudio} from './private-transcription';
import {privateSpeechNative,privateTranscriptionMessage} from './private-transcription-native';
import {useUnsavedWork} from './unsaved-work';
export type PrivateTranscriptGesture={identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;claim:()=>boolean};
/** Private machine text is a device source, never a clinician note or shared draft. */
export function PrivateTranscriptPanel({identity,scope,recording,isCurrent,onBusy,onDirty,onPrepareNavigation,transcriptionGesture,savedScribeSource=false,allowTranscription=true,locked=false}:{identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;isCurrent:()=>boolean;onBusy?:(busy:boolean)=>void;onDirty?:(dirty:boolean)=>void;onPrepareNavigation?:(prepare:(()=>Promise<void>)|null)=>void;transcriptionGesture?:PrivateTranscriptGesture;savedScribeSource?:boolean;allowTranscription?:boolean;locked?:boolean}){
 const [value,setValue]=useState<PrivateTranscript|null>(null),[working,setWorking]=useState(''),[ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[progress,setProgress]=useState({chunks:0,total:0});
 const [openAttempt,setOpenAttempt]=useState(0);
 const [opening,setOpening]=useState(true);
 const revision=identity.mode==='clerk_jwt'?identity.nativeSession?.revision:undefined;
 type Owner={alive:boolean;identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;revision:string|undefined;openAttempt:number;controller:PrivateTranscriptionController|null};
 const owner=useRef<Owner|null>(null),loadedOwner=useRef<Owner|null>(null),live=useRef({identity,scope,recording,isCurrent,locked,allowTranscription});live.current={identity,scope,recording,isCurrent,locked,allowTranscription};
 const valueRef=useRef<PrivateTranscript|null>(null),workingRef=useRef(''),busyRef=useRef(false);
 const navigationRegistration=useRef<{prepare:()=>Promise<void>;callback:NonNullable<typeof onPrepareNavigation>}|null>(null);
 const unsettledSave=useRef<{owner:Owner;prior:PrivateTranscript;words:string}|null>(null);
 const workingBusy=(next:boolean)=>{busyRef.current=next;setBusy(next);};
 const intent=useRef<{gesture:PrivateTranscriptGesture;identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;revision:string|undefined;claimed:boolean;started:boolean}|null>(null);
 const bound=(selected=owner.current)=>!!selected?.alive&&owner.current===selected&&selected.identity===identity&&selected.scope===scope&&selected.recording===recording&&selected.revision===revision&&selected.openAttempt===openAttempt&&
  live.current.identity===identity&&live.current.scope===scope&&live.current.recording===recording;
 const current=(selected=owner.current)=>bound(selected)&&identity.mode==='clerk_jwt'&&identity.nativeSession?.isCurrent()===true&&live.current.isCurrent();
 const displayed=current()&&loadedOwner.current===owner.current?value:null;
 const displayedWorking=displayed?working:'';
 const dirty=!!displayed?.raw&&(displayedWorking!==displayed.working||unsettledSave.current?.owner===owner.current);
 const releaseOwnUnsaved=useUnsavedWork(dirty);
 useEffect(()=>{const selected:Owner={alive:true,identity,scope,recording,revision,openAttempt,controller:null};owner.current=selected;loadedOwner.current=null;
  let selectedIntent=intent.current;
  if(!transcriptionGesture){intent.current=null;selectedIntent=null;}
  else if(!selectedIntent||selectedIntent.gesture!==transcriptionGesture||selectedIntent.identity!==identity||selectedIntent.scope!==scope||selectedIntent.recording!==recording||selectedIntent.revision!==revision){
   selectedIntent={gesture:transcriptionGesture,identity,scope,recording,revision,claimed:transcriptionGesture.identity===identity&&transcriptionGesture.scope===scope&&transcriptionGesture.recording===recording&&transcriptionGesture.claim(),started:false};intent.current=selectedIntent;
  }
  const explicit=!!selectedIntent?.claimed&&!selectedIntent.started;
  const selectedCurrent=()=>current(selected);
  valueRef.current=null;workingRef.current='';unsettledSave.current=null;setValue(null);setWorking('');setReady(false);setOpening(true);workingBusy(false);setError('');setMessage('');setProgress({chunks:0,total:0});
  void(async()=>{if(!revision)throw Object.assign(new Error('Native session unavailable'),{code:'private_speech_changed'});const store=await openPrivateRecordingStore(scope,'ios');if(!selectedCurrent()){store.close();return;}
   const controller=new PrivateTranscriptionController({scope,revision,recording,store,native:privateSpeechNative,isCurrent:selectedCurrent,onProgress:(chunks,total)=>{if(selectedCurrent())setProgress({chunks,total});}});selected.controller=controller;
   const saved=await controller.load();if(!selectedCurrent())return;loadedOwner.current=selected;valueRef.current=saved;workingRef.current=saved?.working??'';setValue(saved);setWorking(workingRef.current);setReady(true);
   if(explicit&&!saved?.raw&&selectedIntent&&intent.current===selectedIntent&&!selectedIntent.started&&!live.current.locked&&live.current.allowTranscription){selectedIntent.started=true;workingBusy(true);try{const result=await controller.transcribe();if(selectedCurrent()){valueRef.current=result;workingRef.current=result.working;setValue(result);setWorking(result.working);setMessage('Private transcript saved on this iPhone. Review and edit the words below.');}}finally{if(selectedCurrent())workingBusy(false);}}
  })().catch(cause=>{if(selectedCurrent())setError(privateTranscriptionMessage(cause));}).finally(()=>{if(bound(selected))setOpening(false);});
  return()=>{selected.alive=false;void selected.controller?.close();};
 },[identity,scope,recording,revision,transcriptionGesture,openAttempt]);
 useEffect(()=>{onBusy?.(busy);return()=>onBusy?.(false);},[busy,onBusy]);
 useEffect(()=>{onDirty?.(dirty);return()=>onDirty?.(false);},[dirty,onDirty]);
 useEffect(()=>{
  if(!onPrepareNavigation)return;const selected=owner.current;
  const prepare=()=>flushPrivateEdits(selected);const registration={prepare,callback:onPrepareNavigation};navigationRegistration.current=registration;onPrepareNavigation(prepare);
  return()=>{if(navigationRegistration.current===registration){navigationRegistration.current=null;registration.callback(null);}};
 },[onPrepareNavigation,identity,scope,recording,revision,openAttempt]);
 async function transcribe(){const selected=owner.current;if(!allowTranscription||locked||!selected?.controller||!ready||busyRef.current||!current(selected))return;workingBusy(true);setError('');setMessage('');
  try{const result=await selected.controller.transcribe();if(current(selected)){valueRef.current=result;workingRef.current=result.working;setValue(result);setWorking(result.working);setMessage('Private transcript saved on this iPhone. Review and edit the words below.');}}
  catch(cause){if(current(selected))setError(privateTranscriptionMessage(cause));}finally{if(current(selected))workingBusy(false);}
 }
 async function flushPrivateEdits(selected:Owner|null){
  const unavailable=()=>Object.assign(new Error('Private transcript unavailable'),{code:'private_speech_changed'});
  if(!bound(selected)||!live.current.isCurrent()||busyRef.current)throw unavailable();
  if(!unsettledSave.current&&(!valueRef.current?.raw||workingRef.current===valueRef.current.working))return;
  if(!current(selected)||loadedOwner.current!==selected||!selected?.controller||live.current.locked||busyRef.current)throw unavailable();
  workingBusy(true);setError('');
  const immutable=(v:PrivateTranscript)=>JSON.stringify([v.contract,v.scope,v.recordingId,v.workspaceId,v.source.audioSHA256,v.source.chunks,v.source.frames,v.language,v.intent,v.state,v.raw?.text,v.raw?.engine,v.raw?.completedAt,v.createdAt]);
  try{
   const pending=unsettledSave.current;
   if(pending){
    if(pending.owner!==selected)throw unavailable();
    const retained=await selected.controller.load();if(!current(selected)||loadedOwner.current!==selected||!retained)throw unavailable();
    const sameBase=immutable(retained)===immutable(pending.prior);
    const prior=sameBase&&retained.revision===pending.prior.revision&&retained.working===pending.prior.working&&retained.updatedAt===pending.prior.updatedAt;
    const confirmed=sameBase&&retained.revision===pending.prior.revision+1&&retained.working===pending.words;
    if(!prior&&!confirmed)throw unavailable();
    unsettledSave.current=null;
    if(confirmed){valueRef.current=retained;setValue(retained);}
   }
   const prior=valueRef.current!,words=workingRef.current;
   if(words===prior.working){releaseOwnUnsaved();workingBusy(false);return;}
   unsettledSave.current={owner:selected,prior,words};
   const saved=await selected.controller.saveWorking(words);
   if(!current(selected)||loadedOwner.current!==selected||workingRef.current!==words||!saved)throw unavailable();
   unsettledSave.current=null;valueRef.current=saved;
   setValue(saved);setMessage('Private transcript edits saved on this iPhone.');releaseOwnUnsaved();workingBusy(false);
  }catch(cause){if(current(selected))setError(privateTranscriptionMessage(cause));throw cause;}
  finally{if(current(selected))workingBusy(false);}
 }
 async function save(){try{await flushPrivateEdits(owner.current);}catch{/* The editor retains its words and shows only the safe failure above. */}
 }
 if(!current()||!allowTranscription&&!displayed?.raw&&!error&&!busy)return null;
 return <section aria-label="Private on-device transcript" className="private-recording-transcript">
  <h2>Private transcript</h2><p>{savedScribeSource?'Make a private transcript from the original audio on this iPhone. This does not resend the recording or replace your Scribe transcript.':'Transcribe on this iPhone. Your recording and words stay private on this device; no patient or visit is required.'}</p>
  {!ready&&!error&&<p role="status">{opening?'Opening private transcript…':'Private transcript has not been opened. Choose Retry opening to check it.'}</p>}
  {!ready&&!opening&&<button disabled={locked||busy||!current()} onClick={()=>setOpenAttempt(attempt=>attempt+1)}>Retry opening private transcript</button>}
  {allowTranscription&&!displayed?.raw&&<><button className="team-primary" disabled={locked||!ready||busy||!current()} onClick={()=>void transcribe()}>{busy?'Transcribing on this iPhone…':error||displayed?.state==='running'||displayed?.state==='interrupted'?'Transcribe again on this iPhone':'Transcribe on this iPhone'}</button><p>iOS may ask for speech recognition access when you choose Transcribe. English recordings up to ten minutes; on-device recognition must be available.</p></>}
  {busy&&<p role="status">{displayed?.raw?'Saving private transcript edits on this iPhone…':`${progress.total?`${progress.chunks} of ${progress.total} saved audio parts prepared. `:''}Recognizing the continuous recording on this iPhone. Keep CosmaBot open.`}</p>}
  {displayed?.raw&&<><label>Private transcript<textarea aria-label="Editable private transcript" value={displayedWorking} maxLength={32000} disabled={locked||busy||!current()} onChange={event=>{workingRef.current=event.target.value;setWorking(event.target.value);setMessage('');}}/></label><button disabled={locked||!dirty||busy||!current()} onClick={()=>void save()}>Save transcript edits</button>
   <details><summary>Original on-device transcript</summary><pre style={{whiteSpace:'pre-wrap'}}>{displayed.raw.text}</pre><p>Original machine wording is retained separately from your edits and encrypted audio.</p></details></>}
  {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
 </section>;
}
