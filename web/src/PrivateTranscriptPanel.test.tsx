import {act,StrictMode} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PrivateTranscriptPanel,type PrivateTranscriptGesture} from './PrivateTranscriptPanel';
import type {PrivateTranscriptAudio} from './private-transcription';
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
async function render(gesture?:PrivateTranscriptGesture){await act(async()=>root.render(<PrivateTranscriptPanel identity={identity} scope={scope} recording={recording} isCurrent={()=>true} transcriptionGesture={gesture}/>));}
async function wait(check:()=>unknown){await vi.waitFor(check);}
it('requires one explicit Transcribe action, saves editable words separately, and reopens without recognizing again',async()=>{
 await render();await wait(()=>expect(button('Transcribe recording')?.disabled).toBe(false));expect(mocks.begin).not.toHaveBeenCalled();
 await act(async()=>button('Transcribe recording')!.click());await wait(()=>expect(host.querySelector('textarea')?.value).toBe('Invented original private transcript.'));
 const textarea=host.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(textarea,'Invented reviewed private text.');textarea.dispatchEvent(new Event('input',{bubbles:true}));});
 await act(async()=>button('Save transcript edits')!.click());expect(rows.get('private-transcript:'+id)).toMatchObject({working:'Invented reviewed private text.',raw:{text:'Invented original private transcript.'}});
 await act(async()=>root.unmount());root=createRoot(host);await render();await wait(()=>expect(host.querySelector('textarea')?.value).toBe('Invented reviewed private text.'));expect(mocks.begin).toHaveBeenCalledOnce();
});
it('consumes an explicit fallback gesture once and never repeats its denied request on reopen',async()=>{
 let spent=false;const claim=vi.fn(()=>{if(spent)return false;spent=true;return true;}),gesture={identity,scope,recording,claim};mocks.begin.mockRejectedValue({code:'private_speech_permission_denied'});
 await render(gesture);await wait(()=>expect(host.textContent).toContain('Speech recognition access is not allowed'));expect(mocks.begin).toHaveBeenCalledOnce();
 await act(async()=>root.unmount());root=createRoot(host);await render(gesture);await wait(()=>expect(button('Transcribe again')?.disabled).toBe(false));expect(mocks.begin).toHaveBeenCalledOnce();expect(rows.get('private-transcript:'+id)).toMatchObject({state:'interrupted',raw:null});
});
it('withholds a fallback gesture that belongs to a different exact audio owner',async()=>{
 const claim=vi.fn(()=>true),other={...recording} as PrivateTranscriptAudio;await render({identity,scope,recording:other,claim});await wait(()=>expect(button('Transcribe recording')?.disabled).toBe(false));expect(claim).not.toHaveBeenCalled();expect(mocks.begin).not.toHaveBeenCalled();
});

it('continues one explicit local gesture through StrictMode setup without repeating or losing it',async()=>{
 let spent=false;const claim=vi.fn(()=>{if(spent)return false;spent=true;return true;}),gesture={identity,scope,recording,claim};
 await act(async()=>root.render(<StrictMode><PrivateTranscriptPanel identity={identity} scope={scope} recording={recording} isCurrent={()=>true} transcriptionGesture={gesture}/></StrictMode>));
 await wait(()=>expect(host.querySelector('textarea')?.value).toBe('Invented original private transcript.'));expect(claim).toHaveBeenCalledOnce();expect(mocks.begin).toHaveBeenCalledOnce();expect(mocks.append).toHaveBeenCalledOnce();
});
