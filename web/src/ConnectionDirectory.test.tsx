import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,it,expect,vi} from 'vitest';
import {SettingsHub} from './SettingsHub';
import {readConnectionCatalog} from './connection-catalog-api';
import type {AuthenticatedWorkspaceIdentity} from './workspace-api';
vi.mock('./connection-catalog-api',()=>({readConnectionCatalog:vi.fn()}));
const identity:AuthenticatedWorkspaceIdentity={mode:'clerk_jwt',getToken:async()=>null};
const catalog={core:true,google:false,microsoft:false,scheduling:false,messaging:false,payments:false,portals:false};
let host:HTMLDivElement,root:Root;
beforeEach(()=>{Object.assign(globalThis,{IS_REACT_ACT_ENVIRONMENT:true});vi.clearAllMocks();host=document.createElement('div');document.body.append(host);root=createRoot(host);});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();});
async function click(label:string){const button=[...host.querySelectorAll('button')].find(b=>!b.closest('[hidden]')&&b.textContent?.includes(label));expect(button).toBeDefined();await act(async()=>button!.click());}
const mount=(google:React.ReactNode,owner=identity)=>act(async()=>root.render(<SettingsHub open initialScreen="connections" team={<p>Team</p>} core={<p>Practice setup</p>} google={google} microsoft={<p>Microsoft</p>} messaging={<p>Messaging</p>} payments={<p>Payments</p>} portals={<p>Portals</p>} scheduling={<p>Scheduling</p>} teamSummary="Five bots" teamDirty={false} onClose={()=>{}} connectionIdentity={owner}/>));
it('shows disabled services with useful setup steps without mounting a dead editor',async()=>{
  const editor=vi.fn();function Google(){useEffect(()=>{editor();},[]);return <p>OAuth editor</p>;}
  vi.mocked(readConnectionCatalog).mockResolvedValue(catalog);await mount(<Google/>);
  expect(host.querySelectorAll('.connection-card')).toHaveLength(7);expect(host.textContent).toContain('Setup needed');
  await click('Gmail inbox');expect(editor).not.toHaveBeenCalled();expect(host.textContent).toContain('Google sign-in has not been enabled');
  expect(host.textContent).toContain('Review the requested Gmail access');
  vi.mocked(readConnectionCatalog).mockResolvedValue({...catalog,google:true});await click('Check availability again');await click('Gmail inbox');
  expect(editor).toHaveBeenCalledOnce();expect(host.querySelector('[data-settings-screen="google"]')?.hasAttribute('hidden')).toBe(false);
});
it('does not turn a failed availability read into an available or connected badge',async()=>{
  vi.mocked(readConnectionCatalog).mockRejectedValue(new Error('offline'));await mount(<p>Google</p>);
  expect(host.textContent).toContain('Availability could not be checked');
  expect([...host.querySelectorAll('.connection-badge')].every(x=>x.textContent==='Review setup')).toBe(true);
});
it('ignores a late response from the previous signed-in account',async()=>{
  let finish!:(value:typeof catalog)=>void;
  vi.mocked(readConnectionCatalog).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue({...catalog,core:false});
  await mount(<p>Google</p>);await mount(<p>Google</p>,{...identity});
  await act(async()=>finish({...catalog,google:true}));
  expect(host.querySelector('.connection-badge-ready')).toBeNull();
});
