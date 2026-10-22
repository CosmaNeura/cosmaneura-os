import {act,useEffect,useLayoutEffect,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PrivateRecordingPanel,type PrivateRecordingPanelProps,type PrivateNotebookResult} from './PrivateRecordingPanel';
import type {PrivateRecordingSnapshot,PrivateRecordingStore} from './private-recording-runtime';
import type {PrivateTranscriptAudio} from './private-transcription';

type Prepare=()=>Promise<void>;
const child=vi.hoisted(()=>({prepare:vi.fn(),registrations:[] as ((prepare:Prepare|null)=>void)[],sources:[] as PrivateTranscriptAudio[]}));
// The actual recorder/navigation component runs against a controlled child-save
// seam. The child suite separately proves its encrypted saveWorking contract.
vi.mock('./PrivateTranscriptPanel',()=>({PrivateTranscriptPanel:({recording,onPrepareNavigation,locked=false}:{recording:PrivateTranscriptAudio;onPrepareNavigation?:(prepare:Prepare|null)=>void;locked?:boolean})=>{
  const [words,setWords]=useState('Invented unsaved private words.');
  useEffect(()=>{if(onPrepareNavigation){child.registrations.push(onPrepareNavigation);child.sources.push(recording);onPrepareNavigation(child.prepare);return()=>onPrepareNavigation(null);}},[onPrepareNavigation,recording]);
  return <section aria-label="Private on-device transcript"><textarea aria-label="Editable private transcript" value={words} disabled={locked} onChange={event=>setWords(event.target.value)}/></section>;
}}));
const ledger=vi.hoisted(()=>({read:vi.fn(),attach:vi.fn(),finish:vi.fn()}));
vi.mock('./private-recording-ledger',()=>({PrivateRecordingLedgerController:class{
  readCurrent=ledger.read;attach=ledger.attach;finish=ledger.finish;
}}));
type Controller=Awaited<ReturnType<NonNullable<PrivateRecordingPanelProps['runtimeFactory']>>>;
const uuid=(n:number)=>`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`;
const scope='b'.repeat(64);
let root:Root,host:HTMLDivElement,props:PrivateRecordingPanelProps,runtimes:Controller[],events:string[],mapping:PrivateNotebookResult;
const closed=vi.fn(),opened=vi.fn(),transcribed=vi.fn();
// This seam skips ledger parsing, but a finished handoff must still carry the
// exact sealed source receipt consumed by the real navigation component.
function finishedLedger(){return {state:'finished',receipt:{finish:{manifest_sha256:'c'.repeat(64),chunks:3,frames:368000}}};}
function runtime(recordingId:string):Controller{
  const snapshot:PrivateRecordingSnapshot={recordingId,title:'Invented saved recording',phase:'sealed',elapsedSeconds:23,recordedChunks:3,recordedBytes:736132,workspaceId:uuid(2),busy:false,localOnly:true,transcription:'not_requested',failure:null,startupStage:null};
  return {snapshot,subscribe:listener=>{listener(snapshot);return()=>{};},start:vi.fn(),pause:vi.fn(),stop:vi.fn(),rename:vi.fn(),
    close:vi.fn(async()=>{events.push('close-runtime');}),attachWorkspace:vi.fn(async()=>{events.push('attach');}),
    exportWav:vi.fn(async()=>{throw new Error('Synthetic playback is outside this navigation test');}),
    snapshotForLedger:vi.fn<Controller['snapshotForLedger']>(async()=>({recordingId,scope,consent:{language:'en-US',modality:'in_person',participant_regions:[],method:'verbal_attestation',all_parties_consented:true,granted_at:new Date().toISOString()},consentIntervals:[],startedAt:new Date().toISOString(),phase:'sealed',frames:368000,chunks:3,manifestSHA256:'c'.repeat(64),updatedAt:new Date().toISOString()})),
    snapshotForPrivateTranscript:vi.fn(),savedChunks:async function*(){}};
}
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();child.registrations=[];child.sources=[];runtimes=[];events=[];
  child.prepare.mockImplementation(async()=>{events.push('saved-words');});ledger.read.mockResolvedValue(finishedLedger());
  const identity={mode:'clerk_jwt' as const,getToken:vi.fn(),nativeSession:{revision:'invented-native-session',isCurrent:()=>true}};
  mapping={identity,workspace:{id:uuid(2),appointment_id:null,label:'Invented private notebook',revision:1,entries:[],work_candidates:[],private_draft:{title:'Invented private notebook',state:'unlinked',link_receipt_id:null,linked_at:null}},team:{revision:1,recovery_scope:scope,template_version:'provider-team-v1',llm:{enabled:false,model:'gpt-4.1'},configuration:{practice_context:'',bots:[]},members:[]}};
  const store:PrivateRecordingStore={read:vi.fn(),write:vi.fn(),keys:vi.fn(async()=>[]),close:vi.fn()};
  props={identity,scope,platform:'ios',recordingId:uuid(1),isCurrent:()=>true,onClose:closed,onNotebook:opened,onTranscribe:transcribed,
    prepareNotebook:async()=>mapping,prepareStore:async()=>store,prepareNative:async({revision})=>({receiptId:uuid(3),revision,expiresAt:new Date(Date.now()+60000).toISOString()}),
    runtimeFactory:async(_options,input)=>{const value=runtime(input.recordingId!);runtimes.push(value);return value;}};
  host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();});
async function render(){await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('textarea')).not.toBeNull();});}
const button=(name:string)=>{const value=[...host.querySelectorAll('button')].find(b=>b.textContent===name);expect(value,name).toBeTruthy();return value!;};
const names={close:'Close recording',notebook:'Open private notebook',scribe:'Use Scribe for a confirmed visit'} as const;
type Action=keyof typeof names;
async function click(action:Action){await act(async()=>button(names[action]).click());}
const navigation=(action:Action)=>action==='close'?closed:action==='notebook'?opened:transcribed;

it.each(['close','notebook','scribe'] as const)('saves edited private words before one %s action and ignores duplicate gestures during the save',async action=>{
  await render();events=[];
  let release!:()=>void;const held=new Promise<void>(resolve=>release=resolve);
  child.prepare.mockImplementationOnce(async()=>{await held;events.push('saved-words');});
  await act(async()=>{button(names[action]).click();button(names[action]).click();});
  expect(child.prepare).toHaveBeenCalledOnce();expect(navigation(action)).not.toHaveBeenCalled();expect(runtimes[0].close).not.toHaveBeenCalled();expect(events).toEqual([]);
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Invented unsaved private words.');
  await act(async()=>{release();await held;});
  await vi.waitFor(()=>expect(navigation(action)).toHaveBeenCalledOnce());
  expect(events[0]).toBe('saved-words');
  if(action==='scribe')expect(transcribed).toHaveBeenCalledExactlyOnceWith(mapping,uuid(1));
  if(action==='notebook')expect(opened).toHaveBeenCalledExactlyOnceWith(mapping);
  expect(ledger.attach).not.toHaveBeenCalled();expect(ledger.finish).not.toHaveBeenCalled();
});

it.each(['close','notebook','scribe'] as const)('keeps edited words mounted after a failed save for %s and retries only on the next explicit action',async action=>{
  await render();events=[];child.prepare.mockRejectedValueOnce(new Error('Synthetic encrypted save failed'));
  await click(action);expect(navigation(action)).not.toHaveBeenCalled();expect(runtimes[0].close).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Your transcript edits could not be saved');expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Invented unsaved private words.');
  expect(child.prepare).toHaveBeenCalledOnce();await act(async()=>{});expect(child.prepare).toHaveBeenCalledOnce();
  await click(action);await vi.waitFor(()=>expect(navigation(action)).toHaveBeenCalledOnce());expect(child.prepare).toHaveBeenCalledTimes(2);
});

it.each(['missing','manifest','chunks','frames'] as const)('withholds Scribe on a %s finish receipt and retries only after the exact sealed receipt is available',async mismatch=>{
  await render();const receipt=finishedLedger();
  if(mismatch==='manifest')receipt.receipt.finish.manifest_sha256='d'.repeat(64);
  if(mismatch==='chunks')receipt.receipt.finish.chunks++;
  if(mismatch==='frames')receipt.receipt.finish.frames++;
  ledger.read.mockResolvedValue(mismatch==='missing'?{state:'finished'}:receipt);
  await click('scribe');expect(transcribed).not.toHaveBeenCalled();expect(runtimes[0].close).not.toHaveBeenCalled();
  expect(host.textContent).toContain('The recording details need to finish saving before transcription');
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Invented unsaved private words.');
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(false);expect(child.prepare).toHaveBeenCalledOnce();
  ledger.read.mockResolvedValue(finishedLedger());await act(async()=>{});expect(transcribed).not.toHaveBeenCalled();expect(child.prepare).toHaveBeenCalledOnce();
  await click('scribe');expect(transcribed).toHaveBeenCalledExactlyOnceWith(mapping,uuid(1));expect(runtimes[0].close).toHaveBeenCalledOnce();
  expect(child.prepare).toHaveBeenCalledTimes(2);expect(ledger.attach).not.toHaveBeenCalled();expect(ledger.finish).not.toHaveBeenCalled();
});

it.each([false,true])('withholds an obsolete transcript-save completion after same-owner recording replacement (%s)',async fails=>{
  await render();let release!:()=>void;const held=new Promise<void>(resolve=>release=resolve);
  child.prepare.mockImplementationOnce(async()=>{await held;if(fails)throw new Error('Synthetic old save failed');});
  const obsoleteRegistration=child.registrations[0];await click('close');expect(closed).not.toHaveBeenCalled();
  props={...props,recordingId:uuid(4)};await render();expect(child.sources.at(-1)?.snapshot.recordingId).toBe(uuid(4));expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(false);
  await act(async()=>obsoleteRegistration(null));
  await act(async()=>{release();await held;});expect(closed).not.toHaveBeenCalled();expect(host.textContent).not.toContain('Your transcript edits could not be saved');
  const newPreparation=child.prepare.mock.calls.length;await click('close');expect(child.prepare).toHaveBeenCalledTimes(newPreparation+1);expect(closed).toHaveBeenCalledOnce();
});

it('locks further transcript typing after preparation while runtime close remains held',async()=>{
  await render();let save!:()=>void,finishClose!:()=>void;
  const saving=new Promise<void>(resolve=>save=resolve),closing=new Promise<void>(resolve=>finishClose=resolve);
  child.prepare.mockImplementationOnce(async()=>{await saving;});vi.mocked(runtimes[0].close).mockImplementationOnce(async()=>{await closing;});
  await click('close');expect(child.prepare).toHaveBeenCalledOnce();expect(runtimes[0].close).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(false);
  await act(async()=>{save();await saving;});await vi.waitFor(()=>expect(runtimes[0].close).toHaveBeenCalledOnce());
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(true);expect(closed).not.toHaveBeenCalled();
  await act(async()=>{finishClose();await closing;});expect(closed).toHaveBeenCalledOnce();
});

it('retains the transcript lock after failed close until the same explicit Close retry is confirmed',async()=>{
  await render();let finishClose!:()=>void;const closing=new Promise<void>(resolve=>finishClose=resolve);
  vi.mocked(runtimes[0].close).mockImplementationOnce(async()=>{await closing;throw new Error('Synthetic close result lost');});
  await click('close');expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(true);
  await act(async()=>{finishClose();await closing;});expect(closed).not.toHaveBeenCalled();expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(true);
  expect(host.textContent).toContain('The microphone stop remains unconfirmed');expect(button(names.close).disabled).toBe(false);
  expect(button(names.notebook).disabled).toBe(true);expect(button(names.scribe).disabled).toBe(true);expect(button('Rename recording').disabled).toBe(true);
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Invented unsaved private words.');
  await click('notebook');await click('scribe');expect(opened).not.toHaveBeenCalled();expect(transcribed).not.toHaveBeenCalled();expect(child.prepare).toHaveBeenCalledOnce();
  let confirmClose!:()=>void;const confirming=new Promise<void>(resolve=>confirmClose=resolve);
  vi.mocked(runtimes[0].close).mockImplementationOnce(async()=>{await confirming;});
  await act(async()=>{button(names.close).click();button(names.close).click();});
  expect(child.prepare).toHaveBeenCalledTimes(2);expect(runtimes[0].close).toHaveBeenCalledTimes(2);expect(runtimes).toHaveLength(1);expect(closed).not.toHaveBeenCalled();
  expect(host.querySelector<HTMLTextAreaElement>('textarea')?.disabled).toBe(true);expect(host.querySelector<HTMLTextAreaElement>('textarea')?.value).toBe('Invented unsaved private words.');
  await act(async()=>{confirmClose();await confirming;});expect(closed).toHaveBeenCalledOnce();expect(opened).not.toHaveBeenCalled();expect(transcribed).not.toHaveBeenCalled();
});

it('withholds notebook navigation when access changes while private words are saving',async()=>{
  await render();let release!:()=>void;const held=new Promise<void>(resolve=>release=resolve);
  child.prepare.mockImplementationOnce(async()=>{await held;});await click('notebook');props={...props,isCurrent:()=>false};await act(async()=>root.render(<PrivateRecordingPanel {...props}/>));
  await act(async()=>{release();await held;});expect(opened).not.toHaveBeenCalled();expect(transcribed).not.toHaveBeenCalled();expect(closed).not.toHaveBeenCalled();expect(host.textContent).toContain('Recording access changed');
});

it('hides an old recording synchronously when entry props change before passive owner cleanup',async()=>{
  const beforePaint:string[]=[];
  function Entry(){useLayoutEffect(()=>{beforePaint.push(host.textContent??'');},[props.recordingId]);return <PrivateRecordingPanel {...props}/>;}
  await act(async()=>root.render(<Entry/>));await vi.waitFor(async()=>{await act(async()=>{});expect(host.querySelector('textarea')).not.toBeNull();});
  props={...props,recordingId:uuid(4)};await act(async()=>root.render(<Entry/>));
  expect(beforePaint.at(-1)).toContain('Recording access changed');expect(beforePaint.at(-1)).not.toContain('Invented saved recording');
  expect(child.sources.at(-1)?.snapshot.recordingId).toBe(uuid(4));expect(closed).not.toHaveBeenCalled();expect(opened).not.toHaveBeenCalled();expect(transcribed).not.toHaveBeenCalled();
});
