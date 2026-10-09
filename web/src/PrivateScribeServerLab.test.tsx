import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,expect,it,vi} from 'vitest';
import {WorkspaceCompatibilityGate} from './WorkspaceCompatibilityGate';
import {PracticeAccessGate} from './PracticeAccessGate';
import {PrivateRecordingRuntime} from './private-recording-runtime';
import type {PrivateRecordingReceipt} from './private-recording-api';
import {BrowserMicrophoneCaptureSource} from '../../clients/capture/src/audio/browser-microphone-source';
import {EncounterWorkspace} from './EncounterWorkspace';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
// The OS worklet producer is generated here; the production source/decoder stays real.
vi.mock('../../clients/capture/src/audio/pcm-capture-worklet.ts?worker&url',()=>({default:'https://generated-hardware.invalid/worklet.js'}));
const environment=(globalThis as typeof globalThis&{process?:{env:Record<string,string|undefined>}}).process?.env;
const base=environment?.COSMAS_PRIVATE_SCRIBE_LAB_URL,realFetch=globalThis.fetch.bind(globalThis);
let root:Root|undefined;
let priorLocks:PropertyDescriptor|undefined;
const runtimes:PrivateRecordingRuntime[]=[];
afterEach(async()=>{if(root)await act(async()=>root!.unmount());root=undefined;for(const runtime of runtimes)await runtime.close().catch(()=>{});runtimes.length=0;if(priorLocks)Object.defineProperty(navigator,'locks',priorLocks);else Reflect.deleteProperty(navigator,'locks');document.body.replaceChildren();vi.restoreAllMocks();vi.unstubAllGlobals();vi.unstubAllEnvs();});
it.skipIf(!base)('starts actual browser capture before a slow signed notebook create and reopens verified encrypted audio',async()=>{
  const util='node:util';const {transferableAbortController}=await import(/* @vite-ignore */util) as {transferableAbortController:()=>AbortController};
  const abort=transferableAbortController();vi.stubGlobal('AbortController',abort.constructor);vi.stubGlobal('AbortSignal',abort.signal.constructor);
  const cryptoModule='node:crypto';const {webcrypto}=await import(/* @vite-ignore */cryptoModule) as {webcrypto:Crypto};vi.stubGlobal('crypto',webcrypto);
  vi.stubGlobal('indexedDB',new IDBFactory());
  // Browser lock API seam only: the production acquireCaptureFlowLock holds this callback until Stop.
  let captureLockHeld=false,lockAcquisitions=0;
  priorLocks=Object.getOwnPropertyDescriptor(navigator,'locks');
  Object.defineProperty(navigator,'locks',{configurable:true,value:{request:async(_name:string,_options:LockOptions,callback:LockGrantedCallback<unknown>)=>{
    if(captureLockHeld)return callback(null);captureLockHeld=true;lockAcquisitions++;
    try{return await callback({name:'cosmaneura-capture-active-flow-v1',mode:'exclusive'} as Lock);}finally{captureLockHeld=false;}
  }}});
  // Match the binary-object realm used by fake-indexeddb and Node WebCrypto.
  vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);vi.stubGlobal('Float32Array',structuredClone(new Float32Array(0)).constructor);
  const bufferModule='node:buffer';const {Blob:NodeBlob}=await import(/* @vite-ignore */bufferModule) as {Blob:typeof Blob};vi.stubGlobal('Blob',NodeBlob);
  const playbacks:Blob[]=[];vi.stubGlobal('URL',Object.assign(URL,{createObjectURL:(blob:Blob)=>{playbacks.push(blob);return 'blob:generated-private-recording';},revokeObjectURL:()=>{}}));
  const logical='https://api.example.invalid';
  const originalWindow=window;vi.stubGlobal('window',new Proxy(originalWindow,{get(target,key){return key==='location'?new URL('https://workspace.example.invalid/'):Reflect.get(target,key);}}));
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_API_BASE',logical);vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','true');
  for(const [key,value] of Object.entries({VITE_COSMAS_ENV:'early_adopter_beta',VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_CLIENT:'web',VITE_WORKSPACE_HOSTED_API_ORIGIN:logical,VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',VITE_WORKSPACE_DESKTOP_AUTH_ENABLED:'false',VITE_WORKSPACE_NATIVE_AUTH_ENABLED:'false',VITE_DESKTOP_SYNTHETIC_ENABLED:'false',VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED:'false',VITE_WORKSPACE_CAPTURE_ENABLED:'true'}))vi.stubEnv(key,value);
  const calls:{method:string;path:string;status:number;completed_at_ms:number}[]=[];
  const metadataReceipts:PrivateRecordingReceipt[]=[];
  vi.stubGlobal('fetch',async(input:RequestInfo|URL,init?:RequestInit)=>{const url=typeof input==='string'?input:input instanceof URL?input.href:input.url;
    if(!url.startsWith(logical+'/')&&url!==base+'/lab/identity')throw new Error('Unexpected external request');const target=url.startsWith(logical+'/')?base+url.slice(logical.length):url;const response=await realFetch(target,init);calls.push({method:init?.method??'GET',path:new URL(url).pathname,status:response.status,completed_at_ms:performance.now()});
    const bytes=await response.arrayBuffer();
    if(response.ok&&/\/private-recordings(?:\/[^/]+\/finish)?$/.test(new URL(url).pathname))metadataReceipts.push(JSON.parse(new TextDecoder().decode(bytes)) as PrivateRecordingReceipt);
    return new Response(bytes,{status:response.status,headers:response.headers});});
  const packet=await(await fetch(base+'/lab/identity')).json() as {token:string};
  const identity={mode:'clerk_jwt' as const,getToken:async()=>packet.token};
  const container=document.createElement('div');document.body.append(container);root=createRoot(container);
  const render=()=>root!.render(<WorkspaceCompatibilityGate identity={identity} accountControls={null}><PracticeAccessGate identity={identity} accountControls={null}>{access=><EncounterWorkspace authenticated={identity} practiceAccess={access}/>}</PracticeAccessGate></WorkspaceCompatibilityGate>);
  async function wait(check:()=>void){const end=performance.now()+15000;while(performance.now()<end){let passed=false;await act(async()=>{await new Promise(resolve=>setTimeout(resolve,10));try{check();passed=true;}catch{}});if(passed)return;}check();}
  const visible=(element:Element)=>!element.closest('[hidden]');
  const button=(label:string)=>[...container.querySelectorAll<HTMLButtonElement>('button')].find(b=>visible(b)&&b.textContent?.trim()===label)!;
  async function click(label:string){await wait(()=>{expect(button(label),`${label}: ${container.textContent}`).toBeTruthy();expect(button(label).disabled,label).toBe(false);});await act(async()=>button(label).click());}
  async function input(label:string,value:string){const parent=[...container.querySelectorAll('label')].find(el=>visible(el)&&el.textContent?.startsWith(label))!,field=parent.querySelector<HTMLInputElement>('input')!;
    await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(field,value);field.dispatchEvent(new Event('input',{bubbles:true}));});}
  const started=performance.now();await act(render);await click('Set up my practice');
  await input('Practice name','Invented solo Quick start');await input('Your name','Invented physician');await click('Continue to my workspace');
  await wait(()=>expect(container.querySelector('[aria-label="Practice Home"]'),container.textContent??'').toBeTruthy());
  expect(calls.some(call=>call.path==='/workspaces')).toBe(false);expect(button('Close notebook')).toBeUndefined();await click('Use this team');
  await wait(()=>expect(container.querySelector('.team-roster small')?.textContent).toBe('On'));
  const hardware=new GeneratedAudioHardware();
  const actualOpen=PrivateRecordingRuntime.open.bind(PrivateRecordingRuntime);
  vi.spyOn(PrivateRecordingRuntime,'open').mockImplementation(async(options,value)=>{
    const runtime=await actualOpen({...options,createSource:async()=>new BrowserMicrophoneCaptureSource({
      mediaDevices:{getUserMedia:async()=>{hardware.requestedAt=performance.now();return hardware.stream;}},
      createAudioContext:()=>hardware.context as unknown as AudioContext,
      createAudioWorkletNode:()=>hardware.worklet as unknown as AudioWorkletNode,
      workletModuleUrl:new URL('https://generated-hardware.invalid/worklet.js'),
      visibilityDocument:{visibilityState:'visible',addEventListener:()=>{},removeEventListener:()=>{}},
      pageLifecycleWindow:{addEventListener:()=>{},removeEventListener:()=>{}},
    })},value);runtimes.push(runtime);return runtime;
  });
  const scribe=[...container.querySelectorAll<HTMLButtonElement>('.team-roster button')].find(b=>b.textContent?.includes('Scribe'))!;
  await wait(()=>{expect(scribe,container.textContent??'').toBeTruthy();expect(scribe.disabled,container.textContent??'').toBe(false);});
  const readyAt=performance.now();
  const selectedAt=performance.now();await act(async()=>scribe.click());
  await wait(()=>expect(container.querySelector('[aria-label="Private Scribe recording"]'),container.textContent??'').toBeTruthy());
  expect(hardware.requestedAt).toBeNull();expect(button('Start recording').disabled).toBe(true);
  expect(container.textContent).not.toContain('Where everyone is located');
  const checkbox=container.querySelector<HTMLInputElement>('.private-recording-check input')!;
  const consentAt=performance.now();await act(async()=>checkbox.click());await click('Start recording');
  await wait(()=>expect(container.querySelector('.private-recording-status strong')?.textContent,container.textContent??'').toBe('Recording'));
  expect(container.querySelector<HTMLElement>('.team-sidebar')!.hidden).toBe(true);
  expect(container.querySelector<HTMLElement>('.team-topbar')!.hidden).toBe(true);
  expect(button('Close recording').disabled).toBe(true);
  const adapterStartedAt=hardware.startedAt!;
  expect(adapterStartedAt).toBeGreaterThan(consentAt);
  expect(calls.filter(call=>call.method==='POST'&&call.path==='/workspaces/private-drafts')).toHaveLength(0);
  const microphoneStartedBeforeCreateResponse=true;
  // Generated AudioWorklet PCM traverses the real decoder/resampler/chunker; no typed transcript.
  const frames=new Float32Array(1600).fill(0.5);hardware.worklet.emit(frames);
  await click('Stop and save recording');await wait(()=>expect(container.querySelector('.private-recording-status strong')?.textContent).toBe('Saved on this device'));
  expect(hardware.track.stopped).toBe(true);expect(hardware.context.state).toBe('closed');expect(frames.every(value=>value===0)).toBe(true);
  expect(captureLockHeld).toBe(false);expect(lockAcquisitions).toBe(1);
  await wait(()=>expect(runtimes[0].snapshot.workspaceId).not.toBeNull());
  await wait(()=>expect(metadataReceipts.some(receipt=>receipt.state==='finished'),container.textContent??'').toBe(true));
  const saved=runtimes[0].snapshot;expect(saved.recordedChunks).toBe(1);expect(saved.recordedBytes).toBe(3244);
  await click('Play saved recording');await wait(()=>expect(playbacks.length).toBe(1));
  const first=new Uint8Array(await playbacks[0].arrayBuffer());expect(new DataView(first.buffer).getInt16(44,true)).toBe(16384);
  const sha=async(bytes:Uint8Array<ArrayBuffer>)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),v=>v.toString(16).padStart(2,'0')).join('');
  const wavSha=await sha(first);const workspaceId=saved.workspaceId!;
  await click('Close recording');
  await wait(()=>expect(container.querySelector('.private-recording-panel')).toBeNull());
  expect(container.querySelector<HTMLElement>('.team-sidebar')!.hidden).toBe(false);
  expect(container.querySelector<HTMLElement>('.team-topbar')!.hidden).toBe(false);
  await wait(()=>expect(button('Home').disabled).toBe(false));
  await wait(()=>expect(container.querySelector('[aria-label="Saved private recordings"] .practice-home-note')).toBeTruthy());
  expect(visible(container.querySelector('[aria-label="Saved private recordings"]')!)).toBe(true);
  await act(async()=>root!.unmount());root=createRoot(container);await act(render);
  await wait(()=>expect(container.querySelector('[aria-label="Saved private recordings"] .practice-home-note'),container.textContent??'').toBeTruthy());
  await act(async()=>container.querySelector<HTMLButtonElement>('[aria-label="Saved private recordings"] .practice-home-note')!.click());
  await wait(()=>expect(container.querySelector('.private-recording-status strong')?.textContent,container.textContent??'').toBe('Saved on this device'));
  expect(hardware.requestCount).toBe(1);await click('Play saved recording');await wait(()=>expect(playbacks.length).toBe(2));
  const reopenedSha=await sha(new Uint8Array(await playbacks[1].arrayBuffer()));expect(reopenedSha).toBe(wavSha);
  await click('Open private notebook');await wait(()=>expect(container.querySelector<HTMLTextAreaElement>('#team-notebook')?.disabled).toBe(false));
  expect(calls.filter(call=>call.method==='POST'&&call.path==='/workspaces/private-drafts')).toHaveLength(1);
  expect(calls.filter(call=>call.method==='POST'&&call.path==='/practice-access/setup/complete')).toHaveLength(1);
  expect(calls.filter(call=>call.method==='POST'&&call.path==='/provider-team')).toHaveLength(1);
  expect(calls.some(call=>call.path.includes('/capture/'))).toBe(false);
  expect(calls.filter(call=>call.method==='POST'&&/\/private-recordings$/.test(call.path))).toHaveLength(1);
  expect(calls.filter(call=>call.method==='POST'&&/\/private-recordings\/[^/]+\/finish$/.test(call.path))).toHaveLength(1);
  expect(metadataReceipts.at(-1)).toMatchObject({workspace_id:workspaceId,local_recording_id:saved.recordingId,state:'finished',audio_uploaded:false,transcription_started:false,upstream_capture_admitted:false});
  const elapsed=performance.now()-started;
  const fs='node:fs/promises';const {writeFile}=await import(/* @vite-ignore */fs) as {writeFile:(path:string,text:string)=>Promise<void>};
  await writeFile(environment!.COSMAS_PRIVATE_SCRIBE_LAB_REPORT!,JSON.stringify({completed:true,synthetic_only:true,actual_signed_api:true,actual_DOM_controls:true,hardware_simulated:true,actual_browser_capture_adapter:true,production_encrypted_indexeddb:true,microphone_started_before_create_response:microphoneStartedBeforeCreateResponse,recording:{recording_id:saved.recordingId,workspace_id:workspaceId,chunks:saved.recordedChunks,wav_sha256:wavSha},reopened_wav_sha256:reopenedSha,timings:{ready_to_select_ms:selectedAt-readyAt,select_to_adapter_start_ms:adapterStartedAt-selectedAt,consent_to_adapter_start_ms:adapterStartedAt-consentAt,private_create_complete_ms:calls.find(c=>c.method==='POST'&&c.path==='/workspaces/private-drafts')!.completed_at_ms-selectedAt},automated_elapsed_ms:elapsed,real_users_tested:false,physical_devices_tested:false,phone_visual_or_native_qualified:false,provider_io_performed:false,calls},null,2)+'\n');
},90000);

/** OS APIs only are simulated; the production BrowserMicrophoneCaptureSource remains intact. */
class GeneratedAudioHardware {
  requestedAt:number|null=null;startedAt:number|null=null;requestCount=0;
  readonly track=Object.assign(new EventTarget(),{stopped:false,stop:()=>{this.track.stopped=true;}});
  readonly stream={getTracks:()=>[this.track],getAudioTracks:()=>[this.track]} as unknown as MediaStream;
  readonly worklet={connect:()=>{},disconnect:()=>{},onprocessorerror:null,port:{onmessage:null as ((event:MessageEvent)=>void)|null,postMessage:()=>{}},emit(frames:Float32Array){this.port.onmessage?.({data:{type:'pcm',version:1,sequence:0,frames:frames.buffer}} as MessageEvent);}};
  readonly context={sampleRate:16000,state:'suspended' as AudioContextState,destination:{},audioWorklet:{addModule:async()=>{}},addEventListener:()=>{},removeEventListener:()=>{},
    createMediaStreamSource:()=>({connect:()=>{},disconnect:()=>{}}),createGain:()=>({gain:{value:1},connect:()=>{},disconnect:()=>{}}),
    resume:async()=>{this.context.state='running';this.startedAt=performance.now();this.requestCount++;},suspend:async()=>{this.context.state='suspended';},close:async()=>{this.context.state='closed';}};
}
