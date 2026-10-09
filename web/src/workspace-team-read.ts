import {WorkspaceApiError,type ProviderTeam,type WorkspaceIdentity} from './workspace-api';
import {subscribeWorkspaceProtocol,workspaceProtocolGeneration,workspaceProtocolPhase} from './workspace-protocol';

type Subscriber={signal?:AbortSignal;resolve:(team:ProviderTeam)=>void;reject:(cause:unknown)=>void;remove:()=>void};
type Flight={controller:AbortController;generation:number;subscribers:Set<Subscriber>;close:()=>void};
const flights=new WeakMap<WorkspaceIdentity,Flight>();
function current(identity:WorkspaceIdentity){
  if(!('mode'in identity))return true;
  return identity.mode==='desktop_native'?identity.isCurrent():!identity.nativeSession||identity.nativeSession.isCurrent();
}

/** Share only an unresolved, validated GET. Each consumer retains its own owner and abort fence. */
export function readWorkspaceTeam(identity:WorkspaceIdentity,read:(signal:AbortSignal)=>Promise<ProviderTeam>,signal?:AbortSignal):Promise<ProviderTeam>{
  if(signal?.aborted)return Promise.reject(new WorkspaceApiError(503));
  if(!current(identity))return Promise.reject(new WorkspaceApiError(401));
  if(workspaceProtocolPhase(identity)!=='ready')return Promise.reject(new WorkspaceApiError(503));
  const generation=workspaceProtocolGeneration(identity);
  let flight=flights.get(identity);
  if(flight?.generation!==generation||flight.controller.signal.aborted)flight=undefined;
  if(!flight){
    const controller=new AbortController(),subscribers=new Set<Subscriber>();
    const selected:Flight={controller,generation,subscribers,close:()=>{}};
    const removeProtocol=subscribeWorkspaceProtocol(identity,()=>{
      if(workspaceProtocolGeneration(identity)!==generation||workspaceProtocolPhase(identity)!=='ready')controller.abort();
    });
    const close=()=>{if(flights.get(identity)===selected)flights.delete(identity);removeProtocol();};
    selected.close=close;flight=selected;flights.set(identity,selected);
    const settle=(value:ProviderTeam|undefined,cause?:unknown)=>{
      // Remove before notifying consumers: a read begun after settlement always dispatches afresh.
      close();
      for(const subscriber of subscribers){subscriber.remove();
        if(cause!==undefined)subscriber.reject(cause);
        else if(subscriber.signal?.aborted)subscriber.reject(new WorkspaceApiError(503));
        else if(!current(identity))subscriber.reject(new WorkspaceApiError(401));
        else if(workspaceProtocolGeneration(identity)!==generation)subscriber.reject(new WorkspaceApiError(503));
        else subscriber.resolve(structuredClone(value!));
      }
      subscribers.clear();
    };
    controller.signal.addEventListener('abort',()=>settle(undefined,new WorkspaceApiError(503)),{once:true});
    void Promise.resolve().then(()=>{controller.signal.throwIfAborted();return read(controller.signal);})
      .then(value=>{if(!controller.signal.aborted)settle(value);},cause=>settle(undefined,cause));
  }
  const selected=flight;
  return new Promise<ProviderTeam>((resolve,reject)=>{
    const abort=()=>{
      selected.subscribers.delete(subscriber);subscriber.remove();reject(new WorkspaceApiError(503));
      if(!selected.subscribers.size){selected.close();selected.controller.abort();}
    };
    const subscriber:Subscriber={signal,resolve,reject,remove:()=>signal?.removeEventListener('abort',abort)};
    selected.subscribers.add(subscriber);signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted)abort();
  });
}

/** One current bootstrap handoff, never a later Start/write authorization cache. */
export type WorkspaceStartupTeam={identity:WorkspaceIdentity;protocolGeneration:number;expiresAt:number;value:ProviderTeam};
const consumedStartupTeams=new WeakSet<WorkspaceStartupTeam>();
export function consumeWorkspaceStartupTeam(startup:WorkspaceStartupTeam|undefined,identity:WorkspaceIdentity):ProviderTeam|undefined{
  if(!startup||consumedStartupTeams.has(startup)||startup.identity!==identity||!current(identity)||workspaceProtocolPhase(identity)!=='ready'||workspaceProtocolGeneration(identity)!==startup.protocolGeneration||performance.now()>=startup.expiresAt)return;
  consumedStartupTeams.add(startup);return structuredClone(startup.value);
}

