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
vi.mock('./PrivateTranscriptPanel',()=>({PrivateTranscriptPanel:({recording,onPrepareNavigation}:{recording:PrivateTranscriptAudio;onPrepareNavigation?:(prepare:Prepare|null)=>void})=>{
  const [words,setWords]=useState('Invented unsaved private words.');
  useEffect(()=>{if(onPrepareNavigation){child.registrations.push(onPrepareNavigation);child.sources.push(recording);onPrepareNavigation(child.prepare);return()=>onPrepareNavigation(null);}},[onPrepareNavigation,recording]);
  return <section aria-label="Private on-device transcript"><textarea aria-label="Editable private transcript" value={words} onChange={event=>setWords(event.target.value)}/></section>;
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
  child.prepare.mockImplementation(async()=>{events.push('saved-words');});ledger.read.mockResolvedValue({state:'finished'});
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

it.each([false,true])('withholds an obsolete transcript-save completion after same-owner recording replacement (%s)',async fails=>{
  await render();let release!:()=>void;const held=new Promise<void>(resolve=>release=resolve);
  child.prepare.mockImplementationOnce(async()=>{await held;if(fails)throw new Error('Synthetic old save failed');});
  const obsoleteRegistration=child.registrations[0];await click('close');expect(closed).not.toHaveBeenCalled();
  props={...props,recordingId:uuid(4)};await render();expect(child.sources.at(-1)?.snapshot.recordingId).toBe(uuid(4));
  await act(async()=>obsoleteRegistration(null));
  await act(async()=>{release();await held;});expect(closed).not.toHaveBeenCalled();expect(host.textContent).not.toContain('Your transcript edits could not be saved');
  const newPreparation=child.prepare.mock.calls.length;await click('close');expect(child.prepare).toHaveBeenCalledTimes(newPreparation+1);expect(closed).toHaveBeenCalledOnce();
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
