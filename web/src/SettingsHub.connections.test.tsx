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
 expect(catalog.textContent).toContain('No live connection');expect(catalog.textContent).toContain('Access checked when opened');expect(catalog.textContent).not.toContain('Connected');
 await click('Atlas.MD');expect(opened).toHaveBeenLastCalledWith('atlas_md');await click('Elation');await click('Tebra');await click('Athena');expect(opened.mock.calls.map(c=>c[0])).toEqual(['atlas_md','elation','tebra','athena']);
 expect(mounted).not.toHaveBeenCalled();expect(readConnectionCatalog).not.toHaveBeenCalled();expect(readConnectionSummary).not.toHaveBeenCalled();
});
it('exposes the supplied account control at home without duplicating or replacing its action',async()=>{
 const logout=vi.fn();await act(async()=>root.render(<SettingsHub {...{accountControls:<button onClick={logout}>Log out</button>}} open team={<p>Team</p>} teamSummary="Five coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(host.querySelector('[aria-label="Account"]')?.textContent).toContain('Log out');await click('Log out');expect(logout).toHaveBeenCalledOnce();
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
 await click('Back to connections');await click('Google email & calendar');expect(host.querySelector('[aria-label="Connection draft"]')).toBe(input);expect(input.value).toBe('Retained invented draft');expect(mounted).toHaveBeenCalledOnce();
});
