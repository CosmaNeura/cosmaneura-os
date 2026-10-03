import {encodePcm16MonoWav,pcm16WavProfile,type CaptureSourceStartOptions} from '../../clients/capture/src/capture';
export const IOS_NATIVE_PCM_CAPTURE_ENABLED=false;
export const isIosNativePlatform=async()=>false;
export const evidence={starts:0,stops:0};
let options:CaptureSourceStartOptions|null=null;
export async function emit(number:number){if(!options)throw new Error('Capture not started');const frames=number<2?16000:2400;const samples=new Int16Array(frames);for(let i=0;i<frames;i++)samples[i]=((i*17+(number+1)*101)%24001)-12000;const wavBytes=encodePcm16MonoWav(samples,pcm16WavProfile(options.capabilities));await options.onChunk({sequenceNumber:number,durationMs:frames/16,wavBytes});if(!wavBytes.every(b=>b===0))throw new Error('Recording client did not clear generated audio');}
export async function createCaptureSource(){return {kind:'synthetic' as const,async start(value:CaptureSourceStartOptions){if(options)throw new Error('Duplicate active capture');options=value;evidence.starts++;},async stop(){if(options){await emit(2);options=null;evidence.stops++;}}};}
