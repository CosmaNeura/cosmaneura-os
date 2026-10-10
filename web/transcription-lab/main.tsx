import {useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {SavedRecordingTranscriptionPanel,type SavedRecordingEntry} from '../src/SavedRecordingTranscriptionPanel';
import {RecordingVisitPanel} from '../src/RecordingVisitPanel';
import {PrivateRecordingRuntime,openPrivateRecordingStore} from '../src/private-recording-runtime';
import {PrivateRecordingLedgerController} from '../src/private-recording-ledger';
import {privateRecordingApi,type PrivateRecordingReceipt,type PrivateRecordingIntent,type RecordingVisitBinding} from '../src/private-recording-api';
import {workspaceApi,type Workspace,type ProviderTeam} from '../src/workspace-api';
import {EditorRecoveryContext,type EditorRecoveryAccess} from '../src/editor-recovery';
import {DraftJournal} from '../src/draft-journal';
import {memoryDraftStorage} from '../src/draft-test-fixture';
import {vendorCanonical,vendorSha256} from '../src/vendor-contract';
import {encodePcm16MonoWav} from '../../clients/capture/src/capture/wav';
import type {CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import {id,sessionId,resetServices} from './services';
import '../src/encounter-workspace.css';
import '../src/practice-home.css';

const identity={mode:'clerk_jwt' as const,getToken:async()=> 'synthetic-walkthrough-token'},scope='e'.repeat(64);
let receipt:PrivateRecordingReceipt,originalIntent:PrivateRecordingIntent,visitBinding:RecordingVisitBinding|null=null;
let workspace:Workspace={id:id(1),appointment_id:null,label:'Private synthetic recording',revision:1,entries:[],work_candidates:[],private_draft:{title:'Provider walkthrough',state:'unlinked',link_receipt_id:null,linked_at:null}};
let team:ProviderTeam;
const ready=(async()=>{
  const recoveryScope=await vendorSha256(new TextEncoder().encode(vendorCanonical({contract:'cosmas-private-drafts-v1',box_id:id(10),owner_id:id(11)})));
  team={revision:1,recovery_scope:recoveryScope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},capture:{enabled:true,notes_enabled:true},configuration:{practice_context:'Invented practice',bots:[{role:'scribe',name:'Scribe',enabled:true,response_style:'brief',include_notebook:true,include_evidence:true}]},members:[{role:'scribe',agent_id:id(12),name:'Scribe',initials:'S',description:'Scribe',prompt:'',capabilities:[]}]};
  Object.assign(privateRecordingApi,{attach:async(_identity:unknown,v:PrivateRecordingIntent)=>{originalIntent=v;receipt={contract:'cosmas.private-recording.v1',custody:'local_device_metadata',recording_id:id(3),local_recording_id:v.request.local_recording_id,workspace_id:workspace.id,workspace_revision:1,owner_id:id(11),box_id:id(10),agent_id:id(12),team_revision_id:id(13),recovery_scope:recoveryScope,attach_sha256:v.request_sha256,started_at:v.request.started_at,created_at:new Date().toISOString(),state:'unfinished',finish:null,link:null,upstream_capture_admitted:false,audio_uploaded:false,transcription_started:false};return receipt;},
    finish:async(_i:unknown,_v:unknown,_t:unknown,_r:unknown,f:{request_sha256:string;request:{manifest_sha256:string;chunks:number;frames:number;ended_at:string}})=>{const {manifest_sha256,chunks,frames,ended_at}=f.request;receipt={...receipt,state:'finished',finish:{receipt_id:id(4),request_sha256:f.request_sha256,manifest_sha256,chunks,frames,ended_at}};return receipt;},
    read:async()=>receipt,link:async(_i:unknown,_v:unknown,_t:unknown,_r:unknown,body:{workspace_link_receipt_id:string})=>{receipt={...receipt,state:'linked_metadata',link:{receipt_id:id(5),workspace_link_receipt_id:body.workspace_link_receipt_id,source_sha256:'a'.repeat(64),request_sha256:'b'.repeat(64)}};return receipt;}});
  const target:Workspace={id:id(50),appointment_id:id(30),label:'Jordan Cypress · Oct 9 · synthetic visit',revision:4,entries:[],work_candidates:[]};
  const sha=(v:unknown)=>vendorSha256(new TextEncoder().encode(vendorCanonical(v)));
  Object.assign(privateRecordingApi,{readVisitBinding:async()=>visitBinding,bindVisit:async(_i:unknown,_v:unknown,_t:unknown,_r:unknown,request:RecordingVisitBinding['request'])=>{
    const request_sha256=await sha({contract:'cosmas.private-recording.visit-binding.v1',request});
    visitBinding={contract:'cosmas.private-recording.visit-binding.v1',receipt_id:id(51),recording_id:receipt.recording_id,origin_workspace_id:workspace.id,target_workspace_id:target.id,appointment_id:target.appointment_id!,request,request_sha256,appointment_sha256:'a'.repeat(64),source_sha256:await sha({contract:'cosmas.private-recording.visit-source.v1',recording_id:receipt.recording_id,origin_workspace_id:workspace.id,attach_sha256:receipt.attach_sha256,finish_sha256:receipt.finish!.request_sha256,manifest_sha256:receipt.finish!.manifest_sha256,target_workspace_id:target.id,appointment_sha256:'a'.repeat(64),binding_request_sha256:request_sha256})};return visitBinding;}});
  Object.assign(workspaceApi,{catalog:async()=>[{appointment_id:id(30),workspace_id:target.id,label:target.label}],open:async()=>({identity,workspace:target,team}),openExisting:async()=>({identity,workspace:target,team})});
  const actualFetch=window.fetch.bind(window);
  window.fetch=async(input,init)=>String(input).includes('/capture/admission')?new Response(JSON.stringify({status:'prepared',workspace_id:id(50),session_id:sessionId,consent_record_id:id(23),configured_capture:{schema_version:'1.0',language_mode:'en-US'}}),{headers:{'content-type':'application/json','cache-control':'no-store'}}):actualFetch(input,init);
})();
const storage=memoryDraftStorage();
function Lab(){
  const [entry,setEntry]=useState<SavedRecordingEntry|null>(null),[screen,setScreen]=useState<'home'|'recording'|'transcription'>('home'),[currentWorkspace,setWorkspace]=useState(workspace),[access,setAccess]=useState<EditorRecoveryAccess|null>(null),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[phone,setPhone]=useState(false);
  useEffect(()=>{void ready.then(async()=>{const journal=new DraftJournal(await storage({scope}));setAccess({journal,workspaceId:workspace.id,authorize:async()=>workspace,denied:()=>{}});});},[]);
  async function record(){setBusy(true);resetServices();visitBinding=null;
    try{await ready;let source:CaptureSourceStartOptions|null=null;
      const consent={modality:'in_person' as const,participant_regions:['US-NY'],method:'verbal_attestation' as const,all_parties_consented:true as const,granted_at:new Date().toISOString(),language:'en-US' as const};
      const runtime=await PrivateRecordingRuntime.open({scope,platform:'desktop',isCurrent:()=>true,acquireLock:async()=>async()=>{},createSource:async()=>({kind:'microphone',start:async o=>{source=o;},stop:async()=>{}})}, {title:'Synthetic provider recording',consent});
      await runtime.start(consent);
      for(let i=0;i<2;i++){const bytes=encodePcm16MonoWav(new Int16Array(Array(16000*(i?9:10)).fill(1234)),{sampleRateHz:16000,channels:1,targetChunkDurationMs:10000,maxEnvelopeBytes:320044});await source!.onChunk({sequenceNumber:i,durationMs:i?9000:10000,wavBytes:bytes});}
      await runtime.stop();
      if(workspace.appointment_id){workspace={...workspace,appointment_id:null,label:'Private synthetic recording',revision:1,private_draft:{title:'Provider walkthrough',state:'unlinked',link_receipt_id:null,linked_at:null}};}
      await runtime.attachWorkspace(workspace.id,true);
      const store=await openPrivateRecordingStore(scope,'desktop'),ledger=new PrivateRecordingLedgerController({identity,team,workspace,store,scope,isCurrent:()=>true});
      await ledger.attach(await runtime.snapshotForLedger());await ledger.finish(await runtime.snapshotForLedger());store.close();
      setEntry({recordingId:runtime.snapshot.recordingId,scope,platform:'desktop',originWorkspace:workspace});await runtime.close();setWorkspace(workspace);setScreen('recording');setMessage('19-second recording saved.');
    }catch(cause){setMessage(String(cause));}finally{setBusy(false);}}
  return <><aside style={{padding:12,background:'#fff3cc'}}>Scripted service walkthrough. Production recording storage, visit controls, transcription screen and note editor; synthetic audio and service replies. No live speech recognition or patient data.<label><input type="checkbox" checked={phone} onChange={e=>setPhone(e.target.checked)}/> Phone width</label></aside>
    <main className="team-workspace" style={{display:'block',maxWidth:phone?390:850,margin:'20px auto',padding:16}}>
      <button className="private-recording-close" onClick={()=>setScreen('home')}>Home</button>
      {screen==='home'&&<><h1>Home</h1><button className="team-primary" disabled={busy||!access} onClick={()=>void record()}>Record synthetic visit</button><h2>Recordings on this device</h2>{entry&&<button onClick={()=>setScreen('recording')}>Synthetic provider recording · 0:19 · Open recording</button>}</>}
      {screen==='recording'&&entry&&<><h1>Saved recording</h1><p>0:19 · 2 saved audio chunks</p><button className="team-primary" onClick={()=>setScreen('transcription')}>Transcribe recording</button><button className="private-recording-close" onClick={()=>setScreen('home')}>Close recording</button></>}
      {screen==='transcription'&&entry&&access&&<EditorRecoveryContext.Provider value={access}>
        {entry.binding?<SavedRecordingTranscriptionPanel entry={entry} identity={identity} workspace={currentWorkspace} team={team} isCurrent={()=>true} locked={false} notesEnabled onDraftLock={()=>{}} onReviewDraft={()=>setMessage('Saved draft selected for clinical review.')} onCurrentDraft={()=>{}} notebookDirty={false} onNotebook={()=>{}} taskBot={{selection:{address:'scribe',team_revision:1},name:'Scribe',enabled:true,includeNotebook:true}}/>
          :<RecordingVisitPanel entry={entry} identity={identity} origin={entry.originWorkspace!} team={team} locked={false} isCurrent={()=>true} onSelected={async(target,binding)=>{setWorkspace(target);setAccess({...access!,workspaceId:target.id,authorize:async()=>target});setEntry({...entry,binding:binding!});}}/>}
      </EditorRecoveryContext.Provider>}
      <p role="status">{message}</p>
    </main></>;
}
void originalIntent;
createRoot(document.getElementById('root')!).render(<Lab/>);
