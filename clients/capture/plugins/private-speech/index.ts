import {registerPlugin} from '@capacitor/core';
export type PrivateSpeechSource={scope:string;revision:string;recordingId:string;audioSHA256:string;chunks:number;frames:number;language:'en-US';intent:string};
export interface PrivateSpeechPlugin {
  begin(source:PrivateSpeechSource):Promise<{runId:string}>;
  append(input:{runId:string;sequence:number;sha256:string;wavBase64:string}):Promise<{sequence:number}>;
  finish(input:{runId:string}):Promise<{runId:string;recordingId:string;audioSHA256:string;frames:number;text:string;engine:'ios-speech-on-device-v1';language:'en-US'}>;
  cancel(input:{runId:string}):Promise<void>;
}
export const PrivateSpeech=registerPlugin<PrivateSpeechPlugin>('CosmasPrivateSpeech');
