import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {MicrosoftConnectionPanel} from './MicrosoftConnectionPanel';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {connectionHealth,observeConnectionStatus,invalidateConnectionHealth} from './connection-operation-health';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
vi.mock('./microsoft-connection-api',()=>({microsoftConnectionRequest:vi.fn()}));
const browser:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const disconnected={state:'sign_in_required' as const,account:null,connected_at:null};
const connected={state:'connected' as const,account:{label:'Invented member',email:'member@example.invalid'},connected_at:new Date().toISOString()};
const link={authorization_url:'https://login.microsoftonline.com/invented',expires_at:new Date(Date.now()+600000).toISOString()};
const inbox={kind:'mail' as const,account:connected.account,more:false,observed_at:new Date().toISOString(),items:[{id:'invented-message',subject:'Invented message subject',sender:'sender@example.invalid',received_at:new Date().toISOString(),is_read:false}]};
const calendar={kind:'calendar' as const,account:connected.account,more:false,observed_at:new Date().toISOString(),items:[{id:'invented-event',subject:'Invented appointment',starts_at:'2026-10-02T12:00:00Z',ends_at:'2026-10-02T13:00:00Z',all_day:false,cancelled:false}]};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.resetAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);delete window.cosmasMicrosoftNavigation;});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();vi.restoreAllMocks();delete window.cosmasMicrosoftNavigation;});
const mount=(identity:AuthenticatedWorkspaceIdentity=browser,onAuthenticationLost:(error:unknown)=>void=()=>{})=>act(async()=>root.render(<MicrosoftConnectionPanel identity={identity} onAuthenticationLost={onAuthenticationLost}/>));
const click=(label:string)=>act(async()=>{const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeDefined();button!.click();});
it('connects, checks on browser return, reads inbox and disconnects without browser persistence',async()=>{
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox).mockResolvedValueOnce({state:'disconnected'}).mockResolvedValueOnce(link);
 const storage=vi.spyOn(Storage.prototype,'setItem');await mount();await click('Connect with Microsoft');
 const anchor=host.querySelector('a')!;expect(anchor.target).toBe('_blank');anchor.addEventListener('click',event=>event.preventDefault());await act(async()=>anchor.click());
 await act(async()=>window.dispatchEvent(new Event('focus')));expect(host.textContent).toContain('Microsoft connected.');
 await click('Read recent email');expect(host.textContent).toContain('Invented message subject');expect(host.textContent).toContain('Unread');
 await click('Disconnect Microsoft');expect(host.textContent).not.toContain('Invented message subject');expect(host.textContent).not.toContain('member@example.invalid');
 await click('Connect with Microsoft');expect(host.querySelector('a')).not.toBeNull();
 expect(storage).not.toHaveBeenCalled();expect(vi.mocked(microsoftConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','start','status','mail','disconnect','start']);
});
it('cancels a pending consent without having to wait for its expiry',async()=>{
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockResolvedValueOnce({state:'disconnected'});
 await mount();await click('Connect with Microsoft');await click('Cancel Microsoft connection');expect(host.querySelector('a')).toBeNull();
});
it('uses native trusted-click navigation and prevents handoff after session revocation',async()=>{
 let current=true;const native:AuthenticatedWorkspaceIdentity={mode:'desktop_native',revision:'12345678-1234-4234-8234-123456789abc',isCurrent:()=>current};
 window.cosmasMicrosoftNavigation={version:1,available:true,mode:'trusted-click'};
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount(native);await click('Connect with Microsoft');
 const button=host.querySelector<HTMLButtonElement>('[data-microsoft-connection]')!;expect(host.querySelector('a')).toBeNull();expect(JSON.parse(button.dataset.microsoftConnection!).expectedRevision).toBe(native.revision);
 current=false;const event=new MouseEvent('click',{bubbles:true,cancelable:true});await act(async()=>{button.dispatchEvent(event);});expect(event.defaultPrevented).toBe(true);
});
it('clears private data and ignores a late email response after switching accounts',async()=>{
 let finish!:(value:typeof inbox)=>void;
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce(disconnected);
 await mount();await click('Read recent email');await mount({...browser,getToken:async()=>null});
 expect(host.textContent).not.toContain('member@example.invalid');await act(async()=>finish(inbox));expect(host.textContent).not.toContain('Invented message subject');
});
it('shows calendar summaries with cancellation and all-day status',async()=>{
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce({kind:'calendar',account:connected.account,more:true,observed_at:new Date().toISOString(),items:[{id:'event',subject:'Invented team event',starts_at:'2026-10-01T00:00:00Z',ends_at:'2026-10-02T00:00:00Z',cancelled:true,all_day:true}]});
 await mount();await click('View next 7 days');expect(host.textContent).toContain('Invented team event');expect(host.textContent).toContain('Cancelled');expect(host.textContent).toContain('All day');expect(host.textContent).toContain('More are available in Outlook.');
});

it('keeps Connect disabled after unavailable status until the connection check succeeds',async()=>{
 vi.mocked(microsoftConnectionRequest).mockRejectedValueOnce(new WorkspaceApiError(404)).mockRejectedValueOnce(new WorkspaceApiError(503)).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount();
 const connect=()=>[...host.querySelectorAll('button')].find(button=>button.textContent==='Connect with Microsoft')!;
 expect(host.textContent).toContain('not enabled for this practice yet.');expect(connect().disabled).toBe(true);
 await click('Connect with Microsoft');expect(microsoftConnectionRequest).toHaveBeenCalledTimes(1);
 await click('Check Microsoft connection');expect(connect().disabled).toBe(true);
 await click('Check Microsoft connection');expect(connect().disabled).toBe(false);
 await click('Connect with Microsoft');expect(host.querySelector('a')).not.toBeNull();
 expect(vi.mocked(microsoftConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','status','status','start']);
});
it.each([401,403])('retains sign-in recovery after status %s',async status=>{
 const error=new WorkspaceApiError(status),denied=vi.fn();
 vi.mocked(microsoftConnectionRequest).mockRejectedValueOnce(error).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount(browser,denied);expect(denied).toHaveBeenCalledWith(error);expect(host.textContent).toContain('Sign in to CosmasOS again');
 await click('Check Microsoft connection');await click('Connect with Microsoft');expect(host.querySelector('a')).not.toBeNull();
});

const button=(label:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent===label);
const actions=()=>vi.mocked(microsoftConnectionRequest).mock.calls.map(call=>call[1]);
const native=(isCurrent=()=>true):AuthenticatedWorkspaceIdentity=>({mode:'clerk_jwt',getToken:async()=>null,
 nativeSession:{revision:'00000000-0000-4000-8000-000000000001',isCurrent}});
const nativeHint=(identity:AuthenticatedWorkspaceIdentity,active:boolean)=>act(async()=>notifyNativeWorkspaceForeground(identity,active));
async function loadBoth(identity=browser){
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox).mockResolvedValueOnce(calendar);
 await mount(identity);await click('Read recent email');await click('View next 7 days');
}

it('keeps independent dated results when switching services and checking the same account',async()=>{
 await loadBoth();
 expect(host.textContent).toContain('Invented appointment');expect(button('Refresh calendar')?.classList.contains('team-primary')).toBe(true);
 await click('Email');expect(host.textContent).toContain('Invented message subject');expect(host.textContent).toContain('Email headers · Last loaded');
 expect(host.textContent).not.toContain('Invented appointment');expect(button('Refresh email')?.classList.contains('team-primary')).toBe(true);
 expect(button('Reconnect Microsoft')?.classList.contains('team-primary')).toBe(false);
 expect(host.querySelector('.microsoft-account-controls')?.hasAttribute('open')).toBe(false);
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected);await click('Check Microsoft connection');
 expect(host.textContent).toContain('Invented message subject');await click('Calendar');expect(host.textContent).toContain('Invented appointment');
 expect(host.textContent).toContain('Calendar summaries · Last loaded');expect(actions()).toEqual(['status','mail','calendar','status']);
});

it.each([
 ['account',{...connected,account:{label:'Other invented member',email:'other@example.invalid'}}],
 ['grant version',{...connected,connected_at:new Date(Date.now()-60000).toISOString()}],
] as const)('removes both snapshots when an account check observes a changed %s',async(_change,next)=>{
 await loadBoth();vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(next);await click('Check Microsoft connection');
 expect(host.textContent).not.toContain('Invented appointment');await click('Email');expect(host.textContent).not.toContain('Invented message subject');
 expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
 expect(host.textContent).not.toContain('Verified in this session');expect(actions()).toEqual(['status','mail','calendar','status']);
});

it.each([
 ['account',{...connected,account:{label:'Other invented member',email:'other@example.invalid'}}],
 ['grant version',{...connected,connected_at:new Date(Date.now()-60000).toISOString()}],
 ['revoked access',disconnected],
 ['reconnection',null],
] as const)('immediately clears a hidden mounted panel after shared %s changes',async(_change,next)=>{
 await loadBoth();host.hidden=true;
 await act(async()=>{if(next)observeConnectionStatus(browser,'microsoft',next);else invalidateConnectionHealth(browser,'microsoft');});
 expect(host.textContent).not.toContain('member@example.invalid');expect(host.textContent).not.toContain('Microsoft connected.');
 expect(host.textContent).not.toContain('Invented appointment');expect(host.textContent).not.toContain('Invented message subject');
 host.hidden=false;expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
 expect(button('Check Microsoft connection')?.disabled).toBe(false);expect(actions()).toEqual(['status','mail','calendar']);
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected);await click('Check Microsoft connection');
 await click('Email');expect(host.textContent).not.toContain('Invented message subject');
 await click('Calendar');expect(host.textContent).not.toContain('Invented appointment');
});

it('keeps snapshots when the directory confirms the same Microsoft account and grant',async()=>{
 await loadBoth();host.hidden=true;await act(async()=>observeConnectionStatus(browser,'microsoft',connected));
 expect(host.textContent).toContain('Invented appointment');host.hidden=false;
 await click('Email');expect(host.textContent).toContain('Invented message subject');expect(actions()).toEqual(['status','mail','calendar']);
});

it.each([
 ['status','account'],['status','revocation'],['read','account'],['read','revocation'],['recovery','account'],['recovery','revocation'],
] as const)('keeps a newer directory %s observation after %s changes',async(phase,change)=>{
  const next=change==='account'?{...connected,account:{label:'Other invented member',email:'other@example.invalid'}}:disconnected;
  await loadBoth();let finish!:(value:typeof connected|typeof calendar)=>void,signal!:AbortSignal;
  if(phase==='recovery')vi.mocked(microsoftConnectionRequest).mockRejectedValueOnce(new WorkspaceApiError(502));
  vi.mocked(microsoftConnectionRequest).mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
  await click(phase==='status'?'Check Microsoft connection':'Refresh calendar');
  const count=actions().length;let newer!:ReturnType<typeof connectionHealth>;
  // Resolve in the same turn as the directory change to exercise the response
  // guard as well as the effect that aborts an outstanding old request.
  await act(async()=>{observeConnectionStatus(browser,'microsoft',next);newer=connectionHealth(browser,'microsoft');finish(phase==='read'?calendar:connected);});
  expect(connectionHealth(browser,'microsoft')).toBe(newer);expect(signal.aborted).toBe(true);
  expect(host.textContent).not.toContain('member@example.invalid');expect(host.textContent).not.toContain('Invented appointment');
  expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();expect(actions()).toHaveLength(count);
  vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(next);await click('Check Microsoft connection');
  expect(host.textContent?.includes('Microsoft connected.')).toBe(next.state==='connected');
  if(next.account)expect(host.textContent).toContain(next.account.email);
});

it('does not let a late read failure invalidate the directory account or trigger old-account recovery',async()=>{
 await loadBoth();let reject!:(reason:unknown)=>void,signal!:AbortSignal;
 vi.mocked(microsoftConnectionRequest).mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise((_resolve,fail)=>{reject=fail;});});
 await click('Refresh calendar');
 const next={...connected,account:{label:'Other invented member',email:'other@example.invalid'}};
 await act(async()=>observeConnectionStatus(browser,'microsoft',next));const newer=connectionHealth(browser,'microsoft');
 await act(async()=>reject(new WorkspaceApiError(502)));
 expect(connectionHealth(browser,'microsoft')).toBe(newer);expect(signal.aborted).toBe(true);expect(actions()).toEqual(['status','mail','calendar','calendar']);
 expect(host.textContent).not.toContain('member@example.invalid');expect(button('Check Microsoft connection')?.disabled).toBe(false);
});

it('fences an initial status reply after a newer disconnected observation when no account scope existed',async()=>{
 let finish!:(value:typeof connected)=>void;
 vi.mocked(microsoftConnectionRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await mount();let newer!:ReturnType<typeof connectionHealth>;
 await act(async()=>{observeConnectionStatus(browser,'microsoft',disconnected);newer=connectionHealth(browser,'microsoft');finish(connected);});
 expect(connectionHealth(browser,'microsoft')).toBe(newer);expect(host.textContent).not.toContain('member@example.invalid');expect(button('Read recent email')).toBeUndefined();
});

it('allows an in-flight read when the directory reconfirms the same account and grant',async()=>{
 await loadBoth();let finish!:(value:typeof calendar)=>void,signal!:AbortSignal;
 vi.mocked(microsoftConnectionRequest).mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
 await click('Refresh calendar');await act(async()=>observeConnectionStatus(browser,'microsoft',connected));
 expect(signal.aborted).toBe(false);
 await act(async()=>finish({...calendar,items:[{...calendar.items[0],subject:'Fresh current appointment'}]}));
 expect(host.textContent).toContain('Fresh current appointment');await click('Email');expect(host.textContent).toContain('Invented message subject');expect(actions()).toEqual(['status','mail','calendar','calendar']);
});

it('clears both snapshots as soon as reconnect starts even if the same account returns',async()=>{
 await loadBoth();let finish!:(value:typeof link)=>void;
 vi.mocked(microsoftConnectionRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 await click('Reconnect Microsoft');expect(host.textContent).not.toContain('Invented appointment');expect(host.textContent).not.toContain('member@example.invalid');
 await act(async()=>finish(link));vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected);await click('Check Microsoft connection');
 await click('Email');expect(host.textContent).not.toContain('Invented message subject');
 await click('Calendar');expect(host.textContent).not.toContain('Invented appointment');
 expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
});

it.each([true,false])('retains earlier email only if failed-calendar recovery confirms the same grant: %s',async same=>{
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox)
  .mockRejectedValueOnce(new WorkspaceApiError(502))
  .mockResolvedValueOnce(same?connected:{...connected,connected_at:new Date(Date.now()-60000).toISOString()});
 await mount();await click('Read recent email');await click('View next 7 days');await click('Email');
 expect(host.textContent?.includes('Invented message subject')).toBe(same);
 expect(host.textContent).toContain('Your account is still connected.');
 expect(actions()).toEqual(['status','mail','calendar','status']);
});

it('withholds both snapshots if a failed read cannot recheck account access',async()=>{
 await loadBoth();vi.mocked(microsoftConnectionRequest).mockRejectedValueOnce(new WorkspaceApiError(502)).mockRejectedValueOnce(new WorkspaceApiError(503));
 await click('Refresh calendar');expect(host.textContent).toContain('The result could not be confirmed');
 expect(host.textContent).not.toContain('Invented appointment');expect(host.textContent).not.toContain('Invented message subject');
 expect(host.textContent).not.toContain('member@example.invalid');expect(button('Check Microsoft connection')?.disabled).toBe(false);
 expect(actions()).toEqual(['status','mail','calendar','calendar','status']);
});

it('retains a dated snapshot after cancelling refresh and rejects a late replacement',async()=>{
 await loadBoth();let finish!:(value:typeof calendar)=>void,signal!:AbortSignal;
 vi.mocked(microsoftConnectionRequest).mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
 await click('Refresh calendar');await click('Stop waiting');expect(signal.aborted).toBe(true);
 await act(async()=>finish({...calendar,items:[{...calendar.items[0],subject:'Late replacement'}]}));
 expect(host.textContent).toContain('Invented appointment');expect(host.textContent).not.toContain('Late replacement');expect(host.textContent).toContain('Read cancelled');
 await click('Email');expect(host.textContent).toContain('Invented message subject');expect(actions()).toEqual(['status','mail','calendar','calendar']);
});

it('does not read in an already suspended native scene and only checks account status on return',async()=>{
 const identity=native();notifyNativeWorkspaceForeground(identity,false);await mount(identity);
 expect(host.textContent).toContain('Microsoft details are hidden');expect(button('Check Microsoft connection')?.disabled).toBe(true);
 expect(microsoftConnectionRequest).not.toHaveBeenCalled();
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected);await nativeHint(identity,true);
 expect(host.textContent).toContain('Microsoft connected.');expect(actions()).toEqual(['status']);
 expect(button('Read recent email')?.disabled).toBe(false);expect(button('Refresh email')).toBeUndefined();
});

it('aborts a native read on suspension, ignores raw focus and its late result, and checks only status on return',async()=>{
 const identity=native();let finish!:(value:typeof inbox)=>void,signal!:AbortSignal;
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected)
  .mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
 await mount(identity);await click('Read recent email');await nativeHint(identity,false);
 expect(signal.aborted).toBe(true);expect(host.textContent).not.toContain('member@example.invalid');
 await act(async()=>{window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));});
 expect(actions()).toEqual(['status','mail']);
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected);await nativeHint(identity,true);
 await act(async()=>finish(inbox));expect(host.textContent).not.toContain('Invented message subject');
 expect(button('Refresh email')).toBeUndefined();expect(actions()).toEqual(['status','mail','status']);
});

it('hides loaded snapshots until authenticated native return and does not restore their contents',async()=>{
 let current=true;const identity=native(()=>current);await loadBoth(identity);await nativeHint(identity,false);
 expect(host.textContent).not.toContain('Invented appointment');expect(host.textContent).not.toContain('member@example.invalid');
 current=false;await nativeHint(identity,true);expect(actions()).toEqual(['status','mail','calendar']);
 let finish!:(value:typeof connected)=>void;vi.mocked(microsoftConnectionRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 current=true;await nativeHint(identity,true);expect(host.textContent).not.toContain('member@example.invalid');
 await act(async()=>finish(connected));expect(host.textContent).toContain('member@example.invalid');
 expect(host.textContent).not.toContain('Invented appointment');await click('Email');expect(host.textContent).not.toContain('Invented message subject');
 expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
 expect(actions()).toEqual(['status','mail','calendar','status']);
});

it('discards status recovery interrupted by suspension without replaying the failed read',async()=>{
 const identity=native();let finish!:(value:typeof connected)=>void,signal!:AbortSignal;
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox)
  .mockRejectedValueOnce(new WorkspaceApiError(502))
  .mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
 await mount(identity);await click('Read recent email');await click('View next 7 days');await nativeHint(identity,false);
 expect(signal.aborted).toBe(true);await act(async()=>finish(connected));expect(host.textContent).not.toContain('member@example.invalid');
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(connected);await nativeHint(identity,true);
 await click('Email');expect(host.textContent).not.toContain('Invented message subject');
 expect(actions()).toEqual(['status','mail','calendar','status','status']);
});

it('waits for authenticated native OAuth return and finishes a slow callback without reading content',async()=>{
 vi.useFakeTimers();const identity=native();window.cosmasMicrosoftNavigation={version:1,available:true,mode:'trusted-click'};
 vi.mocked(microsoftConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link)
  .mockResolvedValueOnce({state:'completing_sign_in',account:null,connected_at:null}).mockResolvedValueOnce(connected);
 await mount(identity);await click('Connect with Microsoft');await click('Continue with Microsoft');await nativeHint(identity,false);
 await act(async()=>{window.dispatchEvent(new Event('focus'));await vi.advanceTimersByTimeAsync(3000);});
 expect(actions()).toEqual(['status','start']);await nativeHint(identity,true);
 expect(host.textContent).toContain('Completing Microsoft sign-in');
 await act(async()=>vi.advanceTimersByTimeAsync(3000));expect(host.textContent).toContain('Microsoft connected.');
 await act(async()=>vi.advanceTimersByTimeAsync(60000));expect(actions()).toEqual(['status','start','status','status']);
});
