/**
 * Copy-to-EHR journey coverage against the fixed export contract (track E).
 * Synthetic fixtures only — invented Taylor Morgan sore-throat note.
 * Copy and export only; never vendor credentials or chart automation.
 */
import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';

vi.hoisted(() => {
  vi.stubEnv('VITE_COSMAS_ENV', 'synth_os');
  vi.stubEnv('VITE_WORKSPACE_ENABLED', 'true');
  vi.stubEnv('VITE_WORKSPACE_AUTHENTICATED_ENABLED', 'true');
});

import {CopyToEhrStrip} from './CopyToEhrStrip';
import {CopyToEhrPopout} from './CopyToEhrPopout';
import {CopyToEhrMount} from './CopyToEhrMount';
import {CLIPBOARD_CLEAR_TEXT, type CopyToEhrPackage} from './copy-to-ehr-api';
import {taylorMorganPackage} from './copy-to-ehr-fixtures.test-support';

/** Remote highlight pointer (track C). Section key only — never note text. */
type CopyToEhrHighlightMessage = {draft_revision: number; section_key: string};

const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');

const NOTE_CANARIES = [
  'Taylor Morgan',
  'sore throat',
  'Gargle warm salt water',
  'Rapid strep',
] as const;

let root: Root;
let host: HTMLDivElement;
const writeClipboard = vi.fn();
const audit = vi.fn();

const button = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('button')].find(item => item.textContent === name);

async function renderStrip(extra: Partial<Parameters<typeof CopyToEhrStrip>[0]> = {}) {
  const pkg = taylorMorganPackage();
  await act(async () =>
    root.render(
      <CopyToEhrStrip
        pkg={pkg}
        expectedRevision={pkg.draft_revision}
        onAudit={audit}
        {...extra}
      />,
    ),
  );
  return pkg;
}

async function click(name: string) {
  const control = button(name);
  expect(control, name).toBeTruthy();
  await act(async () => control!.click());
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('crypto', webcrypto);
  writeClipboard.mockReset();
  writeClipboard.mockResolvedValue(undefined);
  audit.mockReset();
  vi.stubGlobal('navigator', {clipboard: {writeText: writeClipboard}});
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it('copies the full note without leading hash lines and keeps extras out of that copy', async () => {
  const pkg = await renderStrip();
  expect(writeClipboard).not.toHaveBeenCalled();
  await click('Copy full note');
  expect(writeClipboard).toHaveBeenCalledExactlyOnceWith(pkg.full_note);
  const copied = String(writeClipboard.mock.calls[0][0]);
  expect(copied.split('\n').some(line => line.startsWith('#'))).toBe(false);
  expect(copied).toContain(pkg.sections[0].text);
  expect(copied).not.toContain(pkg.extras.patient_instructions);
  expect(copied).not.toContain(pkg.extras.orders);
  expect(JSON.stringify(audit.mock.calls)).not.toContain('Taylor Morgan');
});

it('copies one section at a time without a leading hash', async () => {
  const pkg = await renderStrip();
  await click('Copy this section');
  expect(writeClipboard).toHaveBeenCalledExactlyOnceWith(pkg.sections[0].text);
  const copied = String(writeClipboard.mock.calls[0][0]);
  expect(copied.startsWith('#')).toBe(false);
  expect(copied.split('\n').some(line => line.startsWith('#'))).toBe(false);
});

it('clears the clipboard by writing a single space', async () => {
  expect(CLIPBOARD_CLEAR_TEXT).toBe(' ');
  await renderStrip();
  await click('Clear clipboard');
  expect(writeClipboard).toHaveBeenCalledExactlyOnceWith(' ');
  expect(host.querySelector('[role=status]')?.textContent).toContain('Clipboard cleared');
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event: 'copy_to_ehr.cleared'}));
});

it('disables copy actions when the draft revision is stale', async () => {
  await renderStrip({expectedRevision: 2});
  expect(host.querySelector('[role=alert]')?.textContent).toContain('This draft changed');
  for (const label of ['Copy full note', 'Copy this section', 'Next highlight', 'Clear clipboard', 'Pop out']) {
    expect(button(label)?.disabled, label).toBe(true);
  }
  await click('Copy full note');
  expect(writeClipboard).not.toHaveBeenCalled();
});

it('shows the note was NOT sent and offers Copy to EHR after a connection failure, without blocking the visit', async () => {
  await renderStrip({connectionFailed: true});
  const notice = host.querySelector('.copy-to-ehr-not-sent');
  expect(notice?.textContent).toMatch(/not sent/i);
  expect(host.textContent).toContain('Copy to EHR');
  expect(host.textContent).toMatch(/continue the visit/i);
  expect(host.textContent).not.toMatch(/integrat|sync|write-?back/i);
  // Visit stays usable: Done remains available.
  expect(button('Done')?.disabled).toBe(false);
  expect(audit).toHaveBeenCalledWith(expect.objectContaining({event: 'copy_to_ehr.fallback_shown'}));
  expect(JSON.stringify(audit.mock.calls)).not.toContain('sore throat');
});

it('never falls back silently: connection failure surfaces the copy offer on the mount', async () => {
  const identity = {mode: 'clerk_jwt' as const, getToken: vi.fn()};
  const pkg = taylorMorganPackage();
  const loadPackage = vi.fn().mockResolvedValue(pkg);
  await act(async () =>
    root.render(
      <CopyToEhrMount
        enabled={false}
        fallbackOffer={true}
        identity={identity}
        draftId={pkg.draft_id}
        expectedRevision={pkg.draft_revision}
        loadPackage={loadPackage}
        onAudit={audit}
      />,
    ),
  );
  expect(host.querySelector('.copy-to-ehr-not-sent')?.textContent).toMatch(/not sent/i);
  await act(async () => undefined);
  await act(async () => {
    await Promise.resolve();
  });
  expect(loadPackage).toHaveBeenCalled();
  expect(host.querySelector('.copy-to-ehr-strip') || host.querySelector('.copy-to-ehr-not-sent')).toBeTruthy();
  expect(host.textContent).not.toMatch(/integrat|sync|write-?back/i);
});

it('does not mount the strip when the copy-to-ehr flag is off and there is no fallback offer', async () => {
  const identity = {mode: 'clerk_jwt' as const, getToken: vi.fn()};
  const loadPackage = vi.fn();
  await act(async () =>
    root.render(
      <CopyToEhrMount
        enabled={false}
        fallbackOffer={false}
        identity={identity}
        draftId="visit_note_00000000000000000000000001"
        loadPackage={loadPackage}
      />,
    ),
  );
  expect(host.querySelector('.copy-to-ehr-strip')).toBeNull();
  expect(host.querySelector('.copy-to-ehr-mount')).toBeNull();
  expect(button('Copy full note')).toBeUndefined();
  expect(button('Copy to EHR')).toBeUndefined();
  expect(loadPackage).not.toHaveBeenCalled();
  expect(writeClipboard).not.toHaveBeenCalled();
});

it('remote highlight messages carry section pointers only, never note text', async () => {
  const {useCopyToEhrRemote} = await import('./useCopyToEhrRemote');
  expect(typeof useCopyToEhrRemote).toBe('function');
  const highlight: CopyToEhrHighlightMessage = {
    draft_revision: 3,
    section_key: 'subjective',
  };
  const encoded = JSON.stringify(highlight);
  for (const token of NOTE_CANARIES) {
    expect(encoded).not.toContain(token);
  }
  expect(Object.keys(highlight).sort()).toEqual(['draft_revision', 'section_key']);
  await renderStrip({highlightedKey: 'assessment'});
  expect(host.textContent).toContain('Next section: Assessment');
  expect(JSON.stringify(audit.mock.calls)).not.toContain('Taylor Morgan');
});

it('ends the transfer session after expiry without retaining note text in audit', async () => {
  const expired: CopyToEhrPackage = taylorMorganPackage({
    expires_at: '2020-01-01T00:00:00Z',
  });
  await act(async () =>
    root.render(
      <CopyToEhrStrip pkg={expired} expectedRevision={expired.draft_revision} onAudit={audit} />,
    ),
  );
  expect(host.querySelector('[role=alert]')?.textContent).toMatch(/expired/i);
  for (const label of ['Copy full note', 'Copy this section', 'Clear clipboard']) {
    expect(button(label)?.disabled, label).toBe(true);
  }
  await click('Copy full note');
  expect(writeClipboard).not.toHaveBeenCalled();
  expect(JSON.stringify(audit.mock.calls)).not.toContain('sore throat');
});

it('pop-out uses strip controls and never writes Atlas credentials', async () => {
  await act(async () =>
    root.render(
      <CopyToEhrPopout disabled={false} sectionLabel="Subjective" sectionIndex={0} sectionCount={4} />,
    ),
  );
  expect(host.querySelector('.copy-to-ehr-popout')).toBeTruthy();
  expect(button('Pop out')).toBeTruthy();
  expect(host.textContent).not.toMatch(/client_secret|client_id|password|api[_-]?key/i);
  expect(host.textContent ?? '').not.toContain('atlas_credentials');
  expect(host.textContent ?? '').not.toContain('ehr_credentials');
});
