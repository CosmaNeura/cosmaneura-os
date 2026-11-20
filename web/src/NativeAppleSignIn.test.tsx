import {act} from 'react';
import {createRoot, type Root} from 'react-dom/client';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {BetaSignIn} from './beta-sign-in';
import {APPLE_ERROR_MESSAGE, APPLE_INVITATION_MESSAGE} from './apple-sign-in';

const mocks = vi.hoisted(() => ({clerk: null as any, plugin: null as any, tapped: null as null | ((value: {id: string}) => void), available: true}));
vi.mock('@clerk/react', () => ({
  useClerk: () => mocks.clerk,
  SignIn: (props: {withSignUp: boolean; transferable: boolean}) => <div data-signup={String(props.withSignUp)} data-transfer={String(props.transferable)}>
    <button>Email and password</button><button>Email code</button><button>Google</button>
  </div>,
}));
vi.mock('../../clients/capture/src/native/apple-sign-in-plugin', () => ({
  nativeAppleSignInAvailable: () => mocks.available,
  get AppleSignIn() { return mocks.plugin; },
}));

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, {IS_REACT_ACT_ENVIRONMENT: true});
  mocks.available = true; mocks.tapped = null;
  mocks.clerk = {loaded: true, publishableKey: 'pk_test_synthetic', session: null,
    client: {signIn: {create: vi.fn(async () => ({status: 'complete', createdSessionId: 'sess_synthetic',
      firstFactorVerification: {status: 'verified', error: null}}))}, signUp: {create: vi.fn()}, resetSignIn: vi.fn(), resetSignUp: vi.fn()},
    setActive: vi.fn(async () => {})};
  mocks.plugin = {environment: vi.fn(async () => ({enabled: true})), mount: vi.fn(async () => {}),
    unmount: vi.fn(async () => {}), finish: vi.fn(async () => {}),
    credential: vi.fn(async () => ({status: 'credential', token: 'synthetic-token'})),
    addListener: vi.fn(async (_event: string, listener: (value: {id: string}) => void) => {
      mocks.tapped = listener; return {remove: vi.fn(async () => {})};
    })};
  vi.stubGlobal('ResizeObserver', class {observe() {} disconnect() {}});
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({x: 10, y: 80, width: 300, height: 44} as DOMRect);
  host = document.createElement('div'); document.body.append(host); root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.location.hash = '';
});
async function render() { await act(async () => root.render(<BetaSignIn />)); }
async function tap() {
  const id = mocks.plugin.mount.mock.calls.at(-1)[0].id;
  await act(async () => mocks.tapped!({id}));
}
function usable() {
  expect(host.querySelector('[inert]')).toBeNull();
  expect([...host.querySelectorAll('button')].every(button => !button.disabled)).toBe(true);
  expect(host.textContent).toContain('Email and password'); expect(host.textContent).toContain('Email code'); expect(host.textContent).toContain('Google');
  expect(host.querySelector('[data-signup="false"][data-transfer="false"]')).not.toBeNull();
}
it('leaves the existing screen alone when native Apple is unavailable', async () => {
  mocks.available = false; await render(); usable();
  expect(mocks.plugin.environment).not.toHaveBeenCalled(); expect(mocks.plugin.mount).not.toHaveBeenCalled();
});
it('stays hidden until Clerk and the positive environment response are loaded', async () => {
  mocks.clerk.loaded = false; await render();
  expect(mocks.plugin.environment).not.toHaveBeenCalled(); expect(mocks.plugin.mount).not.toHaveBeenCalled(); usable();
  let resolve!: (value: {enabled: boolean}) => void;
  mocks.plugin.environment.mockReturnValue(new Promise(value => {resolve = value;}));
  mocks.clerk.loaded = true; await render();
  expect(mocks.plugin.mount).not.toHaveBeenCalled(); usable();
  await act(async () => resolve({enabled: true}));
  expect(mocks.plugin.mount).toHaveBeenCalled();
  expect(mocks.plugin.environment).toHaveBeenCalledExactlyOnceWith({publishableKey: 'pk_test_synthetic'});
});
it.each([{}, {enabled: false}, {enabled: 'true'}, {enabled: 1}])('does not mount for an absent/false/nonboolean flag %j', async value => {
  mocks.plugin.environment.mockResolvedValue(value); await render();
  expect(mocks.plugin.mount).not.toHaveBeenCalled(); expect(host.querySelector('[role="alert"]')).toBeNull(); usable();
});
it.each(['load failure', 'timeout'])('environment %s keeps the screen unchanged', async error => {
  mocks.plugin.environment.mockRejectedValue(new Error(error)); await render();
  expect(mocks.plugin.mount).not.toHaveBeenCalled(); expect(host.querySelector('[role="alert"]')).toBeNull(); usable();
});
it('success activates the existing Clerk client and finishes native button custody', async () => {
  await render(); await tap();
  expect(mocks.clerk.setActive).toHaveBeenCalledExactlyOnceWith({session: 'sess_synthetic'});
  expect(mocks.plugin.finish).toHaveBeenCalledOnce(); usable();
});
it('cancellation is silent, restores every option, and retry succeeds', async () => {
  mocks.plugin.credential.mockResolvedValueOnce({status: 'canceled'});
  await render(); await tap(); usable();
  expect(host.querySelector('[role="alert"]')).toBeNull(); expect(mocks.clerk.client.signIn.create).not.toHaveBeenCalled();
  await tap(); expect(mocks.clerk.setActive).toHaveBeenCalledOnce();
});
it('other Apple errors show short recovery copy and permit another try', async () => {
  mocks.plugin.credential.mockResolvedValueOnce({status: 'error'});
  await render(); await tap(); usable(); expect(host.textContent).toContain(APPLE_ERROR_MESSAGE);
  await tap(); expect(mocks.clerk.setActive).toHaveBeenCalledOnce(); expect(host.querySelector('[role="alert"]')).toBeNull();
});
it.each(['uninvited@example.test', 'synthetic@privaterelay.appleid.com'])('unmatched %s clears attempts, restores all options, and retries', async email => {
  mocks.clerk.client.signIn.create.mockResolvedValueOnce({status: 'needs_identifier', createdSessionId: null,
    firstFactorVerification: {status: 'transferable', error: null}, identifier: email});
  await render(); await tap(); usable(); expect(host.textContent).toContain(APPLE_INVITATION_MESSAGE);
  expect(mocks.clerk.client.resetSignIn).toHaveBeenCalledOnce(); expect(mocks.clerk.client.resetSignUp).toHaveBeenCalledOnce();
  expect(mocks.clerk.client.signUp.create).not.toHaveBeenCalled();
  expect(mocks.clerk.setActive).not.toHaveBeenCalled();
  await tap(); expect(mocks.clerk.setActive).toHaveBeenCalledOnce(); expect(host.querySelector('[role="alert"]')).toBeNull();
});
it('keeps options inert while Clerk is pending and ignores repeated Apple taps', async () => {
  let resolve!: (value: unknown) => void;
  mocks.clerk.client.signIn.create.mockReturnValueOnce(new Promise(value => {resolve = value;}));
  await render(); await tap();
  expect(host.querySelector('[inert]')).not.toBeNull(); expect(mocks.plugin.finish).not.toHaveBeenCalled();
  expect((host.querySelector('.beta-forgot-password') as HTMLButtonElement).disabled).toBe(true);
  await tap(); expect(mocks.plugin.credential).toHaveBeenCalledOnce();
  await act(async () => resolve({status: 'complete', createdSessionId: 'sess_synthetic', firstFactorVerification: {status: 'verified', error: null}}));
  usable(); expect(mocks.plugin.finish).toHaveBeenCalledOnce();
});
