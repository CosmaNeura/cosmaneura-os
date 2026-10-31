import {WorkspaceApiError,type WorkspaceIdentity} from './workspace-api';

export const WORKSPACE_ENROLLMENT_HEADER='X-Cosmas-Enrollment-Admission';
export type WorkspaceEnrollmentHold='workspace_enrollment_access_required'|'workspace_enrollment_admission_unavailable';
type State={hold:WorkspaceEnrollmentHold|null;revision:number;listeners:Set<()=>void>};
const identities=new WeakMap<object,State>();
function state(identity:WorkspaceIdentity):State{
  let value=identities.get(identity);if(!value){value={hold:null,revision:0,listeners:new Set()};identities.set(identity,value);}return value;
}
export const workspaceEnrollmentHold=(identity:WorkspaceIdentity)=>state(identity).hold;
export const workspaceEnrollmentRevision=(identity:WorkspaceIdentity)=>state(identity).revision;
export function subscribeWorkspaceEnrollment(identity:WorkspaceIdentity,listener:()=>void){const value=state(identity);value.listeners.add(listener);return()=>{value.listeners.delete(listener);};}
export function observeWorkspaceEnrollment(identity:WorkspaceIdentity|undefined,response:Response):WorkspaceApiError|null{
  const code=response.headers?.get(WORKSPACE_ENROLLMENT_HEADER);
  if(!(response.status===403&&code==='workspace_enrollment_access_required'||response.status===503&&code==='workspace_enrollment_admission_unavailable'))return null;
  if(!identity||!('mode'in identity))return null;
  // Only an enrollment denial adds a currency check; ordinary responses keep
  // their existing transport contracts. An obsolete session cannot set a hold.
  try{if(identity.mode==='desktop_native'?!identity.isCurrent():identity.nativeSession&&!identity.nativeSession.isCurrent())return new WorkspaceApiError(401);}
  catch{return new WorkspaceApiError(401);}
  const value=state(identity);value.hold=code;value.revision++;for(const listener of value.listeners)listener();return new WorkspaceApiError(response.status,code);
}
/** Only a complete fresh protected probe may release the observed hold. */
export function releaseWorkspaceEnrollment(identity:WorkspaceIdentity,revision:number){const value=state(identity);
  if(value.revision!==revision)throw new WorkspaceApiError(403,value.hold??'workspace_enrollment_access_required');
  value.hold=null;value.revision++;for(const listener of value.listeners)listener();
}
