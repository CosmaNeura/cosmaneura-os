import type {CaptureSource,CaptureSourceStartOptions} from '../../clients/capture/src/capture/source';
import type {CaptureAttestation,CaptureLanguage} from './capture-api';

interface PrivateDesktopPort {
  enabled:boolean;
  privateAcquire(value:{requestId:string;revision:string;recordingId:string;consent:CaptureAttestation&{language:CaptureLanguage}}):Promise<unknown>;
  privateRelease(value:{requestId:string;permitId:string}):Promise<unknown>;
  privateIdle(value:{requestId:string;revision:string}):Promise<unknown>;
  onPrivateRevoked(listener:(value:{permitId:string})=>void):()=>void;
}
interface PrivateDesktopAuth {getState():Promise<{phase:string;revision:string}>}
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const unavailable=()=>new Error('Private microphone unavailable. Saved audio is retained.');
function exact(value:unknown,keys:string):Record<string,unknown>{if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!==keys)throw unavailable();return value as Record<string,unknown>;}
function shell(){const value=window as unknown as {cosmasDesktopCapture?:PrivateDesktopPort;cosmasDesktopAuth?:PrivateDesktopAuth};
  if(!value.cosmasDesktopAuth)return null;const port=value.cosmasDesktopCapture;
  if(!port?.enabled||!port.privateAcquire||!port.privateRelease||!port.privateIdle||!port.onPrivateRevoked)throw unavailable();return {port,auth:value.cosmasDesktopAuth};}

/** The app's main process retains physical exclusion across renderer lifetimes.
 * A browser-only page still uses the existing origin lock and browser producer. */
export function privateDesktopRecordingSource(source:CaptureSource,context?:{recordingId:string;consent:CaptureAttestation&{language:CaptureLanguage}},injected?:{port:PrivateDesktopPort;auth:PrivateDesktopAuth}):CaptureSource{
  const native=injected??shell();if(!native)return source;
  let permit:string|null=null,starting=false,stopped=false,physicallyClosed=false,remove:(()=>void)|null=null;
  const release=async()=>{if(!permit)return;const id=permit,requestId=crypto.randomUUID();const result=exact(await native.port.privateRelease({requestId,permitId:id}),'released,requestId');
    if(result.requestId!==requestId||result.released!==true)throw unavailable();if(permit===id){permit=null;remove?.();remove=null;}};
  const stop=async()=>{stopped=true;await source.stop();physicallyClosed=true;if(starting)throw unavailable();await release();};
  return {kind:'microphone',
    confirmRecoveryClosed:async()=>{const state=await native.auth.getState();if(state.phase!=='ready'||!uuid.test(state.revision))return false;const requestId=crypto.randomUUID();
      const result=exact(await native.port.privateIdle({requestId,revision:state.revision}),'idle,requestId');return result.requestId===requestId&&result.idle===true;},
    start:async(options:CaptureSourceStartOptions)=>{if(!context||permit||starting||stopped||options.authority)throw unavailable();starting=true;
      try{const state=await native.auth.getState();if(state.phase!=='ready'||!uuid.test(state.revision)||stopped)throw unavailable();const requestId=crypto.randomUUID();
        const result=exact(await native.port.privateAcquire({requestId,revision:state.revision,recordingId:context.recordingId,consent:context.consent}),'expiresAt,permitId,requestId,revision');
        if(result.requestId!==requestId||result.revision!==state.revision||typeof result.permitId!=='string'||!uuid.test(result.permitId)||typeof result.expiresAt!=='string'||Date.parse(result.expiresAt)<=Date.now()||Date.parse(result.expiresAt)>Date.now()+901000)throw unavailable();
        permit=result.permitId;remove=native.port.onPrivateRevoked(value=>{if(value.permitId===permit){stopped=true;void source.stop().then(()=>{physicallyClosed=true;return !starting?release():undefined;}).catch(()=>{});options.onInterruption?.('capture_backgrounded');}});
        if(stopped)throw unavailable();await source.start(options);
      }catch(error){stopped=true;await source.stop();physicallyClosed=true;throw error;}
      finally{starting=false;if(stopped&&physicallyClosed)await release();}
    },stop};
}
