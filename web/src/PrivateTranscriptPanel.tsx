import {useEffect,useRef,useState} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {openPrivateRecordingStore} from './private-recording-runtime';
import {PrivateTranscriptionController,type PrivateTranscript,type PrivateTranscriptAudio} from './private-transcription';
import {privateSpeechNative,privateTranscriptionMessage} from './private-transcription-native';
import {useUnsavedWork} from './unsaved-work';
export type PrivateTranscriptGesture={identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;claim:()=>boolean};
/** Private machine text is a device source, never a clinician note or shared draft. */
export function PrivateTranscriptPanel({identity,scope,recording,isCurrent,onBusy,transcriptionGesture,savedScribeSource=false}:{identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;isCurrent:()=>boolean;onBusy?:(busy:boolean)=>void;transcriptionGesture?:PrivateTranscriptGesture;savedScribeSource?:boolean}){
 const [value,setValue]=useState<PrivateTranscript|null>(null),[working,setWorking]=useState(''),[ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[progress,setProgress]=useState({chunks:0,total:0});
 const owner=useRef<{alive:boolean;controller:PrivateTranscriptionController|null}|null>(null),live=useRef({identity,scope,recording,isCurrent});live.current={identity,scope,recording,isCurrent};
 const revision=identity.mode==='clerk_jwt'?identity.nativeSession?.revision:undefined;
 const intent=useRef<{gesture:PrivateTranscriptGesture;identity:AuthenticatedWorkspaceIdentity;scope:string;recording:PrivateTranscriptAudio;revision:string|undefined;claimed:boolean;started:boolean}|null>(null);
 const dirty=!!value?.raw&&working!==value.working;useUnsavedWork(dirty);
 useEffect(()=>{const selected={alive:true,controller:null as PrivateTranscriptionController|null};owner.current=selected;
  let selectedIntent=intent.current;
  if(!transcriptionGesture){intent.current=null;selectedIntent=null;}
  else if(!selectedIntent||selectedIntent.gesture!==transcriptionGesture||selectedIntent.identity!==identity||selectedIntent.scope!==scope||selectedIntent.recording!==recording||selectedIntent.revision!==revision){
   selectedIntent={gesture:transcriptionGesture,identity,scope,recording,revision,claimed:transcriptionGesture.identity===identity&&transcriptionGesture.scope===scope&&transcriptionGesture.recording===recording&&transcriptionGesture.claim(),started:false};intent.current=selectedIntent;
  }
  const explicit=!!selectedIntent?.claimed&&!selectedIntent.started;
  const current=()=>selected.alive&&owner.current===selected&&live.current.identity===identity&&live.current.scope===scope&&live.current.recording===recording&&identity.mode==='clerk_jwt'&&identity.nativeSession?.isCurrent()===true&&live.current.isCurrent();
  setValue(null);setWorking('');setReady(false);setBusy(false);setError('');setMessage('');setProgress({chunks:0,total:0});
  void(async()=>{if(!revision)throw Object.assign(new Error('Native session unavailable'),{code:'private_speech_changed'});const store=await openPrivateRecordingStore(scope,'ios');if(!current()){store.close();return;}
   const controller=new PrivateTranscriptionController({scope,revision,recording,store,native:privateSpeechNative,isCurrent:current,onProgress:(chunks,total)=>{if(current())setProgress({chunks,total});}});selected.controller=controller;
   const saved=await controller.load();if(!current())return;setValue(saved);setWorking(saved?.working??'');setReady(true);
   if(explicit&&!saved?.raw&&selectedIntent&&intent.current===selectedIntent&&!selectedIntent.started){selectedIntent.started=true;setBusy(true);try{const result=await controller.transcribe();if(current()){setValue(result);setWorking(result.working);setMessage('Private transcript saved on this iPhone. Review and edit the words below.');}}finally{if(current())setBusy(false);}}
  })().catch(cause=>{if(current())setError(privateTranscriptionMessage(cause));});
  return()=>{selected.alive=false;void selected.controller?.close();};
 },[identity,scope,recording,revision,transcriptionGesture]);
 useEffect(()=>{onBusy?.(busy);return()=>onBusy?.(false);},[busy,onBusy]);
 const current=(selected=owner.current)=>!!selected?.alive&&owner.current===selected&&live.current.identity===identity&&live.current.scope===scope&&live.current.recording===recording&&identity.mode==='clerk_jwt'&&identity.nativeSession?.isCurrent()===true&&live.current.isCurrent();
 async function transcribe(){const selected=owner.current;if(!selected?.controller||!ready||busy||!current(selected))return;setBusy(true);setError('');setMessage('');
  try{const result=await selected.controller.transcribe();if(current(selected)){setValue(result);setWorking(result.working);setMessage('Private transcript saved on this iPhone. Review and edit the words below.');}}
  catch(cause){if(current(selected))setError(privateTranscriptionMessage(cause));}finally{if(current(selected))setBusy(false);}
 }
 async function save(){const selected=owner.current;if(!selected?.controller||busy||!dirty||!current(selected))return;setBusy(true);setError('');
  try{const saved=await selected.controller.saveWorking(working);if(current(selected)){setValue(saved);setMessage('Private transcript edits saved on this iPhone.');}}
  catch(cause){if(current(selected))setError(privateTranscriptionMessage(cause));}finally{if(current(selected))setBusy(false);}
 }
 return <section aria-label="Private on-device transcript" className="private-recording-transcript">
  <h2>Private transcript</h2><p>{savedScribeSource?'Make a private transcript from the original audio on this iPhone. This does not resend the recording or replace your Scribe transcript.':'Transcribe on this iPhone. Your recording and words stay private on this device; no patient or visit is required.'}</p>
  {!value?.raw&&<><button className="team-primary" disabled={!ready||busy||!current()} onClick={()=>void transcribe()}>{busy?'Transcribing on this iPhone…':error||value?.state==='running'||value?.state==='interrupted'?'Transcribe again':'Transcribe recording'}</button><p>iOS may ask for speech recognition access when you choose Transcribe. English recordings up to ten minutes; on-device recognition must be available.</p></>}
  {busy&&<p role="status">{progress.total?`${progress.chunks} of ${progress.total} saved audio parts prepared. `:''}Recognizing the continuous recording on this iPhone. Keep CosmaBot open.</p>}
  {value?.raw&&<><label>Private transcript<textarea aria-label="Editable private transcript" value={working} maxLength={32000} disabled={busy||!current()} onChange={event=>{setWorking(event.target.value);setMessage('');}}/></label><button disabled={!dirty||busy||!current()} onClick={()=>void save()}>Save transcript edits</button>
   <details><summary>Original on-device transcript</summary><pre style={{whiteSpace:'pre-wrap'}}>{value.raw.text}</pre><p>Original machine wording is retained separately from your edits and encrypted audio.</p></details></>}
  {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
 </section>;
}
