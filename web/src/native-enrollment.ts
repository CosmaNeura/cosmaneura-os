import type {NativePracticeConnectionPlugin} from '../../clients/capture/src/native/practice-connection-plugin';
import {EnrollmentError} from './enrollment-contract';
import {enrollmentApiForOwnedTransport,type EnrollmentApi,type EnrollmentIdentity,type EnrollmentRequest} from './enrollment-api';

export type NativeAccountState=Readonly<{phase:'signedOut'|'signingIn'|'accountReady'|'unavailable';revision:string;
  identity:Readonly<{userId:string;sessionId:string;email:string;displayName:string}>|null}>;
const uuid=/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const closed=(value:unknown,keys:string[]):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value)&&
  Object.keys(value).sort().join(',')===[...keys].sort().join(',')&&Reflect.ownKeys(value).length===keys.length&&
  Object.values(Object.getOwnPropertyDescriptors(value)).every(property=>'value'in property&&property.enumerable);
const invalid=():never=>{throw new EnrollmentError(401,'enrollment_authentication_required');};
/** An account deliberately has no clinical organization and cannot be a WorkspaceIdentity. */
export function parseNativeAccountState(value:unknown):NativeAccountState {
  if(!closed(value,['phase','revision','identity'])||typeof value.phase!=='string'||
    !['signedOut','signingIn','accountReady','unavailable'].includes(value.phase)||typeof value.revision!=='string'||!uuid.test(value.revision))return invalid();
  let identity:NativeAccountState['identity']=null;
  if(value.phase==='accountReady'){
    if(!closed(value.identity,['userId','sessionId','email','displayName'])||
      typeof value.identity.userId!=='string'||!/^user_[A-Za-z0-9_]{1,250}$/.test(value.identity.userId)||
      typeof value.identity.sessionId!=='string'||!/^sess_[A-Za-z0-9_]{1,250}$/.test(value.identity.sessionId)||
      typeof value.identity.email!=='string'||value.identity.email.length>320||!/^\S+@\S+\.\S+$/.test(value.identity.email)||
      typeof value.identity.displayName!=='string'||value.identity.displayName.length>120||/[\u0000-\u001f\u007f]/.test(value.identity.displayName))return invalid();
    identity=Object.freeze({userId:value.identity.userId,sessionId:value.identity.sessionId,email:value.identity.email,displayName:value.identity.displayName});
  }else if(value.identity!==null)return invalid();
  return Object.freeze({phase:value.phase as NativeAccountState['phase'],revision:value.revision,identity});
}
export const NATIVE_ENROLLMENT_OPERATIONS={
  '/config':['config','GET'],'/status':['status','GET'],'/practices':['practices','GET'],
  '/select-practice':['selectPractice','POST'],'/profile':['profile','PUT'],'/practice':['practice','PUT'],
  '/join':['join','POST'],'/baa/current':['document','GET'],'/baa/accept':['accept','POST'],'/baa/receipt':['receipt','GET'],
  '/quote':['quote','GET'],'/checkout':['checkout','POST'],'/recover':['recover','POST'],
  '/workspace/confirm':['confirmWorkspace','POST'],'/invitations':['invitation','POST'],'/portal':['portal','POST'],
} as const;
export type NativeEnrollmentOperation=typeof NATIVE_ENROLLMENT_OPERATIONS[keyof typeof NATIVE_ENROLLMENT_OPERATIONS][0];
export interface NativeEnrollmentPort extends NativePracticeConnectionPlugin {
  enrollmentRequest(options:{expectedRevision:string;operation:NativeEnrollmentOperation;body?:object;idempotencyKey?:string}):Promise<unknown>;
  openEnrollmentDestination(options:{expectedRevision:string;destination:'checkout'|'portal'}):Promise<unknown>;
}
/** Method presence is only a UI hint. The native capability receipt and server authorize every operation. */
export function nativeEnrollmentPort(plugin:NativePracticeConnectionPlugin):NativeEnrollmentPort|null {
  const candidate=plugin as NativeEnrollmentPort;
  return typeof candidate.enrollmentRequest==='function'&&typeof candidate.openEnrollmentDestination==='function'?candidate:null;
}
export function nativeEnrollmentCapabilities(value:unknown):boolean {
  if(!closed(value,['contract_version','available','enrollment_available'])||
    value.contract_version!=='cosmabot.native-practice-connection.v1'||typeof value.available!=='boolean'||typeof value.enrollment_available!=='boolean')return false;
  return value.available&&value.enrollment_available;
}
/** Separate optional contract: older hosts keep the existing closed v1 shape. */
export function nativeSelectedPracticeCapabilities(value:unknown):boolean {
  return closed(value,['contract_version','available'])&&value.contract_version==='cosmabot.native-selected-practice.v1'&&value.available===true;
}
/** Resume an already explicit native account transition on a replacement scene.
 * This selects a presentation only; account/clinical authority still comes from
 * the host and server. No browser flag, query parameter or installer is read.
 */
export function nativeAccountEntryRequested(available:boolean):boolean {
  if(!available||typeof window==='undefined')return false;
  const descriptor=Object.getOwnPropertyDescriptor(window,'__cosmasNativePracticeEntry');
  if(!descriptor)return false;
  return Object.hasOwn(descriptor,'value')&&descriptor.writable===false&&descriptor.configurable===false&&
    closed(descriptor.value,['contract_version','entry'])&&Object.isFrozen(descriptor.value)&&
    descriptor.value.contract_version==='cosmabot.native-practice-entry.v1'&&descriptor.value.entry==='account';
}

/** No URL, issuer, Org, Box, browser fetch or credential is passed to this port. */
export function createNativeEnrollmentApi(port:NativeEnrollmentPort,current:()=>NativeAccountState|null,isActive:()=>boolean):EnrollmentApi {
  const request:EnrollmentRequest=async<T,>(path:string,validate:(value:unknown)=>T,identity?:EnrollmentIdentity,body?:object,key?:string,signal?:AbortSignal,method=body?'POST':'GET')=>{
    const captured=current(),operation=NATIVE_ENROLLMENT_OPERATIONS[path as keyof typeof NATIVE_ENROLLMENT_OPERATIONS];
    if(!captured||!isActive()||!operation||operation[1]!==method)throw new EnrollmentError(503);
    if(key&&!/^[A-Za-z0-9_-]{1,128}$/.test(key)||body&&new TextEncoder().encode(JSON.stringify(body)).length>16384)throw new EnrollmentError(422);
    const check=()=>{if(signal?.aborted)throw new EnrollmentError(503);
      if(!isActive()||current()?.revision!==captured.revision||identity&&!identity.isCurrent())throw new EnrollmentError(401,'enrollment_authentication_required');};
    let reject!: (reason:EnrollmentError)=>void;
    const interrupted=new Promise<never>((_,no)=>{reject=no;});void interrupted.catch(()=>{});
    const abort=()=>reject(new EnrollmentError(503));signal?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(()=>reject(new EnrollmentError(504)),15000);
    try{
      check();const result=await Promise.race([port.enrollmentRequest({expectedRevision:captured.revision,operation:operation[0],
        ...(body?{body}:{}),...(key?{idempotencyKey:key}:{})}),interrupted]);check();
      if(!closed(result,['status','body'])||!Number.isSafeInteger(result.status)||(result.status as number)<200||(result.status as number)>599||
        new TextEncoder().encode(JSON.stringify(result.body)).length>600000)throw new EnrollmentError(502);
      if((result.status as number)<200||(result.status as number)>=300){
        const detail=result.body&&typeof result.body==='object'&&'detail'in result.body?result.body.detail:null;
        const code=detail&&typeof detail==='object'&&'code'in detail?detail.code:detail;
        throw new EnrollmentError(result.status as number,typeof code==='string'&&/^enrollment_[a-z_]{1,80}$/.test(code)?code:'enrollment_unavailable');
      }
      return validate(result.body);
    }catch(error){if(error instanceof EnrollmentError)throw error;throw new EnrollmentError(503);}
    finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
  };
  return enrollmentApiForOwnedTransport(request);
}
