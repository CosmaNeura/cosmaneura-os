import {PrivateSpeech,type PrivateSpeechPlugin} from '../../clients/capture/plugins/private-speech';
export type {PrivateSpeechPlugin,PrivateSpeechSource} from '../../clients/capture/plugins/private-speech';
export const privateSpeechNative:PrivateSpeechPlugin=PrivateSpeech;
export function privateTranscriptionMessage(error:unknown):string {
 const code=error&&typeof error==='object'&&'code'in error?String(error.code):'';
 const reason:Record<string,string>={
  private_speech_permission_denied:'Speech recognition access is not allowed. Enable it in iPhone Settings when you are ready.',
  private_speech_permission_restricted:'Speech recognition is restricted on this iPhone.',
  private_speech_language_unsupported:'On-device transcription currently supports English recordings. This recording’s language is unsupported.',
  private_speech_unavailable:'On-device speech recognition is unavailable for this language on this iPhone. No audio was sent to a server.',
  private_speech_inactive:'Transcription paused when CosmaBot became inactive. Keep the app open and choose Transcribe again.',
  private_speech_empty:'No words were recognized. Play the saved clip to check its audio, then try again.',
  private_speech_too_long:'Private on-device transcription supports saved recordings up to ten minutes.',
  private_speech_incomplete:'The on-device recognizer stopped before the complete recording was recognized. Try again with a shorter recording.',
  private_speech_timeout:'This iPhone could not finish recognizing the clip. Keep CosmaBot open and try again.',
  private_speech_changed:'The recording or signed-in owner changed. Reopen the original recording before continuing.',
 };
 return (reason[code]??'This iPhone could not finish private transcription. Try again when on-device speech recognition is available.')+' Your original encrypted audio is retained.';
}
