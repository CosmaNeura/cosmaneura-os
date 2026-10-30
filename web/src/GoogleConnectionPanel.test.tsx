import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {GoogleConnectionPanel,type GoogleCalendarWorkControls,type GoogleMessageWorkControls} from './GoogleConnectionPanel';
import {googleConnectionRequest} from './google-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {notifyNativeWorkspaceForeground} from './native-workspace-foreground';
vi.mock('./google-connection-api',()=>({googleConnectionRequest:vi.fn()}));
const browser:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const disconnected={state:'sign_in_required' as const,account:null,connected_at:null};
const connected={state:'connected' as const,account:{label:'Invented member',email:'member@example.invalid'},connected_at:new Date().toISOString()};
const link={authorization_url:'https://login.googleonline.com/invented',expires_at:new Date(Date.now()+600000).toISOString()};
const inbox={kind:'mail' as const,account:connected.account,more:false,observed_at:new Date().toISOString(),items:[{id:'invented-message',subject:'Invented message subject',sender:'sender@example.invalid',received_at:new Date().toISOString(),is_read:false}]};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);delete window.cosmasGoogleNavigation;});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();delete window.cosmasGoogleNavigation;});
const mount=(identity:AuthenticatedWorkspaceIdentity=browser,onAuthenticationLost:(error:unknown)=>void=()=>{})=>act(async()=>root.render(<GoogleConnectionPanel identity={identity} onAuthenticationLost={onAuthenticationLost}/>));
const click=(label:string)=>act(async()=>{const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeDefined();button!.click();});
const nativeOwner=():AuthenticatedWorkspaceIdentity=>({mode:'clerk_jwt',getToken:async()=>null,nativeSession:{revision:'00000000-0000-4000-8000-000000000901',isCurrent:()=>true}});
const nativeHint=(identity:AuthenticatedWorkspaceIdentity,active:boolean)=>act(async()=>notifyNativeWorkspaceForeground(identity,active));
it('checks an idle connection once on authenticated native return and never replays its prior inbox read',async()=>{
 const identity=nativeOwner();vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox).mockResolvedValueOnce(connected);
 await mount(identity);await click('Read recent email');expect(host.textContent).toContain('Invented message subject');await nativeHint(identity,false);
 expect(host.textContent).not.toContain('Invented message subject');expect(host.textContent).not.toContain('member@example.invalid');
 await act(async()=>{window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));});expect(googleConnectionRequest).toHaveBeenCalledTimes(2);
 const visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');await nativeHint(identity,true);await nativeHint(identity,true);
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','mail','status']);expect(host.textContent).toContain('Google connected.');expect(host.textContent).not.toContain('Invented message subject');visibility.mockRestore();
});
it('observes native OAuth return through status while WebView focus remains unchanged',async()=>{
 const identity=nativeOwner();window.cosmasGoogleNavigation={version:1,available:true,mode:'trusted-click'};
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockResolvedValueOnce(connected);
 await mount(identity);await click('Connect with Google');await click('Continue with Google');await nativeHint(identity,false);
 const visibility=vi.spyOn(document,'visibilityState','get').mockReturnValue('hidden');await nativeHint(identity,true);
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','start','status']);expect(host.textContent).toContain('Google connected.');visibility.mockRestore();
});
it('ignores a late native email result and checks status without repeating the read',async()=>{
 const identity=nativeOwner();let release!:(r:typeof inbox)=>void;
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected).mockReturnValueOnce(new Promise(r=>{release=r;})).mockResolvedValueOnce(connected);
 await mount(identity);await click('Read recent email');const signal=vi.mocked(googleConnectionRequest).mock.calls[1][2]!;
 await nativeHint(identity,false);expect(signal.aborted).toBe(true);await nativeHint(identity,true);await act(async()=>release(inbox));
 expect(host.textContent).not.toContain('Invented message subject');expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','mail','status']);
});
it('pauses and fences an in-flight OAuth status check until authenticated return',async()=>{
 const identity=nativeOwner();window.cosmasGoogleNavigation={version:1,available:true,mode:'trusted-click'};let release!:(r:typeof connected)=>void;
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockReturnValueOnce(new Promise(r=>{release=r;})).mockResolvedValueOnce(disconnected);
 await mount(identity);await click('Connect with Google');await click('Continue with Google');await nativeHint(identity,true);expect(googleConnectionRequest).toHaveBeenCalledTimes(3);
 await nativeHint(identity,false);expect(vi.mocked(googleConnectionRequest).mock.calls[2][2]!.aborted).toBe(true);await nativeHint(identity,true);expect(googleConnectionRequest).toHaveBeenCalledTimes(3);
 await act(async()=>release(connected));expect(host.textContent).not.toContain('member@example.invalid');expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','start','status','status']);
});
it('shows calendar dates and explains missing consent without replaying the read',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected)
  .mockRejectedValueOnce(new WorkspaceApiError(409,'google_calendar_consent_required')).mockResolvedValueOnce(connected);
 const denied=vi.fn();await mount(browser,denied);await click('View next 7 days');
 expect(host.textContent).toContain('Choose Add calendar access');expect(denied).not.toHaveBeenCalled();
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','calendar','status']);
 expect(host.textContent).not.toContain('View next 7 days');
 vi.mocked(googleConnectionRequest).mockReset().mockResolvedValueOnce({...connected,capabilities:{mail:true,calendar:true}})
  .mockResolvedValueOnce({kind:'calendar',account:connected.account,more:false,observed_at:new Date().toISOString(),items:[
   {id:'invented',subject:'Invented all-day visit',starts_at:'2026-11-01',ends_at:'2026-11-03',all_day:true,cancelled:false}]});
 await click('Check Google connection');
 await click('View next 7 days');expect(host.textContent).toContain('Invented all-day visit');expect(host.textContent).toContain(new Date('2026-11-01T12:00:00Z').toLocaleDateString(undefined,{dateStyle:'medium',timeZone:'UTC'}));
 expect(host.textContent).toContain('All day');
});
it('uses the latest capability check if Calendar permission changed during recovery',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected)
  .mockRejectedValueOnce(new WorkspaceApiError(409,'google_calendar_consent_required'))
  .mockResolvedValueOnce({...connected,capabilities:{mail:true,calendar:true}});
 await mount();await click('View next 7 days');
 expect(host.querySelector('[data-connection-operation="google.calendar_summaries"]')?.textContent).toContain('Permission granted; a read has not been verified.');expect(host.textContent).toContain('View next 7 days');
 expect(host.textContent).not.toContain('Add calendar access');
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','calendar','status']);
});
it('shows missing Calendar permission before a failed read and preserves email access',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce({...connected,capabilities:{mail:true,calendar:false}}).mockResolvedValueOnce(inbox).mockResolvedValueOnce(link);
 await mount();expect(host.querySelector('[data-connection-operation="google.calendar_summaries"]')?.textContent).toContain('Permission needed');expect(host.textContent).not.toContain('View next 7 days');
 await click('Read recent email');expect(host.textContent).toContain('Invented message subject');
 await click('Add calendar access');expect(host.querySelector('a')?.textContent).toBe('Continue with Google');
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','mail','start']);
});
it('connects, checks on browser return, reads inbox and disconnects without browser persistence',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox).mockResolvedValueOnce({state:'disconnected'}).mockResolvedValueOnce(link);
 const storage=vi.spyOn(Storage.prototype,'setItem');await mount();await click('Connect with Google');
 const anchor=host.querySelector('a')!;expect(anchor.target).toBe('_blank');anchor.addEventListener('click',event=>event.preventDefault());await act(async()=>anchor.click());
 await act(async()=>window.dispatchEvent(new Event('focus')));expect(host.textContent).toContain('Google connected.');
 await click('Read recent email');expect(host.textContent).toContain('Invented message subject');expect(host.textContent).toContain('Unread');
 await click('Disconnect Google');expect(host.textContent).not.toContain('Invented message subject');expect(host.textContent).not.toContain('member@example.invalid');
 await click('Connect with Google');expect(host.querySelector('a')).not.toBeNull();
 expect(storage).not.toHaveBeenCalled();expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','start','status','mail','disconnect','start']);
});
it('cancels a pending consent without having to wait for its expiry',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link).mockResolvedValueOnce({state:'disconnected'});
 await mount();await click('Connect with Google');await click('Cancel Google connection');expect(host.querySelector('a')).toBeNull();
});
it('uses native trusted-click navigation and prevents handoff after session revocation',async()=>{
 let current=true;const native:AuthenticatedWorkspaceIdentity={mode:'desktop_native',revision:'12345678-1234-4234-8234-123456789abc',isCurrent:()=>current};
 window.cosmasGoogleNavigation={version:1,available:true,mode:'trusted-click'};
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount(native);await click('Connect with Google');
 const button=host.querySelector<HTMLButtonElement>('[data-google-connection]')!;expect(host.querySelector('a')).toBeNull();expect(JSON.parse(button.dataset.googleConnection!).expectedRevision).toBe(native.revision);
 current=false;const event=new MouseEvent('click',{bubbles:true,cancelable:true});await act(async()=>{button.dispatchEvent(event);});expect(event.defaultPrevented).toBe(true);
});
it('clears private data and ignores a late email response after switching accounts',async()=>{
 let finish!:(value:typeof inbox)=>void;
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValueOnce(disconnected);
 await mount();await click('Read recent email');await mount({...browser,getToken:async()=>null});
 expect(host.textContent).not.toContain('member@example.invalid');await act(async()=>finish(inbox));expect(host.textContent).not.toContain('Invented message subject');
});

it('keeps Connect disabled after unavailable status until the connection check succeeds',async()=>{
 vi.mocked(googleConnectionRequest).mockRejectedValueOnce(new WorkspaceApiError(404)).mockRejectedValueOnce(new WorkspaceApiError(503)).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount();
 const connect=()=>[...host.querySelectorAll('button')].find(button=>button.textContent==='Connect with Google')!;
 expect(host.textContent).toContain('not enabled for this practice yet.');expect(connect().disabled).toBe(true);
 await click('Connect with Google');expect(googleConnectionRequest).toHaveBeenCalledTimes(1);
 await click('Check Google connection');expect(connect().disabled).toBe(true);
 await click('Check Google connection');expect(connect().disabled).toBe(false);
 await click('Connect with Google');expect(host.querySelector('a')).not.toBeNull();
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','status','status','start']);
});

it('offers a connection check before new consent when the prior result is unknown',async()=>{
 vi.mocked(googleConnectionRequest).mockRejectedValueOnce(new WorkspaceApiError(503)).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount();const connect=()=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(button=>button.textContent==='Connect with Google')!;
 expect(connect().disabled).toBe(true);expect([...host.querySelectorAll('.google-connection .team-primary')].map(button=>button.textContent)).toEqual(['Check Google connection']);
 expect(host.querySelector('.google-next-step')?.textContent).toContain('Confirm the current connection');await click('Connect with Google');expect(googleConnectionRequest).toHaveBeenCalledTimes(1);
 await click('Check Google connection');expect(connect().disabled).toBe(false);expect([...host.querySelectorAll('.google-connection .team-primary')].map(button=>button.textContent)).toEqual(['Connect with Google']);
 await click('Connect with Google');expect(host.querySelector('a')?.textContent).toBe('Continue with Google');expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','status','start']);
});

it('guides an unfinished sign-in back to its result check without automatically starting over',async()=>{
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce({state:'sign_in_pending',account:null,connected_at:null}).mockResolvedValueOnce(connected);
 await mount();expect(host.querySelector('.google-next-step')?.textContent).toContain('Finish in your browser');
 expect([...host.querySelectorAll('.google-connection .team-primary')].map(button=>button.textContent)).toEqual(['Check Google connection']);
 expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Restart Google sign-in')).toBe(true);
 await click('Check Google connection');expect(host.textContent).toContain('Google connected.');expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','status']);
});

it('highlights one source-review next step while leaving previews and other saved work reachable',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');
 vi.mocked(googleConnectionRequest).mockResolvedValue({...connected,capabilities:{mail:true,calendar:false}});const mail=vi.fn(),calendar=vi.fn();
 try{
  await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenMessageWork={mail} onOpenCalendarWork={calendar}/>));
  const primary=()=>[...host.querySelectorAll('.google-connection .team-primary')].map(button=>button.textContent);
  expect(primary()).toEqual(['Work with email']);expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Read recent email')).toBe(true);
  await click('Calendar');expect(primary()).toEqual(['📅 Work with calendar']);expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Add calendar access')).toBe(true);
  await click('📅 Work with calendar');expect(calendar).toHaveBeenCalledOnce();expect(mail).not.toHaveBeenCalled();expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status']);
 }finally{vi.unstubAllEnvs();}
});
it.each([401,403])('retains sign-in recovery after status %s',async status=>{
 const error=new WorkspaceApiError(status),denied=vi.fn();
 vi.mocked(googleConnectionRequest).mockRejectedValueOnce(error).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);
 await mount(browser,denied);expect(denied).toHaveBeenCalledWith(error);expect(host.textContent).toContain('Sign in to CosmasOS again');
 await click('Check Google connection');await click('Connect with Google');expect(host.querySelector('a')).not.toBeNull();
});

it('opens compact calendar work deliberately without reading the old transient calendar path',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');vi.mocked(googleConnectionRequest).mockResolvedValue(connected);const open=vi.fn();
 await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenCalendarWork={open} calendarWork={<p>Invented calendar work panel</p>}/>));
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status']);await click('📅 Work with calendar');expect(open).toHaveBeenCalledOnce();
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status']);expect(host.textContent).toContain('Invented calendar work panel');vi.unstubAllEnvs();
});
it('keeps service and account changes locked while an exact calendar command is unresolved',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');vi.mocked(googleConnectionRequest).mockResolvedValue(connected);
 await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenCalendarWork={()=>{}} calendarWorkLocked/>));
 for(const label of ['📅 Work with calendar','Email','Calendar','Reconnect Google','Disconnect Google'])expect([...host.querySelectorAll('button')].find(b=>b.textContent===label)?.disabled,label).toBe(true);
 expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status']);vi.unstubAllEnvs();
});

it('opens private recovery work after a disconnected account check without reading Google',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');
 vi.mocked(googleConnectionRequest).mockResolvedValue(disconnected);const mail=vi.fn(),calendar=vi.fn();
 try{
  await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenMessageWork={mail} onOpenCalendarWork={calendar}/>));
  await click('Work with email');await click('📅 Work with calendar');
  expect(mail).toHaveBeenCalledOnce();expect(calendar).toHaveBeenCalledOnce();
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status']);
  expect(host.textContent).toContain('contents need current Google access');
  for(const label of ['Read recent email','View next 7 days','Reconnect Google','Disconnect Google'])expect([...host.querySelectorAll('button')].some(b=>b.textContent===label)).toBe(false);
  await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenMessageWork={mail} onOpenCalendarWork={calendar} messageWorkLocked/>));
  for(const label of ['Work with email','📅 Work with calendar'])expect([...host.querySelectorAll('button')].find(b=>b.textContent===label)?.disabled).toBe(true);
 }finally{vi.unstubAllEnvs();}
});
it('withholds private recovery entry until the current identity account check finishes',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','true');let release!:(r:typeof disconnected)=>void;
 const other:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
 vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockReturnValueOnce(new Promise(r=>{release=r;}));
 try{
  await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenMessageWork={()=>{}}/>));
  expect(host.textContent).toContain('Work with email');
  await act(async()=>root.render(<GoogleConnectionPanel identity={other} onAuthenticationLost={()=>{}} onOpenMessageWork={()=>{}}/>));
  expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Work with email')).toBe(false);
  await act(async()=>release(disconnected));expect(host.textContent).toContain('Work with email');
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','status']);
 }finally{vi.unstubAllEnvs();}
});

it('keeps Calendar recovery reopenable while blocking every account mutation and Gmail permission escalation',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_GOOGLE_MESSAGE_ENABLED','true');vi.mocked(googleConnectionRequest).mockResolvedValue(connected);
 let calendar!:GoogleCalendarWorkControls,mail!:GoogleMessageWorkControls;const open=vi.fn(),show=vi.fn();
 await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} onOpenCalendarWork={open} onShowConnection={show} calendarWork={controls=>{calendar=controls;return <p>Retained calendar recovery</p>;}} messageWork={controls=>{mail=controls;return <p>Retained email work</p>;}}/>));
 await act(async()=>calendar.onBusyChange(true));expect(mail.fullMailAccessBusy).toBe(true);expect(host.textContent).toContain('Review your saved Calendar work before continuing with email.');const buttons=[...host.querySelectorAll<HTMLButtonElement>('button')];expect(buttons.find(b=>b.textContent==='Reconnect Google')?.disabled).toBe(true);expect(buttons.find(b=>b.textContent==='Disconnect Google')?.disabled).toBe(true);expect(buttons.find(b=>b.textContent==='📅 Work with calendar')?.disabled).toBe(false);
 await act(async()=>{mail.requestFullMailAccess();calendar.requestCalendarAccess();});await click('📅 Work with calendar');expect(open).toHaveBeenCalledOnce();expect(show).not.toHaveBeenCalled();expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status']);
 await act(async()=>calendar.onBusyChange(false));await click('Check Google connection');await act(async()=>calendar.requestCalendarAccess());expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','status','start']);vi.unstubAllEnvs();
});

it('withholds a previously prepared browser authorization URL while Calendar work is unresolved and restores it only after unlock',async()=>{
 vi.stubEnv('VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED','true');vi.mocked(googleConnectionRequest).mockResolvedValueOnce(disconnected).mockResolvedValueOnce(link);let calendar!:GoogleCalendarWorkControls;
 await act(async()=>root.render(<GoogleConnectionPanel identity={browser} onAuthenticationLost={()=>{}} calendarWork={controls=>{calendar=controls;return <p>Retained calendar work</p>;}}/>));await click('Connect with Google');const anchor=host.querySelector<HTMLAnchorElement>('a.microsoft-continue')!;expect(anchor.getAttribute('href')).toBe(link.authorization_url);
 await act(async()=>calendar.onBusyChange(true));expect(anchor.hasAttribute('href')).toBe(false);expect(anchor.getAttribute('aria-disabled')).toBe('true');expect(anchor.tabIndex).toBe(-1);expect(host.querySelector('[data-google-connection]')).toBeNull();expect([...host.querySelectorAll('[href]')].some(e=>e.getAttribute('href')===link.authorization_url)).toBe(false);
 await act(async()=>calendar.onBusyChange(false));expect(anchor.getAttribute('href')).toBe(link.authorization_url);expect(anchor.hasAttribute('aria-disabled')).toBe(false);expect(vi.mocked(googleConnectionRequest).mock.calls.map(c=>c[1])).toEqual(['status','start']);vi.unstubAllEnvs();
});
