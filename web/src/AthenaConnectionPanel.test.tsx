import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/athena-connection.json';
import {AthenaConnectionPanel,athenaLocalTime} from './AthenaConnectionPanel';
import {coreConnectionApi} from './core-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const sha=fixture.connection.command.connection_sha256;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.clearAllMocks();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeTruthy();await act(async()=>button!.click());}
async function mount(who=identity,onAccessLost=vi.fn()){await act(async()=>root.render(<AthenaConnectionPanel identity={who} connectionSha={sha} onAccessLost={onAccessLost}/>));}
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
it('shows a useful setup prerequisite when no schedule is configured',async()=>{
  const value=structuredClone(fixture.connection.response);Object.assign(value.athena_discovery,{account:null});
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(value as never);await mount();await click('Check Athena connection');
  expect(host.textContent).toContain('practice has not connected an Athena schedule');expect(host.textContent).not.toContain('View Athena appointments');
});
it('formats department-local DST time without shifting to the device timezone',()=>{
  const formatted=athenaLocalTime('2026-11-01T01:30:00');expect(formatted).toContain('1:30');expect(formatted).toContain('2026');
});
