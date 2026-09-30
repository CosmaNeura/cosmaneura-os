import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {SettingsHub} from './SettingsHub';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./connection-catalog-api',()=>({readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const catalog={core:true,google:false,microsoft:false,scheduling:false,messaging:false,payments:false,portals:false};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.resetAllMocks();vi.mocked(readConnectionSummary).mockResolvedValue({label:'Not connected',reason:'Sign in to connect your account.',action:'Connect account',tone:'attention'});host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>!b.closest('[hidden]')&&b.textContent?.includes(label));expect(button).toBeDefined();await act(async()=>button!.click());}
const mount=(google:React.ReactNode,owner=identity)=>act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} core={<p>Practice setup</p>} google={google} microsoft={<p>Microsoft</p>} messaging={<p>Messaging</p>} payments={<p>Payments</p>} portals={<p>Portals</p>} scheduling={<p>Scheduling</p>} teamSummary="Five bots" teamDirty={false} onClose={()=>{}} connectionIdentity={owner}/>));
it('shows disabled services with useful setup steps without mounting a dead editor',async()=>{
  const editor=vi.fn();function Google(){useEffect(()=>{editor();},[]);return <p>OAuth editor</p>;}
  vi.mocked(readConnectionCatalog).mockResolvedValue(catalog);await mount(<Google/>);
  expect(host.querySelectorAll('.connection-card')).toHaveLength(7);expect(host.textContent).toContain('Admin setup');
  await click('Google email & calendar');expect(editor).not.toHaveBeenCalled();expect(host.textContent).toContain('Google sign-in has not been enabled');
  expect(host.textContent).toContain('Review the requested email and calendar access');
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});await click('Check availability again');await click('Google email & calendar');
  expect(editor).toHaveBeenCalledOnce();expect(host.querySelector('[data-settings-screen="google"]')?.hasAttribute('hidden')).toBe(false);
});
it('does not turn a failed availability read into an available or connected badge',async()=>{
  vi.mocked(readConnectionCatalog).mockRejectedValue(new Error('offline'));await mount(<p>Google</p>);
  expect(host.textContent).toContain('Connections could not be checked');
  expect([...host.querySelectorAll('.connection-badge')].every(x=>x.textContent==='Couldn’t check')).toBe(true);
  expect(readConnectionSummary).not.toHaveBeenCalled();
});
it('shows independent account results without confusing enabled setup with a connection',async()=>{
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true,microsoft:true});
  vi.mocked(readConnectionSummary).mockImplementation(async(_owner,id)=>{
    if(id==='google')return {label:'Connected',reason:'invented@example.invalid',action:'View connection',tone:'ready',checkedAt:Date.now()};
    if(id==='microsoft')throw new Error('offline');
    return {label:'Needs review',reason:'Ask your administrator.',action:'Review connection',tone:'attention'};
  });
  await mount(<p>Google</p>);
  const row=(name:string)=>[...host.querySelectorAll('.connection-card')].find(x=>x.textContent?.includes(name))!;
  expect(row('Google email & calendar').textContent).toContain('Connected');expect(row('Google email & calendar').textContent).toContain('Checked');
  expect(row('Microsoft email').textContent).toContain('Couldn’t check');
  expect(row('Cosmaneura account').textContent).toContain('Needs review');
  expect(readConnectionSummary).toHaveBeenCalledTimes(3);
  expect(host.querySelectorAll('.connection-badge-ready')).toHaveLength(1);
});
it('aborts account checks on exit and ignores late private results from another owner',async()=>{
  let finish!:(value:Awaited<ReturnType<typeof readConnectionSummary>>)=>void;
  let signal!:AbortSignal;
  vi.mocked(readConnectionCatalog).mockResolvedValue(catalog);
  vi.mocked(readConnectionSummary).mockImplementationOnce((_owner,_id,s)=>{signal=s;return new Promise(resolve=>{finish=resolve;});});
  await mount(<p>Google</p>);await mount(<p>Google</p>,{...identity});
  expect(signal.aborted).toBe(true);
  await act(async()=>finish({label:'Connected',reason:'Previous private account',action:'View',tone:'ready'}));
  expect(host.textContent).not.toContain('Previous private account');expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
it('ignores a late response from the previous signed-in account',async()=>{
  let finish!:(value:typeof catalog)=>void;
  vi.mocked(readConnectionCatalog).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue({...catalog,core:false});
  await mount(<p>Google</p>);await mount(<p>Google</p>,{...identity});
  await act(async()=>finish({...catalog,google:true}));
  expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
it('checks only services actually present in this client',async()=>{
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true,microsoft:true,scheduling:true});
  await act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} core={<p>Practice setup</p>} teamSummary="Five bots" teamDirty={false} onClose={()=>{}} connectionIdentity={identity}/>));
  expect(host.querySelectorAll('.connection-card')).toHaveLength(1);
  expect(readConnectionSummary).toHaveBeenCalledOnce();
  expect(vi.mocked(readConnectionSummary).mock.calls[0][1]).toBe('core');
});
it('retains last confirmed status through both refresh phases and a failed new check',async()=>{
  const connected={label:'Connected',reason:'invented@example.invalid',action:'View connection',tone:'ready' as const,checkedAt:Date.now()};
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});vi.mocked(readConnectionSummary).mockResolvedValue(connected);
  await mount(<p>Google</p>);
  let catalogDone!:(v:typeof catalog)=>void,summaryDone!:(v:typeof connected)=>void;
  vi.mocked(readConnectionCatalog).mockImplementationOnce(()=>new Promise(resolve=>{catalogDone=resolve;}));
  await click('Refresh connections');
  expect(host.textContent).toContain('Checking again');expect(host.textContent).toContain('Last confirmed: Connected');expect(host.querySelector('.connection-badge-ready')).toBeNull();
  vi.mocked(readConnectionSummary).mockImplementation(()=>new Promise(resolve=>{summaryDone=resolve;}));
  await act(async()=>catalogDone({...catalog,core:false,google:true}));
  expect(host.textContent).toContain('Last confirmed: Connected');
  expect(host.querySelector('.connection-directory-status')?.textContent).toContain('Checking again');
  expect([...host.querySelectorAll('button')].find(button=>button.textContent==='Refresh connections')?.disabled).toBe(true);
  await act(async()=>summaryDone(connected));expect(host.querySelector('.connection-badge-ready')).not.toBeNull();
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});vi.mocked(readConnectionSummary).mockRejectedValue(new Error('offline'));
  await click('Refresh connections');expect(host.textContent).toContain('Current status is unknown');expect(host.textContent).toContain('Last confirmed: Connected');expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
it('clears cached account results and rejects sibling responses after authorization is lost',async()=>{
  const connected={label:'Connected',reason:'Invented private account',action:'View connection',tone:'ready' as const,checkedAt:Date.now()};
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});vi.mocked(readConnectionSummary).mockResolvedValue(connected);await mount(<p>Google</p>);
  let finish!:(v:typeof connected)=>void;
  vi.mocked(readConnectionSummary).mockImplementation(async(_owner,id)=>{
    if(id==='core')return new Promise(resolve=>{finish=resolve;});
    throw new (await import('./workspace-api')).WorkspaceApiError(401);
  });
  await click('Refresh connections');await act(async()=>finish(connected));
  expect(host.textContent).not.toContain('Invented private account');expect(host.querySelector('.connection-badge-ready')).toBeNull();expect(host.textContent).not.toContain('Last confirmed:');
});
