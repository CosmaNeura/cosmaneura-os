/**
 * Runtime flag wiring. Synthetic note only. Flags come from the API, never a build switch.
 */
import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';

vi.mock('./copy-to-ehr-api', async () => {
  const actual = await vi.importActual<typeof import('./copy-to-ehr-api')>('./copy-to-ehr-api');
  return {...actual, fetchCopyToEhrPackage: vi.fn()};
});
vi.mock('./capture-notes-api', () => ({
  captureDraft: vi.fn(),
  captureNoteTemplates: vi.fn(),
  saveCaptureDraft: vi.fn(),
}));

import {captureDraft, captureNoteTemplates} from './capture-notes-api';
import {CaptureDraftPanel} from './CaptureDraftPanel';
import {fetchCopyToEhrPackage} from './copy-to-ehr-api';
import {COPY_TO_EHR_FLAGS_OFF, copyToEhrFlagProps, fetchCopyToEhrFlags} from './copy-to-ehr-flags';
import {NoteReview} from './NoteReview';
import {useCopyToEhrFlags} from './useCopyToEhrFlags';
import {workspaceFetch} from './workspace-protocol';
import type {AuthenticatedWorkspaceIdentity, PrivateNote, Workspace} from './workspace-api';
import type {CaptureDraft} from './capture-notes-api';

const NOTE = 'Sore throat for two days.';
const identity = {mode: 'clerk_jwt' as const, getToken: vi.fn(async () => 'synthetic-token')};
const saved: PrivateNote = {
  id: 'note-one', version: 1, workspace_revision: 2, content: NOTE, content_hash: 'a'.repeat(64),
  source_reply_id: null, source_revision: 1, source_fingerprint: 'b'.repeat(64), sources_changed: false,
  review: {id: 'review-one', reviewer_id: 'clinician-one', created_at: '2026-09-16T12:05:00Z'},
  created_at: '2026-09-16T12:00:00Z',
};
const workspace: Workspace = {
  id: 'workspace', appointment_id: 'appointment', label: 'Invented person', revision: 2,
  entries: [], work_candidates: [], note: {latest: saved, history: [saved]},
};
const captureWorkspace = '00000000-0000-4000-8000-000000000002';
const session = '00000000-0000-4000-8000-000000000003';
const source = '00000000-0000-4000-8000-000000000004';
const schema = `doctor_note_schema_${'0'.repeat(25)}1`;
const captureSaved: CaptureDraft = {
  session_id: session, scribe_source_id: source, source_sha256: 'a'.repeat(64), schema_ref: schema,
  status: 'draft', note_type: 'Visit note', transcript_ref: 'synthetic-transcript', note_ref: 'visit_note_taylor',
  fields: {Plan: 'Fluids and rest.', CC: 'Invented sore throat'}, field_order: ['CC', 'Plan'],
  note_sha256: 'b'.repeat(64), created_at: '2026-09-17T09:00:00Z', review_required: true,
};

function flagResponse(header: string, body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: {'Content-Type': 'application/json', 'X-Cosmas-Copy-To-Ehr-Flags': header},
  });
}

function WiredReview({signedIn}: {signedIn: AuthenticatedWorkspaceIdentity}) {
  const flags = useCopyToEhrFlags(signedIn);
  return <NoteReview workspace={workspace} locked={false} onSave={() => {}} onSources={() => {}}
    copyToEhrIdentity={signedIn} {...copyToEhrFlagProps(flags)} />;
}

let root: Root;
let host: HTMLDivElement;

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  vi.mocked(fetchCopyToEhrPackage).mockReset();
  vi.mocked(fetchCopyToEhrPackage).mockResolvedValue({
    profile_id: 'atlas_md', draft_id: 'note-one', draft_revision: '1', payload_hash: 'c'.repeat(64),
    sections: [{key: 'subjective', label: 'Subjective', text: NOTE}], extras: [],
    created_at: '2026-09-16T12:00:00Z', expires_at: '2026-09-16T12:15:00Z',
    review_state: 'reviewed', visit_copy_to_ehr_status: 'unset',
    full_note: `Subjective\n${NOTE}`, section_notes: {subjective: `Subjective\n${NOTE}`},
  });
  vi.mocked(captureNoteTemplates).mockResolvedValue([{schema_ref: schema, note_type: 'Visit note', field_names: ['CC', 'Plan']}]);
  vi.mocked(captureDraft).mockResolvedValue(captureSaved);
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it('keeps Copy to EHR off when the API flags are false, even if a build value says true', async () => {
  vi.stubEnv('VITE_COPY_TO_EHR_ENABLED', 'true');
  const fetchMock = vi.fn(async () => flagResponse('0,0,0', {
    copy_to_ehr_enabled: false, copy_to_ehr_remote_enabled: false, copy_to_ehr_fallback_enabled: false,
  }));
  vi.stubGlobal('fetch', fetchMock);
  await act(async () => root.render(<WiredReview signedIn={identity} />));
  expect(host.querySelector('.copy-to-ehr-mount')).toBeNull();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(fetchCopyToEhrPackage).not.toHaveBeenCalled();
  await act(async () => { await workspaceFetch(identity, 'http://127.0.0.1:8000/workspaces', {method: 'GET'}); });
  expect(host.querySelector('.copy-to-ehr-mount')).toBeNull();
  expect(host.textContent).not.toMatch(/copy to ehr/i);
  const read = await fetchCopyToEhrFlags(identity);
  expect(read).toEqual(COPY_TO_EHR_FLAGS_OFF);
});

it('passes API flags through to the reviewed note and the capture draft', async () => {
  vi.stubEnv('VITE_COPY_TO_EHR_ENABLED', 'false');
  vi.stubGlobal('fetch', vi.fn(async () => flagResponse('1,1,0', {
    copy_to_ehr_enabled: true, copy_to_ehr_remote_enabled: true, copy_to_ehr_fallback_enabled: false,
  })));
  await act(async () => root.render(<WiredReview signedIn={identity} />));
  expect(host.querySelector('.copy-to-ehr-mount')).toBeNull();
  await act(async () => { await workspaceFetch(identity, 'http://127.0.0.1:8000/workspaces', {method: 'GET'}); });
  const mount = host.querySelector('.copy-to-ehr-mount');
  expect(mount).toBeTruthy();
  expect(mount?.getAttribute('data-copy-to-ehr-remote')).toBe('on');
  expect(fetchCopyToEhrPackage).toHaveBeenCalled();
  const calls = vi.mocked(fetchCopyToEhrPackage).mock.calls;
  expect(calls[0]?.[1]).toBe('note-one');
  expect(calls[0]?.[3]).toBe('1');

  await act(async () => root.render(
    <CaptureDraftPanel workspaceId={captureWorkspace} sessionId={session} sourceId={source} identity={identity}
      {...copyToEhrFlagProps({enabled: true, remoteEnabled: true, fallbackOffer: false})} />,
  ));
  await vi.waitFor(() => expect(host.querySelector('.copy-to-ehr-mount')).toBeTruthy());
  expect(host.querySelector('.copy-to-ehr-mount')?.getAttribute('data-copy-to-ehr-remote')).toBe('on');
  expect(host.textContent).not.toMatch(/integrat|sync|write-?back/i);
});

it('does not render Copy to EHR on a capture draft when the flags are off', async () => {
  await act(async () => root.render(
    <CaptureDraftPanel workspaceId={captureWorkspace} sessionId={session} sourceId={source} identity={identity}
      {...copyToEhrFlagProps(COPY_TO_EHR_FLAGS_OFF)} />,
  ));
  await vi.waitFor(() => expect(host.textContent).toContain('clinical review required'));
  expect(host.querySelector('.copy-to-ehr-mount')).toBeNull();
  expect(host.textContent).not.toMatch(/copy to ehr/i);
});
