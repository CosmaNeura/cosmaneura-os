import {act} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {beforeEach,afterEach,expect,it,vi} from 'vitest';
vi.hoisted(()=>{vi.stubEnv('VITE_COSMAS_ENV','synth_os');vi.stubEnv('VITE_WORKSPACE_ENABLED','true');vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED','true');vi.stubEnv('VITE_EFAX_INBOUND_ENABLED','true');});
import {SettingsHub} from './SettingsHub';
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
 expect(visible('Done')!.disabled).toBe(true);await act(async()=>visible('Done')!.click());expect(close).not.toHaveBeenCalled();expect(efaxInboundApi.command).not.toHaveBeenCalled();
});
