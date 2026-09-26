import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-appointment-setup.json';
import {CoreAppointmentSetupPanel} from './CoreAppointmentSetupPanel';
import {coreConnectionApi} from './core-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const window=fixture.preview.command.window,sha=fixture.preview.command.connection_sha256;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.clearAllMocks();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function click(label:string){const b=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(b).toBeTruthy();await act(async()=>b!.click());}
async function mount(who=identity,dates=window,lost=vi.fn(),connected=vi.fn()){await act(async()=>root.render(<CoreAppointmentSetupPanel identity={who} connectionSha={sha} window={dates} onAccessLost={lost} onConnected={connected}/>));}
it('previews before connecting exactly the reviewed plan without patient identifiers',async()=>{
  const connected=vi.fn();vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.preview.response as never).mockResolvedValueOnce(fixture.connect.response as never);
  await mount(identity,window,vi.fn(),connected);expect(coreConnectionApi.read).not.toHaveBeenCalled();
  await click('Check existing appointments');expect(host.textContent).toContain('25 ready to connect');expect(connected).not.toHaveBeenCalled();
  await click('Connect existing appointments');expect(connected).toHaveBeenCalledOnce();expect(host.textContent).toContain('25 appointments connected.');
  const command=vi.mocked(coreConnectionApi.read).mock.calls[1][1];
  expect(command).toEqual({...fixture.connect.command,request_nonce:expect.any(String)});
});
it('does not replay a lost confirmation and clears its old review',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.preview.response as never).mockRejectedValueOnce(new WorkspaceApiError(503));
  await mount();await click('Check existing appointments');await click('Connect existing appointments');
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);expect(host.textContent).toContain('It may have been saved.');expect(host.textContent).not.toContain('25 ready to connect');
  expect([...host.querySelectorAll('button')].some(b=>b.textContent==='Connect existing appointments')).toBe(false);
});
it('invalidates review when the selected dates change',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.preview.response as never);
  await mount();await click('Check existing appointments');await mount(identity,{start_date:'2026-09-25',end_date:'2026-09-26'});
  expect(host.textContent).not.toContain('25 ready to connect');expect(coreConnectionApi.read).toHaveBeenCalledOnce();
});
it('withholds a late result after identity replacement',async()=>{
  let resolve!:(v:never)=>void;vi.mocked(coreConnectionApi.read).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));
  await mount();await click('Check existing appointments');const signal=vi.mocked(coreConnectionApi.read).mock.calls[0][2];
  await mount({mode:'clerk_jwt',getToken:async()=>null});await act(async()=>resolve(fixture.preview.response as never));
  expect(signal?.aborted).toBe(true);expect(host.textContent).not.toContain('25 ready to connect');
});
it('reports changed authority and never claims a connection',async()=>{
  const lost=vi.fn();vi.mocked(coreConnectionApi.read).mockRejectedValueOnce(new WorkspaceApiError(409));
  await mount(identity,window,lost);await click('Check existing appointments');expect(lost).toHaveBeenCalledOnce();expect(host.textContent).not.toContain('appointments connected.');
});
it('checks the next batch only when requested',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValue(fixture.preview.response as never);
  await mount();await click('Check existing appointments');await click('Check next appointments');
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);expect(vi.mocked(coreConnectionApi.read).mock.calls[1][1]).toMatchObject({action:'appointment_setup_preview',cursor:fixture.preview.response.appointment_setup.next_cursor});
});
