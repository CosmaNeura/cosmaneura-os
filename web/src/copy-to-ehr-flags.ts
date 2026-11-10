import {workspaceApiBase} from './workspace-base';
import {workspaceFetch} from './workspace-protocol';
import {permittedWorkspaceApi} from './workspace-origin';
import {workspaceAuthHeaders,assertCurrentDesktopSession} from './workspace-auth-headers';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {COPY_TO_EHR_FLAGS_OFF,parseCopyToEhrFlags,type CopyToEhrFlags} from './copy-to-ehr-flag-store';

export {COPY_TO_EHR_FLAGS_OFF,copyToEhrFlagProps,parseCopyToEhrFlags,type CopyToEhrFlags} from './copy-to-ehr-flag-store';

/** Direct read of GET /api/copy-to-ehr/flags. A failed read stays off. No build-time switch. */
export async function fetchCopyToEhrFlags(
  identity:AuthenticatedWorkspaceIdentity,
  signal?:AbortSignal,
):Promise<CopyToEhrFlags>{
  const controller=new AbortController();
  const abort=()=>controller.abort();
  const timer=setTimeout(abort,20_000);
  signal?.addEventListener('abort',abort,{once:true});
  if(signal?.aborted)abort();
  try{
    const base=workspaceApiBase(identity);
    if(!permittedWorkspaceApi(base,import.meta.env.VITE_DESKTOP_SYNTHETIC_ENABLED==='true',window.location.href)){
      return COPY_TO_EHR_FLAGS_OFF;
    }
    const headers=await workspaceAuthHeaders(identity,base);
    assertCurrentDesktopSession(identity);
    const response=await workspaceFetch(identity,`${base}/api/copy-to-ehr/flags`,{
      method:'GET',cache:'no-store',credentials:'omit',redirect:'error',referrerPolicy:'no-referrer',
      headers,signal:controller.signal,
    });
    assertCurrentDesktopSession(identity);
    if(!response.ok)return COPY_TO_EHR_FLAGS_OFF;
    return parseCopyToEhrFlags(await response.json());
  }catch{
    return COPY_TO_EHR_FLAGS_OFF;
  }finally{
    clearTimeout(timer);
    signal?.removeEventListener('abort',abort);
    controller.abort();
  }
}
