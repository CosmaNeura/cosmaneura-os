import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_FAX_INBOUND_ENABLED','true');});
import {SettingsHub} from './SettingsHub';
import {WorkspaceApiError} from './workspace-api';
import {AccountRecoveryContext,type AccountRecoveryAccess} from './account-recovery';
import {DraftJournal} from './draft-journal';
import {openDraftStore,privateDraftScope} from './draft-store';
import {IDBFactory} from '../../clients/capture/node_modules/fake-indexeddb';
import {accountIdentityApi} from './account-identity-api';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {faxInboundApi} from './fax-inbound-api';
import {faxScope,faxStatus} from './fax-inbound-fixtures.test-support';
vi.mock('./connection-catalog-api',()=>({readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async()=>({...await vi.importActual<Record<string,unknown>>('./connection-summary'),readConnectionSummary:vi.fn()}));
const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');
const identity={mode:'clerk_jwt' as const,getToken:async()=>null},opaque='e'.repeat(64);
let root:Root,host:HTMLDivElement,journal:DraftJournal,context:AccountRecoveryAccess;
const visible=(label:string)=>[...host.querySelectorAll<HTMLButtonElement>('button')].find(b=>!b.closest('[hidden]')&&b.textContent?.includes(label));
async function wait(check:()=>void){for(let i=0;i<200;i++){let ok=false;await act(async()=>{await new Promise(r=>setTimeout(r,2));try{check();ok=true;}catch{}});if(ok)return;}check();}
async function click(label:string){await wait(()=>expect(visible(label)?.disabled).toBe(false));await act(async()=>visible(label)!.click());}
beforeEach(async()=>{vi.stubGlobal('crypto',webcrypto);vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);vi.stubGlobal('ArrayBuffer',structuredClone(new ArrayBuffer(0)).constructor);vi.stubGlobal('Uint8Array',structuredClone(new Uint8Array(0)).constructor);journal=new DraftJournal(await openDraftStore({scope:await privateDraftScope(opaque,'http://127.0.0.1:8000',webcrypto),native:false,indexedDB:new IDBFactory(),crypto:webcrypto}));context={journal,recoveryScope:opaque,authorize:vi.fn(async()=>{})};
 vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,scheduling:false,google:false,microsoft:false,messaging:true,payments:false,portals:false});vi.mocked(readConnectionSummary).mockResolvedValue({label:'Needs setup',reason:'Invented unconfigured account',action:'Open setup',tone:'attention'});vi.spyOn(accountIdentityApi,'read').mockResolvedValue({contract_version:1,box_id:faxScope.box_id,actor_id:faxScope.owner_id,recovery_scope:opaque});vi.spyOn(faxInboundApi,'status').mockResolvedValue(faxStatus);vi.spyOn(faxInboundApi,'command');host=document.createElement('div');document.body.append(host);root=createRoot(host);
});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();journal.close();vi.restoreAllMocks();vi.unstubAllGlobals();});
it('reaches the actual private inbound panel below fax readiness and keeps its unresolved journal mounted',async()=>{
 const close=vi.fn();await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={close}/></AccountRecoveryContext.Provider>));
 await click('Connections');await click('Messaging & fax');await wait(()=>expect(visible('Check receiving access')).toBeDefined());expect(host.querySelector('[aria-label="Received practice faxes"]')).toBeTruthy();expect(faxInboundApi.status).not.toHaveBeenCalled();await click('Check receiving access');expect(faxInboundApi.status).toHaveBeenCalledOnce();
 await act(async()=>{const select=host.querySelector<HTMLSelectElement>('[aria-label="Received practice faxes"] select')!;select.value=faxStatus.installations[0].connection_id;select.dispatchEvent(new Event('change',{bubbles:true}));host.querySelector<HTMLInputElement>('[aria-label="Received practice faxes"] input')!.click();});
 expect(visible('Done')!.disabled).toBe(true);await act(async()=>visible('Done')!.click());expect(close).not.toHaveBeenCalled();expect(faxInboundApi.command).not.toHaveBeenCalled();
});

it.each(['disabled','denied','unknown'] as const)('does not open received-fax storage on initially %s availability',async mode=>{
 if(mode==='disabled')vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,scheduling:false,google:false,microsoft:false,messaging:false,payments:false,portals:false});
 else vi.mocked(readConnectionCatalog).mockRejectedValue(mode==='denied'?new WorkspaceApiError(403):new Error('offline'));
 await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="connections" team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={()=>{}}/></AccountRecoveryContext.Provider>));
 await click('Messaging & fax');
 expect(host.querySelector('[data-settings-inbound]')).toBeNull();expect(accountIdentityApi.read).not.toHaveBeenCalled();expect(faxInboundApi.status).not.toHaveBeenCalled();
});
it('hides a previously mounted received-fax panel during pending, disabled and denied checks without losing its review',async()=>{
 await act(async()=>root.render(<AccountRecoveryContext.Provider value={context}><SettingsHub open initialScreen="connections" team={<p>Team</p>} messaging={<p>Provider accounts</p>} teamSummary="5 coworkers" teamDirty={false} connectionIdentity={identity} onClose={()=>{}}/></AccountRecoveryContext.Provider>));
 await click('Messaging & fax');await click('Check receiving access');
 const panel=host.querySelector('[data-settings-inbound]')!;const select=panel.querySelector<HTMLSelectElement>('select')!;
 await act(async()=>{select.value=faxStatus.installations[0].connection_id;select.dispatchEvent(new Event('change',{bubbles:true}));});
 const selection=select.value;let finish!:(value:Awaited<ReturnType<typeof readConnectionCatalog>>)=>void;
 vi.mocked(readConnectionCatalog).mockReturnValueOnce(new Promise(resolve=>{finish=resolve}));
 await click('Check fax setup');expect(panel.hasAttribute('hidden')).toBe(false);
 // The previous enabled catalog remains usable while its refresh is pending.
 await act(async()=>finish({core:false,scheduling:false,google:false,microsoft:false,messaging:false,payments:false,portals:false}));
 expect(panel.hasAttribute('hidden')).toBe(true);expect(host.querySelector('[data-settings-inbound]')).toBe(panel);expect(select.value).toBe(selection);
 vi.mocked(readConnectionCatalog).mockRejectedValueOnce(new WorkspaceApiError(403));await click('Check fax setup');
 expect(panel.hasAttribute('hidden')).toBe(true);expect(select.value).toBe(selection);
 vi.mocked(readConnectionCatalog).mockResolvedValue({core:false,scheduling:false,google:false,microsoft:false,messaging:true,payments:false,portals:false});await click('Check fax setup');
 expect(panel.hasAttribute('hidden')).toBe(false);expect(host.querySelector('[data-settings-inbound]')).toBe(panel);expect(panel.querySelector('select')).toBe(select);expect(select.value).toBe(selection);expect(faxInboundApi.status).toHaveBeenCalledOnce();expect(faxInboundApi.command).not.toHaveBeenCalled();
});
