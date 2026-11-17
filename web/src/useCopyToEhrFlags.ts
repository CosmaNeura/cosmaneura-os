import {useEffect,useState} from 'react';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {
  COPY_TO_EHR_FLAGS_OFF,
  copyToEhrFlagsFor,
  subscribeCopyToEhrFlags,
  type CopyToEhrFlags,
} from './copy-to-ehr-flag-store';

/** Flags from API responses the workspace already receives. Starts off. */
export function useCopyToEhrFlags(identity:AuthenticatedWorkspaceIdentity|undefined):CopyToEhrFlags{
  const [flags,setFlags]=useState<CopyToEhrFlags>(COPY_TO_EHR_FLAGS_OFF);
  useEffect(()=>{
    if(!identity){setFlags(COPY_TO_EHR_FLAGS_OFF);return;}
    setFlags(copyToEhrFlagsFor(identity));
    return subscribeCopyToEhrFlags(identity,setFlags);
  },[identity]);
  return flags;
}
