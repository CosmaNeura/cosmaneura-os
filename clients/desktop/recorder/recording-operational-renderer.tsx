import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { CapturePanel } from '../../../web/src/CapturePanel';
import { openDesktopCaptureRuntime } from '../../../web/src/desktop-capture-runtime';
import {workspaceAuthHeaders} from '../../../web/src/workspace-auth-headers';

type Bridge = {
  workspaceId: string; sessionId: string; revision: string; round: number;
  open(value: unknown): Promise<unknown>; request(value: unknown): Promise<unknown>;
  subscribe(listener: (value: unknown) => void): () => void;
  fetch(input: unknown, init?: RequestInit): Promise<Response>;
  emit(frames: number): Promise<void>; reopen(): Promise<void>;
  capture(label: string, value: unknown): void;
};
declare global { interface Window { __recordingLab: Bridge; runRecordingScenario(): Promise<unknown> } }
const bridge = window.__recordingLab;
Object.assign(window, { IS_REACT_ACT_ENVIRONMENT: true });
window.cosmasDesktopCapture = {enabled: true, open: bridge.open, request: bridge.request, subscribe: bridge.subscribe};
window.fetch = bridge.fetch as typeof fetch;
const identity = {mode: 'desktop_native' as const, revision: bridge.revision, isCurrent: () => true};
const container = document.createElement('div'); document.body.append(container);
const root = createRoot(container);
const steps: unknown[] = [];
function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll('button')].find(value => value.textContent === label);
  if (!found || found.disabled) throw new Error('Provider cannot use '+label);
  return found;
}
async function waitFor(check: () => boolean): Promise<void> {
  const limit = performance.now()+8000;
  while (!check()) {
    if (performance.now()>limit) throw new Error('Recording UI did not reach expected state: '+container.textContent);
    await act(async () => {await new Promise(resolve=>setTimeout(resolve,10));});
  }
}
async function click(label: string, expected: () => boolean): Promise<void> {
  await waitFor(()=>[...container.querySelectorAll('button')].some(value=>value.textContent===label&&!value.disabled));
  const start=performance.now(); await act(async()=>{button(label).click();}); await waitFor(expected);
  const step={action:label,confirmed_ms:Math.round((performance.now()-start)*100)/100,
    status:container.querySelector('[role="status"]')?.textContent,visible_controls:[...container.querySelectorAll('button')].map(b=>b.textContent)};
  steps.push(step); bridge.capture('ui_step',step);
}
const status=()=>container.querySelector('[role="status"]')?.textContent;
const factory = (workspace: string, session: string) => openDesktopCaptureRuntime(workspace,session,identity,async()=>{});
const render = async () => {await act(async()=>root.render(<CapturePanel workspaceId={bridge.workspaceId} identity={identity}
  runtimeFactory={factory} encounterLabel="Invented walk-in visit · date of birth unavailable"/>));};
window.runRecordingScenario = async () => {
  await workspaceAuthHeaders(identity,'app://cosmas/api');
  await render();
  await click('Record visit',()=>!!container.querySelector('[aria-label="Recording consent"]'));
  if (container.querySelector('input[type="date"]')) throw new Error('Recording unexpectedly requires date of birth');
  const region=container.querySelector<HTMLInputElement>('input')!;
  await act(async()=>{
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(region,'US-NY');
    region.dispatchEvent(new Event('input',{bubbles:true}));
    const source=container.querySelector<HTMLSelectElement>('[aria-label="Recording source"]')!;
    source.value='desktop_meeting';source.dispatchEvent(new Event('change',{bubbles:true}));
  });
  bridge.capture('dob_optional',{date_input_present:false,patient_name:'Invented walk-in',dob:null});
  await click('Confirm consent & record',()=>status()==='Recording');
  await act(async()=>{await bridge.emit(160000);});
  await click('Pause recording',()=>status()==='Recording paused');
  await click('Prepare to resume',()=>status()==='Ready to start');
  await click('Start recording',()=>status()==='Recording');
  await act(async()=>{await bridge.emit(176000);});
  if(bridge.round===2){
    await click('Stop and upload',()=>status()==='Audio uploaded');
    bridge.capture('ui_complete',{status:status(),plaintext_in_ui:container.textContent?.includes('PCM')??false});
    await act(async()=>root.unmount());container.remove();
    return {steps,final_status:'Audio uploaded',dob_required:false};
  }
  await click('Pause recording',()=>status()==='Recording paused');
  await act(async()=>root.unmount()); await bridge.reopen(); container.replaceChildren();
  const recoveredRoot=createRoot(container);
  await act(async()=>recoveredRoot.render(<CapturePanel workspaceId={bridge.workspaceId} identity={identity}
    runtimeFactory={factory} encounterLabel="Invented visit · recovered saved recording"/>));
  await click('Record visit',()=>status()==='Recording paused');
  await click('Finish this recording',()=>status()==='Audio uploaded');
  bridge.capture('ui_complete',{status:status(),plaintext_in_ui:container.textContent?.includes('PCM')??false});
  await act(async()=>recoveredRoot.unmount());container.remove();
  return {steps,final_status:'Audio uploaded',dob_required:false};
};
