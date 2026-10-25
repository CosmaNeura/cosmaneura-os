import {act, useEffect, useState} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {SettingsHub} from './SettingsHub';
import {readConnectionCatalog} from './connection-catalog-api';
import {readConnectionSummary} from './connection-summary';
import {readinessFixture} from './connection-readiness-fixture';
import {WorkspaceApiError} from './workspace-api';
vi.mock('./connection-catalog-api',async original=>({...await original<typeof import('./connection-catalog-api')>(),readConnectionCatalog:vi.fn()}));
vi.mock('./connection-summary',async original=>({...await original<typeof import('./connection-summary')>(),readConnectionSummary:vi.fn()}));

let container: HTMLDivElement, root: Root;
beforeEach(() => { Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
function visibleButtons() { return [...container.querySelectorAll('button')].filter(button => !button.closest('[hidden]')); }
async function click(text: string) {
  const button = visibleButtons().find(button => button.textContent?.includes(text));
  expect(button, `Visible button: ${text}`).toBeDefined(); await act(async () => button!.click());
}
it('opens Elation only when offered and selected, and retains its pending editor across navigation', async () => {
  const mounted = vi.fn(), unmounted = vi.fn();
  function Elation() { useEffect(() => { mounted(); return unmounted; }, []); return <input aria-label="Elation dates" defaultValue="Retained window"/>; }
  const render = (enabled:boolean, initialScreen:'home'|'ehr'='home') => act(async () => root.render(<SettingsHub open initialScreen={initialScreen}
    ehr={enabled?<Elation/>:undefined} team={<p>Team</p>} teamSummary="5 coworkers" teamDirty={false} onClose={()=>{}}/>));
  await render(false);
  expect(visibleButtons().some(button=>button.textContent?.includes('Connections'))).toBe(false);
  await render(true);
  expect(mounted).not.toHaveBeenCalled();
  await click('Connections');
  expect(mounted).not.toHaveBeenCalled();
  expect(container.querySelector('[aria-label="Practice records"]')?.textContent).not.toContain('Connected');
  await click('Practice appointments');
  expect(mounted).toHaveBeenCalledOnce();
  expect(container.querySelector('[aria-label="Elation dates"]')).toBeTruthy();
  await click('All connections'); await click('Practice appointments');
  expect(mounted).toHaveBeenCalledOnce(); expect(unmounted).not.toHaveBeenCalled();
  expect((container.querySelector('[aria-label="Elation dates"]') as HTMLInputElement).value).toBe('Retained window');
});
it('restores Elation after visit selection and blocks leaving during an exact pending command', async () => {
  const close=vi.fn();
  await act(async()=>root.render(<SettingsHub open initialScreen="ehr" navigationLocked ehr={<p>Selected visit</p>}
    team={<p>Team</p>} teamSummary="5 coworkers" teamDirty={false} onClose={close}/>));
  expect(container.querySelector('[data-settings-screen="ehr"]')?.hasAttribute('hidden')).toBe(false);
  expect(visibleButtons().find(button=>button.textContent==='Done')?.disabled).toBe(true);
  expect(visibleButtons().find(button=>button.textContent?.includes('All connections'))?.disabled).toBe(true);
  expect(close).not.toHaveBeenCalled();
});
it('opens appointment discovery directly and retains it after returning from connections', async () => {
  const mounted = vi.fn();
  function Core() { useEffect(() => { mounted(); }, []); return <button>View appointments</button>; }
  await act(async () => root.render(<SettingsHub open initialScreen="core" core={<Core/>} team={<p>Team</p>}
    teamSummary="5 coworkers" teamDirty={false} onClose={() => {}}/>));
  expect(visibleButtons().some(button => button.textContent === 'View appointments')).toBe(true);
  await click('All connections'); await click('Cosmaneura account');
  expect(visibleButtons().some(button => button.textContent === 'View appointments')).toBe(true);
  expect(mounted).toHaveBeenCalledOnce();
});

it('starts with two choices and loads only the selected editor', async () => {
  const mounted = vi.fn();
  function Editor({name}: {name:string}) { useEffect(() => { mounted(name); }, [name]); return <label>{name}<input /></label>; }
  await act(async () => root.render(<SettingsHub open team={<Editor name="team"/>} messaging={<Editor name="messaging"/>}
    payments={<Editor name="payments"/>} portals={<Editor name="portals"/>} teamSummary="4 coworkers" teamDirty={false} onClose={() => {}}/>));
  expect(mounted).not.toHaveBeenCalled();
  expect(container.querySelectorAll('input')).toHaveLength(0);
  expect(visibleButtons()).toHaveLength(3);
  await click('Connections'); expect(mounted).not.toHaveBeenCalled();
  await click('Messaging & fax'); expect(mounted.mock.calls).toEqual([['messaging']]);
  expect(container.querySelectorAll('input')).toHaveLength(1);
  await click('All connections'); await click('Payments');
  expect(mounted.mock.calls).toEqual([['messaging'], ['payments']]);
  expect([...container.querySelectorAll('input')].filter(field => !field.closest('[hidden]'))).toHaveLength(1);
  await click('All connections'); await click('All settings'); await click('Your team');
  expect(mounted.mock.calls).toEqual([['messaging'], ['payments'], ['team']]);
});
it('retains an editor and a completing request across navigation and Done', async () => {
  let finish: (() => void) | undefined;
  const unmount = vi.fn();
  function Editor() {
    const [value, setValue] = useState('Draft retained');
    useEffect(() => () => unmount(), []);
    return <><p>{value}</p><button onClick={() => { finish = () => setValue('Request confirmed'); }}>Save exact draft</button></>;
  }
  function App({identity = 'owner'}: {identity?:string}) {
    const [open, setOpen] = useState(true);
    return <><button onClick={() => setOpen(true)}>Open settings</button><SettingsHub key={identity} open={open} team={<Editor/>}
      messaging={<p>Messaging editor</p>} teamSummary="4 coworkers" teamDirty onClose={() => setOpen(false)}/></>;
  }
  await act(async () => root.render(<App/>));
  await click('Your team'); await click('Save exact draft'); await click('All settings'); await click('Done');
  expect(unmount).not.toHaveBeenCalled();
  await act(async () => finish!()); await click('Open settings'); await click('Your team');
  expect(container.querySelector('[data-settings-screen="team"]')?.textContent).toContain('Request confirmed');
  expect(unmount).not.toHaveBeenCalled();
  await act(async () => root.render(<App identity="another-owner"/>));
  expect(unmount).toHaveBeenCalledOnce();
  expect(container.textContent).not.toContain('Request confirmed');
});
it('moves focus to the new screen title and keeps unavailable connections out', async () => {
  const close = vi.fn();
  await act(async () => root.render(<SettingsHub open team={<p>Team</p>} teamSummary="Choose coworkers" teamDirty={false} onClose={close}/>));
  expect(document.activeElement?.textContent).toBe('Settings');
  expect(visibleButtons().some(button => button.textContent?.includes('Connections'))).toBe(false);
  await click('Your team'); expect(document.activeElement?.textContent).toBe('Your team');
  await click('Done'); expect(close).toHaveBeenCalledOnce();
});

it.each(['workspace','messages',undefined] as const)('keeps Settings navigation in the native scroll target while preserving heading focus (native=%s)', async nativePresentation => {
  const originalScroll = Object.getOwnPropertyDescriptor(HTMLElement.prototype,'scrollIntoView');
  const scroll = vi.fn();
  const focus = vi.spyOn(HTMLElement.prototype,'focus');
  Object.defineProperty(HTMLElement.prototype,'scrollIntoView',{configurable:true,writable:true,value:scroll});
  const render = (open:boolean,layout=nativePresentation) => act(async () => root.render(<SettingsHub open={open} nativePresentation={layout}
    team={<div><p>Long team settings</p><input aria-label="Retained team draft" defaultValue="Invented draft"/></div>}
    teamSummary="Five coworkers" teamDirty={false} onClose={() => {}}/>));
  try {
    await render(false);
    expect(scroll).not.toHaveBeenCalled();
    expect(focus).not.toHaveBeenCalled();
    await render(true);
    const section = container.querySelector('.settings-hub')!;
    const title = section.querySelector('h1')!;
    const expectedTarget = nativePresentation ? section : title;
    expect(document.activeElement).toBe(title);
    expect(focus).toHaveBeenLastCalledWith({preventScroll:true});
    expect(scroll.mock.contexts).toEqual([expectedTarget]);
    expect(scroll).toHaveBeenLastCalledWith({block:'start'});
    expect(section.querySelector('.settings-hub-nav')?.textContent).toContain('Done');
    await click('Your team');
    const editor = section.querySelector('[aria-label="Retained team draft"]');
    expect(document.activeElement?.textContent).toBe('Your team');
    expect(scroll.mock.contexts).toEqual([expectedTarget,expectedTarget]);
    await click('All settings');
    expect(document.activeElement?.textContent).toBe('Settings');
    expect(scroll.mock.contexts).toEqual([expectedTarget,expectedTarget,expectedTarget]);
    expect(section.querySelector('[aria-label="Retained team draft"]')).toBe(editor);
    if(nativePresentation){
      await render(true,nativePresentation==='messages'?'workspace':'messages');
      expect(document.activeElement?.textContent).toBe('Settings');
      expect(scroll.mock.contexts).toEqual([section,section,section,section]);
      expect(section.querySelector('[aria-label="Retained team draft"]')).toBe(editor);
    }
    const focusCount = focus.mock.calls.length;
    await render(false);
    expect(scroll).toHaveBeenCalledTimes(nativePresentation?4:3);
    expect(focus).toHaveBeenCalledTimes(focusCount);
  } finally {
    focus.mockRestore();
    if(originalScroll)Object.defineProperty(HTMLElement.prototype,'scrollIntoView',originalScroll);
    else delete (HTMLElement.prototype as Partial<HTMLElement>).scrollIntoView;
  }
});

it('keeps recovery available while preventing navigation during an undurable edit', async () => {
  const close = vi.fn();
  function App() {
    const [locked, setLocked] = useState(false);
    return <SettingsHub open team={<p>Team</p>} teamSummary="4 coworkers" teamDirty={false} navigationLocked={locked} onClose={close}
      messaging={<><button onClick={() => setLocked(true)}>Simulate failed draft storage</button>
        <button onClick={() => setLocked(false)}>Retry local save</button></>}/>;
  }
  await act(async () => root.render(<App/>));
  await click('Connections'); await click('Messaging & fax'); await click('Simulate failed draft storage');
  for (const label of ['All connections', 'Done']) {
    const button = visibleButtons().find(button => button.textContent?.includes(label))!;
    expect(button.disabled).toBe(true); await act(async () => button.click());
  }
  expect(close).not.toHaveBeenCalled();
  expect(container.querySelector('[data-settings-screen="messaging"]')?.hasAttribute('hidden')).toBe(false);
  await click('Retry local save'); await click('All connections'); await click('Done');
  expect(close).toHaveBeenCalledOnce();
});

it('keeps user OAuth actionable and puts unsupported portals and uninstalled practice services outside onboarding setup',async()=>{
 const catalog=readinessFixture();vi.mocked(readConnectionCatalog).mockResolvedValue(catalog);
 vi.mocked(readConnectionSummary).mockResolvedValue({label:'Needs setup',reason:'Sign in to connect your account.',action:'Connect account',tone:'attention'});
 const mounted=vi.fn();function Portal(){useEffect(()=>{mounted();},[]);return <button>Connect portal</button>;}
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" guidedConnections connectionIdentity={{mode:'clerk_jwt',getToken:async()=>null}}
   team={<p>Team</p>} google={<button>Connect Google</button>} messaging={<button>Configure account</button>} portals={<Portal/>} payments={<button>Connect Stripe</button>}
   teamSummary="5 coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(container.querySelector('[aria-label="Coming soon"]')?.textContent).toContain('Patient portals');
 expect(container.querySelector('[aria-label="Managed by your practice"]')?.textContent).toContain('Messaging & fax');
 expect(visibleButtons().some(b=>b.textContent?.includes('Open portals')||b.textContent?.includes('Connect Stripe')||b.textContent?.includes('Configure account'))).toBe(false);
 expect(mounted).not.toHaveBeenCalled();await click('Google email & calendar');
 expect(visibleButtons().some(b=>b.textContent==='Connect Google')).toBe(true);
 expect(container.textContent).toContain('Send email · Coming soon');
});

it('retains a visited recovery editor when a supported installation is removed without showing a new Connect action',async()=>{
 const available=readinessFixture({portals:'practice_setup'});available.portals=true;available.readiness!.portals.supported=true;available.readiness!.portals.installed_account='installed';
 vi.mocked(readConnectionCatalog).mockResolvedValue(available);const mounted=vi.fn();
 function Portal(){useEffect(()=>{mounted();},[]);return <button>Resolve exact saved request</button>;}
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" guidedConnections connectionIdentity={{mode:'clerk_jwt',getToken:async()=>null}}
   team={<p>Team</p>} portals={<Portal/>} teamSummary="5 coworkers" teamDirty={false} onClose={()=>{}}/>));
 await click('Patient portals');await click('All connections');
 vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture());await click('Refresh connections');
 expect(visibleButtons().some(b=>b.textContent?.includes('Open portals'))).toBe(false);
 await click('Review saved Patient portals work');expect(visibleButtons().some(b=>b.textContent==='Resolve exact saved request')).toBe(true);
 expect(mounted).toHaveBeenCalledOnce();
});
it('can deliberately open private recovery on a fresh coming-soon service without treating it as connectable',async()=>{
 vi.mocked(readConnectionCatalog).mockResolvedValue(readinessFixture());const mounted=vi.fn();
 function Portal(){useEffect(()=>{mounted();},[]);return <button>Resolve exact retained request</button>;}
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" guidedConnections connectionIdentity={{mode:'clerk_jwt',getToken:async()=>null}}
   team={<p>Team</p>} portals={<Portal/>} teamSummary="5 coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(mounted).not.toHaveBeenCalled();await click('Review saved Patient portals work');
 expect(mounted).toHaveBeenCalledOnce();expect(visibleButtons().some(b=>b.textContent==='Resolve exact retained request')).toBe(true);
 expect(container.textContent).toContain('Current access is still required');
});
it('directs an unsupported catalog contract to an app update and preserves a deliberately opened recovery editor',async()=>{
 vi.mocked(readConnectionCatalog).mockRejectedValue(new WorkspaceApiError(426));
 await act(async()=>root.render(<SettingsHub open initialScreen="connections" connectionIdentity={{mode:'clerk_jwt',getToken:async()=>null}}
   team={<p>Team</p>} google={<button>Check exact saved request</button>} teamSummary="5 coworkers" teamDirty={false} onClose={()=>{}}/>));
 expect(container.textContent).toContain('CosmaBot → Update CosmaBot…');
 await click('Google email & calendar');expect(container.textContent).toContain('Your saved work and unresolved requests are retained');
 expect(visibleButtons().some(b=>b.textContent==='Check exact saved request')).toBe(true);
});
