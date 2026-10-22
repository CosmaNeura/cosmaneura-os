import {act,StrictMode,useLayoutEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PrivateTranscriptPanel,type PrivateTranscriptGesture} from './PrivateTranscriptPanel';
import type {PrivateTranscript,PrivateTranscriptAudio} from './private-transcription';
import {hasUnsavedWork} from './unsaved-work';
const mocks=vi.hoisted(()=>({begin:vi.fn(),append:vi.fn(),finish:vi.fn(),cancel:vi.fn(),close:vi.fn(),read:vi.fn(),write:vi.fn()}));
vi.mock('./private-transcription-native',async original=>({...await original<typeof import('./private-transcription-native')>(),privateSpeechNative:{begin:mocks.begin,append:mocks.append,finish:mocks.finish,cancel:mocks.cancel}}));
vi.mock('./private-recording-runtime',()=>({openPrivateRecordingStore:async()=>({read:mocks.read,write:mocks.write,close:mocks.close})}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id='00000000-0000-4000-8000-000000000001',runId='00000000-0000-4000-8000-000000000002',scope='b'.repeat(64),hash='c'.repeat(64);
const identity={mode:'clerk_jwt' as const,getToken:async()=>null,nativeSession:{revision:'invented-native-revision',isCurrent:()=>true}};
let root:Root,host:HTMLDivElement,recording:PrivateTranscriptAudio,rows:Map<string,unknown>;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();vi.stubGlobal('crypto',webcrypto);rows=new Map();
 mocks.read.mockImplementation(async key=>structuredClone(rows.get(key)??null));mocks.write.mockImplementation(async(key,before,next)=>{expect(rows.get(key)??null).toEqual(before);rows.set(key,structuredClone(next));});
 mocks.begin.mockResolvedValue({runId});mocks.append.mockImplementation(async v=>({sequence:v.sequence}));mocks.finish.mockResolvedValue({runId,recordingId:id,audioSHA256:hash,frames:1,text:'Invented original private transcript.',engine:'ios-speech-on-device-v1',language:'en-US'});mocks.cancel.mockResolvedValue(undefined);
 recording={snapshot:{recordingId:id,workspaceId:null},snapshotForPrivateTranscript:async()=>({recordingId:id,scope,phase:'sealed',audioSHA256:hash,chunks:1,frames:1,consent:{language:'en-US'}}),savedChunks:async function*(){yield{sequence:0,sha256:'d'.repeat(64),wavBytes:new Uint8Array(46)};}} as unknown as PrivateTranscriptAudio;
 host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const button=(label:string)=>[...host.querySelectorAll('button')].find(b=>b.textContent===label);
async function render(gesture?:PrivateTranscriptGesture,options:{allow?:boolean;locked?:boolean;current?:()=>boolean;prepare?:(value:(()=>Promise<void>)|null)=>void;dirty?:(value:boolean)=>void}={}){await act(async()=>root.render(<PrivateTranscriptPanel identity={identity} scope={scope} recording={recording} isCurrent={options.current??(()=>true)} transcriptionGesture={gesture} allowTranscription={options.allow} locked={options.locked} onPrepareNavigation={options.prepare} onDirty={options.dirty}/>));}
async function wait(check:()=>unknown){await vi.waitFor(check);}
it('requires one explicit Transcribe action, saves editable words separately, and reopens without recognizing again',async()=>{
 await render();await wait(()=>expect(button('Transcribe on this iPhone')?.disabled).toBe(false));expect(mocks.begin).not.toHaveBeenCalled();
 await act(async()=>button('Transcribe on this iPhone')!.click());await wait(()=>expect(host.querySelector('textarea')?.value).toBe('Invented original private transcript.'));
 const textarea=host.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(textarea,'Invented reviewed private text.');textarea.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>button('Save transcript edits')!.click());expect(rows.get('private-transcript:'+id)).toMatchObject({working:'Invented reviewed private text.',raw:{text:'Invented original private transcript.'}});
 await act(async()=>root.unmount());root=createRoot(host);await render();await wait(()=>expect(host.querySelector('textarea')?.value).toBe('Invented reviewed private text.'));expect(mocks.begin).toHaveBeenCalledOnce();
});
it('consumes an explicit fallback gesture once and never repeats its denied request on reopen',async()=>{
 let spent=false;const claim=vi.fn(()=>{if(spent)return false;spent=true;return true;}),gesture={identity,scope,recording,claim};mocks.begin.mockRejectedValue({code:'private_speech_permission_denied'});
 await render(gesture);await wait(()=>expect(host.textContent).toContain('Speech recognition access is not allowed'));expect(mocks.begin).toHaveBeenCalledOnce();
 await act(async()=>root.unmount());root=createRoot(host);await render(gesture);await wait(()=>expect(button('Transcribe again on this iPhone')?.disabled).toBe(false));expect(mocks.begin).toHaveBeenCalledOnce();expect(rows.get('private-transcript:'+id)).toMatchObject({state:'interrupted',raw:null});
});
it('withholds a fallback gesture that belongs to a different exact audio owner',async()=>{
 const claim=vi.fn(()=>true),other={...recording} as PrivateTranscriptAudio;await render({identity,scope,recording:other,claim});await wait(()=>expect(button('Transcribe on this iPhone')?.disabled).toBe(false));expect(claim).not.toHaveBeenCalled();expect(mocks.begin).not.toHaveBeenCalled();
});

function saved():PrivateTranscript{return {contract:'cosmabot.private-transcript.v1',scope,recordingId:id,workspaceId:null,
 source:{audioSHA256:hash,chunks:1,frames:1},language:'en-US',intent:runId,state:'ready',raw:{text:'Invented private machine text.',engine:'ios-speech-on-device-v1',completedAt:'2026-10-21T12:00:00Z'},
 working:'Invented reviewed private text.',revision:2,createdAt:'2026-10-21T11:59:00Z',updatedAt:'2026-10-21T12:00:00Z'};}
function noRecognition(){for(const method of [mocks.begin,mocks.append,mocks.finish,mocks.cancel,mocks.write])expect(method).not.toHaveBeenCalled();expect(fetch).not.toHaveBeenCalled();}
it('opens matching saved private words directly without recognition, permission or network while Scribe is pending',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('Unexpected network')));const retained=saved();rows.set('private-transcript:'+id,retained);
 await render(undefined,{allow:false});await wait(()=>expect(host.querySelector('textarea')?.value).toBe(retained.working));
 expect(host.textContent).toContain('Private transcript');expect(button('Transcribe on this iPhone')).toBeUndefined();noRecognition();expect(rows.get('private-transcript:'+id)).toEqual(retained);
});
it.each(['scope','recording','audio','malformed'] as const)('rejects %s saved private transcript before exposing its words or starting recognition',async change=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('Unexpected network')));const retained=saved();
 if(change==='scope')retained.scope='e'.repeat(64);if(change==='recording')retained.recordingId=runId;if(change==='audio')retained.source.audioSHA256='e'.repeat(64);
 rows.set('private-transcript:'+id,change==='malformed'?{...retained,untrusted:'private-data'}:retained);
 await render(undefined,{allow:false});await wait(()=>expect(host.querySelector('[role=alert]')).not.toBeNull());
 expect(host.querySelector('textarea')).toBeNull();expect(host.textContent).not.toContain(retained.working);expect(host.textContent).not.toContain('private-data');noRecognition();
});
it('retries only a failed encrypted read and opens saved words without starting speech',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('Unexpected network')));rows.set('private-transcript:'+id,saved());mocks.read.mockRejectedValueOnce(new Error('Private storage unavailable'));
 await render(undefined,{allow:false});await wait(()=>expect(button('Retry opening private transcript')?.disabled).toBe(false));
 await act(async()=>button('Retry opening private transcript')!.click());await wait(()=>expect(host.querySelector('textarea')?.value).toBe(saved().working));noRecognition();expect(mocks.read).toHaveBeenCalledTimes(2);
});
it('keeps first-time speech closed until an explicit allowed action and respects a pending review lock',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('Unexpected network')));await render(undefined,{allow:false});await wait(()=>expect(mocks.read).toHaveBeenCalledOnce());
 expect(host.childElementCount).toBe(0);noRecognition();
 await render(undefined,{allow:true,locked:true});expect(button('Transcribe on this iPhone')?.disabled).toBe(true);noRecognition();
 await render(undefined,{allow:true,locked:false});await act(async()=>button('Transcribe on this iPhone')!.click());await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());expect(mocks.begin).toHaveBeenCalledOnce();expect(fetch).not.toHaveBeenCalled();
});
it('drops a held saved-word read after exact current owner is retired',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('Unexpected network')));let resolve!:(value:PrivateTranscript)=>void;let current=true;
 mocks.read.mockImplementationOnce(()=>new Promise(value=>resolve=value));await render(undefined,{allow:false,current:()=>current});
 current=false;await act(async()=>resolve(saved()));expect(host.querySelector('textarea')).toBeNull();expect(host.textContent).not.toContain(saved().working);noRecognition();
});
function CommitProbe({capture}:{capture:()=>void}){useLayoutEffect(()=>{capture();});return null;}
it.each(['identity','scope','recording','revision'] as const)('hides previous private words in the first committed DOM after %s replacement',async change=>{
 rows.set('private-transcript:'+id,saved());const observations:{text:string;words:string|undefined}[]=[];
 const capture=()=>observations.push({text:host.textContent??'',words:host.querySelector('textarea')?.value});
 const base={identity,scope,recording,isCurrent:()=>true,allowTranscription:false};
 const commit=(props:typeof base)=>act(async()=>root.render(<><PrivateTranscriptPanel {...props}/><CommitProbe capture={capture}/></>));
 await commit(base);await wait(()=>expect(host.querySelector('textarea')?.value).toBe(saved().working));
 mocks.read.mockImplementation(()=>new Promise(()=>{}));observations.length=0;
 const next={...base};if(change==='identity')next.identity={...identity};if(change==='scope')next.scope='f'.repeat(64);if(change==='recording')next.recording={...recording};if(change==='revision')next.identity={...identity,nativeSession:{...identity.nativeSession,revision:'new-native-revision'}};
 await commit(next);expect(observations[0].words).toBeUndefined();expect(observations[0].text).not.toContain(saved().working);expect(observations[0].text).not.toContain(saved().raw!.text);
 expect(mocks.begin).not.toHaveBeenCalled();expect(mocks.write).not.toHaveBeenCalled();
});
async function edit(words:string){const textarea=host.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(textarea,words);textarea.dispatchEvent(new Event('input',{bubbles:true}));});}
it('prepares navigation by saving exact current edits once without recognizing, then clean preparation is a no-op',async()=>{
 rows.set('private-transcript:'+id,saved());let prepare:(()=>Promise<void>)|null=null;const dirty=vi.fn();
 await render(undefined,{allow:false,prepare:value=>{prepare=value;},dirty});await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());
 await edit('Invented last private words.');expect(dirty).toHaveBeenLastCalledWith(true);
 await act(async()=>prepare!());expect(rows.get('private-transcript:'+id)).toMatchObject({working:'Invented last private words.',raw:saved().raw});expect(dirty).toHaveBeenLastCalledWith(false);
 await act(async()=>prepare!());expect(mocks.write).toHaveBeenCalledOnce();expect(mocks.begin).not.toHaveBeenCalled();
});
it('keeps dirty locked words unsaved but allows a clean Close retry after their exact save without another write',async()=>{
 rows.set('private-transcript:'+id,saved());let prepare:(()=>Promise<void>)|null=null;const register=(value:(()=>Promise<void>)|null)=>{prepare=value;};
 await render(undefined,{allow:false,prepare:register});await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());await edit('Invented words retained during Close.');
 await render(undefined,{allow:false,locked:true,prepare:register});await act(async()=>{await expect(prepare!()).rejects.toThrow();});
 expect(host.querySelector('textarea')?.disabled).toBe(true);expect(host.querySelector('textarea')?.value).toBe('Invented words retained during Close.');
 expect(mocks.write).not.toHaveBeenCalled();expect(rows.get('private-transcript:'+id)).toEqual(saved());
 await render(undefined,{allow:false,locked:false,prepare:register});await act(async()=>prepare!());
 const confirmed=structuredClone(rows.get('private-transcript:'+id));expect(confirmed).toMatchObject({working:'Invented words retained during Close.',revision:3,raw:saved().raw});
 const reads=mocks.read.mock.calls.length;await render(undefined,{allow:false,locked:true,prepare:register});await act(async()=>prepare!());
 expect(host.querySelector('textarea')?.disabled).toBe(true);expect(host.querySelector('textarea')?.value).toBe('Invented words retained during Close.');
 expect(rows.get('private-transcript:'+id)).toEqual(confirmed);expect(mocks.write).toHaveBeenCalledOnce();expect(mocks.read).toHaveBeenCalledTimes(reads);
 expect(mocks.begin).not.toHaveBeenCalled();expect(mocks.append).not.toHaveBeenCalled();expect(mocks.finish).not.toHaveBeenCalled();
});
it('refuses navigation on encrypted save failure and retains dirty words for the same explicit retry',async()=>{
 rows.set('private-transcript:'+id,saved());let prepare:(()=>Promise<void>)|null=null;const dirty=vi.fn();
 await render(undefined,{allow:false,prepare:value=>{prepare=value;},dirty});await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());await edit('Invented unsaved words.');
 mocks.write.mockRejectedValueOnce(new Error('Untrusted private storage failure'));
 await act(async()=>{await expect(prepare!()).rejects.toThrow();});expect(host.querySelector('textarea')?.value).toBe('Invented unsaved words.');expect(dirty).toHaveBeenLastCalledWith(true);
 expect(host.textContent).not.toContain('Untrusted private storage failure');expect(rows.get('private-transcript:'+id)).toEqual(saved());
 await act(async()=>prepare!());expect(rows.get('private-transcript:'+id)).toMatchObject({working:'Invented unsaved words.'});expect(mocks.begin).not.toHaveBeenCalled();
});
it('confirms a lost encrypted save acknowledgement by reading the exact next words without writing again',async()=>{
 rows.set('private-transcript:'+id,saved());let prepare:(()=>Promise<void>)|null=null;const dirty=vi.fn();
 await render(undefined,{allow:false,prepare:value=>{prepare=value;},dirty});await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());await edit('Invented acknowledged-late words.');
 mocks.write.mockImplementationOnce(async(key,_before,next)=>{rows.set(key,structuredClone(next));throw new Error('Lost encrypted write reply');});
 await act(async()=>{await expect(prepare!()).rejects.toThrow();});expect(host.querySelector('textarea')?.value).toBe('Invented acknowledged-late words.');expect(dirty).toHaveBeenLastCalledWith(true);
 await act(async()=>prepare!());expect(mocks.write).toHaveBeenCalledOnce();expect(dirty).toHaveBeenLastCalledWith(false);expect(rows.get('private-transcript:'+id)).toMatchObject({working:'Invented acknowledged-late words.',revision:3});expect(mocks.begin).not.toHaveBeenCalled();
});
it('saves an explicit reversion after a lost acknowledgement instead of treating prior words as clean',async()=>{
 rows.set('private-transcript:'+id,saved());let prepare:(()=>Promise<void>)|null=null;const dirty=vi.fn();
 await render(undefined,{allow:false,prepare:value=>{prepare=value;},dirty});await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());await edit('Invented words saved before a lost reply.');
 mocks.write.mockImplementationOnce(async(key,_before,next)=>{rows.set(key,structuredClone(next));throw new Error('Lost encrypted write reply');});
 await act(async()=>{await expect(prepare!()).rejects.toThrow();});await edit(saved().working);
 expect(dirty).toHaveBeenLastCalledWith(true);expect(hasUnsavedWork()).toBe(true);expect(button('Save transcript edits')?.disabled).toBe(false);
 let protectedAfterConfirmation=true;await act(async()=>{await prepare!();protectedAfterConfirmation=hasUnsavedWork();});
 expect(protectedAfterConfirmation).toBe(false);expect(dirty).toHaveBeenLastCalledWith(false);expect(host.querySelector('textarea')?.value).toBe(saved().working);
 expect(rows.get('private-transcript:'+id)).toMatchObject({working:saved().working,revision:4,raw:saved().raw});expect(mocks.write).toHaveBeenCalledTimes(2);expect(mocks.read).toHaveBeenCalledTimes(2);expect(mocks.begin).not.toHaveBeenCalled();
});
it('refuses an unrelated saved revision on explicit recovery and retains the current edited words',async()=>{
 rows.set('private-transcript:'+id,saved());let prepare:(()=>Promise<void>)|null=null;
 await render(undefined,{allow:false,prepare:value=>{prepare=value;}});await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());await edit('Invented local unsaved words.');mocks.write.mockRejectedValueOnce(new Error('Write unavailable'));
 await act(async()=>{await expect(prepare!()).rejects.toThrow();});const other={...saved(),revision:3,working:'Invented unrelated saved words.'};rows.set('private-transcript:'+id,other);
 await act(async()=>{await expect(prepare!()).rejects.toThrow();});expect(host.querySelector('textarea')?.value).toBe('Invented local unsaved words.');expect(rows.get('private-transcript:'+id)).toEqual(other);expect(mocks.write).toHaveBeenCalledOnce();expect(mocks.begin).not.toHaveBeenCalled();
});
it.each(['missing','unavailable'] as const)('clean %s private words do not add a read or permission gate to navigation',async mode=>{
 let prepare:(()=>Promise<void>)|null=null;if(mode==='unavailable')mocks.read.mockRejectedValueOnce(new Error('Encrypted read unavailable'));
 await render(undefined,{allow:true,prepare:value=>{prepare=value;}});await wait(()=>expect(mocks.read).toHaveBeenCalledOnce());await wait(()=>expect(prepare).not.toBeNull());
 await act(async()=>prepare!());expect(mocks.read).toHaveBeenCalledOnce();expect(mocks.write).not.toHaveBeenCalled();expect(mocks.begin).not.toHaveBeenCalled();
});
it('an older navigation preparation cannot save or unregister a replacement owner',async()=>{
 rows.set('private-transcript:'+id,saved());let preparation:(()=>Promise<void>)|null=null;const register=vi.fn((value:(()=>Promise<void>)|null)=>{preparation=value;});
 const panel=(selected:typeof identity)=>act(async()=>root.render(<PrivateTranscriptPanel identity={selected} scope={scope} recording={recording} isCurrent={()=>true} allowTranscription={false} onPrepareNavigation={register}/>));
 await panel(identity);await wait(()=>expect(host.querySelector('textarea')).not.toBeNull());await edit('Invented older words.');const older=preparation!;
 await panel({...identity});await wait(()=>expect(preparation).not.toBe(older));const newer=preparation;
 await expect(older()).rejects.toThrow();expect(preparation).toBe(newer);expect(mocks.write).not.toHaveBeenCalled();expect(mocks.begin).not.toHaveBeenCalled();
});
it('requires an explicit encrypted reopen after initial access was closed, without starting speech',async()=>{
 rows.set('private-transcript:'+id,saved());let permitted=false;const current=()=>permitted;
 await render(undefined,{allow:true,current});await wait(()=>expect(mocks.close).toHaveBeenCalledOnce());permitted=true;
 await render(undefined,{allow:true,current});await wait(()=>expect(button('Retry opening private transcript')?.disabled).toBe(false));
 await act(async()=>button('Retry opening private transcript')!.click());await wait(()=>expect(host.querySelector('textarea')?.value).toBe(saved().working));expect(mocks.begin).not.toHaveBeenCalled();
});

it('continues one explicit local gesture through StrictMode setup without repeating or losing it',async()=>{
 let spent=false;const claim=vi.fn(()=>{if(spent)return false;spent=true;return true;}),gesture={identity,scope,recording,claim};
 await act(async()=>root.render(<StrictMode><PrivateTranscriptPanel identity={identity} scope={scope} recording={recording} isCurrent={()=>true} transcriptionGesture={gesture}/></StrictMode>));
 await wait(()=>expect(host.querySelector('textarea')?.value).toBe('Invented original private transcript.'));expect(claim).toHaveBeenCalledOnce();expect(mocks.begin).toHaveBeenCalledOnce();expect(mocks.append).toHaveBeenCalledOnce();
});
