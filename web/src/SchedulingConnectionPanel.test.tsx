import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {SchedulingConnectionPanel} from './SchedulingConnectionPanel';
import {schedulingLoginRequest} from './scheduling-login-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./scheduling-login-api',()=>({SCHEDULING_LOGIN_BUILD:false,schedulingLoginRequest:vi.fn()}));
const browser:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const disconnected={state:'sign_in_required' as const,label:'Invented practice',connected_at:null};
const connected={...disconnected,state:'connected' as const,connected_at:new Date().toISOString()};
const link={authorization_url:'https://accounts.google.com/o/oauth2/v2/auth?invented',expires_at:new Date(Date.now()+600000).toISOString()};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);delete window.cosmasSchedulingNavigation;});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();delete window.cosmasSchedulingNavigation;});
const mount=(identity:AuthenticatedWorkspaceIdentity=browser)=>act(async()=>root.render(<SchedulingConnectionPanel identity={identity} onAuthenticationLost={()=>{}}/>));
const click=(label:string)=>act(async()=>{const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeDefined();button!.click();});
it('connects through Google, refreshes status on return, and disconnects from the app',async()=>{
 vi.mocked(schedulingLoginRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockResolvedValueOnce(connected).mockResolvedValueOnce({state:'disconnected'});
 const storage=vi.spyOn(Storage.prototype,'setItem');await mount();expect(schedulingLoginRequest).toHaveBeenCalledTimes(1);
 await click('Connect with Google');const anchor=host.querySelector('a')!;expect(anchor.target).toBe('_blank');
 anchor.addEventListener('click',event=>event.preventDefault());await act(async()=>anchor.click());
 await act(async()=>window.dispatchEvent(new Event('focus')));expect(host.textContent).toContain('Connected to Scheduling.');
 await click('Disconnect Scheduling');expect(host.textContent).toContain('Scheduling disconnected from CosmasOS.');expect(storage).not.toHaveBeenCalled();
 expect(vi.mocked(schedulingLoginRequest).mock.calls.map(c=>c[1])).toEqual(['status','start','status','disconnect']);
});
it('uses the native trusted-click handoff and cancels when its session changes',async()=>{
 let current=true;const native:AuthenticatedWorkspaceIdentity={mode:'desktop_native',revision:'12345678-1234-4234-8234-123456789abc',isCurrent:()=>current};
 window.cosmasSchedulingNavigation={version:1,available:true,mode:'trusted-click'};
 vi.mocked(schedulingLoginRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount(native);await click('Connect with Google');
 const button=host.querySelector<HTMLButtonElement>('[data-scheduling-sign-in]')!;expect(host.querySelector('a')).toBeNull();expect(JSON.parse(button.dataset.schedulingSignIn!).expectedRevision).toBe(native.revision);
 current=false;const event=new MouseEvent('click',{bubbles:true,cancelable:true});await act(async()=>{button.dispatchEvent(event);});expect(event.defaultPrevented).toBe(true);
});
it('clears a replaced account and permits a fresh status request while an old reply is pending',async()=>{
 let finish!:(value:typeof connected)=>void;vi.mocked(schedulingLoginRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce(disconnected);
 await mount();await mount({...browser,getToken:async()=>null});
 await act(async()=>finish(connected));expect(host.textContent).not.toContain('Connected to Scheduling.');expect(schedulingLoginRequest).toHaveBeenCalledTimes(2);
});
