import {ConnectorTools, parseAgentResearchHistory, parseAgentResearchReview, type ConnectorTransport, type AgentResearchHandle} from '../../clients/capture/src/team/connector-tools';
import {validAgentResearchApproval, type AgentResearchApproval} from './agent-research-recovery';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';
import {assertCurrentDesktopSession, workspaceAuthHeaders} from './workspace-auth-headers';
import {workspaceFetch} from './workspace-protocol';
import {parseVendorJson} from './vendor-contract';
import {validateGoogleResponse} from './google-connection-api';
import {validateMicrosoftResponse} from './microsoft-connection-api';
import {validGoogleMessageStatus} from './google-message-api';
import {validGoogleCalendarStatus} from './google-calendar-api';
import {validateFaxStatus} from './fax-inbound-api';
import {validateEFaxStatus} from './efax-inbound-api';
import {verifyFinanceSetupView} from './finance-setup-contract';
import {verifyPortalCatalog} from './portal-setup-contract';

async function validateStatus(path: string, value: unknown) {
  if (path === '/connections/google/session') return validateGoogleResponse(value, 'status');
  if (path === '/connections/microsoft/session') return validateMicrosoftResponse(value, 'status');
  if (path === '/connections/google/messages') {if (!validGoogleMessageStatus(value)) throw new WorkspaceApiError(502); return value;}
  if (path === '/connections/google/calendar-summaries') {if (!validGoogleCalendarStatus(value)) throw new WorkspaceApiError(502); return value;}
  if (path === '/fax-inbound') return validateFaxStatus(value);
  if (path === '/efax-inbound') {
    const scope = value && typeof value === 'object' && !Array.isArray(value) ? (value as {scope?: unknown}).scope : null;
    if (!scope || typeof scope !== 'object' || Array.isArray(scope)) throw new WorkspaceApiError(502);
    return validateEFaxStatus(value, scope as {box_id: string; owner_id: string});
  }
  if (path === '/finance-setup') return verifyFinanceSetupView('Catalog', value);
  if (path === '/portal-setup') return verifyPortalCatalog(value);
  return value;
}

/** Fresh existing-session auth; credentials are never copied into a plugin file. */
export function connectorTransport(identity: AuthenticatedWorkspaceIdentity): ConnectorTransport {
  return async (path, request) => {
    const uuid = '[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}';
    const reviewPath = new RegExp(`^/workspaces/${uuid}/agent-research(?:/${uuid}/review)?$`).test(path);
    if (!reviewPath && !['/connections/plugins', '/connections/google/session', '/connections/google/messages',
      '/connections/google/calendar-summaries', '/connections/microsoft/session', '/fax-inbound', '/efax-inbound',
      '/portal-setup', '/finance-setup'].includes(path)) throw new WorkspaceApiError(422);
    const base = import.meta.env.VITE_API_BASE?.trim().replace(/\/+$/, '') || 'http://127.0.0.1:8000';
    const controller = new AbortController(), abort = () => controller.abort();
    const interrupted = new Promise<never>((_, reject) => controller.signal.addEventListener('abort',
      () => reject(new WorkspaceApiError(503)), {once: true}));
    void interrupted.catch(() => {});
    const wait = <T,>(value: Promise<T>) => Promise.race([value, interrupted]);
    const check = () => {controller.signal.throwIfAborted(); assertCurrentDesktopSession(identity);
      if (identity.mode !== 'desktop_native' && identity.nativeSession && !identity.nativeSession.isCurrent()) throw new WorkspaceApiError(401);};
    const timer = setTimeout(abort, reviewPath ? 30000 : 15000); request.signal?.addEventListener('abort', abort, {once: true});
    let response: Response | undefined, reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    const cancel = (stream: {cancel: () => Promise<unknown>} | undefined | null) => {try {void stream?.cancel().catch(() => {});} catch {/* Already closed. */}};
    try {
      if (request.signal?.aborted) abort(); check();
      const headers = await wait(workspaceAuthHeaders(identity, base).catch(() => {throw new WorkspaceApiError(401);})); check();
      headers.set(request.contractHeader, '1'); headers.set('Accept', 'application/json');
      response = await wait(workspaceFetch(identity, base + path, {method: request.method, headers,
        ...(request.body === undefined ? {} : {body: JSON.stringify(request.body)}), signal: controller.signal,
        credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer'}).then(value => {
          if (controller.signal.aborted) {cancel(value.body); throw new WorkspaceApiError(503);} return value;
        })); check();
      if (!response) throw new WorkspaceApiError(503);
      if ([401, 403, 404, 426].includes(response.status)) throw new WorkspaceApiError(response.status);
      if (response.status !== 200 || response.redirected || response.headers.has('content-encoding') ||
          response.headers.get('content-type')?.split(';', 1)[0] !== 'application/json' ||
          !response.headers.get('cache-control')?.split(',').some(value => value.trim() === 'no-store')) throw new WorkspaceApiError(502);
      reader = response.body?.getReader(); if (!reader) throw new WorkspaceApiError(502);
      const bytes = new Uint8Array(reviewPath ? 48000 : 1048576); let size = 0;
      for (;;) {const chunk = await wait(reader.read()); check(); if (chunk.done) break;
        if (chunk.value.byteLength > bytes.length - size) throw new WorkspaceApiError(502);
        bytes.set(chunk.value, size); size += chunk.value.byteLength;}
      const value = parseVendorJson(new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, size))); check();
      const validated = await wait(validateStatus(path, value)); check(); return validated;
    } catch (cause) {if (cause instanceof WorkspaceApiError) throw cause; throw new WorkspaceApiError(503);}
    finally {clearTimeout(timer); request.signal?.removeEventListener('abort', abort); cancel(reader ?? response?.body);
      try {reader?.releaseLock();} catch {/* Already closed. */} controller.abort();}
  };
}
export const connectorToolsApi = (identity: AuthenticatedWorkspaceIdentity) => new ConnectorTools(connectorTransport(identity));
const handle = (value: AgentResearchHandle) => ({ticket_id: value.ticket_id, revision_id: value.revision_id, payload_hash: value.payload_hash});
export const agentResearchApi = {
  async list(identity: AuthenticatedWorkspaceIdentity, workspaceId: string, signal?: AbortSignal) {
    return parseAgentResearchHistory(await connectorTransport(identity)(`/workspaces/${workspaceId}/agent-research`,
      {method: 'GET', contractHeader: 'X-Cosmas-Research-Contract', signal}), workspaceId);
  },
  async approve(identity: AuthenticatedWorkspaceIdentity, workspaceId: string, value: AgentResearchApproval, signal?: AbortSignal) {
    if (!validAgentResearchApproval(value)) throw new WorkspaceApiError(422);
    const result = parseAgentResearchReview(await connectorTransport(identity)(`/workspaces/${workspaceId}/agent-research/${value.ticket_id}/review`,
      {method: 'POST', contractHeader: 'X-Cosmas-Research-Contract', body: {revision_id: value.revision_id,
        payload_hash: value.payload_hash, public_query_confirmed: true}, signal}), workspaceId);
    if (JSON.stringify(handle(result)) !== JSON.stringify(handle(value)) || result.state !== 'approved') throw new WorkspaceApiError(502);
    return result;
  },
};
