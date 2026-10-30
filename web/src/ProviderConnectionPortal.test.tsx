import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {ProviderConnectionPortal} from './ProviderConnectionPortal';

let host: HTMLDivElement, root: Root;
const buttons = () => [...host.querySelectorAll<HTMLButtonElement>('button')].filter(button => !button.closest('[hidden]'));
beforeEach(() => { vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host); });
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });

it('keeps EHR access read only and refuses to describe Rx Relay as able to send', async () => {
  const open = vi.fn();
  await act(async () => root.render(<ProviderConnectionPortal records={{elation: open, tebra: open, athena: open, atlas_md: open}} locked={false}/>));
  expect(host.textContent).toContain('CosmaBot connector');
  expect(host.textContent).toContain('Read only');
  expect(host.textContent).toContain('Not connected for sending');
  expect(host.querySelector('[aria-label="Sign-in portal backup"]')).toBeNull();
  expect(host.textContent).toContain('does not sign or transmit');
  const elation = buttons().find(button => button.textContent?.includes('Elation'))!;
  expect(elation.getAttribute('aria-pressed')).toBe('true');
  await act(async () => buttons().find(button => button.textContent === 'Open Elation records')!.click());
  expect(open).toHaveBeenCalledOnce();
  await act(async () => buttons().find(button => button.textContent?.includes('Atlas.MD'))!.click());
  expect(host.textContent).toContain('File import only');
  expect(host.textContent).toContain('cannot send or sign');
  expect(buttons().some(button => /send prescription|transmit prescription/i.test(button.textContent ?? ''))).toBe(false);
});

it('labels a records system that this app cannot open yet', async () => {
  await act(async () => root.render(<ProviderConnectionPortal locked={false}/>));
  const action = buttons().find(button => button.textContent === 'Not available in this app')!;
  expect(action.disabled).toBe(true);
  expect(host.querySelector('[aria-label="Sign-in portal backup"]')?.textContent).toContain('No vendor sign-in is started');
  await act(async () => action.click());
  expect(host.textContent).toContain('Ask your practice administrator');
});
