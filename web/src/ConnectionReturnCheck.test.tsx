import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, describe, expect, it, vi} from 'vitest';
import {GoogleConnectionPanel} from './GoogleConnectionPanel';
import {MicrosoftConnectionPanel} from './MicrosoftConnectionPanel';
import {googleConnectionRequest} from './google-connection-api';
import {microsoftConnectionRequest} from './microsoft-connection-api';
import {WorkspaceApiError, type AuthenticatedWorkspaceIdentity} from './workspace-api';

vi.mock('./google-connection-api', () => ({googleConnectionRequest: vi.fn()}));
vi.mock('./microsoft-connection-api', () => ({microsoftConnectionRequest: vi.fn()}));
const owner: AuthenticatedWorkspaceIdentity = {mode: 'clerk_jwt', getToken: async () => null};
const status = (state: 'sign_in_required' | 'sign_in_pending' | 'completing_sign_in') => ({state, account: null, connected_at: null});
const connected = {state: 'connected' as const, account: {label: 'Invented owner', email: 'owner@example.invalid'}, connected_at: '2026-09-29T12:00:00Z'};
let host: HTMLDivElement, root: Root;

beforeEach(() => {
  Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
  vi.useFakeTimers(); vi.resetAllMocks();
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove();
  vi.useRealTimers(); vi.restoreAllMocks();
});
const advance = (ms = 3000) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });
const focus = () => act(async () => { window.dispatchEvent(new Event('focus')); });
const click = (label: string) => act(async () => {
  const button = [...host.querySelectorAll('button')].find(button => button.textContent === label);
  expect(button?.disabled).toBe(false); button!.click();
});

describe.each([
  {name: 'Google', Panel: GoogleConnectionPanel, request: googleConnectionRequest},
  {name: 'Microsoft', Panel: MicrosoftConnectionPanel, request: microsoftConnectionRequest},
])('$name OAuth return', ({name, Panel, request}) => {
  const api = vi.mocked(request);
  const mount = (identity = owner, denied = vi.fn()) => act(async () => root.render(<Panel identity={identity} onAuthenticationLost={denied}/>));
  const begin = async () => {
    api.mockResolvedValueOnce(status('sign_in_required')).mockResolvedValueOnce({
      authorization_url: 'https://example.invalid/oauth', expires_at: new Date(Date.now() + 600_000).toISOString(),
    });
    await mount(); await click(`Connect with ${name}`);
    const anchor = host.querySelector('a')!;
    anchor.addEventListener('click', event => event.preventDefault());
    await act(async () => anchor.click());
  };
  const actions = () => api.mock.calls.map(call => call[1]);

  it('finishes a slow callback automatically, without reading mail or restarting consent', async () => {
    await begin();
    api.mockResolvedValueOnce(status('sign_in_pending')).mockResolvedValueOnce(status('completing_sign_in')).mockResolvedValueOnce(connected);
    await focus(); expect(host.textContent).toContain(`sign-in is ready to continue`);
    await advance(); expect(host.textContent).toContain(`Completing ${name} sign-in`);
    await advance(); expect(host.textContent).toContain(`${name} connected.`);
    await advance(60_000); await focus();
    expect(actions()).toEqual(['status', 'start', 'status', 'status', 'status']);
  });

  it('does not start polling merely because pending sign-in was observed', async () => {
    api.mockResolvedValue(status('completing_sign_in'));
    await mount(); await focus(); await advance(60_000);
    expect(actions()).toEqual(['status']);
  });

  it('waits while hidden and caps repeated pending observations at ten', async () => {
    await begin(); api.mockResolvedValue(status('completing_sign_in'));
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await focus(); await advance(60_000); expect(api).toHaveBeenCalledTimes(2);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    await focus(); await focus(); await focus(); expect(api).toHaveBeenCalledTimes(3);
    await advance(30_000);
    expect(actions().filter(action => action === 'status')).toHaveLength(11); // initial + ten return observations
    expect(host.textContent).toContain(`CosmaBot has not confirmed the ${name} connection.`);
    await advance(60_000); await focus(); expect(api).toHaveBeenCalledTimes(12);
  });

  it('distinguishes a missing callback from a connection still being processed', async () => {
    await begin(); api.mockResolvedValue(status('sign_in_pending'));
    await focus(); await advance(30_000);
    expect(host.textContent).toContain(`CosmaBot has not received the ${name} sign-in result.`);
    expect(host.textContent).not.toContain('still finishing');
    api.mockResolvedValueOnce(status('sign_in_required'));
    await click(`Check ${name} connection`);
    expect(host.textContent).toContain(`Connect your ${name} account to continue.`);
    expect(host.textContent).not.toContain('has not received');
    expect(actions().filter(action => action === 'start')).toHaveLength(1);
  });

  it('stops automatic checks after the owner cancels the connection', async () => {
    await begin(); api.mockResolvedValueOnce(status('sign_in_pending')).mockResolvedValueOnce({state: 'disconnected'});
    await focus(); await click(`Cancel ${name} connection`); await advance(60_000); await focus();
    expect(actions()).toEqual(['status', 'start', 'status', 'disconnect']);
  });

  it('pauses pending checks while hidden and stops after the panel is closed', async () => {
    await begin(); api.mockResolvedValue(status('completing_sign_in'));
    await focus();
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    await advance(9000); expect(api).toHaveBeenCalledTimes(3);
    vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); });
    expect(api).toHaveBeenCalledTimes(4);
    await act(async () => root.render(null)); await advance(60_000); await focus();
    expect(api).toHaveBeenCalledTimes(4);
  });

  it('ends automatic checks when the provider requires a new sign-in', async () => {
    await begin(); api.mockResolvedValue(status('sign_in_required'));
    await focus(); await advance(60_000); await focus();
    expect(actions()).toEqual(['status', 'start', 'status']);
    expect(host.textContent).toContain(`Connect your ${name} account to continue.`);
  });

  it('stops on authentication failure and preserves the sign-in recovery message', async () => {
    await begin(); const denied = vi.fn(); await mount(owner, denied);
    api.mockRejectedValueOnce(new WorkspaceApiError(401));
    await focus(); await advance(60_000); await focus();
    expect(denied).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain('Sign in to CosmasOS again');
    expect(actions()).toEqual(['status', 'start', 'status']);
  });

  it('does not overlap return checks or publish their late result into a different account', async () => {
    await begin(); let resolve!: (value: typeof connected) => void;
    api.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    await focus(); await focus(); await advance(); expect(api).toHaveBeenCalledTimes(3);
    api.mockResolvedValueOnce(status('sign_in_required'));
    await mount({...owner, getToken: async () => null});
    await act(async () => resolve(connected)); await advance(60_000); await focus();
    expect(host.textContent).not.toContain('owner@example.invalid');
    expect(api).toHaveBeenCalledTimes(4);
  });
});
