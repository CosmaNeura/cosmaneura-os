import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
import fixture from './__fixtures__/core-connection.json';
import {CoreConnectionPanel} from './CoreConnectionPanel';
import {coreConnectionApi} from './core-connection-api';
import {validateCoreCommand,type CoreConnectionCommand} from './core-connection-contract';
import {WorkspaceApiError,type AuthenticatedWorkspaceIdentity} from './workspace-api';
const {readFileSync}=await vi.importActual<{readFileSync:(path:string,encoding:'utf8')=>string}>('node:fs');
const {fileURLToPath}=await vi.importActual<{fileURLToPath:(url:string)=>string}>('node:url');
const styles=readFileSync(fileURLToPath(import.meta.url).replace(/[^/]+$/,'encounter-workspace.css'),'utf8');
vi.mock('./core-connection-api',()=>({coreConnectionApi:{read:vi.fn()}}));
let host:HTMLDivElement,root:Root,style:HTMLStyleElement;
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});host=document.createElement('div');document.body.append(host);root=createRoot(host);style=document.createElement('style');style.textContent=styles;document.head.append(style);vi.clearAllMocks();});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();style.remove();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>b.textContent===label);expect(button).toBeTruthy();await act(async()=>button!.click());}
async function mount(){await act(async()=>root.render(<CoreConnectionPanel identity={identity} onAuthenticationLost={()=>{}}/>));}
function declared(selector:string,width:number){
  const found:Record<string,string>={};
  function read(rules:CSSRuleList){for(const rule of Array.from(rules)){
    if(rule.type===CSSRule.MEDIA_RULE){const media=rule as CSSMediaRule,limit=/max-width:\s*(\d+)px/.exec(media.conditionText);if(limit&&width<=Number(limit[1]))read(media.cssRules);}
    else if(rule.type===CSSRule.STYLE_RULE){const entry=rule as CSSStyleRule;if(entry.selectorText.split(',').map(part=>part.trim()).includes(selector))for(let i=0;i<entry.style.length;i++){const key=entry.style[i];found[key]=entry.style.getPropertyValue(key).trim();}}
  }}
  read(style.sheet!.cssRules);return found;
}
it.each([[409,'core_existing_recording_conflict','does not match this visit’s notebook'],[503,'core_scribe_encounter_unavailable','Scribe encounters could not be loaded']] as const)('explains the Scribe encounter lookup failure %s',async(status,code,message)=>{
  vi.mocked(coreConnectionApi.read).mockRejectedValueOnce(new WorkspaceApiError(status,code));
  await mount();await click('Check connection status');expect(host.textContent).toContain(message);expect(coreConnectionApi.read).toHaveBeenCalledOnce();
});
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
  await click('Check connection status');
  expect([...host.querySelectorAll('button')].find(button=>button.textContent==='View appointments')?.classList).toContain('team-primary');
  await click('View appointments');
  const row=host.querySelector('.connection-appointment-row')!;
  expect(row.querySelector('.connection-appointment-copy')?.textContent).toContain('Invented W41 person');
  expect(row.querySelector('details')?.open).toBe(false);
  expect(row.querySelector('details summary')?.textContent).toBe('Time zone not supplied');
  expect(row.querySelector('details')?.textContent).toContain('Check the practice-recorded time');
  expect(row.querySelectorAll('button')).toHaveLength(1);
  expect(row.querySelector('button')?.classList).toContain('team-primary');
  expect([...host.querySelectorAll('button')].find(button=>button.textContent==='Refresh appointments')?.classList).not.toContain('team-primary');
  await click('Open notebook');
  const selected=fixture.encounters.response.discovery.encounters[0];
  expect(opened).toHaveBeenCalledWith({action:'open',request_nonce:expect.any(String),connection_sha256:selected.connection_sha256,appointment_ref:selected.appointment.appointment_ref,source_sha256:selected.source_sha256});
  expect(coreConnectionApi.read).toHaveBeenCalledTimes(2);
});
it.each([320,375,390])('stacks appointment controls into full-width phone rows at %ipx',width=>{
  const dates=declared('.connection-appointments-section .connection-date-range',width),row=declared('.connection-appointments .connection-appointment-row',width),open=declared('.core-connection-setup .connection-appointments .connection-appointment-open',width);
  expect(dates.display).toBe('grid');expect(dates['grid-template-columns']).toBe('minmax(0,1fr)');
  expect(row['grid-template-columns']).toBe('minmax(0,1fr)');expect(open.width).toBe('100%');expect(open.margin).toBe('0');
  expect(declared('.connection-appointment-details summary',width)['min-height']).toBe('44px');
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
