/** Local visual acceptance uses actual encrypted recording with generated PCM. */
import {PrivateRecordingRuntime as ActualRuntime,type PrivateRecordingOptions} from '../src/private-recording-runtime';
import type {CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import {encodePcm16MonoWav} from '../../clients/capture/src/capture/wav';
export * from '../src/private-recording-runtime';
export type PrivateRecordingRuntime=ActualRuntime;
export const PrivateRecordingRuntime={
  open(options:PrivateRecordingOptions,input:Parameters<typeof ActualRuntime.open>[1]){
    return ActualRuntime.open({...options,createSource:async()=>{
      let timer:ReturnType<typeof setInterval>|undefined,sequence=0,chain=Promise.resolve();
      return {kind:'microphone' as const,start:async(start:CaptureSourceStartOptions)=>{
        timer=setInterval(()=>{if(sequence>=start.capabilities.max_chunks){clearInterval(timer);start.onWindowClosed?.();return;}const samples=new Int16Array(16000);for(let i=0;i<samples.length;i++)samples[i]=Math.round(4000*Math.sin(i*0.08));
          start.onInputLevel?.(0.4);const chunk={sequenceNumber:sequence++,durationMs:1000,wavBytes:encodePcm16MonoWav(samples,{sampleRateHz:16000,channels:1,targetChunkDurationMs:10000,maxEnvelopeBytes:320044})};chain=chain.then(()=>start.onChunk(chunk)).catch(()=>{clearInterval(timer);start.onError?.(new Error('Synthetic audio storage failed'));});},1000);
      },stop:async()=>{clearInterval(timer);await chain;}};
    }},input);
  }
};
