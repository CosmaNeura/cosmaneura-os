import {Capacitor} from '@capacitor/core';
import {IOSPCM,type IOSPCMPlugin,type IosPrivateRecordingConsent,type IosPrivateRecordingReceipt} from '../../plugins/ios-pcm';
import {CapacitorIosNativePcmBridge} from './capacitor-ios-native-pcm-bridge';
import {IosNativeMicrophoneCaptureSource} from './ios-native-microphone-source';
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
function available(){if(Capacitor.getPlatform()!=='ios'||!Capacitor.isPluginAvailable('IOSPCM'))throw new Error('Private microphone unavailable');}
let cache:{key:string;receipt:IosPrivateRecordingReceipt|null;flight:Promise<IosPrivateRecordingReceipt>|null}|null=null;
export function invalidatePrivateRecordingNativeReceipt(){cache=null;}
export function consumePrivateRecordingNativeReceipt(receipt:IosPrivateRecordingReceipt):Pick<IosPrivateRecordingReceipt,'receiptId'|'revision'>|null{
  if(!cache?.receipt||cache.receipt.receiptId!==receipt.receiptId||cache.receipt.revision!==receipt.revision||Date.parse(cache.receipt.expiresAt)<=Date.now())return null;
  cache=null;return {receiptId:receipt.receiptId,revision:receipt.revision};
}

/** Native account proof only, never a token or clinical capture admission. */
export async function prewarmPrivateRecordingNative(options:{scope:string;revision:string},plugin:IOSPCMPlugin=IOSPCM):Promise<IosPrivateRecordingReceipt>{
  available();if(!plugin.preparePrivate||!/^[a-f0-9]{64}$/.test(options.scope)||!uuid.test(options.revision))throw new Error('Private microphone unavailable');
  const key=options.scope+':'+options.revision;
  if(cache?.key===key){if(cache.receipt&&Date.parse(cache.receipt.expiresAt)>Date.now())return structuredClone(cache.receipt);if(cache.flight)return cache.flight;}
  const selected={key,receipt:null as IosPrivateRecordingReceipt|null,flight:null as Promise<IosPrivateRecordingReceipt>|null};cache=selected;
  const flight=(async()=>{const result=await plugin.preparePrivate!(options);
  if(!result||Object.keys(result).sort().join(',')!=='expiresAt,receiptId,revision'||!uuid.test(result.receiptId)||result.revision!==options.revision||typeof result.expiresAt!=='string'||!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(result.expiresAt)||new Date(result.expiresAt).toISOString()!==result.expiresAt||Date.parse(result.expiresAt)<=Date.now()||Date.parse(result.expiresAt)>Date.now()+301000||cache!==selected)throw new Error('Private microphone unavailable');
    selected.receipt=structuredClone(result);return structuredClone(result);
  })().catch(error=>{if(cache===selected)cache=null;throw error;}).finally(()=>{selected.flight=null;});selected.flight=flight;return flight;
}

/** Explicit private recording uses the owned real foreground PCM source, never a silent fallback. */
export function privateIosRecordingSource(context:{scope:string;recordingId:string;consent:IosPrivateRecordingConsent;receipt:Pick<IosPrivateRecordingReceipt,'receiptId'|'revision'>},plugin:IOSPCMPlugin=IOSPCM){
  available();if(!plugin.startPrivate)throw new Error('Private microphone unavailable');
  const selected=structuredClone(context),startIntent=crypto.randomUUID();let used=false;
  const privatePlugin:IOSPCMPlugin={
    getAppState:()=>plugin.getAppState(),confirmCaptureIdle:()=>plugin.confirmCaptureIdle?.()??Promise.resolve({version:1,idle:false}),
    start:options=>{if(used||options.authority)throw new Error('Private microphone unavailable');used=true;
      return plugin.startPrivate!({...options,receiptId:selected.receipt.receiptId,revision:selected.receipt.revision,scope:selected.scope,recordingId:selected.recordingId,consent:selected.consent,startIntent});},
    ready:o=>plugin.ready(o),heartbeat:o=>plugin.heartbeat(o),stop:o=>plugin.stop(o),acknowledge:o=>plugin.acknowledge(o),replayPendingPacket:o=>plugin.replayPendingPacket(o),addListener:(name,listener)=>plugin.addListener(name,listener),
  };
  return new IosNativeMicrophoneCaptureSource(new CapacitorIosNativePcmBridge(privatePlugin));
}
