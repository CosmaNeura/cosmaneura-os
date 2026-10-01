import {modelWorkApi} from '../src/model-work-api';
import {exactModelObservation, MODEL_RECEIPT_BYTES, MODEL_WORKSPACE_BYTES,
  validModelOperation, validModelWorkspace, type ModelOperation, type ModelRequestObservation} from '../src/model-work-request';
import {teamUuid} from '../src/team-setup-request';
import {validProviderTeam} from '../src/team-setup-validators';
import {workspaceApi, WorkspaceApiError, type ProviderTeam, type Workspace} from '../src/workspace-api';

export const LAB_ORIGIN = 'http://127.0.0.1:5194';
export const identity = {mode: 'clerk_jwt' as const, getToken: async () => null};
type Session = {persona: 'provider' | 'nurse' | 'pa'; round: '1' | '2'; base: string};
type OpenResult = {workspace: Workspace; team: ProviderTeam};
type SavedResult = {entry_revision: number; workspace: Workspace};
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

export function labSession(href: string): Session {
  const url = new URL(href);
  const persona = url.searchParams.get('persona'), round = url.searchParams.get('round');
  if (url.origin !== LAB_ORIGIN || url.pathname !== '/' || url.hash || url.username || url.password ||
      url.searchParams.size !== 2 || !['provider', 'nurse', 'pa'].includes(persona ?? '') || !['1', '2'].includes(round ?? '')) {
    throw new Error('Open a supplied local clinician test link.');
  }
  return {persona: persona as Session['persona'], round: round as Session['round'], base: `/lab-api/${persona}/${round}`};
}

/** A test-only transport. Results always come from the fixed local session. */
export async function installLiveBridge(href = window.location.href): Promise<Session> {
  const session = labSession(href);
  const nativeFetch = window.fetch.bind(window);
  let workspaceId: string | undefined, appointmentId: string | undefined;
  const allowedApi = (path: string) => path === `${session.base}/open` || path === `${session.base}/workspace` ||
    path === `${session.base}/entries` || path === `${session.base}/ask` || path === `${session.base}/resolve` ||
    path === `${session.base}/status` || path === `${session.base}/notes` ||
    new RegExp(`^${session.base}/notes/[a-f0-9-]{36}/review$`).test(path);

  // Browser imports and Vite assets remain same-origin. Application requests
  // cannot reach other sessions, real services, or authenticated endpoints.
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), LAB_ORIGIN);
    if (url.origin !== LAB_ORIGIN || url.username || url.password || url.hash ||
        url.pathname.startsWith('/lab-api') && (!allowedApi(url.pathname) || url.search)) {
      throw new WorkspaceApiError(503);
    }
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (!url.pathname.startsWith('/lab-api/') && method !== 'GET' && method !== 'HEAD') throw new WorkspaceApiError(503);
    return nativeFetch(input, {...init, credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer'});
  };

  async function request(path: string, body?: unknown, signal?: AbortSignal, maximum = MODEL_WORKSPACE_BYTES): Promise<unknown> {
    const controller = new AbortController(), abort = () => controller.abort();
    const timer = window.setTimeout(abort, 180_000);
    signal?.addEventListener('abort', abort, {once: true});
    if (signal?.aborted) abort();
    try {
      const response = await window.fetch(`${session.base}/${path}`, {
        method: body === undefined ? 'GET' : 'POST',
        body: body === undefined ? undefined : JSON.stringify(body),
        headers: {'Content-Type': 'application/json', 'X-Cosmas-Model-Contract': '1'},
        cache: 'no-store', signal: controller.signal,
      });
      if (response.headers.get('content-type')?.split(';')[0].trim() !== 'application/json' ||
          !response.headers.get('cache-control')?.split(',').some(value => value.trim().toLowerCase() === 'no-store')) {
        throw new WorkspaceApiError(503);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new WorkspaceApiError(503);
      const chunks: Uint8Array[] = [];
      let size = 0;
      try {
        for (;;) {
          const part = await reader.read();
          if (part.done) break;
          size += part.value.byteLength;
          if (size > maximum) throw new WorkspaceApiError(503);
          chunks.push(part.value);
        }
      } finally { void reader.cancel().catch(() => {}); }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
      const value: unknown = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
      // A 409 may carry the ordinary saved model admission observation.
      if (response.status !== 200 && !(response.status === 409 && record(value) && value.contract_version === 1)) {
        const code = record(value) && typeof value.detail === 'string' && /^[a-z_]+$/.test(value.detail) ? value.detail : undefined;
        throw new WorkspaceApiError(response.status, code);
      }
      return value;
    } catch (cause) {
      if (cause instanceof WorkspaceApiError) throw cause;
      throw new WorkspaceApiError(503);
    } finally {
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }
  function check(id: string) {
    if (!workspaceId || id !== workspaceId) throw new WorkspaceApiError(403);
  }
  async function checkedWorkspace(value: unknown): Promise<Workspace> {
    if (!record(value) || !teamUuid(value.id) || !teamUuid(value.appointment_id) ||
        workspaceId && value.id !== workspaceId || appointmentId && value.appointment_id !== appointmentId ||
        !await validModelWorkspace(value, value.id as string)) throw new WorkspaceApiError(503);
    return value as unknown as Workspace;
  }
  async function open(signal?: AbortSignal): Promise<OpenResult> {
    const value = await request('open', undefined, signal);
    if (!record(value) || !validProviderTeam(value.team)) throw new WorkspaceApiError(503);
    const workspace = await checkedWorkspace(value.workspace);
    workspaceId ??= workspace.id;
    appointmentId ??= workspace.appointment_id;
    return {workspace, team: value.team};
  }
  async function saved(path: string, id: string, body: unknown): Promise<SavedResult> {
    check(id);
    const value = await request(path, body);
    if (!record(value)) throw new WorkspaceApiError(503);
    const workspace = await checkedWorkspace(value.workspace);
    if (!Number.isInteger(value.entry_revision) || value.entry_revision !== workspace.revision) throw new WorkspaceApiError(503);
    return value as unknown as SavedResult;
  }
  async function command(id: string, operation: ModelOperation, resolve: boolean, signal?: AbortSignal): Promise<ModelRequestObservation> {
    check(id);
    if (!validModelOperation(operation)) throw new WorkspaceApiError(422);
    if (operation.type !== 'ask') throw new WorkspaceApiError(503);
    const value = await request(resolve ? 'resolve' : 'ask', operation.body, signal, MODEL_RECEIPT_BYTES);
    if (!await exactModelObservation(value, id, operation)) throw new WorkspaceApiError(503);
    return value as ModelRequestObservation;
  }

  await open();
  const unavailable = async (): Promise<never> => { throw new WorkspaceApiError(503); };
  for (const key of Object.keys(workspaceApi)) Object.assign(workspaceApi, {[key]: unavailable});
  Object.assign(modelWorkApi, {
    submit: (_identity, id, operation, signal) => command(id, operation, false, signal),
    resolve: (_identity, id, operation, signal) => command(id, operation, true, signal),
    readWorkspace: async (_identity, id, signal) => { check(id); return checkedWorkspace(await request('workspace', undefined, signal)); },
  } satisfies typeof modelWorkApi);
  Object.assign(workspaceApi, {
    catalog: async () => { const {workspace} = await open(); return [{appointment_id: workspace.appointment_id, label: workspace.label, workspace_id: workspace.id}]; },
    team: async (_identity, signal) => (await open(signal)).team,
    open: async (_identity, appointment) => {
      if (appointment !== appointmentId) throw new WorkspaceApiError(403);
      return {identity, ...await open()};
    },
    openExisting: async (_identity, selection) => {
      check(selection.workspace_id);
      if (selection.appointment_id !== appointmentId) throw new WorkspaceApiError(403);
      return {identity, ...await open()};
    },
    read: (access, id, signal) => modelWorkApi.readWorkspace(access, id, signal),
    append: async (_identity, id, body) => {
      const value = await saved('entries', id, body);
      if (!('entry_id' in value) || !teamUuid(value.entry_id) || !value.workspace.entries.some(entry => entry.id === value.entry_id && entry.revision === value.entry_revision)) throw new WorkspaceApiError(503);
      return value as SavedResult & {entry_id: string};
    },
    ask: (access, id, body) => modelWorkApi.submit(access, id, {type: 'ask', body}),
    saveNote: (_identity, id, body) => saved('notes', id, body),
    reviewNote: (_identity, id, noteId, body) => {
      if (!teamUuid(noteId)) throw new WorkspaceApiError(422);
      return saved(`notes/${noteId}/review`, id, body);
    },
  } satisfies Partial<typeof workspaceApi>);
  return session;
}
