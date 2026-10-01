import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {GoogleConnectionPanel} from './GoogleConnectionPanel';
import {googleConnectionRequest,type GoogleStatus} from './google-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {observeConnectionStatus} from './connection-operation-health';

vi.mock('./google-connection-api',()=>({googleConnectionRequest:vi.fn()}));
const connected:GoogleStatus={state:'connected',account:{label:'Invented member',email:'member@example.invalid'},
  connected_at:new Date(Date.now()-600000).toISOString(),capabilities:{mail:true,calendar:true}};
const inbox={kind:'mail' as const,account:connected.account!,more:false,observed_at:new Date().toISOString(),items:[
  {id:'invented-message',subject:'Invented message subject',sender:'sender@example.invalid',received_at:new Date().toISOString(),is_read:false}]};
const calendar={kind:'calendar' as const,account:connected.account!,more:false,observed_at:new Date().toISOString(),items:[
  {id:'invented-event',subject:'Invented appointment',starts_at:'2026-10-02T12:00:00Z',ends_at:'2026-10-02T13:00:00Z',all_day:false,cancelled:false}]};
const link={authorization_url:'https://accounts.google.com/invented-consent',expires_at:new Date(Date.now()+600000).toISOString()};
let host:HTMLDivElement,root:Root,identity:AuthenticatedWorkspaceIdentity;
beforeEach(()=>{
  vi.resetAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);
  identity={mode:'clerk_jwt',getToken:vi.fn()};host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const mount=(owner=identity)=>act(async()=>root.render(<GoogleConnectionPanel identity={owner} onAuthenticationLost={vi.fn()}/>));
const button=(label:string)=>[...host.querySelectorAll('button')].find(item=>item.textContent===label);
const click=(label:string)=>act(async()=>{expect(button(label)).toBeDefined();expect(button(label)!.disabled).toBe(false);button(label)!.click();});
async function loadBoth(){
  vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox).mockResolvedValueOnce(calendar);
  await mount();await click('Read recent email');await click('View next 7 days');
}

it('retains both service results through switching and a check of the same account and grant',async()=>{
  await loadBoth();
  expect(host.textContent).toContain('Invented appointment');expect(button('Refresh calendar')?.classList.contains('team-primary')).toBe(true);
  await click('Email');expect(host.textContent).toContain('Invented message subject');expect(host.textContent).toContain('Email headers · Last loaded');
  expect(host.textContent).not.toContain('Invented appointment');expect(button('Refresh email')?.classList.contains('team-primary')).toBe(true);
  expect(button('Reconnect Google')?.classList.contains('team-primary')).toBe(false);
  expect(host.querySelector('a')).toBeNull();
  vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected);await click('Check Google connection');
  expect(host.textContent).toContain('Invented message subject');await click('Calendar');expect(host.textContent).toContain('Invented appointment');
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','mail','calendar','status']);
});

it.each([
  ['account', {...connected,account:{label:'Other invented member',email:'other@example.invalid'}}],
  ['grant version', {...connected,connected_at:new Date(Date.now()-100000).toISOString()}],
  ['permissions', {...connected,capabilities:{mail:true,calendar:false}}],
] as const)('purges both snapshots when the %s changes',async(_change,next)=>{
  await loadBoth();vi.mocked(googleConnectionRequest).mockResolvedValueOnce(next);await click('Check Google connection');
  expect(host.textContent).not.toContain('Invented appointment');expect(button('Refresh calendar')).toBeUndefined();
  await click('Email');expect(host.textContent).not.toContain('Invented message subject');expect(button('Refresh email')).toBeUndefined();
  expect(button('Read recent email')).toBeDefined();expect(host.textContent).not.toContain('Verified in this session');
});

it.each([
  ['account', {...connected,account:{label:'Other invented member',email:'other@example.invalid'}}],
  ['grant version', {...connected,connected_at:new Date(Date.now()-100000).toISOString()}],
  ['permissions', {...connected,capabilities:{mail:true,calendar:false}}],
  ['revoked access', {state:'sign_in_required',account:null,connected_at:null}],
] as const)('clears the hidden mounted panel when the directory observes changed %s',async(_change,next)=>{
  await loadBoth();host.hidden=true;
  // Exercise the real shared subscription without rerendering or remounting the panel.
  await act(async()=>{observeConnectionStatus(identity,'google',next);});
  expect(host.textContent).not.toContain(connected.account!.email);
  expect(host.textContent).not.toContain('Google connected.');
  expect(host.textContent).not.toContain('Invented appointment');
  expect(host.textContent).not.toContain('Invented message subject');
  host.hidden=false;
  expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
  expect(button('Check Google connection')?.disabled).toBe(false);
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','mail','calendar']);
  vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected);await click('Check Google connection');
  await click('Email');expect(host.textContent).not.toContain('Invented message subject');
  await click('Calendar');expect(host.textContent).not.toContain('Invented appointment');
  expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
});

it('retains both snapshots when a hidden-panel directory check confirms the same scope',async()=>{
  await loadBoth();host.hidden=true;
  await act(async()=>{observeConnectionStatus(identity,'google',connected);});
  expect(host.textContent).toContain('Invented appointment');host.hidden=false;
  await click('Email');expect(host.textContent).toContain('Invented message subject');
  await click('Calendar');expect(host.textContent).toContain('Invented appointment');
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','mail','calendar']);
});

it('purges both results as soon as reconnection starts even if the same account returns',async()=>{
  await loadBoth();vi.mocked(googleConnectionRequest).mockResolvedValueOnce(link).mockResolvedValueOnce(connected);
  await click('Reconnect Google');expect(host.textContent).not.toContain('Invented appointment');expect(host.textContent).not.toContain(connected.account!.email);
  await click('Check Google connection');await click('Email');expect(host.textContent).not.toContain('Invented message subject');
  await click('Calendar');expect(host.textContent).not.toContain('Invented appointment');
  expect(button('Refresh email')).toBeUndefined();expect(button('Refresh calendar')).toBeUndefined();
});

it('removes both snapshots on identity change and ignores an old refresh arriving later',async()=>{
  await loadBoth();let finish!:(value:typeof calendar)=>void;
  vi.mocked(googleConnectionRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}))
    .mockResolvedValueOnce(connected);
  await click('Refresh calendar');await mount({mode:'clerk_jwt',getToken:vi.fn()});
  await act(async()=>finish(calendar));expect(host.textContent).not.toContain('Invented appointment');
  await click('Email');expect(host.textContent).not.toContain('Invented message subject');
  expect(button('Read recent email')).toBeDefined();expect(button('Refresh calendar')).toBeUndefined();
});

it.each([true,false])('restores an earlier email read only when recovery confirms the same grant: %s',async(same)=>{
  vi.mocked(googleConnectionRequest).mockResolvedValueOnce(connected).mockResolvedValueOnce(inbox)
    .mockRejectedValueOnce(new WorkspaceApiError(502))
    .mockResolvedValueOnce(same?connected:{...connected,connected_at:new Date(Date.now()-100000).toISOString()});
  await mount();await click('Read recent email');await click('View next 7 days');await click('Email');
  expect(host.textContent?.includes('Invented message subject')).toBe(same);
  expect(host.textContent).toContain('Your account is still connected');
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','mail','calendar','status']);
});

it('clears both snapshots if the failed read cannot confirm account access',async()=>{
  await loadBoth();vi.mocked(googleConnectionRequest).mockRejectedValueOnce(new WorkspaceApiError(502)).mockRejectedValueOnce(new WorkspaceApiError(503));
  await click('Refresh calendar');expect(host.textContent).toContain('The result could not be confirmed');
  expect(host.textContent).not.toContain('Invented appointment');expect(host.textContent).not.toContain('Invented message subject');
  expect(host.textContent).not.toContain(connected.account!.email);expect(button('Refresh email')).toBeUndefined();
  expect(button('Check Google connection')?.disabled).toBe(false);
});

it('keeps the dated snapshot after cancelling a refresh and rejects its late result',async()=>{
  await loadBoth();let finish!:(value:typeof calendar)=>void;
  vi.mocked(googleConnectionRequest).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await click('Refresh calendar');await click('Stop waiting');
  await act(async()=>finish({...calendar,items:[{...calendar.items[0],subject:'Late replacement'}]}));
  expect(host.textContent).toContain('Invented appointment');expect(host.textContent).toContain('Calendar summaries · Last loaded');
  expect(host.textContent).not.toContain('Late replacement');expect(host.textContent).toContain('Read cancelled');
  await click('Email');expect(host.textContent).toContain('Invented message subject');
  expect(vi.mocked(googleConnectionRequest).mock.calls.map(call=>call[1])).toEqual(['status','mail','calendar','calendar']);
});
