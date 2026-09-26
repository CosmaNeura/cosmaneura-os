import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-connection.json';
import {CoreConnectionPanel} from './CoreConnectionPanel';
import {coreConnectionApi} from './core-connection-api';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.clearAllMocks();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeTruthy();await act(async()=>button!.click());}
async function mount(){await act(async()=>root.render(<CoreConnectionPanel identity={identity} onAuthenticationLost={()=>{}}/>));}
it('requires practice confirmation and never sends internal account identifiers',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockResolvedValueOnce(fixture.connect.response as never);
  await mount();expect(coreConnectionApi.read).not.toHaveBeenCalled();await click('Check connection status');
  expect(host.textContent).toContain('Invented W41 practice');expect(coreConnectionApi.read).toHaveBeenCalledTimes(1);
  await click('Connect this practice');
  const request=vi.mocked(coreConnectionApi.read).mock.calls[1][1];
  expect(Object.keys(request).sort()).toEqual(['action','connection_sha256','request_nonce']);
  expect(host.textContent).toContain('Connected to your practice.');
});
it('clears patient choices on access loss and explains the administrator step',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connect.response as never).mockResolvedValueOnce(fixture.encounters.response as never).mockRejectedValueOnce(new WorkspaceApiError(403));
  await mount();await click('Check connection status');await click('View appointments');
  expect(host.textContent).toContain('Invented W41 person');await click('Check connection status');
  expect(host.textContent).not.toContain('Invented W41 person');expect(host.textContent).toContain('practice administrator');
});
it('does not repeat a confirmation after a lost response',async()=>{
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connection.response as never).mockRejectedValueOnce(new WorkspaceApiError(503));
  await mount();await click('Check connection status');await click('Connect this practice');
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain('It may have been saved; check connection status');
  expect(host.textContent).not.toContain('Connected to your practice.');
});
it('opens the exact observed visit through the private notebook owner flow',async()=>{
  const opened=vi.fn(async()=>{});
  vi.mocked(coreConnectionApi.read).mockResolvedValueOnce(fixture.connect.response as never).mockResolvedValueOnce(fixture.encounters.response as never);
  await act(async()=>root.render(<CoreConnectionPanel identity={identity} onAuthenticationLost={()=>{}} onOpenNotebook={opened}/>));
  await click('Check connection status');await click('View appointments');await click('Open notebook');
  const selected=fixture.encounters.response.discovery.encounters[0];
  expect(opened).toHaveBeenCalledWith({action:'open',request_nonce:expect.any(String),connection_sha256:selected.connection_sha256,appointment_ref:selected.appointment.appointment_ref,source_sha256:selected.source_sha256});
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);
});
