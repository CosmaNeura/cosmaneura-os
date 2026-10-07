// @vitest-environment-options {"url":"capacitor://localhost/index.html"}
import {act,useState} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {NativeAuthenticatedWorkspace} from './NativeAuthenticatedWorkspace';
import {nativeSceneSignal,notifyNativeWorkspaceForeground,subscribeNativeWorkspaceForeground} from './native-workspace-foreground';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import type {NativeAuthState} from './native-auth';

const ready:NativeAuthState={phase:'ready',revision:'00000000-0000-4000-8000-000000000001',
  identity:{userId:'user_first',sessionId:'sess_first',organizationId:'org_test'}};
const generation='00000000-0000-4000-8000-000000000010';
vi.mock('./EncounterWorkspace',()=>({EncounterWorkspace:()=>{const [text,setText]=useState('');return <textarea aria-label="Unsent note" value={text} onChange={e=>setText(e.target.value)}/>;}}));
function deferred<T>(){let resolve!:(v:T)=>void;const promise=new Promise<T>(yes=>{resolve=yes;});return {promise,resolve};}
let root:Root,host:HTMLDivElement,identity:AuthenticatedWorkspaceIdentity;
let remove:(()=>void)[],resumed:ReturnType<typeof vi.fn>,suspended:ReturnType<typeof vi.fn>;
let plugin:{getState:ReturnType<typeof vi.fn>;getToken:ReturnType<typeof vi.fn>;signIn:ReturnType<typeof vi.fn>;signOut:ReturnType<typeof vi.fn>;addListener:ReturnType<typeof vi.fn>};
const createIdentity=(_state:NativeAuthState,isCurrent:()=>boolean)=>{
  identity={mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:_state.revision,isCurrent}};return identity;
};
async function render(){await act(async()=>root.render(<NativeAuthenticatedWorkspace plugin={plugin} available createIdentity={createIdentity}/>));}
async function scene(active:boolean,selected=generation){await act(async()=>window.dispatchEvent(new CustomEvent('cosmas:native-scene-state',{detail:{generation:selected,active}})));}
beforeEach(async()=>{
  vi.useFakeTimers();
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubEnv('VITE_WORKSPACE_HOSTED_ENABLED','false');
  Object.defineProperty(window,'__cosmasWorkspaceGeneration',{value:generation,configurable:true});
  plugin={getState:vi.fn(async()=>ready),getToken:vi.fn(),signIn:vi.fn(),signOut:vi.fn(),
    addListener:vi.fn(async()=>({remove:async()=>{}}))};
  host=document.createElement('div');document.body.append(host);root=createRoot(host);remove=[];resumed=vi.fn();suspended=vi.fn();
  await render();remove.push(subscribeNativeWorkspaceForeground(identity,resumed,suspended));
});
afterEach(async()=>{for(const dispose of remove)dispose();await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();
  delete (window as Window&{__cosmasWorkspaceGeneration?:string}).__cosmasWorkspaceGeneration;
  vi.unstubAllGlobals();vi.unstubAllEnvs();vi.useRealTimers();});
it('pauses observation while retaining capture ownership and resumes only after fresh unchanged native state',async()=>{
  const held=deferred<NativeAuthState>();plugin.getState.mockReturnValueOnce(held.promise);
  const input=host.querySelector('textarea')!;await act(async()=>{Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')!.set!.call(input,'Keep my unsent note');input.dispatchEvent(new Event('input',{bubbles:true}));});input.focus();
  await scene(false);expect(suspended).toHaveBeenCalledOnce();expect(identity.mode==='clerk_jwt'&&identity.nativeSession!.isCurrent()).toBe(true);
  await scene(true);await scene(true);expect(plugin.getState).toHaveBeenCalledTimes(2);expect(resumed).not.toHaveBeenCalled();
  expect(host.querySelector('textarea')).toBe(input);expect(input.value).toBe('Keep my unsent note');expect(document.activeElement).toBe(input);
  await act(async()=>held.resolve(ready));expect(resumed).toHaveBeenCalledOnce();expect(identity.mode==='clerk_jwt'&&identity.nativeSession!.isCurrent()).toBe(true);
  expect(input.value).toBe('Keep my unsent note');expect(plugin.getToken).not.toHaveBeenCalled();
});
it('settles a read started before backgrounding and then revalidates instead of accepting its stale result',async()=>{
  vi.useFakeTimers();const old=deferred<NativeAuthState>(),fresh=deferred<NativeAuthState>();plugin.getState.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
  await act(async()=>vi.advanceTimersByTimeAsync(5000));await scene(false);await scene(true);
  expect(plugin.getState).toHaveBeenCalledTimes(2);await act(async()=>old.resolve(ready));
  expect(plugin.getState).toHaveBeenCalledTimes(3);expect(resumed).not.toHaveBeenCalled();
  await act(async()=>fresh.resolve(ready));expect(resumed).toHaveBeenCalledOnce();
});
it('a second background transition fences the first resume read and requires a fresh state',async()=>{
  const first=deferred<NativeAuthState>(),second=deferred<NativeAuthState>();plugin.getState.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  await scene(false);await scene(true);await scene(false);await scene(true);
  await act(async()=>first.resolve(ready));expect(resumed).not.toHaveBeenCalled();expect(plugin.getState).toHaveBeenCalledTimes(3);
  await act(async()=>second.resolve(ready));expect(resumed).toHaveBeenCalledOnce();
});
it('a different identity closes prior work without delivering a resume hint to it',async()=>{
  const held=deferred<NativeAuthState>();plugin.getState.mockReturnValueOnce(held.promise);
  await scene(false);await scene(true);await act(async()=>held.resolve({...ready,revision:'00000000-0000-4000-8000-000000000002',identity:{userId:'user_second',sessionId:'sess_second',organizationId:'org_test'}}));
  expect(resumed).not.toHaveBeenCalled();expect(suspended).toHaveBeenCalledOnce();
});
it('rejects stale generation and unexpected payload without refreshing authentication',async()=>{
  await scene(true,'00000000-0000-4000-8000-000000000099');
  for(const detail of [{generation,active:true,token:'invented'},[generation,true],{generation,active:'true'},null]){
    expect(nativeSceneSignal(new CustomEvent('cosmas:native-scene-state',{detail}))).toBeNull();
    await act(async()=>window.dispatchEvent(new CustomEvent('cosmas:native-scene-state',{detail})));
  }
  expect(plugin.getState).toHaveBeenCalledOnce();expect(resumed).not.toHaveBeenCalled();
});
it('failed state verification closes access and never announces work resumed',async()=>{
  plugin.getState.mockRejectedValueOnce(new Error('private provider detail'));
  await scene(false);await scene(true);expect(resumed).not.toHaveBeenCalled();
  expect(host.textContent).toContain('Sign-in needs attention');expect(host.textContent).not.toContain('private provider detail');
});
it('a late read cannot notify an unmounted subscriber or replaced session',async()=>{
  const held=deferred<NativeAuthState>();plugin.getState.mockReturnValueOnce(held.promise);
  await scene(false);await scene(true);for(const dispose of remove)dispose();remove=[];
  await act(async()=>root.render(<div>Closed</div>));await act(async()=>held.resolve(ready));
  expect(resumed).not.toHaveBeenCalled();expect(host.textContent).toBe('Closed');
});
it('retains a suspended identity for observers mounted after the inactive scene signal',async()=>{
  await scene(false);const later=vi.fn(),resume=vi.fn();remove.push(subscribeNativeWorkspaceForeground(identity,resume,later));
  expect(later).toHaveBeenCalledOnce();expect(resume).not.toHaveBeenCalled();
  await scene(true);expect(resume).toHaveBeenCalledOnce();
});
it('uses native scene state after it is known rather than a conflicting WebView visibility report',async()=>{
  const visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('visible');
  await scene(false);await act(async()=>document.dispatchEvent(new Event('visibilitychange')));
  await act(async()=>vi.advanceTimersByTimeAsync(15000));expect(plugin.getState).toHaveBeenCalledOnce();expect(resumed).not.toHaveBeenCalled();
  visibility.mockReturnValue('hidden');await scene(true);expect(resumed).toHaveBeenCalledOnce();
  await act(async()=>document.dispatchEvent(new Event('visibilitychange')));expect(suspended).toHaveBeenCalledOnce();
});
it('marks an identity that becomes ready while inactive as suspended before later observers attach',async()=>{
  await act(async()=>root.render(null));const held=deferred<NativeAuthState>();plugin.getState.mockReturnValueOnce(held.promise);
  await render();await scene(false);await act(async()=>held.resolve(ready));
  // The read started before backgrounding is discarded. A native auth event
  // can independently admit the account while the scene remains inactive.
  const listener=plugin.addListener.mock.calls.at(-1)![1] as (value:unknown)=>void;
  await act(async()=>listener(ready));const later=vi.fn(),resume=vi.fn();remove.push(subscribeNativeWorkspaceForeground(identity,resume,later));
  expect(later).toHaveBeenCalledOnce();await act(async()=>vi.advanceTimersByTimeAsync(15000));expect(resume).not.toHaveBeenCalled();
  await scene(true);expect(resume).toHaveBeenCalledOnce();
});
it('keeps foreground observations private to the exact identity and honors removal during delivery',()=>{
  const selected:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
  const other:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
  const untouched=vi.fn(),removed=vi.fn();let disposeSecond=()=>{};
  remove.push(subscribeNativeWorkspaceForeground(selected,()=>disposeSecond(),()=>{}));
  disposeSecond=subscribeNativeWorkspaceForeground(selected,removed,()=>{});remove.push(disposeSecond);
  remove.push(subscribeNativeWorkspaceForeground(other,untouched,()=>{}));
  notifyNativeWorkspaceForeground(selected,true);expect(removed).not.toHaveBeenCalled();expect(untouched).not.toHaveBeenCalled();
});
