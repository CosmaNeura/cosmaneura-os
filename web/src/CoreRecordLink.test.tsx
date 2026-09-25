import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {CoreRecordLink} from './CoreRecordLink';
import {coreRecordApi} from './core-record-api';
import {RECORD_NAVIGATION_EVENT,type CoreRecordLocation} from './core-record-location';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./core-record-api',()=>({coreRecordApi:{location:vi.fn()}}));
const workspace='00000000-0000-4000-8000-000000000001';
const origin='https://core.example.invalid',appointment='appointment_'+'0'.repeat(25)+'1';
const result=():CoreRecordLocation=>({contract_version:1,workspace_id:workspace,appointment_ref:appointment,href:origin+'/notes/'+appointment,checked_at:new Date().toISOString()});
const browser:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const native:AuthenticatedWorkspaceIdentity={mode:'desktop_native',revision:workspace,isCurrent:()=>true};
let host:HTMLDivElement,root:Root;
const denied=vi.fn();
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();
  vi.stubEnv('VITE_COSMANEURA_WEB_ORIGIN',origin);delete window.cosmasCosmaneuraNavigation;
  vi.mocked(coreRecordApi.location).mockResolvedValue(result());host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllEnvs();vi.useRealTimers();vi.restoreAllMocks();delete window.cosmasCosmaneuraNavigation;});
const mount=(identity:AuthenticatedWorkspaceIdentity=browser,locked=false,wid=workspace)=>act(async()=>root.render(<CoreRecordLink identity={identity} workspaceId={wid} locked={locked} onDenied={denied}/>));

it('offers the existing Core encounter in a separate context without persisting or changing drafts',async()=>{
  const store=vi.spyOn(Storage.prototype,'setItem');await mount();const link=host.querySelector('a')!;
  expect(link.href).toBe(result().href);expect(link.target).toBe('_blank');expect(link.rel).toBe('noopener noreferrer');
  expect(link.getAttribute('referrerpolicy')).toBe('no-referrer');expect(store).not.toHaveBeenCalled();store.mockRestore();
});
it('blocks navigation during an active operation',async()=>{
  await mount();expect(host.querySelector('a[href]')).not.toBeNull();
  await mount(browser,true);expect(host.querySelector('a[href]')).toBeNull();
  expect(host.querySelector('button')!.disabled).toBe(true);
  await mount();expect(host.querySelector('a[href]')).not.toBeNull();
});
it('clears the old destination and ignores its late response after encounter replacement',async()=>{
  let finish!:(v:CoreRecordLocation)=>void;vi.mocked(coreRecordApi.location).mockImplementationOnce(()=>new Promise(r=>{finish=r;}));
  await mount();vi.mocked(coreRecordApi.location).mockRejectedValueOnce(new WorkspaceApiError(404));
  await mount(browser,false,'00000000-0000-4000-8000-000000000002');await act(async()=>finish(result()));
  expect(host.querySelector('a')).toBeNull();expect(host.textContent).toContain('unavailable');
});
it('reports explicit loss of access without retaining the destination',async()=>{
  vi.mocked(coreRecordApi.location).mockRejectedValueOnce(new WorkspaceApiError(403));await mount();
  expect(host.querySelector('a')).toBeNull();expect(denied).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({status:403}));
});
it('does not expose a browser fallback when native opening is unconfigured',async()=>{
  await mount(native);expect(coreRecordApi.location).not.toHaveBeenCalled();expect(host.querySelector('a')).toBeNull();
  expect(host.querySelector('button')!.disabled).toBe(true);
});
it('prepares a closed native button without an opener function and only consumes matching dispatch status',async()=>{
  window.cosmasCosmaneuraNavigation={version:1,available:true,mode:'trusted-click'};await mount(native);
  const button=host.querySelector('button')!,payload=JSON.parse(button.dataset.cosmaneuraRecordLink!);
  expect(payload).toEqual({schemaVersion:1,requestId:expect.any(String),expectedRevision:workspace,href:result().href});
  await act(async()=>button.click());expect(button.disabled).toBe(true);
  const event=(id:string)=>document.dispatchEvent(new CustomEvent(RECORD_NAVIGATION_EVENT,{detail:JSON.stringify({schemaVersion:1,requestId:id,status:'opened'})}));
  await act(async()=>{event(crypto.randomUUID());});expect(button.disabled).toBe(true);
  await act(async()=>{event(payload.requestId);});expect(button.disabled).toBe(false);
  expect(JSON.parse(button.dataset.cosmaneuraRecordLink!).requestId).not.toBe(payload.requestId);
  expect(host.textContent).toContain('Sent to your browser');expect(host.textContent).not.toContain('saved');
});
it('supports current Apple native session metadata and refuses a stale click',async()=>{
  let current=true;const apple:AuthenticatedWorkspaceIdentity={...browser,nativeSession:{revision:workspace,isCurrent:()=>current}};
  window.cosmasCosmaneuraNavigation={version:1,available:true,mode:'trusted-click'};await mount(apple);
  expect(host.querySelector('a')).toBeNull();current=false;await act(async()=>host.querySelector('button')!.click());
  expect(host.querySelector('button')!.disabled).toBe(false);expect(host.textContent).not.toContain('Opening');
});
it('expires an observed destination without silently creating another Core interaction',async()=>{
  vi.useFakeTimers();await mount();await act(async()=>{await vi.advanceTimersByTimeAsync(30001);});
  expect(host.querySelector('a[href]')).toBeNull();expect(host.textContent).toContain('Refresh Cosmaneura link');
  expect(coreRecordApi.location).toHaveBeenCalledTimes(1);
  vi.mocked(coreRecordApi.location).mockResolvedValueOnce(result());
  await act(async()=>host.querySelector('button')!.click());expect(coreRecordApi.location).toHaveBeenCalledTimes(2);
  expect(host.querySelector('a[href]')).not.toBeNull();
});
it.each(['click','auxclick','contextmenu'])('cancels stale browser %s before its navigation default',async type=>{
  vi.useFakeTimers();await mount();vi.setSystemTime(Date.now()+31000);
  const event=new MouseEvent(type,{bubbles:true,cancelable:true,button:type==='auxclick'?1:0});
  await act(async()=>{host.querySelector('a')!.dispatchEvent(event);});
  expect(event.defaultPrevented).toBe(true);expect(host.querySelector('a[href]')).toBeNull();
});
it('keeps expiry bounded when the wall clock moves backwards',async()=>{
  vi.useFakeTimers();await mount();vi.setSystemTime(Date.now()-60000);
  await act(async()=>{await vi.advanceTimersByTimeAsync(30001);});
  expect(host.querySelector('a[href]')).toBeNull();expect(coreRecordApi.location).toHaveBeenCalledTimes(1);
});
it('treats native unavailable as an unconfirmed handoff and never retries automatically',async()=>{
  window.cosmasCosmaneuraNavigation={version:1,available:true,mode:'trusted-click'};await mount(native);
  const button=host.querySelector('button')!,payload=JSON.parse(button.dataset.cosmaneuraRecordLink!);
  await act(async()=>button.click());
  await act(async()=>{document.dispatchEvent(new CustomEvent(RECORD_NAVIGATION_EVENT,{detail:JSON.stringify({schemaVersion:1,requestId:payload.requestId,status:'unavailable'})}));});
  expect(host.textContent).toContain('Check your browser before opening again');
  expect(host.textContent).not.toContain('could not be opened');expect(coreRecordApi.location).toHaveBeenCalledTimes(1);
});
