import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-connection.json';
import visitFixture from './__fixtures__/athena-visit-links.json';
import {AthenaConnectionPanel,athenaLocalTime} from './AthenaConnectionPanel';
import {coreConnectionApi} from './core-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const sha=fixture.connection.command.connection_sha256;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.resetAllMocks();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.useRealTimers();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeTruthy();await act(async()=>button!.click());}
async function mount(who=identity,onAccessLost=vi.fn(),connectionSha=sha){await act(async()=>root.render(<AthenaConnectionPanel identity={who} connectionSha={connectionSha} onAccessLost={onAccessLost}/>));}
async function chooseDates(start:string,end:string){
  for(const [index,value] of [start,end].entries())await act(async()=>{
    const input=host.querySelectorAll<HTMLInputElement>('input[type="date"]')[index];
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);
    input.dispatchEvent(new Event('input',{bubbles:true}));
  });
}
it('checks only on request and distinguishes enablement from schedule success',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.appointments.response as never);
  await mount();expect(coreConnectionApi.read).not.toHaveBeenCalled();
  await click('Check Athena connection');expect(host.textContent).toContain('Check appointments to verify access.');
  expect(host.textContent).not.toContain('Schedule read successfully.');
  await click('View Athena appointments');expect(host.textContent).toContain('Schedule read successfully.');
  expect(host.textContent).toContain('Booked · 30 minutes');expect(host.textContent).toContain('Patient names are not available');
  expect(host.textContent).not.toContain('9001');expect(host.textContent).not.toContain('8001');
  const command=vi.mocked(coreConnectionApi.read).mock.calls[1][1];
  expect(Object.keys(command).sort()).toEqual(['account_sha256','action','connection_sha256','end_date','offset','request_nonce','start_date']);
});
it('withholds the prior page when refresh fails and supports checking again',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.appointments.response as never).mockRejectedValueOnce(new WorkspaceApiError(503));
  await mount();await click('Check Athena connection');await click('View Athena appointments');
  expect(host.textContent).toContain('Booked · 30 minutes');await click('Check Athena connection');
  expect(host.textContent).not.toContain('Booked · 30 minutes');expect(host.textContent).toContain('Athena could not be checked');
});
it.each(['View Athena appointments','Check Athena connection'])('retains chosen dates and clears old observations when %s fails',async refresh=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.appointments.response as never).mockRejectedValueOnce(new WorkspaceApiError(503)).mockResolvedValueOnce(fixture.appointments.response as never);
  await mount();await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');await click('View Athena appointments');
  expect(host.textContent).toContain('Booked · 30 minutes');await click(refresh);
  expect(host.textContent).toContain('Invented office');expect(host.textContent).toContain('Your selected dates are kept below');
  expect(host.textContent).not.toContain('Booked · 30 minutes');expect(host.textContent).not.toContain('Schedule read successfully.');
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="date"]')].map(input=>input.value)).toEqual(['2026-09-20','2026-09-26']);
  await click('View Athena appointments');
  expect(vi.mocked(coreConnectionApi.read).mock.calls[3][1]).toMatchObject({action:'athena_appointments',account_sha256:fixture.connection.response.athena_discovery.account.account_sha256,start_date:'2026-09-20',end_date:'2026-09-26',offset:0});
  expect(host.textContent).toContain('Schedule read successfully.');expect(host.textContent).toContain('Booked · 30 minutes');
});
it('preserves chosen dates when a connection recheck confirms the same account',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValue(fixture.connection.response as never);
  await mount();await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');await click('Check Athena connection');
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="date"]')].map(input=>input.value)).toEqual(['2026-09-20','2026-09-26']);
});
it('uses the new department and its local dates when a recheck changes accounts',async()=>{
  vi.setSystemTime(new Date('2026-10-25T04:00:00Z'));
  const changed=structuredClone(fixture.connection.response);
  Object.assign(changed.athena_discovery.account,{account_ref:crypto.randomUUID(),account_sha256:'c'.repeat(64),department_label:'Invented West office',department_timezone:'America/Los_Angeles'});
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.appointments.response as never).mockResolvedValueOnce(changed as never);
  await mount();await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');await click('View Athena appointments');await click('Check Athena connection');
  expect(host.textContent).toContain('Invented West office');expect(host.textContent).not.toContain('Invented office');expect(host.textContent).not.toContain('Booked · 30 minutes');
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="date"]')].map(input=>input.value)).toEqual(['2026-10-24','2026-10-30']);
});
it('closes the selected visit immediately during refresh and keeps it closed after failure and retry',async()=>{
  let reject!:(reason:unknown)=>void;
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.appointments.response as never).mockResolvedValueOnce(visitFixture.lookup.response as never).mockImplementationOnce(()=>new Promise((_resolve,fail)=>{reject=fail;})).mockResolvedValueOnce(fixture.appointments.response as never);
  await act(async()=>root.render(<AthenaConnectionPanel identity={identity} connectionSha={sha} connection={fixture.connection.response.athena_discovery.connection} onAccessLost={vi.fn()} visitLinkEnabled/>));
  await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');await click('View Athena appointments');await click('Connect or open visit');
  expect(host.querySelector('[aria-label="Connect Athena visit"]')).not.toBeNull();
  await click('View Athena appointments');
  expect(host.querySelector('[aria-label="Connect Athena visit"]')).toBeNull();expect(host.textContent).not.toContain('Booked · 30 minutes');
  expect([...host.querySelectorAll<HTMLInputElement>('input[type="date"]')].every(input=>input.disabled)).toBe(true);
  await act(async()=>reject(new WorkspaceApiError(503)));
  expect(host.textContent).toContain('Your selected dates are kept below');expect(coreConnectionApi.read).toHaveBeenCalledTimes(4);
  await click('View Athena appointments');
  expect(host.textContent).toContain('Booked · 30 minutes');expect(host.querySelector('[aria-label="Connect Athena visit"]')).toBeNull();expect(coreConnectionApi.read).toHaveBeenCalledTimes(5);
});
it.each([401,403,404,409])('clears the retained account and dates after a %s refresh response',async status=>{
  const lost=vi.fn();vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.appointments.response as never).mockRejectedValueOnce(new WorkspaceApiError(status));
  await mount(identity,lost);await click('Check Athena connection');await click('View Athena appointments');await click('View Athena appointments');
  expect(host.textContent).not.toContain('Invented office');expect(host.querySelector('input[type="date"]')).toBeNull();expect(host.querySelector('li')).toBeNull();
  expect(lost).toHaveBeenCalledTimes(status===404?0:1);
});
it('clears a previously reviewed account when the schedule is no longer configured',async()=>{
  const disconnected=structuredClone(fixture.connection.response);Object.assign(disconnected.athena_discovery,{account:null});
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(disconnected as never);
  await mount();await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');await click('Check Athena connection');
  expect(host.textContent).toContain('practice has not connected an Athena schedule');expect(host.textContent).not.toContain('Invented office');expect(host.querySelector('input[type="date"]')).toBeNull();
});
it('clears the retained account and dates when the signed-in identity changes',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never);
  await mount();await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');
  await mount({...identity,getToken:async()=>null});
  expect(host.textContent).not.toContain('Invented office');expect(host.querySelector('input[type="date"]')).toBeNull();
});
it('reports access loss without retaining source observations',async()=>{
  const lost=vi.fn();vi.mocked(coreConnectionApi.read).mockRejectedValueOnce(new WorkspaceApiError(403));
  await mount(identity,lost);await click('Check Athena connection');expect(lost).toHaveBeenCalledOnce();expect(host.querySelector('li')).toBeNull();
});
it('discards an old account response and aborts when the identity changes',async()=>{
  let resolve!:(value:never)=>void;
  vi.mocked(coreConnectionApi.read).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
  await mount();await click('Check Athena connection');
  const signal=vi.mocked(coreConnectionApi.read).mock.calls[0][2];
  const next:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};await mount(next);
  await act(async()=>resolve(fixture.connection.response as never));
  expect(signal?.aborted).toBe(true);expect(host.textContent).not.toContain('Invented office');
});
it.each(['identity','connection'])('discards a late schedule reply and retained dates after the %s scope changes',async scope=>{
  let resolve!:(value:never)=>void;
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
  await mount();await click('Check Athena connection');await chooseDates('2026-09-20','2026-09-26');await click('View Athena appointments');
  const signal=vi.mocked(coreConnectionApi.read).mock.calls[1][2];
  await mount(scope==='identity'?{...identity,getToken:async()=>null}:identity,vi.fn(),scope==='connection'?'f'.repeat(64):sha);
  await act(async()=>resolve(fixture.appointments.response as never));
  expect(signal?.aborted).toBe(true);expect(host.textContent).not.toContain('Invented office');expect(host.textContent).not.toContain('Booked · 30 minutes');expect(host.querySelector('input[type="date"]')).toBeNull();
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);
});
it('shows a useful setup prerequisite when no schedule is configured',async()=>{
  const value=structuredClone(fixture.connection.response);Object.assign(value.athena_discovery,{account:null});
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(value as never);await mount();await click('Check Athena connection');
  expect(host.textContent).toContain('practice has not connected an Athena schedule');expect(host.textContent).not.toContain('View Athena appointments');
});
it('formats department-local DST time without shifting to the device timezone',()=>{
  const formatted=athenaLocalTime('2026-11-01T01:30:00');expect(formatted).toContain('1:30');expect(formatted).toContain('2026');
});
