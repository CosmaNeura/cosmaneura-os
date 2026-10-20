import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {PrivateTranscriptionController,type PrivateTranscriptAudio} from './private-transcription';
import type {PrivateRecordingStore} from './private-recording-runtime';
import type {PrivateSpeechPlugin} from './private-transcription-native';
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const id='00000000-0000-4000-8000-000000000001',runId='00000000-0000-4000-8000-000000000002',scope='b'.repeat(64),fingerprint='c'.repeat(64);
function pcm(){const bytes=new Uint8Array(48),d=new DataView(bytes.buffer);const word=(at:number,v:string)=>[...v].forEach((c,i)=>bytes[at+i]=c.charCodeAt(0));word(0,'RIFF');d.setUint32(4,40,true);word(8,'WAVE');word(12,'fmt ');d.setUint32(16,16,true);d.setUint16(20,1,true);d.setUint16(22,1,true);d.setUint32(24,16000,true);d.setUint32(28,32000,true);d.setUint16(32,2,true);d.setUint16(34,16,true);word(36,'data');d.setUint32(40,4,true);d.setInt16(44,84,true);d.setInt16(46,-42,true);return bytes;}
async function fixture(){
 const bytes=pcm(),sha=Array.from(new Uint8Array(await webcrypto.subtle.digest('SHA-256',bytes)),n=>n.toString(16).padStart(2,'0')).join('');
 const source={recordingId:id,scope,phase:'sealed' as const,audioSHA256:fingerprint,chunks:2,frames:4,consent:{language:'en-US' as 'en-US'|'en-US+es-US'}};
 const recording={snapshot:{recordingId:id,workspaceId:null},snapshotForPrivateTranscript:vi.fn(async()=>({...source})),savedChunks:vi.fn(async function*(){for(let sequence=0;sequence<2;sequence++)yield{sequence,sha256:sha,wavBytes:bytes.slice()};})} as unknown as PrivateTranscriptAudio;
 const rows=new Map<string,unknown>();
 const store:PrivateRecordingStore={read:vi.fn(async key=>rows.get(key)??null),keys:vi.fn(async()=>[...rows.keys()]),write:vi.fn(async(key,expected,value)=>{expect(rows.get(key)??null).toEqual(expected);rows.set(key,structuredClone(value));}),close:vi.fn()};
 const result={runId,recordingId:id,audioSHA256:fingerprint,frames:4,text:'Invented private machine words.',engine:'ios-speech-on-device-v1' as const,language:'en-US' as const};
 const native:PrivateSpeechPlugin={begin:vi.fn(async()=>({runId})),append:vi.fn(async v=>({sequence:v.sequence})),finish:vi.fn(async()=>result),cancel:vi.fn(async()=>{})};
 const controller=()=>new PrivateTranscriptionController({scope,revision:'synthetic-revision',recording,store,native,isCurrent:()=>true});
 return{recording,source,rows,store,native,result,controller};
}
beforeEach(()=>vi.stubGlobal('crypto',webcrypto));afterEach(()=>vi.unstubAllGlobals());
describe('private on-device transcription source and intent',()=>{
 it('streams both verified packets through one native request and preserves original words through edits and reopen',async()=>{
  const f=await fixture(),c=f.controller();expect(await c.load()).toBeNull();expect(f.native.begin).not.toHaveBeenCalled();
  const ready=await c.transcribe();expect(f.native.begin).toHaveBeenCalledOnce();expect(f.native.append).toHaveBeenCalledTimes(2);expect(f.native.finish).toHaveBeenCalledOnce();
  expect(vi.mocked(f.native.append).mock.calls.map(([v])=>[v.runId,v.sequence])).toEqual([[runId,0],[runId,1]]);expect(ready.raw?.text).toBe(f.result.text);expect(ready.working).toBe(f.result.text);
  const edited=await c.saveWorking('Invented edited private words.');expect(edited.raw).toEqual(ready.raw);expect(edited.source).toEqual(ready.source);expect(edited.working).toBe('Invented edited private words.');
  const again=f.controller();expect((await again.load())?.working).toBe(edited.working);expect(f.native.begin).toHaveBeenCalledOnce();
 });
 it('rejects a source changed during recognition and never persists its returned machine text',async()=>{
  const f=await fixture();vi.mocked(f.native.finish).mockImplementation(async()=>{f.source.audioSHA256='d'.repeat(64);return f.result;});
  await expect(f.controller().transcribe()).rejects.toMatchObject({code:'private_speech_changed'});
  expect(f.rows.get('private-transcript:'+id)).toMatchObject({state:'interrupted',raw:null,working:''});expect(f.native.cancel).toHaveBeenCalledWith({runId});
 });
 it('withholds a held native result after the selected controller closes',async()=>{
  const f=await fixture();let release!:(v:typeof f.result)=>void;const held=new Promise<typeof f.result>(resolve=>release=resolve);vi.mocked(f.native.finish).mockImplementation(()=>held);
  const c=f.controller(),pending=c.transcribe();const rejected=expect(pending).rejects.toMatchObject({code:'private_speech_changed'});
  await vi.waitFor(()=>expect(f.native.finish).toHaveBeenCalledOnce());await c.close();release(f.result);await rejected;
  expect(f.rows.get('private-transcript:'+id)).toMatchObject({state:'running',raw:null});expect(f.store.close).toHaveBeenCalledOnce();expect(f.native.cancel).toHaveBeenCalledWith({runId});
 });
 it('withholds persisted private words when the exact sealed source changes before reopen',async()=>{
  const f=await fixture();await f.controller().transcribe();f.source.audioSHA256='d'.repeat(64);await expect(f.controller().load()).rejects.toMatchObject({code:'private_speech_changed'});expect(f.native.begin).toHaveBeenCalledOnce();
 });
 it('retains finished raw and edited words when the same audio is explicitly organized into a notebook later',async()=>{
  const f=await fixture(),c=f.controller(),first=await c.transcribe();await c.saveWorking('Invented edited private words.');
  Object.assign(f.recording.snapshot,{workspaceId:'00000000-0000-4000-8000-000000000003'});
  const reopened=f.controller();const saved=await reopened.load();expect(saved?.raw).toEqual(first.raw);expect(saved?.working).toBe('Invented edited private words.');expect(saved?.workspaceId).toBeNull();
  expect((await reopened.saveWorking('Invented later edits.')).raw).toEqual(first.raw);expect(f.native.begin).toHaveBeenCalledOnce();
 });
 it('withholds a recognition result if notebook association changes during that explicit run',async()=>{
  const f=await fixture();vi.mocked(f.native.finish).mockImplementation(async()=>{Object.assign(f.recording.snapshot,{workspaceId:'00000000-0000-4000-8000-000000000003'});return f.result;});
  await expect(f.controller().transcribe()).rejects.toMatchObject({code:'private_speech_changed'});expect(f.rows.get('private-transcript:'+id)).toMatchObject({state:'interrupted',raw:null});
 });
 it('reports unsupported bilingual audio without a native request or a new transcription intent',async()=>{
  const f=await fixture();f.source.consent.language='en-US+es-US';await expect(f.controller().transcribe()).rejects.toMatchObject({code:'private_speech_language_unsupported'});expect(f.native.begin).not.toHaveBeenCalled();expect(f.store.write).not.toHaveBeenCalled();
 });
});
