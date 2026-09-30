import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {GoogleConnectionPanel} from './GoogleConnectionPanel';
import {MicrosoftConnectionPanel} from './MicrosoftConnectionPanel';
import {googleConnectionRequest} from './google-connection-api';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {connectionHealth} from './connection-operation-health';
vi.mock('./google-connection-api',()=>({googleConnectionRequest:vi.fn()}));
vi.mock('./microsoft-connection-api',()=>({microsoftConnectionRequest:vi.fn()}));
const status={state:'connected' as const,account:{label:'Invented QA member',email:'member@example.invalid'},connected_at:new Date(Date.now()-600000).toISOString(),capabilities:{mail:true,calendar:true}};
const inbox={kind:'mail' as const,account:status.account,observed_at:new Date(Date.now()-300000).toISOString(),items:[],more:false};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{vi.resetAllMocks();vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const click=async(label:string)=>{const button=[...host.querySelectorAll('button')].find(item=>item.textContent===label);expect(button,label).toBeTruthy();expect(button!.disabled).toBe(false);await act(async()=>button!.click());};
describe.each([
 {provider:'google' as const,Panel:GoogleConnectionPanel,request:vi.mocked(googleConnectionRequest)},
 {provider:'microsoft' as const,Panel:MicrosoftConnectionPanel,request:vi.mocked(microsoftConnectionRequest)},
])('$provider operation health',({provider,Panel,request})=>{
 const identity=()=>({mode:'clerk_jwt' as const,getToken:vi.fn()});
 it('keeps read-only waiting local, cancels it, and ignores a late result without replaying the read',async()=>{
  const owner=identity(),busy=vi.fn();let finish!:(v:typeof inbox)=>void,signal!:AbortSignal;
  request.mockResolvedValueOnce(status).mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
  await act(async()=>root.render(<Panel identity={owner} onBusyChange={busy} onAuthenticationLost={vi.fn()}/>));await click('Read recent email');
  expect(host.textContent).toContain('email headers');expect(host.textContent).toContain('You can keep working elsewhere');expect(busy.mock.calls.some(([locked])=>locked)).toBe(false);
  await click('Stop waiting');expect(signal.aborted).toBe(true);await act(async()=>finish(inbox));expect(host.textContent).not.toContain('Your inbox has no messages.');
  expect(connectionHealth(owner,provider).mail).toEqual({latest:'cancelled',lastSuccessAt:null});expect(request.mock.calls.map(call=>call[1])).toEqual(['status','mail']);expect(owner.getToken).not.toHaveBeenCalled();
 });
 it('records a real bounded read separately from account check and removes it after an account switch',async()=>{
  const owner=identity();request.mockResolvedValueOnce(status).mockResolvedValueOnce(inbox).mockResolvedValueOnce({...status,account:{label:'Other invented',email:'other@example.invalid'}});
  await act(async()=>root.render(<Panel identity={owner} onAuthenticationLost={vi.fn()}/>));expect(host.textContent).not.toContain('Verified in this session');
  await click('Read recent email');expect(host.querySelector(`[data-connection-operation="${provider}.mail_headers"]`)?.textContent).toContain('Verified in this session');
  expect(host.querySelector(`[data-connection-operation="${provider}.calendar_summaries"]`)?.textContent).toContain('Not verified');expect(host.textContent).toContain('Last account check');expect(host.textContent).toContain('Last successful read');
  await click(`Check ${provider==='google'?'Google':'Microsoft'} connection`);expect(host.textContent).not.toContain('Verified in this session');expect(connectionHealth(owner,provider).mail.lastSuccessAt).toBeNull();
 });
 it('does not display content or readiness returned for a different provider account',async()=>{
  const owner=identity();request.mockResolvedValueOnce(status).mockResolvedValueOnce({...inbox,account:{label:'Other',email:'other@example.invalid'}});
  await act(async()=>root.render(<Panel identity={owner} onAuthenticationLost={vi.fn()}/>));await click('Read recent email');
  expect(host.textContent).toContain('account or its permissions changed');expect(host.textContent).not.toContain('Your inbox has no messages.');expect(connectionHealth(owner,provider).mail.lastSuccessAt).toBeNull();
 });
 it('keeps sign-in preparation locked and offers cancellation only for reads',async()=>{
  const owner=identity(),busy=vi.fn();request.mockResolvedValueOnce({state:'sign_in_required',account:null,connected_at:null}).mockImplementationOnce(()=>new Promise(()=>{}));
  await act(async()=>root.render(<Panel identity={owner} onBusyChange={busy} onAuthenticationLost={vi.fn()}/>));await click(`Connect with ${provider==='google'?'Google':'Microsoft'}`);
  expect(busy.mock.calls.at(-1)).toEqual([true]);expect(host.textContent).toContain('Preparing secure sign-in');expect([...host.querySelectorAll('button')].some(button=>button.textContent==='Stop waiting')).toBe(false);
 });
 it('allows an initial account check to be cancelled and discards its late answer',async()=>{
  const owner=identity(),busy=vi.fn();let finish!:(value:typeof status)=>void,signal!:AbortSignal;
  request.mockImplementationOnce((_owner,_action,s)=>{signal=s!;return new Promise(resolve=>{finish=resolve;});});
  await act(async()=>root.render(<Panel identity={owner} onBusyChange={busy} onAuthenticationLost={vi.fn()}/>));await click('Stop waiting');expect(signal.aborted).toBe(true);
  await act(async()=>finish(status));expect(host.textContent).not.toContain(status.account.email);expect(connectionHealth(owner,provider).accountCurrent).toBe(false);expect(busy.mock.calls.some(([locked])=>locked)).toBe(false);
 });
});
