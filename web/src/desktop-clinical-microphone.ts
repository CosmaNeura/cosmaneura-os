import type {CaptureSource} from '../../clients/capture/src/configured/capture';
import type {CaptureFlowStore} from '../../clients/capture/src/configured/flow/types';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
interface Port {enabled:boolean;clinicalAcquire(v:{requestId:string;revision:string;workspaceId:string;sessionId:string;leaseId:string;leaseReceiptId:string;leaseGeneration:number;captureAuthorizedUntil:string;firstSequenceNumber:number}):Promise<unknown>;clinicalRelease(v:{requestId:string;permitId:string}):Promise<unknown>;clinicalActive(v:{requestId:string;permitId:string}):Promise<unknown>;onPrivateRevoked(listener:(v:{permitId:string})=>void):()=>void}
const unavailable=()=>new Error('Desktop microphone could not be confirmed. Saved audio is retained.');
const uuid=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
function exact(value:unknown,keys:string):Record<string,unknown>{if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).sort().join(',')!==keys)throw unavailable();return value as Record<string,unknown>;}
/** Current configured browser microphone retains native stop custody and the
 * main process's physical exclusion; lease metadata never becomes authority. */
export function desktopClinicalMicrophone(source:CaptureSource,flow:Pick<CaptureFlowStore,'getActiveCaptureState'>,workspaceId:string,sessionId:string,identity:Extract<AuthenticatedWorkspaceIdentity,{mode:'desktop_native'}>,injected?:Port):CaptureSource{
  const port=injected??(window.cosmasDesktopCapture as unknown as Port);if(!port?.enabled||!port.clinicalAcquire||!port.clinicalRelease||!port.clinicalActive||!port.onPrivateRevoked)throw unavailable();
  let permit:string|null=null,starting=false,stopped=false,physicallyClosed=false,remove:(()=>void)|null=null;
  const release=async()=>{if(!permit)return;const id=permit,requestId=crypto.randomUUID(),result=exact(await port.clinicalRelease({requestId,permitId:id}),'released,requestId');if(result.requestId!==requestId||result.released!==true)throw unavailable();permit=null;remove?.();remove=null;};
  return {kind:source.kind,
    start:async options=>{if(starting||permit||!identity.isCurrent())throw unavailable();starting=true;stopped=false;physicallyClosed=false;
      try{const active=await flow.getActiveCaptureState();if(!identity.isCurrent()||!active||active.phase!=='recording'||active.sessionId!==sessionId||active.reviewAfterUpload!==true||(active.channel??'microphone')!=='microphone'||!active.captureAuthorizedUntil)throw unavailable();
        const requestId=crypto.randomUUID(),result=exact(await port.clinicalAcquire({requestId,revision:identity.revision,workspaceId,sessionId,leaseId:active.lease.lease_id,leaseReceiptId:active.lease.receipt_id,leaseGeneration:active.lease.generation,captureAuthorizedUntil:active.captureAuthorizedUntil,firstSequenceNumber:active.continuation?.firstSequenceNumber??0}),'admitted,expiresAt,permitId,requestId,revision');
        if(result.requestId!==requestId||result.revision!==identity.revision||typeof result.permitId!=='string'||!uuid.test(result.permitId)||typeof result.admitted!=='boolean')throw unavailable();permit=result.permitId;
        if(!result.admitted||stopped||!identity.isCurrent()||options.signal?.aborted)throw unavailable();
        remove=port.onPrivateRevoked(value=>{if(value.permitId===permit){stopped=true;void source.stop().then(()=>{physicallyClosed=true;return !starting?release():undefined;}).catch(()=>{});options.onInterruption?.('capture_backgrounded');}});
        const after=await flow.getActiveCaptureState();if(!identity.isCurrent()||!after||after.phase!=='recording'||after.lease.lease_id!==active.lease.lease_id||after.lease.receipt_id!==active.lease.receipt_id||after.captureAuthorizedUntil!==active.captureAuthorizedUntil)throw unavailable();await source.start(options);
        const activeRequest=crypto.randomUUID(),confirmed=exact(await port.clinicalActive({requestId:activeRequest,permitId:permit}),'active,requestId');if(confirmed.requestId!==activeRequest||confirmed.active!==true||!identity.isCurrent()||stopped)throw unavailable();
      }catch(error){stopped=true;await source.stop();physicallyClosed=true;throw error;}
      finally{starting=false;if(stopped&&physicallyClosed)await release();}
    },stop:async()=>{stopped=true;await source.stop();physicallyClosed=true;if(starting)throw unavailable();await release();}};
}
