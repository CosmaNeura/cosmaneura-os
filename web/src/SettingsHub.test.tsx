import {act, useEffect, useState} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {SettingsHub} from './SettingsHub';

let container: HTMLDivElement, root: Root;
beforeEach(() => { Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true}); container = document.createElement('div'); document.body.append(container); root = createRoot(container); });
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
function visibleButtons() { return [...container.querySelectorAll('button')].filter(button => !button.closest('[hidden]')); }
async function click(text: string) {
  const button = visibleButtons().find(button => button.textContent?.includes(text));
  expect(button, `Visible button: ${text}`).toBeDefined(); await act(async () => button!.click());
}
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
