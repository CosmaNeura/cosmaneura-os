import {act, createElement} from 'react';
import {createRoot} from 'react-dom/client';
import {afterEach, expect, it, vi} from 'vitest';
import {clickEnabledLabButton} from './lab-button';

afterEach(() => {document.body.replaceChildren(); vi.unstubAllGlobals();});

it('reproduces a stale enabled observation across act flush, then admits exactly one enabled native click', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const host = document.createElement('div'); document.body.append(host);
  const root = createRoot(host), lookup = vi.fn();
  const render = (disabled: boolean) => root.render(createElement('button', {disabled, onClick: lookup}, 'Use a Scribe recording'));
  const find = () => host.querySelector<HTMLButtonElement>('button')!;
  await act(async () => render(false));
  // A pending recording/recovery update can flush after wait's successful
  // assertion but before its separately scheduled click. The browser ignores it.
  let observed = false;
  await act(async () => {observed = !find().disabled; render(true);});
  expect(observed).toBe(true); expect(find().disabled).toBe(true);
  await act(async () => find().click());
  expect(lookup).not.toHaveBeenCalled();
  await act(async () => render(false));
  const turn = async (callback: () => Promise<void>) => act(async () => {await callback(); render(true);});
  await clickEnabledLabButton(find, turn, () => {}, 'Use a Scribe recording');
  expect(lookup).toHaveBeenCalledOnce(); expect(find().disabled).toBe(true);
  await act(async () => root.unmount());
});

it('does not dispatch while disabled and uses the current replacement control once ready', async () => {
  const host = document.createElement('div'); document.body.append(host);
  const disabled = document.createElement('button'); disabled.disabled = true;
  const blockedClick = vi.fn(); disabled.onclick = blockedClick; host.append(disabled);
  const ready = document.createElement('button'), accepted = vi.fn(); ready.onclick = accepted;
  let turns = 0;
  const turn = async (callback: () => Promise<void>) => {await callback(); if (++turns === 1) disabled.replaceWith(ready);};
  await clickEnabledLabButton(() => host.querySelector('button')!, turn, () => {}, 'recording');
  expect(blockedClick).not.toHaveBeenCalled(); expect(accepted).toHaveBeenCalledOnce();
  expect(turns).toBe(2);
});

it('propagates an act failure after dispatch without retrying or advancing a cancelled episode', async () => {
  const button = document.createElement('button'); document.body.append(button);
  const accepted = vi.fn(); button.onclick = accepted;
  const failure = new Error('original React turn failed');
  await expect(clickEnabledLabButton(() => button, async callback => {await callback(); throw failure;}, () => {}, 'recording')).rejects.toBe(failure);
  expect(accepted).toHaveBeenCalledOnce();
  await expect(clickEnabledLabButton(() => button, async callback => {await callback();}, () => {throw new Error('episode closed');}, 'recording')).rejects.toThrow('episode closed');
  expect(accepted).toHaveBeenCalledOnce();
});
