import {validateActiveNativeWorkspace,type ActiveNativeWorkspace} from '../../clients/shared/native-practice-profile.mjs';
import type {HostedWorkspaceConfiguration} from '../../clients/shared/hosted-workspace-config.mjs';
import {nativePracticeConnectionAvailable} from '../../clients/capture/src/native/practice-connection-plugin';
import type {WorkspaceIdentity} from './workspace-api';

const changed = ():never => {throw new Error('Secure session unavailable');};
const key = (value:ActiveNativeWorkspace) => JSON.stringify([value.revision,value.profile]);
type Bound = {key:string|null};

/** A native profile is captured per identity; changing practice cannot reroute an old request. */
export class NativeWorkspaceTransport {
  private readonly bindings=new WeakMap<object,Bound>();
  constructor(private readonly readOwnedSnapshot:()=>ActiveNativeWorkspace|null) {}
  current():ActiveNativeWorkspace|null {return this.readOwnedSnapshot();}
  resolve(identity?:WorkspaceIdentity):ActiveNativeWorkspace|null {
    const current=this.current();
    if(!identity)return current;
    const previous=this.bindings.get(identity);
    const currentKey=current?key(current):null;
    if(previous&&previous.key!==currentKey)changed();
    if(!current){
      // Default requests retain their caller's session fence and error code; retired profiles cannot reach this path.
      if(!previous)this.bindings.set(identity,{key:null});
      return null;
    }
    const native='mode'in identity&&identity.mode==='clerk_jwt'?identity.nativeSession:undefined;
    if(native&&!native.isCurrent())changed();
    if('mode'in identity&&identity.mode==='desktop_native'&&!identity.isCurrent())changed();
    const account=current.profile.session;
    if(!native||native.revision!==current.revision||native.userId!==account.subject||
        native.sessionId!==account.session_id||native.organizationId!==current.profile.nativeIdentity.organizationId)changed();
    if(!previous)this.bindings.set(identity,{key:currentKey});
    return current;
  }
}

// Only the owned app host can install a profile before loading this document.
// Browser state, query parameters and enrollment responses never install it.
let captured:ActiveNativeWorkspace|null|undefined;
function ownedSnapshot():ActiveNativeWorkspace|null {
  if(captured!==undefined)return captured;
  if(typeof window==='undefined'||!nativePracticeConnectionAvailable())return null;
  const descriptor=Object.getOwnPropertyDescriptor(window,'__cosmasRegisteredWorkspace');
  if(!descriptor){captured=null;return null;}
  if(!Object.hasOwn(descriptor,'value')||descriptor.writable!==false||descriptor.configurable!==false)changed();
  const value=validateActiveNativeWorkspace(descriptor.value);
  if(value.profile.client!=='apple')changed();
  captured=value;return value;
}
const transport=new NativeWorkspaceTransport(ownedSnapshot);

/** Preserve the exact existing fallback when there is no native registered profile. */
export function workspaceApiBase(identity?:WorkspaceIdentity,fallback='http://127.0.0.1:8000'):string {
  const selected=transport.resolve(identity);
  if(selected)return selected.profile.client==='desktop'?'app://cosmas/api':selected.profile.nativeIdentity.apiOrigin;
  return import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/,'')||fallback;
}
export function registeredNativeWorkspaceConfiguration(identity?:WorkspaceIdentity):HostedWorkspaceConfiguration|null {
  const selected=transport.resolve(identity);if(!selected)return null;
  const profile=selected.profile;
  return Object.freeze({client:profile.client,dataMode:'synthetic',apiOrigin:profile.nativeIdentity.apiOrigin,
    apiBase:profile.client==='desktop'?'app://cosmas/api':profile.nativeIdentity.apiOrigin,
    pageOrigin:profile.client==='desktop'?'app://cosmas':'capacitor://localhost'});
}
export function registeredNativeWorkspace():ActiveNativeWorkspace|null {return transport.current();}

/** Raw configuration remains optional for the existing runtime's availability check. */
export function configuredWorkspaceApiBase(identity?:WorkspaceIdentity):string|undefined {
  return transport.resolve(identity)?.profile.nativeIdentity.apiOrigin??import.meta.env.VITE_API_BASE;
}
export function assertNativeWorkspaceTransport(identity:WorkspaceIdentity,base?:string):void {
  const selected=transport.resolve(identity);
  if(selected&&base!==undefined&&base!==(selected.profile.client==='desktop'?'app://cosmas/api':selected.profile.nativeIdentity.apiOrigin))changed();
}
export function assertRegisteredWorkspaceBox(identity:WorkspaceIdentity,boxId:string):void {
  const selected=transport.resolve(identity);
  if(selected&&selected.profile.practice.box_id!==boxId)changed();
}
export function assertRegisteredWorkspaceRequest(identity:WorkspaceIdentity,url:string):void {
  const selected=transport.resolve(identity);
  if(selected){
    const base=selected.profile.client==='desktop'?'app://cosmas/api':selected.profile.nativeIdentity.apiOrigin;
    if(!url.startsWith(base+'/'))changed();
  }
}
