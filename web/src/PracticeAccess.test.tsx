import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {PracticeAccessGate,type PracticeAccessContext} from './PracticeAccessGate';
import {PracticeAccessPanel} from './PracticeAccessPanel';
import {SettingsHub} from './SettingsHub';
import {practiceAccessApi} from './practice-access-api';
import {workspaceApi,WorkspaceApiError,type ProviderTeam} from './workspace-api';
import {accessFixture as row,accessRequired,accessPending,accessConnected} from './practice-access-test-fixture';

let root:Root,container:HTMLDivElement;
const identity={mode:'clerk_jwt' as const,getToken:async()=> 'invented.token'};
const access={role:'owner' as const,onAccessLost:vi.fn()};
beforeEach(()=>{
  Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});container=document.createElement('div');document.body.append(container);root=createRoot(container);
  vi.spyOn(practiceAccessApi,'read').mockResolvedValue(accessRequired);vi.spyOn(practiceAccessApi,'request').mockResolvedValue(accessPending);
  vi.spyOn(practiceAccessApi,'setup').mockImplementation(async()=>vi.mocked(practiceAccessApi.read).mock.results.at(-1)?.type==='return'&&
    (await vi.mocked(practiceAccessApi.read).mock.results.at(-1)!.value).state==='connected'
    ?{contract_version:1,state:'member_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Ada Beta',can_start_practice:false}
    :{contract_version:1,state:'join_existing',practice:null,display_name:null,can_start_practice:false});
  vi.spyOn(practiceAccessApi,'cancel').mockResolvedValue({...accessPending,state:'cancelled',request:{...row,state:'cancelled'}});
  vi.spyOn(practiceAccessApi,'pending').mockResolvedValue([row]);vi.spyOn(practiceAccessApi,'decide').mockResolvedValue({...row,state:'approved'});access.onAccessLost.mockClear();
});
afterEach(async()=>{await act(async()=>root.unmount());container.remove();vi.restoreAllMocks();vi.useRealTimers();});
const button=(text:string)=>[...container.querySelectorAll('button')].find(item=>!item.closest('[hidden]')&&item.textContent===text)!;
const click=async(text:string)=>{expect(button(text)).toBeDefined();await act(async()=>button(text).click());};
async function name(value:string){await act(async()=>{const input=container.querySelector('input')!;Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
async function gate(id=identity){await act(async()=>root.render(<PracticeAccessGate identity={id} accountControls={<button>Account</button>}>{context=><p>Private workspace: {context.role}</p>}</PracticeAccessGate>));if(button('Join an existing practice'))await click('Join an existing practice');}
async function owner(){await act(async()=>root.render(<PracticeAccessPanel identity={identity} access={access} onBusyChange={()=>{}}/>));}

it('holds the workspace closed until approved and shows the matching code after requesting',async()=>{
  await gate();expect(container.textContent).not.toContain('Private workspace');await name('Ada Beta');await click('Request practice access');
  expect(practiceAccessApi.request).toHaveBeenCalledTimes(1);expect(container.textContent).toContain('873C–4F63–2C89');expect(container.textContent).toContain('Waiting for your practice owner');
  vi.mocked(practiceAccessApi.read).mockResolvedValue(accessConnected);await click('Check access');expect(container.textContent).toContain('Private workspace: member');
});
it('recovers a lost submission reply by checking status before another submission',async()=>{
  vi.mocked(practiceAccessApi.request).mockRejectedValueOnce(new WorkspaceApiError(503));await gate();await name('Ada Beta');await click('Request practice access');
  expect(button('Request practice access').disabled).toBe(true);vi.mocked(practiceAccessApi.read).mockResolvedValue(accessPending);await click('Check access');
  expect(container.textContent).toContain('Waiting for your practice owner');expect(practiceAccessApi.request).toHaveBeenCalledTimes(1);
  await click('Cancel access request');expect(practiceAccessApi.cancel).toHaveBeenCalledWith(identity,{request_id:row.request_id,review_sha256:row.review_sha256,confirm:true},expect.any(AbortSignal));
  expect(container.textContent).toContain('This request was cancelled');
  await click('Request practice access');
  const calls=vi.mocked(practiceAccessApi.request).mock.calls;expect(calls).toHaveLength(2);expect(calls[0][1].idempotency_key).not.toBe(calls[1][1].idempotency_key);
});
it('drops a late access response when the signed-in identity changes',async()=>{
  let finish!:(value:typeof accessPending)=>void;vi.mocked(practiceAccessApi.read).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
  await gate();await gate({...identity});await act(async()=>finish(accessPending));expect(container.textContent).not.toContain('Ada Beta');expect(container.textContent).not.toContain('Private workspace');
});
it('requires the owner to match the name and code and recovers the exact interrupted decision',async()=>{
  vi.mocked(practiceAccessApi.decide).mockRejectedValueOnce(new WorkspaceApiError(503));await owner();await click('Review Ada Beta');
  expect(button('Approve member').disabled).toBe(true);expect(container.textContent).toContain('supplied by the requester');
  await act(async()=>container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click());await click('Approve member');
  expect(button('Refresh requests').disabled).toBe(true);expect(container.textContent).toContain('last decision is unconfirmed');await click('Recover approval');
  const calls=vi.mocked(practiceAccessApi.decide).mock.calls;expect(calls).toHaveLength(2);expect(calls[0][1]).toEqual(calls[1][1]);
  expect(container.textContent).toContain('Ada Beta: access approved.');expect(container.textContent).toContain('No pending access requests');
});
it('clears private requests on authority denial and does not regrant on a conflict',async()=>{
  await owner();await click('Review Ada Beta');vi.mocked(practiceAccessApi.decide).mockRejectedValueOnce(new WorkspaceApiError(409));await click('Decline request');
  expect(container.textContent).not.toContain('Ada Beta');expect(button('Refresh requests').disabled).toBe(false);
  vi.mocked(practiceAccessApi.pending).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Refresh requests');expect(access.onAccessLost).toHaveBeenCalledOnce();
});
it('puts people access in its own Settings screen and returns to All settings',async()=>{
  await act(async()=>root.render(<SettingsHub open team={<p>Agent coworkers</p>} members={<PracticeAccessPanel identity={identity} access={access} onBusyChange={()=>{}}/>} teamSummary="Agent team" teamDirty={false} onClose={()=>{}}/>));
  expect(practiceAccessApi.pending).not.toHaveBeenCalled();
  const card=[...container.querySelectorAll('button')].find(item=>item.textContent?.includes('Practice access'))!;await act(async()=>card.click());
  expect(practiceAccessApi.pending).toHaveBeenCalledOnce();expect(button('← All settings')).toBeDefined();await click('← All settings');
  expect(document.activeElement?.textContent).toBe('Settings');
});
it('overlaps the team read with access and hands it off only after both practice reads accept',async()=>{
  let ready!:(value:typeof accessConnected)=>void;
  vi.mocked(practiceAccessApi.read).mockImplementationOnce(()=>new Promise(resolve=>{ready=resolve;}));
  vi.mocked(practiceAccessApi.setup).mockResolvedValue({contract_version:1,state:'member_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Ada Beta',can_start_practice:false});
  const team:ProviderTeam={revision:1,template_version:'provider-team-v1',recovery_scope:'a'.repeat(64),configuration:{practice_context:'Invented',bots:[]},members:[],llm:{enabled:false,model:'offline'}};
  vi.spyOn(workspaceApi,'team').mockResolvedValue(team);let admitted:PracticeAccessContext|undefined;
  await act(async()=>root.render(<PracticeAccessGate identity={identity} accountControls={null} prefetchTeam>{context=>{admitted=context;return <p>Ready</p>;}}</PracticeAccessGate>));
  expect(workspaceApi.team).toHaveBeenCalledOnce();expect(admitted).toBeUndefined();
  await act(async()=>ready(accessConnected));expect(admitted?.startupTeam?.value).toEqual(team);expect(admitted?.startupTeam?.identity).toBe(identity);
});
it('bounds a slow speculative team read by the same15second startup window',async()=>{
  vi.useFakeTimers();vi.mocked(practiceAccessApi.read).mockResolvedValue(accessConnected);
  vi.mocked(practiceAccessApi.setup).mockResolvedValue({contract_version:1,state:'member_ready',practice:{display_name:'Invented practice',specialty:null},display_name:'Ada Beta',can_start_practice:false});
  let signal!:AbortSignal;
  vi.spyOn(workspaceApi,'team').mockImplementation(async(_,value)=>{signal=value!;return new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(new WorkspaceApiError(503)),{once:true}));});
  await act(async()=>root.render(<PracticeAccessGate identity={identity} accountControls={null} prefetchTeam>{()=> <p>Private workspace</p>}</PracticeAccessGate>));
  expect(container.textContent).not.toContain('Private workspace');
  await act(async()=>vi.advanceTimersByTime(15000));expect(signal.aborted).toBe(true);expect(container.textContent).not.toContain('Private workspace');expect(container.textContent).toContain('could not be confirmed');
});
