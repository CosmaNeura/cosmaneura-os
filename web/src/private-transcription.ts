import type {PrivateRecordingRuntime,PrivateRecordingStore} from './private-recording-runtime';
import type {PrivateSpeechPlugin} from './private-transcription-native';
export type PrivateTranscript={contract:'cosmabot.private-transcript.v1';scope:string;recordingId:string;workspaceId:string|null;source:{audioSHA256:string;chunks:number;frames:number};
 language:'en-US';intent:string;state:'running'|'interrupted'|'ready';raw:null|{text:string;engine:'ios-speech-on-device-v1';completedAt:string};working:string;revision:number;createdAt:string;updatedAt:string};
export type PrivateTranscriptAudio=Pick<PrivateRecordingRuntime,'snapshot'|'snapshotForPrivateTranscript'|'savedChunks'>;
const uuid=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(v);
const hash=(v:unknown):v is string=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const fail=(code='private_speech_changed')=>Object.assign(new Error('Private transcription unavailable'),{code});
function need(v:unknown):asserts v{if(!v)throw fail();}
const closed=(v:unknown,keys:string):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v)&&Object.keys(v).sort().join(',')===keys.split(',').sort().join(',');
function text(value:unknown):asserts value is string {need(typeof value==='string'&&value.length<=32000&&!/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/.test(value));}
export function parsePrivateTranscript(v:unknown,scope:string,id:string):PrivateTranscript {
 need(closed(v,'contract,scope,recordingId,workspaceId,source,language,intent,state,raw,working,revision,createdAt,updatedAt')&&v.contract==='cosmabot.private-transcript.v1'&&v.scope===scope&&v.recordingId===id&&uuid(id)&&hash(scope));
 need((v.workspaceId===null||uuid(v.workspaceId))&&closed(v.source,'audioSHA256,chunks,frames')&&hash(v.source.audioSHA256)&&Number.isSafeInteger(v.source.chunks)&&Number(v.source.chunks)>0&&Number(v.source.chunks)<=360&&Number.isSafeInteger(v.source.frames)&&Number(v.source.frames)>0&&Number(v.source.frames)<=57600000);
 need(v.language==='en-US'&&uuid(v.intent)&&['running','interrupted','ready'].includes(String(v.state))&&Number.isSafeInteger(v.revision)&&Number(v.revision)>0&&['createdAt','updatedAt'].every(k=>typeof v[k]==='string'&&Number.isFinite(Date.parse(v[k] as string))));text(v.working);
 if(v.raw!==null){need(closed(v.raw,'text,engine,completedAt')&&v.raw.engine==='ios-speech-on-device-v1'&&typeof v.raw.completedAt==='string'&&Number.isFinite(Date.parse(v.raw.completedAt)));text(v.raw.text);need(v.raw.text.trim().length>0&&v.state==='ready');}else need(v.state!=='ready');
 need(new TextEncoder().encode(JSON.stringify(v)).length<=400000);return structuredClone(v) as PrivateTranscript;
}
export class PrivateTranscriptionController {
 private saved:PrivateTranscript|null=null;private running=false;private runId:string|null=null;private alive=true;
 constructor(private options:{scope:string;revision:string;recording:PrivateTranscriptAudio;store:PrivateRecordingStore;native:PrivateSpeechPlugin;isCurrent:()=>boolean;onProgress?:(chunks:number,total:number)=>void}){}
 private current(){need(this.alive&&this.options.isCurrent());}
 private key(){return 'private-transcript:'+this.options.recording.snapshot.recordingId;}
 async load():Promise<PrivateTranscript|null>{this.current();const v=await this.options.store.read(this.key());this.current();this.saved=v===null?null:parsePrivateTranscript(v,this.options.scope,this.options.recording.snapshot.recordingId);if(this.saved)this.matches(await this.source(),this.saved);return this.view();}
 view(){return this.saved?structuredClone(this.saved):null;}
 private async persist(next:PrivateTranscript){this.current();parsePrivateTranscript(next,this.options.scope,next.recordingId);await this.options.store.write(this.key(),this.saved,next);this.current();this.saved=next;}
 private async source(){this.current();const audio=await this.options.recording.snapshotForPrivateTranscript();this.current();need(audio.phase==='sealed'&&audio.recordingId===this.options.recording.snapshot.recordingId&&audio.scope===this.options.scope&&audio.chunks>0&&audio.chunks<=360&&audio.frames>0&&audio.frames<=57600000&&hash(audio.audioSHA256));if(audio.chunks>60||audio.frames>9600000)throw fail('private_speech_too_long');return audio;}
 private matches(audio:Awaited<ReturnType<PrivateTranscriptAudio['snapshotForPrivateTranscript']>>,saved:PrivateTranscript){need(saved.source.audioSHA256===audio.audioSHA256&&saved.source.chunks===audio.chunks&&saved.source.frames===audio.frames);}
 /** Only an explicit owner gesture calls this method. Loading/reopening never recognizes audio. */
 async transcribe():Promise<PrivateTranscript>{this.current();if(this.running)throw fail();this.running=true;let begun:string|null=null;
  try{const audio=await this.source();if(audio.consent.language!=='en-US')throw fail('private_speech_language_unsupported');if(this.saved){this.matches(audio,this.saved);if(this.saved.raw)return this.view()!;}
   const now=new Date().toISOString(),next:PrivateTranscript={contract:'cosmabot.private-transcript.v1',scope:this.options.scope,recordingId:audio.recordingId,workspaceId:this.options.recording.snapshot.workspaceId,source:{audioSHA256:audio.audioSHA256,chunks:audio.chunks,frames:audio.frames},language:'en-US',intent:crypto.randomUUID(),state:'running',raw:null,working:'',revision:(this.saved?.revision??0)+1,createdAt:this.saved?.createdAt??now,updatedAt:now};await this.persist(next);
   const begin=await this.options.native.begin({scope:this.options.scope,revision:this.options.revision,recordingId:audio.recordingId,audioSHA256:audio.audioSHA256,chunks:audio.chunks,frames:audio.frames,language:'en-US',intent:next.intent});begun=begin.runId;need(uuid(begun));this.runId=begun;this.current();let frames=0,count=0;
   for await(const chunk of this.options.recording.savedChunks()){this.current();need(chunk.sequence===count&&hash(chunk.sha256)&&chunk.wavBytes.length>=46&&chunk.wavBytes.length<=320044);frames+=(chunk.wavBytes.length-44)/2;let encoded='';for(const byte of chunk.wavBytes)encoded+=String.fromCharCode(byte);
    const receipt=await this.options.native.append({runId:begun,sequence:count,sha256:chunk.sha256,wavBase64:btoa(encoded)});encoded='';this.current();need(receipt.sequence===count);count++;this.options.onProgress?.(count,audio.chunks);
   }
   need(frames===audio.frames&&count===audio.chunks);this.matches(await this.source(),next);need(this.options.recording.snapshot.workspaceId===next.workspaceId);
   const result=await this.options.native.finish({runId:begun});this.current();need(closed(result,'runId,recordingId,audioSHA256,frames,text,engine,language')&&result.runId===begun&&result.recordingId===audio.recordingId&&result.audioSHA256===audio.audioSHA256&&result.frames===audio.frames&&result.engine==='ios-speech-on-device-v1'&&result.language==='en-US');text(result.text);if(!result.text.trim())throw fail('private_speech_empty');this.matches(await this.source(),next);need(this.options.recording.snapshot.workspaceId===next.workspaceId);
   const completedAt=new Date().toISOString(),ready:PrivateTranscript={...next,state:'ready',raw:{text:result.text,engine:result.engine,completedAt},working:result.text,updatedAt:completedAt};await this.persist(ready);return ready;
  }catch(error){if(this.alive&&this.options.isCurrent()&&this.saved?.state==='running'){await this.persist({...this.saved,state:'interrupted',updatedAt:new Date().toISOString()}).catch(()=>{});}throw error;
  }finally{if(begun)await this.options.native.cancel({runId:begun}).catch(()=>{});if(this.runId===begun)this.runId=null;this.running=false;}
 }
 async saveWorking(working:string){this.current();text(working);need(!this.running&&this.saved?.state==='ready'&&this.saved.raw);this.matches(await this.source(),this.saved);await this.persist({...this.saved,working,revision:this.saved.revision+1,updatedAt:new Date().toISOString()});return this.view()!;}
 async close(){this.alive=false;const run=this.runId;if(run)await this.options.native.cancel({runId:run}).catch(()=>{});this.options.store.close();}
}
