import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {beforeEach, afterEach, expect, it, vi} from 'vitest';
import {ConnectorToolsPanel} from './ConnectorToolsPanel';
import {connectorToolsApi} from './connector-tools-api';
vi.mock('./connector-tools-api', () => ({connectorToolsApi: vi.fn()}));
let root: Root, host: HTMLDivElement;
beforeEach(() => {vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true); host = document.createElement('div'); document.body.append(host); root = createRoot(host);});
afterEach(async () => {await act(async () => root.unmount()); host.remove(); vi.clearAllMocks(); vi.unstubAllGlobals();});
const button = (name: string) => [...host.querySelectorAll('button')].find(value => value.textContent === name)!;
const identity = {mode: 'clerk_jwt' as const, getToken: async () => 'invented'};
const tool = {id: 'google.connection_status', name: 'google_connection_status', title: 'Google account',
  plugin: 'google', enabled: true, agentCallable: true, readOnly: true, description: 'Read local account state.'};

it('requires deliberate discovery and status actions, leaving provider reads untouched', async () => {
  const catalog = vi.fn(async () => [tool]), status = vi.fn(async () => ({state: 'connected'}));
  vi.mocked(connectorToolsApi).mockReturnValue({catalog, status} as never);
  await act(async () => root.render(<ConnectorToolsPanel identity={identity}/>));
  expect(catalog).not.toHaveBeenCalled(); expect(status).not.toHaveBeenCalled();
  await act(async () => button('Check available connector tools').click());
  await act(async () => button('Check Google account').click());
  expect(status).toHaveBeenCalledWith('google.connection_status', expect.any(AbortSignal));
  expect(host.textContent).toContain('status was read');
});
it('discards previous account discovery on identity replacement', async () => {
  let finish!: (value: typeof tool[]) => void;
  const catalog = vi.fn(() => new Promise<typeof tool[]>(resolve => {finish = resolve;}));
  vi.mocked(connectorToolsApi).mockReturnValue({catalog} as never);
  await act(async () => root.render(<ConnectorToolsPanel identity={identity}/>));
  await act(async () => button('Check available connector tools').click());
  await act(async () => root.render(<ConnectorToolsPanel identity={{...identity}}/>));
  await act(async () => finish([tool])); expect(button('Check Google account')).toBeUndefined();
});
