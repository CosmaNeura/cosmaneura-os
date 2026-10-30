import {act,useEffect} from 'react';
import {createRoot,type Root} from 'react-dom/client';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {SettingsHub} from './SettingsHub';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {readinessFixture} from './connection-readiness-fixture';
vi.mock('./connection-catalog-api',async original=>({...await original<typeof import('./connection-catalog-api')>(),readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));
let host:HTMLDivElement,root:Root;
const identity={mode:'clerk_jwt' as const,getToken:async()=>null};
const buttons=()=>[...host.querySelectorAll<HTMLButtonElement>('button')].filter(b=>!b.closest('[hidden]'));
async function click(name:string){const b=buttons().find(b=>b.textContent?.includes(name));expect(b,`Visible ${name}`).toBeTruthy();expect(b!.disabled).toBe(false);await act(async()=>b!.click());}
beforeEach(()=>{vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT',true);host=document.createElement('div');document.body.append(host);root=createRoot(host);vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture());vi.mocked(readConnectionSummary).mockResolvedValue({label:'Needs setup',reason:'Sign in to connect this invented account.',action:'Connect account',tone:'attention'});});
afterEach(async()=>{await act(async()=>root.unmount());host.remove();vi.clearAllMocks();vi.unstubAllGlobals();});
it('offers four named record paths only after choosing Add connection, without reading or mounting a provider',async()=>{
 const opened=vi.fn(),mounted=vi.fn();function Editor(){useEffect(()=>{mounted();},[]);return <input aria-label="Retained provider draft" defaultValue="Invented draft"/>;}
 const props={practiceRecordActions:{atlas_md:()=>opened('atlas_md'),elation:()=>opened('elation'),tebra:()=>opened('tebra'),athena:()=>opened('athena')}};
 await act(async()=>root.render(<SettingsHub {...props} open initialScreen="connections" ehr={<Editor/>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(mounted).not.toHaveBeenCalled();await click('Add connection');
 const catalog=host.querySelector('[aria-label="Add connection catalog"]')!;expect(catalog).toBeTruthy();
 for(const name of ['Atlas.MD','Elation','Tebra','Athena'])expect(catalog.textContent).toContain(name);
 expect(catalog.textContent).toContain('no live sync');expect(catalog.textContent).toContain('Approved practice access checked when opened');expect(catalog.textContent).toContain('athenahealth allergy');expect(catalog.textContent).not.toContain('Connected');
 await click('Atlas.MD');expect(opened).toHaveBeenLastCalledWith('atlas_md');await click('Elation');await click('Tebra');await click('Athena');expect(opened.mock.calls.map(c=>c[0])).toEqual(['atlas_md','elation','tebra','athena']);
 expect(mounted).not.toHaveBeenCalled();expect(readConnectionCatalog).not.toHaveBeenCalled();expect(readConnectionSummary).not.toHaveBeenCalled();
});
it('exposes the supplied account control at home without duplicating or replacing its action',async()=>{
 const logout=vi.fn();await act(async()=>root.render(<SettingsHub {...{accountControls:<button onClick={logout}>Log out</button>}} open team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(host.querySelector('[aria-label="Account"]')?.textContent).toContain('Log out');await click('Log out');expect(logout).toHaveBeenCalledOnce();
});
it('opens the EHR and Rx Relay portal without claiming a prescription can be sent',async()=>{
 const open=vi.fn();await act(async()=>root.render(<SettingsHub {...{practiceRecordActions:{elation:open}}} open team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await click('EHR & Rx Relay');
 expect(host.querySelector('h1')?.textContent).toBe('EHR & Rx Relay');
 expect(host.textContent).toContain('Not connected for sending');
 expect(host.textContent).not.toMatch(/Send prescription/);
 await click('Open Elation records');expect(open).toHaveBeenCalledOnce();
});
it('keeps Log out reachable from Connections next to Done',async()=>{
 const logout=vi.fn();await act(async()=>root.render(<SettingsHub {...{accountControls:<button onClick={logout}>Log out</button>}} open initialScreen="connections" team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 const navAccount=host.querySelector('.settings-hub-nav [aria-label="Account"]');
 expect(navAccount?.textContent).toContain('Log out');
 expect(host.querySelector('.settings-hub-nav .settings-done')).toBeTruthy();
 await act(async()=>navAccount!.querySelector('button')!.click());expect(logout).toHaveBeenCalledOnce();
});
it('returns from the catalog to its launching control without starting another connection check',async()=>{
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" connectionIdentity={identity} google={<button>Actual Google editor</button>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 const before={catalog:vi.mocked(readConnectionCatalog).mock.calls.length,summary:vi.mocked(readConnectionSummary).mock.calls.length};
 await click('Add connection');expect(document.activeElement?.textContent).toBe('Choose a service');await click('Back to connections');expect(document.activeElement?.textContent).toBe('Add connection');
 expect(readConnectionCatalog).toHaveBeenCalledTimes(before.catalog);expect(readConnectionSummary).toHaveBeenCalledTimes(before.summary);
 await click('Google email & calendar');expect(buttons().some(b=>b.textContent==='Actual Google editor')).toBe(true);
});
it('keeps missing record capabilities explicit and blocks all catalog actions while navigation is locked',async()=>{
 const open=vi.fn();const render=(locked:boolean)=>act(async()=>root.render(<SettingsHub open initialScreen="connections" navigationLocked={locked} practiceRecordActions={{elation:open}} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await render(false);await click('Add connection');
 for(const name of ['Atlas.MD','Tebra','Athena']){const b=buttons().find(b=>b.textContent?.includes(name))!;expect(b.disabled).toBe(true);expect(b.textContent).toContain('Not available in this app');await act(async()=>b.click());}
 await render(true);for(const b of buttons()){expect(b.disabled).toBe(true);await act(async()=>b.click());}expect(open).not.toHaveBeenCalled();
});
it('opens records from the compact Practice records entry and preserves visited editor state on return',async()=>{
 const mounted=vi.fn(),open=vi.fn();function Google(){useEffect(()=>{mounted();},[]);return <input aria-label="Connection draft" defaultValue="Retained invented draft"/>;}
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" google={<Google/>} practiceRecordActions={{elation:open}} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await click('Google email & calendar');const input=host.querySelector<HTMLInputElement>('[aria-label="Connection draft"]')!;await click('All connections');await click('Choose your records system');await click('Elation');expect(open).toHaveBeenCalledOnce();
 await click('Back to connections');expect(document.activeElement?.textContent).toContain('Choose your records system');await click('Google email & calendar');expect(host.querySelector('[aria-label="Connection draft"]')).toBe(input);expect(input.value).toBe('Retained invented draft');expect(mounted).toHaveBeenCalledOnce();
});

async function search(value:string){const input=host.querySelector<HTMLInputElement>('input[type="search"]')!;expect(input).toBeTruthy();await act(async()=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}));});}
it('replaces the ordinary list with one searchable picker and keeps email, fax and records discoverable without new checks',async()=>{
 const mounted=vi.fn();function Google(){useEffect(()=>{mounted();},[]);return <button>Actual Google editor</button>;}
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" connectionIdentity={identity} practiceRecordActions={{elation:vi.fn()}} google={<Google/>} microsoft={<p>Microsoft</p>} messaging={<p>Fax</p>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 const before={catalog:vi.mocked(readConnectionCatalog).mock.calls.length,summary:vi.mocked(readConnectionSummary).mock.calls.length};
 await click('Add connection');
 expect(host.querySelector('.connection-directory-list')?.hasAttribute('hidden')).toBe(true);
 expect(host.querySelector('h1')?.textContent).toBe('Choose a service');expect(host.querySelector('.connection-add-catalog h2')).toBeNull();
 expect(buttons().filter(b=>b.textContent?.includes('Back to'))).toHaveLength(1);
 expect(buttons().some(b=>b.textContent==='Add connection'||b.textContent?.includes('All settings')||b.textContent==='Refresh connections')).toBe(false);
 expect(host.querySelector('[aria-label="Add connection catalog"]')?.textContent).toContain('Messaging & fax');
 await search('G Suite');expect(buttons().some(b=>b.textContent?.includes('Google email & calendar'))).toBe(true);expect(buttons().some(b=>b.textContent?.includes('Microsoft email & calendar'))).toBe(false);
 await search('Office 365');expect(buttons().some(b=>b.textContent?.includes('Microsoft email & calendar'))).toBe(true);expect(buttons().some(b=>b.textContent?.includes('Google email & calendar'))).toBe(false);
 await search('  Gmail  ');expect(buttons().some(b=>b.textContent?.includes('Google email & calendar'))).toBe(true);expect(buttons().some(b=>b.textContent?.includes('Elation')||b.textContent?.includes('Messaging & fax'))).toBe(false);
 expect(mounted).not.toHaveBeenCalled();expect(readConnectionCatalog).toHaveBeenCalledTimes(before.catalog);expect(readConnectionSummary).toHaveBeenCalledTimes(before.summary);
 await click('Google email & calendar');expect(mounted).toHaveBeenCalledOnce();expect(buttons().some(b=>b.textContent==='Actual Google editor')).toBe(true);
});
it('recovers from a search with no results and filters records locally without enabling unavailable services',async()=>{
 const opened=vi.fn();await act(async()=>root.render(<SettingsHub open initialScreen="connections" practiceRecordActions={{elation:opened}} google={<p>Google editor</p>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await click('Add connection');await search('unlisted provider');expect(host.querySelector('[aria-label="Add connection catalog"]')?.textContent).toContain('No services match your search.');
 expect(buttons().some(b=>b.textContent?.includes('Elation'))).toBe(false);await click('Show all services');expect(host.querySelector<HTMLInputElement>('input[type="search"]')!.value).toBe('');
 await click('Records');expect(host.querySelector('[aria-label="Add connection catalog"]')?.textContent).not.toContain('Google email & calendar');expect(buttons().find(b=>b.textContent?.includes('Atlas.MD'))?.disabled).toBe(true);
 expect(opened).not.toHaveBeenCalled();expect(readConnectionCatalog).not.toHaveBeenCalled();expect(readConnectionSummary).not.toHaveBeenCalled();
 await click('Back to connections');expect(document.activeElement?.textContent).toBe('Add connection');await click('Add connection');expect(host.querySelector('[aria-pressed="true"]')?.textContent).toBe('All');expect(host.querySelector<HTMLInputElement>('input[type="search"]')!.value).toBe('');
});
it('opens setup guidance for an unavailable service and mounts saved work only after a deliberate recovery choice',async()=>{
 const mounted=vi.fn();function Portal(){useEffect(()=>{mounted();},[]);return <button>Recover retained portal request</button>;}
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" guidedConnections connectionIdentity={identity} portals={<Portal/>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await click('Add connection');await search('portal');const portal=buttons().find(b=>b.textContent?.includes('Patient portals'))!;expect(portal.textContent).toContain('Coming soon');await click('Patient portals');
 expect(mounted).not.toHaveBeenCalled();expect(host.querySelector('[aria-label="Coming soon"]')?.textContent).toContain('No connection or request is started here');await click('Review saved work');expect(mounted).toHaveBeenCalledOnce();expect(buttons().some(b=>b.textContent==='Recover retained portal request')).toBe(true);
});
it('closes the picker and clears its search when the authenticated account changes',async()=>{
 const render=(account:typeof identity)=>act(async()=>root.render(<SettingsHub open initialScreen="connections" connectionIdentity={account} google={<p>Google</p>} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 await render(identity);await click('Add connection');await search('old search');await render({...identity});expect(host.querySelector('[aria-label="Add connection catalog"]')).toBeNull();await click('Add connection');expect(host.querySelector<HTMLInputElement>('input[type="search"]')!.value).toBe('');
});
it('keeps the native directory compact while the catalog retains setup-only services',async()=>{
 vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture({core:'user_connectable',google:'user_connectable',microsoft:'user_connectable',messaging:'practice_setup'}));
 vi.mocked(readConnectionSummary).mockImplementation(async(_who,id)=>id==='google'
   ?{label:'Connected',reason:'invented@example.test',action:'Open Google',tone:'neutral',checkedAt:Date.now()}
   :id==='microsoft'?{label:'Needs setup',reason:'Sign in to connect.',action:'Connect account',tone:'attention'}
   :{label:'Needs attention',reason:'Practice review is required.',action:'Review connection',tone:'attention'});
 await act(async()=>root.render(<SettingsHub open nativePresentation="messages" initialScreen="connections" connectionIdentity={identity} core={<p>Core</p>} google={<p>Google</p>} microsoft={<p>Microsoft</p>} messaging={<p>Fax</p>} practiceRecordActions={{elation:vi.fn()}} team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 const directory=host.querySelector('[data-native-directory="true"]')!;expect(directory).toBeTruthy();
 expect(directory.textContent).toContain('Google email & calendar');expect(directory.textContent).toContain('Connected');
 expect(directory.textContent).toContain('Cosmaneura account & appointments');expect(directory.textContent).toContain('Needs attention');
 expect(directory.textContent).not.toContain('Microsoft email & calendar');expect(directory.textContent).not.toContain('Messaging & fax');
 expect(directory.querySelectorAll('details')).toHaveLength(0);expect(directory.textContent).toContain('Choose your records system');
 await click('Add connection');const catalog=host.querySelector('[aria-label="Add connection catalog"]')!;
 expect(catalog.textContent).toContain('Microsoft email & calendar');expect(catalog.textContent).toContain('Messaging & fax');expect(catalog.textContent).toContain('Elation');
});
