import {connectDesktopRecorderView,type DesktopRecorderPort} from '../../clients/capture/src/configured/provider/desktop-recorder-view';
import type {CaptureRuntime} from './capture-runtime';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

interface DesktopCapturePort extends DesktopRecorderPort {
  readonly enabled:boolean;
  open(value:{requestId:string;workspaceId:string;sessionId:string;revision:string}):Promise<unknown>;
}
declare global {interface Window {cosmasDesktopCapture?:DesktopCapturePort}}
export function desktopMeetingCaptureAvailable(identity:AuthenticatedWorkspaceIdentity):boolean{
  return identity.mode==='desktop_native'&&identity.isCurrent()&&window.cosmasDesktopCapture?.enabled===true;
}
export async function openDesktopCaptureRuntime(workspaceId:string,sessionId:string,identity:AuthenticatedWorkspaceIdentity,
  release:()=>Promise<void>):Promise<CaptureRuntime>{
  if(identity.mode!=='desktop_native'||!desktopMeetingCaptureAvailable(identity))throw unavailable();
  const port=window.cosmasDesktopCapture!,requestId=crypto.randomUUID(),abort=new AbortController();
  const raw=await port.open({requestId,workspaceId,sessionId,revision:identity.revision});
  if(!raw||typeof raw!=='object'||Array.isArray(raw))throw unavailable();
  const value=raw as Record<string,unknown>;
  if(Object.keys(value).sort().join(',')!==(value.reviewOnly===true?'requestId,reviewOnly,sessionId,workspaceId':'requestId,sessionId,workspaceId')||
    value.requestId!==requestId||value.sessionId!==sessionId||value.workspaceId!==workspaceId)throw unavailable();
  if(value.reviewOnly===true){
    if(!identity.isCurrent())throw unavailable();
    const snapshot={state:'processing' as const,statusCode:'capture_processing',sessionId,recordedChunks:0,queuedChunks:0,
      elapsedSeconds:0,remainingAuthoritySeconds:null,remainingBudgetSeconds:null,transcriptionStatus:null,transcript:null};
    return {sourceKind:'microphone',captureMode:'desktop_meeting',releaseUploadedCapture:async()=>{},close:release,
      controller:{snapshot,subscribe:listener=>{listener(snapshot);return()=>{};},startRecording:async()=>{throw unavailable();},
        stopRecording:async()=>{throw unavailable();},acknowledgeGap:async()=>{throw unavailable();},finishInterruptedCapture:async()=>{throw unavailable();},
        resumePendingWork:async()=>{},refreshTranscriptionStatus:async()=>{}}};
  }
  const recorder=await connectDesktopRecorderView(port,sessionId,abort.signal);
  if(!identity.isCurrent()){await recorder.deactivate();throw unavailable();}
  const check=()=>{if(!identity.isCurrent())throw unavailable();};
  return {sourceKind:'microphone',captureMode:'desktop_meeting',supportsContinuation:true,
    releaseUploadedCapture:()=>recorder.releaseUploadedCapture(),close:async()=>{await recorder.deactivate();abort.abort();await release();},
    controller:{get snapshot(){return recorder.controller.snapshot;},subscribe:listener=>recorder.controller.subscribe(listener),
      startRecording:async()=>{check();await recorder.controller.startRecording();},pauseRecording:()=>recorder.controller.pauseRecording!(),
      stopRecording:()=>recorder.controller.stopRecording(),acknowledgeGap:async()=>{check();await recorder.controller.resumeRecording!();},
      finishInterruptedCapture:()=>recorder.controller.stopRecording(),resumePendingWork:()=>recorder.resumePendingWork(),
      refreshTranscriptionStatus:()=>recorder.controller.refreshTranscriptionStatus(),refreshPermissions:()=>recorder.controller.refreshPermissions!()}};
}
function unavailable():Error{return Object.assign(new Error('Desktop recording unavailable'),{code:'capture_source_unavailable'});}
