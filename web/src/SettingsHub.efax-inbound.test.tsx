import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_EFAX_INBOUND_ENABLED','true');});
import {SettingsHub} from './SettingsHub';
import {WorkspaceApiError} from './workspace-api';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {DraftJournal} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {accountIdentityApi} from './account-identity-api';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {efaxInboundApi} from './efax-inbound-api';
import {efaxScope,efaxStatus} from './efax-inbound-fixtures.test-support';
vi.mock('./connection-catalog-api',()=>({readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async()=>({...await vi.importActual<Record<string,unknown>>('./connection-summary'),readConnectionSummary:vi.fn()}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>null},opaque='e'.repeat(64);
let root:Root,host:HTMLDivElement,journal:DraftJournal,context:AccountRecoveryAccess;
const visible=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&b.textContent?.includes(label));
async function wait(check:()=>void){for(let i=0;i<200;i++){let ok=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();ok=true;}catch{}});if(ok)return;}check();}
async function click(label:string){await wait(()=>expect(visible(label)?.disabled).toBe(false));await act(async()=>visible(label)!.click());}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);journal=new DraftJournal(await openDraftStore({scope:await privateDraftScope(opaque,'http://127.0.0.1:8000',webcrypto),native:false,indexedDB:new IDBFactory(),crypto:webcrypto}));context={journal,recoveryScope:opaque,authorize:vi.fn(async()=>{})};
 vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,scheduling:false,google:false,microsoft:false,messaging:true,payments:false,portals:false});vi.mocked(readConnectionSummary).mockResolvedValue({label:'Needs setup',reason:'Invented unconfigured account',action:'Open setup',tone:'attention'});vi.spyOn(accountIdentityApi,'read').mockResolvedValue({contract_version:1,box_id:efaxScope.box_id,actor_id:efaxScope.owner_id,recovery_scope:opaque});vi.spyOn(efaxInboundApi,'status').mockResolvedValue(efaxStatus);vi.spyOn(efaxInboundApi,'command');host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('reaches the actual private inbound panel below fax readiness and keeps its unresolved journal mounted',async()=>{
 const close=vi.fn();await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={close}/></AccountRecoveryContext.Provider>));
 await click('Connections');await click('Messaging & fax');await wait(()=>expect(visible('Check received-fax access')).toBeDefined());expect(host.querySelector('[aria-label="Received eFax"]')).toBeTruthy();expect(efaxInboundApi.status).not.toHaveBeenCalled();await click('Check received-fax access');expect(efaxInboundApi.status).toHaveBeenCalledOnce();
 await act(async()=>{const select=host.querySelector<HTMLSelectElement>('.efax-inbound-panel select')!;select.value=efaxStatus.installations[0].installation_id;select.dispatchEvent(new Event('change',{bubbles:true}));host.querySelector<HTMLInputElement>('.efax-inbound-panel input')!.click();});
 expect(visible('Done')!.disabled).toBe(false);await act(async()=>visible('Done')!.click());expect(close).toHaveBeenCalledOnce();expect(efaxInboundApi.command).not.toHaveBeenCalled();
});

it.each(['disabled','denied','unknown'] as const)('does not open received-fax storage on initially %s availability',async mode=>{
 if(mode==='disabled')vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,scheduling:false,google:false,microsoft:false,messaging:false,payments:false,portals:false});
 else vi.mocked(readConnectionCatalog).mockRejectedValue(mode==='denied'?new WorkspaceApiError(403):new Error('offline'));
 await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="connections" team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={()=>{}}/></AccountRecoveryContext.Provider>));
 await click('Messaging & fax');
 expect(host.querySelector('[data-settings-inbound]')).toBeNull();expect(accountIdentityApi.read).not.toHaveBeenCalled();expect(efaxInboundApi.status).not.toHaveBeenCalled();
});
it('hides a previously mounted received-fax panel during pending, disabled and denied checks without losing its review',async()=>{
 await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="connections" team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={()=>{}}/></AccountRecoveryContext.Provider>));
 await click('Messaging & fax');await click('Check received-fax access');
 const panel=host.querySelector('[data-settings-inbound]')!;const select=panel.querySelector<HTMLSelectElement>('select')!;
 await act(async()=>{select.value=efaxStatus.installations[0].installation_id;select.dispatchEvent(new Event('change',{bubbles:true}));});
 const selection=select.value;let finish!:(value:Awaited<ReturnType<typeof readConnectionCatalog>>)=>void;
 vi.mocked(readConnectionCatalog).mockReturnValueOnce(new Promise(resolve=>{finish=resolve}));
 await click('Check fax setup');expect(panel.hasAttribute('hidden')).toBe(false);
 // The previous enabled catalog remains usable while its refresh is pending.
 await act(async()=>finish({core:false,scheduling:false,google:false,microsoft:false,messaging:false,payments:false,portals:false}));
 expect(panel.hasAttribute('hidden')).toBe(true);expect(host.querySelector('[data-settings-inbound]')).toBe(panel);expect(select.value).toBe(selection);
 vi.mocked(readConnectionCatalog).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Check fax setup');
 expect(panel.hasAttribute('hidden')).toBe(true);expect(select.value).toBe(selection);
 vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,scheduling:false,google:false,microsoft:false,messaging:true,payments:false,portals:false});await click('Check fax setup');
 expect(panel.hasAttribute('hidden')).toBe(false);expect(host.querySelector('[data-settings-inbound]')).toBe(panel);expect(panel.querySelector('select')).toBe(select);expect(select.value).toBe(selection);expect(efaxInboundApi.status).toHaveBeenCalledOnce();expect(efaxInboundApi.command).not.toHaveBeenCalled();
});


it('presents one retained received-fax task without outer Settings chrome and returns that exact task origin',async()=>{
 const close=vi.fn(),back=vi.fn();const render=(requested:boolean)=>act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="messaging" receivedFaxTaskOpen={requested} receivedFaxReturnLabel="Back to Chief" onCloseReceivedFax={back} team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={close}/></AccountRecoveryContext.Provider>));
 await render(true);await wait(()=>expect(visible('Check received-fax access')).toBeDefined());const panel=host.querySelector('.efax-inbound-panel');expect(host.querySelector('.settings-hub-nav')?.hasAttribute('hidden')).toBe(true);expect(host.querySelector('[aria-label="Review received fax"]')).not.toBeNull();await click('Back to Chief');expect(back).toHaveBeenCalledOnce();expect(close).not.toHaveBeenCalled();
 await render(false);expect(host.querySelector('.settings-hub-nav')?.hasAttribute('hidden')).toBe(false);expect(host.querySelector('.efax-inbound-panel')).toBe(panel);expect(visible('Done')).toBeDefined();expect(efaxInboundApi.command).not.toHaveBeenCalled();
});

it.each(['pending','denied','setup'] as const)('keeps ordinary escape controls while a requested received-fax task has %s access',async state=>{
 let resolve!:(value:Awaited<ReturnType<typeof readConnectionCatalog>>)=>void;
 if(state==='pending')vi.mocked(readConnectionCatalog).mockReturnValueOnce(new Promise(done=>{resolve=done;}));
 if(state==='denied')vi.mocked(readConnectionCatalog).mockRejectedValueOnce(new WorkspaceApiError(403));
 if(state==='setup')vi.mocked(readConnectionCatalog).mockResolvedValueOnce({core:false,scheduling:false,google:false,microsoft:false,messaging:false,payments:false,portals:false});
 const close=vi.fn();await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="messaging" receivedFaxTaskOpen receivedFaxReturnLabel="Back to Chief" onCloseReceivedFax={()=>{}} team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={close}/></AccountRecoveryContext.Provider>));
 await wait(()=>expect(visible('Done')?.disabled).toBe(false));expect(host.querySelector('[data-editor-task="efax"]')).toBeNull();expect(visible('All connections')).toBeDefined();expect(host.querySelector('.efax-inbound-panel')).toBeNull();expect(efaxInboundApi.status).not.toHaveBeenCalled();
 if(state==='pending'){await act(async()=>resolve({core:false,scheduling:false,google:false,microsoft:false,messaging:true,payments:false,portals:false}));await wait(()=>expect(visible('Back to Chief')?.disabled).toBe(false));expect(host.querySelector('[data-editor-task="efax"]')).not.toBeNull();expect(visible('Done')).toBeUndefined();}
 else{await click('Done');expect(close).toHaveBeenCalledOnce();}
});

it('does not let a canceled old task-heading frame steal focus after hide and reopen',async()=>{
 const frames:FrameRequestCallback[]=[];vi.spyOn(window,'requestAnimationFrame').mockImplementation(callback=>{frames.push(callback);return frames.length;});vi.spyOn(window,'cancelAnimationFrame').mockImplementation(()=>{});
 const render=(requested:boolean)=>act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="messaging" receivedFaxTaskOpen={requested} receivedFaxReturnLabel="Back to Chief" onCloseReceivedFax={()=>{}} team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={()=>{}}/></AccountRecoveryContext.Provider>));
 await render(true);await wait(()=>expect(visible('Check received-fax access')?.disabled).toBe(false));expect(frames).toHaveLength(1);const oldFrame=frames[0];await render(false);await render(true);await act(async()=>visible('Back to Chief')!.focus());const focus=document.activeElement;await act(async()=>oldFrame(0));expect(document.activeElement).toBe(focus);
});
