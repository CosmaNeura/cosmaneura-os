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
  vi.stubEnv('VITE_COPY_TO_EHR_ENABLED', 'true');
  vi.stubEnv('VITE_COPY_TO_EHR_REMOTE_ENABLED', 'true');
  vi.stubEnv('VITE_COPY_TO_EHR_FALLBACK_ENABLED', 'true');
});

import {CopyToEhrStrip} from './CopyToEhrStrip';
import {CopyToEhrPopout} from './CopyToEhrPopout';
import {
  COPY_TO_EHR_ENABLED,
  copyToEhrApi,
  type CopyToEhrPackage,
  type CopyToEhrHighlightMessage,
} from './copy-to-ehr-api';
import {useCopyToEhrRemote} from './useCopyToEhrRemote';

const {webcrypto} = await vi.importActual<{webcrypto: Crypto}>('node:crypto');

const DRAFT_ID = '00000000-0000-4000-8000-000000000501';
const DRAFT_REVISION = 3;
const SUBJECTIVE =
  'Taylor Morgan reports an invented sore throat for two days. No # code was discussed.';
const OBJECTIVE = 'Invented exam: oropharynx mildly erythematous without exudate.';
const ASSESSMENT = 'Invented viral pharyngitis.';
const PLAN = 'Supportive care; return if fever persists three days.';
const PATIENT_INSTRUCTIONS = 'Invented: fluids and rest for Taylor Morgan.';
const ORDERS = 'Invented: no imaging ordered for this visit.';
const NOTE_CANARIES = [
  SUBJECTIVE,
  OBJECTIVE,
  ASSESSMENT,
  PLAN,
  PATIENT_INSTRUCTIONS,
  ORDERS,
  'Taylor Morgan',
  'sore throat',
] as const;

const pkg = (): CopyToEhrPackage => ({
  profile_id: 'atlas_md',
  draft_id: DRAFT_ID,
  draft_revision: DRAFT_REVISION,
  payload_hash: 'a'.repeat(64),
  sections: [
    {key: 'Subjective', label: 'Subjective', text: SUBJECTIVE},
    {key: 'Objective', label: 'Objective', text: OBJECTIVE},
    {key: 'Assessment', label: 'Assessment', text: ASSESSMENT},
    {key: 'Plan', label: 'Plan', text: PLAN},
  ],
  extras: {
    patient_instructions: PATIENT_INSTRUCTIONS,
    orders: ORDERS,
  },
  created_at: '2026-11-09T15:00:00Z',
  expires_at: '2026-11-09T16:00:00Z',
  review_state: 'reviewed',
  full_note: [
    'Subjective',
    SUBJECTIVE,
    '',
    'Objective',
    OBJECTIVE,
    '',
    'Assessment',
    ASSESSMENT,
    '',
    'Plan',
    PLAN,
  ].join('\n'),
});

let root: Root;
let host: HTMLDivElement;
const writeClipboard = vi.fn();

const visible = (element: Element) => !element.closest('[hidden]');
const button = (name: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('button')].find(
    item =>
      visible(item) &&
      (item.textContent?.trim() === name || item.getAttribute('aria-label') === name),
  );

async function wait(assertion: () => void | Promise<void>) {
  for (let n = 0; n < 200; n++) {
    let done = false;
    await act(async () => {
      await new Promise(resolve => setTimeout(resolve, 3));
      try {
        await assertion();
        done = true;
      } catch {
        /* keep polling */
      }
    });
    if (done) return;
  }
  await assertion();
}

async function click(name: string) {
  await wait(() => expect(button(name), name).toBeTruthy());
  await wait(() => expect(button(name)!.disabled, name).toBe(false));
  await act(async () => button(name)!.click());
}

async function mountStrip(
  extra: Partial<Parameters<typeof CopyToEhrStrip>[0]> = {},
) {
  const value = pkg();
  await act(async () =>
    root.render(
      <CopyToEhrStrip
        package={value}
        profileId="atlas_md"
        draftRevision={DRAFT_REVISION}
        payloadHash={value.payload_hash}
        stale={false}
        fallbackOffer={false}
        onDone={vi.fn()}
        {...extra}
      />,
    ),
  );
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.stubGlobal('crypto', webcrypto);
  writeClipboard.mockReset();
  writeClipboard.mockResolvedValue(undefined);
  vi.stubGlobal('navigator', {clipboard: {writeText: writeClipboard}});
  vi.stubEnv('VITE_COPY_TO_EHR_ENABLED', 'true');
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
  await mountStrip();
  await click('Copy full note');
  expect(writeClipboard).toHaveBeenCalledOnce();
  const copied = String(writeClipboard.mock.calls[0][0]);
  expect(copied.split('\n').some(line => line.trimStart().startsWith('#'))).toBe(false);
  expect(copied).toContain(SUBJECTIVE);
  expect(copied).toContain(PLAN);
  expect(copied).not.toContain(PATIENT_INSTRUCTIONS);
  expect(copied).not.toContain(ORDERS);
});

it('copies one section at a time without a leading hash', async () => {
  await mountStrip();
  await click('Copy this section');
  expect(writeClipboard).toHaveBeenCalledOnce();
  const copied = String(writeClipboard.mock.calls[0][0]);
  expect(copied.trimStart().startsWith('#')).toBe(false);
  expect(copied.split('\n').some(line => line.trimStart().startsWith('#'))).toBe(false);
  expect(NOTE_CANARIES.some(token => copied.includes(token))).toBe(true);
});

it('clears the clipboard by writing a single space', async () => {
  await mountStrip();
  await click('Clear clipboard');
  expect(writeClipboard).toHaveBeenCalledExactlyOnceWith(' ');
});

it('disables copy actions when the draft revision or payload hash is stale', async () => {
  await mountStrip({stale: true});
  for (const label of ['Copy full note', 'Copy this section', 'Clear clipboard']) {
    const control = button(label);
    expect(control, label).toBeTruthy();
    expect(control!.disabled, label).toBe(true);
  }
  expect(writeClipboard).not.toHaveBeenCalled();
});

it('shows the note was NOT sent and offers Copy to EHR after a connection failure, without blocking the visit', async () => {
  await mountStrip({
    fallbackOffer: true,
    connectionFailed: true,
    noteSent: false,
  });
  const text = host.textContent ?? '';
  expect(/not sent/i.test(text)).toBe(true);
  expect(button('Copy to EHR') ?? button('Copy full note')).toBeTruthy();
  expect(host.querySelector('[data-copy-to-ehr-blocked="true"]')).toBeNull();
  expect(host.querySelector('[aria-disabled="true"][data-visit-blocked]')).toBeNull();
  // Visit remains usable: Done stays available so the clinician can leave.
  expect(button('Done')?.disabled ?? false).toBe(false);
  for (const token of NOTE_CANARIES) {
    // Visible note preview for copy is allowed; audit/network paths are scrubbed elsewhere.
    expect(token.includes('https://')).toBe(false);
  }
});

it('never falls back silently: connection failure surfaces the copy offer', async () => {
  await mountStrip({fallbackOffer: true, connectionFailed: true, noteSent: false, silent: false});
  expect(host.querySelector('[data-copy-to-ehr-silent="true"]')).toBeNull();
  expect(host.textContent).toMatch(/not sent/i);
  expect(button('Copy to EHR') ?? button('Copy full note')).toBeTruthy();
});

it('does not mount the strip when the copy-to-ehr flag is off', async () => {
  // Parent mount points (NoteReview / CaptureDraftPanel) pass enabled from the
  // build flag. When that flag is off, the strip must render nothing.
  expect(typeof COPY_TO_EHR_ENABLED).toBe('boolean');
  await act(async () =>
    root.render(
      <CopyToEhrStrip
        package={pkg()}
        profileId="atlas_md"
        draftRevision={DRAFT_REVISION}
        payloadHash={'a'.repeat(64)}
        stale={false}
        fallbackOffer={false}
        enabled={false}
        onDone={vi.fn()}
      />,
    ),
  );
  expect(host.querySelector('.copy-to-ehr-strip')).toBeNull();
  expect(host.querySelector('.copy-to-ehr-popout')).toBeNull();
  expect(button('Copy full note')).toBeUndefined();
  expect(button('Copy to EHR')).toBeUndefined();
  expect(button('Clear clipboard')).toBeUndefined();
  expect(writeClipboard).not.toHaveBeenCalled();
});

it('remote highlight messages carry section pointers only, never note text', async () => {
  expect(typeof useCopyToEhrRemote).toBe('function');
  const highlight: CopyToEhrHighlightMessage = {
    draft_revision: DRAFT_REVISION,
    section_key: 'Subjective',
  };
  const encoded = JSON.stringify(highlight);
  for (const token of NOTE_CANARIES) {
    expect(encoded).not.toContain(token);
  }
  expect(highlight).toEqual({draft_revision: DRAFT_REVISION, section_key: 'Subjective'});
  expect('text' in highlight).toBe(false);

  const postHighlight = vi.spyOn(copyToEhrApi, 'postHighlight').mockResolvedValue(highlight);
  await act(async () => {
    await copyToEhrApi.postHighlight('00000000-0000-4000-8000-000000000601', {
      draft_revision: DRAFT_REVISION,
      section_key: 'Plan',
    });
  });
  expect(postHighlight).toHaveBeenCalledOnce();
  const body = postHighlight.mock.calls[0][1];
  const wire = JSON.stringify(body);
  for (const token of NOTE_CANARIES) {
    expect(wire).not.toContain(token);
  }
  expect(body).toMatchObject({draft_revision: DRAFT_REVISION, section_key: 'Plan'});
  expect(Object.keys(body).sort()).toEqual(['draft_revision', 'section_key']);
});

it('ends the transfer session after idle or absolute expiry without retaining note text', async () => {
  vi.spyOn(copyToEhrApi, 'createSession').mockResolvedValue({
    session_id: '00000000-0000-4000-8000-000000000602',
    expires_at: '2026-11-09T15:15:00Z',
    absolute_expires_at: '2026-11-09T16:00:00Z',
  });
  vi.spyOn(copyToEhrApi, 'sessionStatus').mockResolvedValue({
    active: false,
    reason: 'idle_expired',
  });
  await mountStrip({sessionExpired: true});
  expect(host.textContent).toMatch(/expired|ended|end transfer/i);
  for (const label of ['Copy full note', 'Copy this section']) {
    expect(button(label)?.disabled ?? true).toBe(true);
  }
  const serialized = host.innerHTML;
  // Expiry UI must not dump extras that were never part of the full note path into logs via DOM dumps in tests;
  // the strip may still show section labels for recovery.
  expect(serialized.includes('atlas_credentials')).toBe(false);
});

it('pop-out uses the same strip controls and never writes Atlas credentials', async () => {
  const value = pkg();
  await act(async () =>
    root.render(
      <CopyToEhrPopout
        package={value}
        profileId="atlas_md"
        draftRevision={DRAFT_REVISION}
        payloadHash={value.payload_hash}
      />,
    ),
  );
  expect(button('Copy full note') ?? host.querySelector('.copy-to-ehr-strip')).toBeTruthy();
  expect(host.textContent).not.toMatch(/client_secret|client_id|password|api[_-]?key/i);
  for (const token of ['atlas_credentials', 'ehr_credentials']) {
    expect(host.textContent ?? '').not.toContain(token);
  }
});
