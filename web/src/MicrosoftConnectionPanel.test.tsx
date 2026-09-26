import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {MicrosoftConnectionPanel} from './MicrosoftConnectionPanel';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./microsoft-connection-api',()=>({microsoftConnectionRequest:vi.fn()}));
const browser:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const disconnected={state:'sign_in_required' as const,account:null,connected_at:null};
const connected={state:'connected' as const,account:{label:'Invented member',email:'member@example.invalid'},connected_at:new Date().toISOString()};
const link={authorization_url:'https://login.microsoftonline.com/invented',expires_at:new Date(Date.now()+600000).toISOString()};
const inbox={kind:'mail' as const,account:connected.account,more:false,observed_at:new Date().toISOString(),items:[{id:'invented-message',subject:'Invented message subject',sender:'sender@example.invalid',received_at:new Date().toISOString(),is_read:false}]};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);delete window.cosmasMicrosoftNavigation;});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.restoreAllMocks();delete window.cosmasMicrosoftNavigation;});
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
