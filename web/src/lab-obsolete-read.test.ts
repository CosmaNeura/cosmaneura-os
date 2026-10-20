import { expect, it } from 'vitest';
import { expectedObsoleteWorkspaceRead, type LabReadWire, type LabValidatedRead } from './lab-obsolete-read';

const cancelled: LabReadWire = {
  path: '/workspaces/invented-workspace', method: 'GET', status: null, mount: 1, scope: 0, abort_ms: 100,
  abort: { caller_aborted: true, episode_closed: false, retired_mount: true, refresh_scope: null },
};
const replacement: LabValidatedRead = { workspace_id: 'invented-workspace', mount: 2, scope: 0, revision: 15, status: 200, observed_ms: 101 };
const refreshed: LabReadWire = { ...cancelled, scope: 2,
  abort: { ...cancelled.abort!, retired_mount: false, refresh_scope: 3 } };
const refreshReplacement: LabValidatedRead = { ...replacement, mount: 1, scope: 3 };

it('recognizes only a caller-cancelled read from an explicitly retired live episode mount', () => {
  expect(expectedObsoleteWorkspaceRead(cancelled, 'invented-workspace', replacement)).toBe(true);
});

it.each([
  { method: 'POST' }, { method: 'PUT' }, { path: '/workspaces/invented-workspace/handoffs/id/review' },
  { path: '/workspaces/another-workspace' }, { status: 500 }, { mount: 0 }, { abort: undefined },
  { abort_ms: undefined },
  { abort: { ...cancelled.abort!, caller_aborted: false } },
  { abort: { ...cancelled.abort!, episode_closed: true } },
  { abort: { ...cancelled.abort!, retired_mount: false } },
])('rejects an unproven cancellation: %j', changed => {
  expect(expectedObsoleteWorkspaceRead({ ...cancelled, ...changed }, 'invented-workspace', replacement)).toBe(false);
});

it('recognizes a read aborted after explicit refresh only after a fully validated current-scope replacement', () => {
  expect(expectedObsoleteWorkspaceRead(refreshed, 'invented-workspace', refreshReplacement)).toBe(true);
});

it.each([
  undefined, { ...replacement, mount: 1 }, { ...replacement, workspace_id: 'another-workspace' },
  { ...replacement, revision: 0 }, { ...replacement, status: 503 },
])('rejects retired-read proof without the exact new-mount validated read: %j', current => {
  expect(expectedObsoleteWorkspaceRead(cancelled, 'invented-workspace', current)).toBe(false);
});

it.each([
  { ...refreshReplacement, scope: 2 }, { ...refreshReplacement, mount: 2 },
  { ...refreshReplacement, workspace_id: 'another-workspace' }, undefined,
])('rejects refresh proof without the exact current-scope validated read: %j', current => {
  expect(expectedObsoleteWorkspaceRead(refreshed, 'invented-workspace', current)).toBe(false);
});

it.each([null, 2, 1, 2.5])('rejects arbitrary or already-current read cancellation: %j', refreshScope => {
  expect(expectedObsoleteWorkspaceRead({ ...refreshed,
    abort: { ...refreshed.abort!, refresh_scope: refreshScope } }, 'invented-workspace', refreshReplacement)).toBe(false);
});

it.each([99, 100, Number.NaN])('rejects a replacement not observed after the abort: %j', observed => {
  expect(expectedObsoleteWorkspaceRead(refreshed, 'invented-workspace',
    { ...refreshReplacement, observed_ms: observed })).toBe(false);
});

it('retains the exact refresh replacement when a later remount has another current read', () => {
  const history = [refreshReplacement, { ...replacement, scope: 3, observed_ms: 200 }];
  expect(expectedObsoleteWorkspaceRead(refreshed, 'invented-workspace', history[1])).toBe(false);
  expect(history.some(read => expectedObsoleteWorkspaceRead(refreshed, 'invented-workspace', read))).toBe(true);
});
