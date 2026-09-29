import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {GoogleConnectionPanel} from './GoogleConnectionPanel';
import {MicrosoftConnectionPanel} from './MicrosoftConnectionPanel';
import {googleConnectionRequest} from './google-connection-api';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';

vi.mock('./google-connection-api',()=>({googleConnectionRequest:vi.fn()}));
vi.mock('./microsoft-connection-api',()=>({microsoftConnectionRequest:vi.fn()}));
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const connected={state:'connected' as const,account:{label:'Invented member',email:'member@example.invalid'},connected_at:'2026-09-29T10:00:00Z'};
const disconnected={state:'sign_in_required' as const,account:null,connected_at:null};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.resetAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();});
const button=(label:string)=>[...host.querySelectorAll('button')].find(value=>value.textContent===label);
const click=(label:string)=>act(async()=>{expect(button(label)).toBeDefined();button(label)!.click();});

describe.each([
  {name:'Google',Panel:GoogleConnectionPanel,request:vi.mocked(googleConnectionRequest)},
  {name:'Microsoft',Panel:MicrosoftConnectionPanel,request:vi.mocked(microsoftConnectionRequest)},
])('$name read recovery',({name,Panel,request})=>{
  const mount=(owner=identity,denied=vi.fn())=>act(async()=>root.render(<Panel identity={owner} onAuthenticationLost={denied}/>));
  it('retains usable read controls after one status check without repeating the failed read',async()=>{
    request.mockResolvedValueOnce(connected).mockRejectedValueOnce(new WorkspaceApiError(502)).mockResolvedValueOnce(connected);
    await mount();await click('Read recent email');
    expect(host.textContent).toContain('Your account is still connected. Try again.');
    expect(button('Read recent email')?.disabled).toBe(false);
    expect(request.mock.calls.map(call=>call[1])).toEqual(['status','mail','status']);
    request.mockResolvedValueOnce({kind:'mail',account:connected.account,observed_at:'2026-09-29T10:00:00Z',items:[],more:false});
    await click('Read recent email');expect(host.textContent).toContain('Your inbox has no messages.');
    expect(host.textContent).not.toContain('could not be loaded');
  });
  it('shows reconnect instead of a stale connected account after credential revocation',async()=>{
    request.mockResolvedValueOnce(connected).mockRejectedValueOnce(new WorkspaceApiError(503)).mockResolvedValueOnce(disconnected);
    await mount();await click('Read recent email');
    expect(host.textContent).toContain(`Connect your ${name} account again`);
    expect(host.textContent).not.toContain('member@example.invalid');
    expect(button('Read recent email')).toBeUndefined();
  });
  it.each([401,403])('retains workspace sign-in recovery when the state check returns %s',async status=>{
    const error=new WorkspaceApiError(status),denied=vi.fn();
    request.mockResolvedValueOnce(connected).mockRejectedValueOnce(new WorkspaceApiError(502)).mockRejectedValueOnce(error);
    await mount(identity,denied);await click('Read recent email');
    expect(denied).toHaveBeenCalledExactlyOnceWith(error);
    expect(host.textContent).toContain('Sign in to CosmasOS again');
    expect(host.textContent).not.toContain('member@example.invalid');
  });
  it('discards a late connection check after the owner changes',async()=>{
    let finish!:(value:typeof connected)=>void;
    request.mockResolvedValueOnce(connected).mockRejectedValueOnce(new WorkspaceApiError(502))
      .mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce(disconnected);
    await mount();await click('Read recent email');await mount({...identity,getToken:async()=>null});
    await act(async()=>finish(connected));
    expect(host.textContent).not.toContain('member@example.invalid');
    expect(host.textContent).not.toContain('still connected');
    expect(button('Read recent email')).toBeUndefined();
  });
  it('bounds the status recovery wait and does not claim connection when it cannot be checked',async()=>{
    vi.useFakeTimers();
    request.mockResolvedValueOnce(connected).mockRejectedValueOnce(new WorkspaceApiError(502))
      .mockImplementationOnce((_owner,_action,signal)=>new Promise((_resolve,reject)=>signal!.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true})));
    await mount();await click('Read recent email');
    await act(async()=>vi.advanceTimersByTimeAsync(10000));
    expect(host.textContent).toContain('The result could not be confirmed');
    expect(button(`Check ${name} connection`)?.disabled).toBe(false);
    expect(button('Read recent email')).toBeUndefined();
    expect(request.mock.calls.map(call=>call[1])).toEqual(['status','mail','status']);
  });
});

it('recovers calendar controls with a calendar-specific explanation',async()=>{
  vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected).mockRejectedValueOnce(new WorkspaceApiError(409)).mockResolvedValueOnce(connected);
  await act(async()=>root.render(<MicrosoftConnectionPanel identity={identity} onAuthenticationLost={vi.fn()}/>));
  await click('View next 7 days');
  expect(host.textContent).toContain('Calendar could not be loaded. Your account is still connected. Try again.');
  expect(button('View next 7 days')?.disabled).toBe(false);
  expect(vi.mocked(microsoftConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','calendar','status']);
});
