import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
import {useGoogleNativeForeground} from './use-google-native-foreground';

let root:Root,host:HTMLDivElement;
const native=(isCurrent=()=>true):AuthenticatedWorkspaceIdentity=>({mode:'clerk_jwt',getToken:async()=>null,
  nativeSession:{revision:'00000000-0000-4000-8000-000000000001',isCurrent}});
const callbacks={resumed:vi.fn(),suspended:vi.fn()};
function Probe({identity}:{identity:AuthenticatedWorkspaceIdentity}){
  const {suspended}=useGoogleNativeForeground(identity,callbacks);
  return <p>{suspended?'hidden':'current'}</p>;
}
beforeEach(()=>{vi.clearAllMocks();Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
it('honors an already suspended native scene before contents are painted',async()=>{
  const identity=native();notifyNativeWorkspaceForeground(identity,false);
  await act(async()=>root.render(<Probe identity={identity}/>));
  expect(host.textContent).toBe('hidden');expect(callbacks.suspended).toHaveBeenCalledOnce();
});
it('coalesces authenticated hints and never uses raw scene/focus events',async()=>{
  const identity=native();await act(async()=>root.render(<Probe identity={identity}/>));
  await act(async()=>{window.dispatchEvent(new Event('focus'));document.dispatchEvent(new CustomEvent('cosmas:native-scene-state',{detail:{active:false}}));});
  expect(callbacks.suspended).not.toHaveBeenCalled();
  await act(async()=>{notifyNativeWorkspaceForeground(identity,false);notifyNativeWorkspaceForeground(identity,false);});
  expect(callbacks.suspended).toHaveBeenCalledOnce();
  await act(async()=>{notifyNativeWorkspaceForeground(identity,true);notifyNativeWorkspaceForeground(identity,true);});
  expect(callbacks.resumed).toHaveBeenCalledOnce();expect(host.textContent).toBe('current');
});
it('requires current native identity on return and removes old subscriptions',async()=>{
  let current=false;const identity=native(()=>current),next=native();
  await act(async()=>root.render(<Probe identity={identity}/>));
  await act(async()=>{notifyNativeWorkspaceForeground(identity,false);notifyNativeWorkspaceForeground(identity,true);});
  expect(host.textContent).toBe('hidden');expect(callbacks.resumed).not.toHaveBeenCalled();
  current=true;await act(async()=>notifyNativeWorkspaceForeground(identity,true));expect(host.textContent).toBe('current');
  await act(async()=>root.render(<Probe identity={next}/>));callbacks.suspended.mockClear();callbacks.resumed.mockClear();
  await act(async()=>notifyNativeWorkspaceForeground(identity,false));expect(callbacks.suspended).not.toHaveBeenCalled();
  await act(async()=>root.render(null));await act(async()=>notifyNativeWorkspaceForeground(next,true));expect(callbacks.resumed).not.toHaveBeenCalled();
});
it('leaves ordinary browser identity outside native scene observation',async()=>{
  const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
  await act(async()=>root.render(<Probe identity={identity}/>));
  await act(async()=>notifyNativeWorkspaceForeground(identity,false));expect(host.textContent).toBe('current');expect(callbacks.suspended).not.toHaveBeenCalled();
});
