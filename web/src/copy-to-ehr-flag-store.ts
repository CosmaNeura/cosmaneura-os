import type {WorkspaceIdentity} from './workspace-api';

/** Runtime copy-to-EHR switches. All stay false until an API response says otherwise. */
export type CopyToEhrFlags={
  enabled:boolean;
  remoteEnabled:boolean;
  fallbackOffer:boolean;
};

export const COPY_TO_EHR_FLAGS_OFF:CopyToEhrFlags={
  enabled:false,
  remoteEnabled:false,
  fallbackOffer:false,
};

const HEADER='x-cosmas-copy-to-ehr-flags';
const flagsByIdentity=new WeakMap<object, CopyToEhrFlags>();
const listeners=new WeakMap<object, Set<(flags:CopyToEhrFlags)=>void>>();

export function parseCopyToEhrFlags(value:unknown):CopyToEhrFlags{
  if(!value||typeof value!=='object')return COPY_TO_EHR_FLAGS_OFF;
  const row=value as Record<string,unknown>;
  return freezeFlags({
    enabled:row.copy_to_ehr_enabled===true,
    remoteEnabled:row.copy_to_ehr_remote_enabled===true,
    fallbackOffer:row.copy_to_ehr_fallback_enabled===true,
  });
}

export function parseCopyToEhrFlagHeader(value:string|null):CopyToEhrFlags|null{
  const match=/^([01]),([01]),([01])$/.exec(value?.trim()??'');
  if(!match)return null;
  return freezeFlags({
    enabled:match[1]==='1',
    remoteEnabled:match[2]==='1',
    fallbackOffer:match[3]==='1',
  });
}

function freezeFlags(flags:CopyToEhrFlags):CopyToEhrFlags{
  if(!flags.enabled&&!flags.remoteEnabled&&!flags.fallbackOffer)return COPY_TO_EHR_FLAGS_OFF;
  return flags;
}

function same(left:CopyToEhrFlags, right:CopyToEhrFlags){
  return left.enabled===right.enabled&&left.remoteEnabled===right.remoteEnabled&&left.fallbackOffer===right.fallbackOffer;
}

export function copyToEhrFlagsFor(identity:object|undefined):CopyToEhrFlags{
  if(!identity)return COPY_TO_EHR_FLAGS_OFF;
  return flagsByIdentity.get(identity)??COPY_TO_EHR_FLAGS_OFF;
}

export function observeCopyToEhrFlags(identity:WorkspaceIdentity|undefined, response:Response){
  try{
    if(!identity||typeof response?.headers?.get!=='function')return;
    const next=parseCopyToEhrFlagHeader(response.headers.get(HEADER));
    if(!next)return;
    const previous=flagsByIdentity.get(identity)??COPY_TO_EHR_FLAGS_OFF;
    if(same(previous, next))return;
    flagsByIdentity.set(identity, next);
    listeners.get(identity)?.forEach(listener=>listener(next));
  }catch{
    // A missing flag header leaves copy-to-EHR off. Never log the response.
  }
}

export function subscribeCopyToEhrFlags(identity:object, listener:(flags:CopyToEhrFlags)=>void){
  const group=listeners.get(identity)??new Set<(flags:CopyToEhrFlags)=>void>();
  group.add(listener);
  listeners.set(identity, group);
  return ()=>{group.delete(listener);};
}

export function copyToEhrFlagProps(flags:CopyToEhrFlags){
  return {
    copyToEhrEnabled:flags.enabled,
    copyToEhrFallbackOffer:flags.fallbackOffer,
    copyToEhrRemoteEnabled:flags.remoteEnabled,
  };
}
