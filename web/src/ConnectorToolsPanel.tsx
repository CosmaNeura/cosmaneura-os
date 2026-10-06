import {useEffect, useRef, useState} from 'react';
import {availableConnectorStatuses, CONNECTOR_STATUS, connectorStatusId, type ConnectorTool} from '../../clients/capture/src/team/connector-tools';
import {connectorToolsApi} from './connector-tools-api';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';

export function ConnectorToolsPanel({identity, locked = false, onAuthenticationLost}: {
  identity: AuthenticatedWorkspaceIdentity; locked?: boolean; onAuthenticationLost?: (cause: unknown) => void;
}) {
  const [tools, setTools] = useState<ConnectorTool[] | null>(null), [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(''), [error, setError] = useState('');
  const request = useRef<AbortController | null>(null), live = useRef(identity);
  live.current = identity;
  useEffect(() => {setTools(null); setBusy(false); setMessage(''); setError('');
    return () => {request.current?.abort();};}, [identity]);
  async function run(id?: string) {
    if (locked || busy) return;
    const current = identity, controller = new AbortController(); request.current = controller;
    setBusy(true); setMessage(''); setError('');
    try {
      const api = connectorToolsApi(current);
      if (id === undefined) {
        const result = await api.catalog(controller.signal);
        if (!controller.signal.aborted && live.current === current) {setTools(result); setMessage('Tool availability loaded. Check each account separately.');}
      } else {
        if (!connectorStatusId(id)) return;
        const result = await api.status(id, controller.signal);
        if (!controller.signal.aborted && live.current === current) setMessage(`${CONNECTOR_STATUS[id].label} status was read${result.account ? ` for ${result.account.email}` : ''}${result.state ? `: ${result.state.replaceAll('_', ' ')}` : ''}. Open Connections to review the account and its permissions.`);
      }
    } catch (cause) {
      if (controller.signal.aborted || live.current !== current) return;
      setError(cause instanceof WorkspaceApiError && cause.status === 401 ? 'Sign in to use this team’s connector tools.' :
        'Connector access could not be confirmed. Check Connections, then try a deliberate status read.');
      if (cause instanceof WorkspaceApiError && [401, 403, 426].includes(cause.status)) onAuthenticationLost?.(cause);
    } finally {if (!controller.signal.aborted && live.current === current) setBusy(false);}
  }
  const statuses = availableConnectorStatuses(tools ?? []);
  return <section aria-label="Connector tools for this team">
    <h2>Connector tools</h2>
    <p>Use your signed-in account to check tools available to this team. Account access and reviewed source permissions are checked separately.</p>
    <button disabled={locked || busy} onClick={() => void run()}>Check available connector tools</button>
    {tools && <ul>{statuses.map(tool => <li key={tool.id}><button disabled={locked || busy}
      onClick={() => void run(tool.id)}>Check {connectorStatusId(tool.id) ? CONNECTOR_STATUS[tool.id].label : tool.title}</button></li>)}</ul>}
    {tools && !statuses.length && <p>No account-status tools are enabled for this connection.</p>}
    {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}
