import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-connection.json';
import {CoreConnectionPanel} from './CoreConnectionPanel';
import {coreConnectionApi} from './core-connection-api';
import {validateCoreCommand,type CoreConnectionCommand} from './core-connection-contract';
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
it.each([
  {start_date:'',end_date:'2026-09-24'},
  {start_date:'2026-09-24',end_date:'2026-09-23'},
  {start_date:'2026-09-01',end_date:'2026-10-03'},
])('keeps the verified practice while correcting an invalid date range: $start_date to $end_date',async dates=>{
  vi.mocked(coreConnectionApi.read).mockImplementation(async(_identity,command)=>{
    const request=command as unknown as CoreConnectionCommand;
    validateCoreCommand(request);
    return (request.action==='connection'?fixture.connect.response:fixture.encounters.response) as never;
  });
  const setDates=async(value:typeof dates)=>{
    const inputs=host.querySelectorAll<HTMLInputElement>('input[type=date]');
    expect(inputs).toHaveLength(2);
    for(const [index,day] of [value.start_date,value.end_date].entries()){
      await act(async()=>{
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(inputs[index],day);
        inputs[index].dispatchEvent(new Event('change',{bubbles:true}));
      });
    }
  };
  await mount();await click('Check connection status');await setDates(dates);await click('View appointments');
  expect(coreConnectionApi.read).toHaveBeenCalledOnce();
  expect(host.textContent).toContain('Connected to your practice.');
  expect(host.querySelector('[role=alert]')?.textContent).toContain('1 to 31 days');
  await setDates(fixture.encounters.command.window);await click('View appointments');
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);
  expect(vi.mocked(coreConnectionApi.read).mock.calls[1][1]).toMatchObject({action:'encounters',window:fixture.encounters.command.window});
  expect(host.textContent).toContain('Invented W41 person');
  expect(host.querySelector('[role=alert]')).toBeNull();
});
