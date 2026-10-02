import type {AuthenticatedWorkspaceIdentity} from './workspace-api';

type Observation = {resumed:()=>void;suspended:()=>void};
const observers = new WeakMap<AuthenticatedWorkspaceIdentity,Set<Observation>>();
const foreground = new WeakMap<AuthenticatedWorkspaceIdentity,boolean>();

// The native scene signal carries no identity or data. Authentication owns
// revalidation before this private, identity-scoped observation hint is emitted.
export function subscribeNativeWorkspaceForeground(identity:AuthenticatedWorkspaceIdentity,
  resumed:()=>void,suspended:()=>void):()=>void {
  let selected=observers.get(identity);
  if(!selected){selected=new Set();observers.set(identity,selected);}
  const observation={resumed,suspended};selected.add(observation);
  if(foreground.get(identity)===false)suspended();
  return ()=>{selected.delete(observation);if(!selected.size)observers.delete(identity);};
}
export function notifyNativeWorkspaceForeground(identity:AuthenticatedWorkspaceIdentity,active:boolean):void {
  foreground.set(identity,active);
  const selected=observers.get(identity);if(!selected)return;
  for(const observation of [...selected]) {
    if(!selected.has(observation))continue;
    if(active)observation.resumed();else observation.suspended();
  }
}

export function nativeSceneSignal(event:Event):boolean|null {
  const generation=(window as Window&{__cosmasWorkspaceGeneration?:unknown}).__cosmasWorkspaceGeneration;
  if(typeof generation!=='string'||window.top!==window)return null;
  try {
    const url=new URL(window.location.href);
    if(url.protocol!=='capacitor:'||url.hostname!=='localhost'||url.port||url.username||url.password)return null;
    if(!(event instanceof CustomEvent))return null;
    const value:unknown=event.detail;
    if(!value||typeof value!=='object'||Array.isArray(value)||
      Object.keys(value).sort().join(',')!=='active,generation')return null;
    const fields=value as Record<string,unknown>;
    if(fields.generation!==generation||typeof fields.active!=='boolean')return null;
    return fields.active;
  }catch{return null;}
}
