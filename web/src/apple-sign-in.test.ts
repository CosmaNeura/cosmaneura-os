import {expect, it, vi} from 'vitest';
import {APPLE_ERROR_MESSAGE, APPLE_INVITATION_MESSAGE, completeAppleSignIn, type AppleBrowserClient} from './apple-sign-in';

function fixture() {
  const result = {id: 'signin_synthetic', status: 'complete', createdSessionId: 'sess_synthetic', firstFactorVerification: {status: 'verified', error: null}};
  const create = vi.fn(async (_options: {strategy: 'oauth_token_apple'; token: string}) => result);
  const client = {signIn: {create}, resetSignIn: vi.fn(), resetSignUp: vi.fn()};
  const credential = vi.fn(async () => ({status: 'credential' as const, token: 'synthetic-apple-token'}));
  const setActive = vi.fn(async () => {});
  return {client, create, credential, setActive, isCurrent: () => true};
}
it('submits Apple to the existing client and activates only a complete session', async () => {
  const f = fixture();
  expect(await completeAppleSignIn({...f, client: () => f.client})).toBeNull();
  expect(f.create).toHaveBeenCalledExactlyOnceWith({strategy: 'oauth_token_apple', token: 'synthetic-apple-token'});
  expect(f.setActive).toHaveBeenCalledExactlyOnceWith({session: 'sess_synthetic'});
  expect(f.client.resetSignIn).toHaveBeenCalledOnce(); expect(f.client.resetSignUp).toHaveBeenCalledOnce();
});
it('cancel invokes no Clerk API and a second authorization succeeds', async () => {
  const f = fixture();
  expect(await completeAppleSignIn({...f, client: () => f.client, credential: async () => ({status: 'canceled'})})).toBeNull();
  expect(f.create).not.toHaveBeenCalled(); expect(f.client.resetSignIn).not.toHaveBeenCalled();
  expect(await completeAppleSignIn({...f, client: () => f.client})).toBeNull();
  expect(f.setActive).toHaveBeenCalledOnce();
});
it.each(['error', 'dismissed'] as const)('Apple %s never activates a session', async status => {
  const f = fixture();
  expect(await completeAppleSignIn({...f, client: () => f.client, credential: async () => ({status})})).toBe(status === 'error' ? APPLE_ERROR_MESSAGE : null);
  expect(f.create).not.toHaveBeenCalled(); expect(f.setActive).not.toHaveBeenCalled();
});
it.each(['uninvited@example.test', 'synthetic@privaterelay.appleid.com'])('refuses %s, resets both attempts and reads a fresh resource on retry', async email => {
  const f = fixture();
  const rejected = {id: 'signin_synthetic', status: 'needs_identifier', createdSessionId: null, firstFactorVerification: {status: 'transferable', error: null}, identifier: email};
  const create = vi.fn(async () => rejected);
  let client: AppleBrowserClient = {...f.client, signIn: {create}};
  expect(await completeAppleSignIn({...f, client: () => client})).toBe(APPLE_INVITATION_MESSAGE);
  expect(f.setActive).not.toHaveBeenCalled(); expect(f.client.resetSignIn).toHaveBeenCalledOnce(); expect(f.client.resetSignUp).toHaveBeenCalledOnce();
  client = f.client;
  expect(await completeAppleSignIn({...f, client: () => client})).toBeNull();
  expect(create).toHaveBeenCalledOnce(); expect(f.create).toHaveBeenCalledOnce(); expect(f.setActive).toHaveBeenCalledOnce();
});
it.each(['sign_up_mode_restricted', 'sign_up_restricted_waitlist', 'form_identifier_not_found'])('handles Clerk refusal %s without exposing private details', async code => {
  const f = fixture(); f.create.mockRejectedValueOnce({errors: [{code, message: 'private synthetic provider detail'}]});
  expect(await completeAppleSignIn({...f, client: () => f.client})).toBe(APPLE_INVITATION_MESSAGE);
  expect(f.setActive).not.toHaveBeenCalled(); expect(f.client.resetSignIn).toHaveBeenCalledOnce(); expect(f.client.resetSignUp).toHaveBeenCalledOnce();
});
it.each(['needs_second_factor', 'needs_new_password', 'needs_identifier'])('incomplete %s stays usable and never activates', async status => {
  const f = fixture(); f.create.mockResolvedValueOnce({id: 'signin_synthetic', status, createdSessionId: 'sess_synthetic', firstFactorVerification: {status: 'verified', error: null}});
  expect(await completeAppleSignIn({...f, client: () => f.client})).toBe(APPLE_ERROR_MESSAGE);
  expect(f.setActive).not.toHaveBeenCalled(); expect(f.client.resetSignIn).toHaveBeenCalledOnce();
});
it('a replaced screen cannot submit or activate a late Apple credential', async () => {
  const f = fixture();
  expect(await completeAppleSignIn({...f, client: () => f.client, isCurrent: () => false})).toBeNull();
  expect(f.create).not.toHaveBeenCalled(); expect(f.setActive).not.toHaveBeenCalled();
});
it('an existing account needs no Apple email to sign in', async () => {
  const f = fixture(); // Apple email is deliberately absent from the native response.
  expect(await completeAppleSignIn({...f, client: () => f.client})).toBeNull();
  expect(f.setActive).toHaveBeenCalledOnce();
});
it('a complete response without a created session is refused', async () => {
  const f = fixture();
  f.create.mockResolvedValueOnce({id: 'signin_synthetic', status: 'complete', createdSessionId: '', firstFactorVerification: {status: 'verified', error: null}});
  expect(await completeAppleSignIn({...f, client: () => f.client})).toBe(APPLE_ERROR_MESSAGE);
  expect(f.setActive).not.toHaveBeenCalled();
});
it('cleanup actually discards partial resources so the next Apple attempt can succeed', async () => {
  let signInPending = false, signUpPending = true, first = true;
  const client: AppleBrowserClient = {
    signIn: {create: async () => {
      if (signInPending) throw new Error('Previous attempt still pending');
      signInPending = true;
      const refused = first; first = false;
      return {id: 'signin_synthetic', status: refused ? 'needs_identifier' : 'complete',
        createdSessionId: refused ? null : 'sess_synthetic', firstFactorVerification: {status: refused ? 'transferable' : 'verified', error: null}};
    }}, resetSignIn: () => {signInPending = false;}, resetSignUp: () => {signUpPending = false;},
  };
  const setActive = vi.fn(async () => {});
  const options = {credential: async () => ({status: 'credential' as const, token: 'synthetic-token'}), client: () => client,
    setActive, isCurrent: () => true};
  expect(await completeAppleSignIn(options)).toBe(APPLE_INVITATION_MESSAGE);
  expect(signInPending).toBe(false); expect(signUpPending).toBe(false); expect(setActive).not.toHaveBeenCalled();
  expect(await completeAppleSignIn(options)).toBeNull(); expect(setActive).toHaveBeenCalledOnce();
});
it('an old screen never resets a newer sign-in resource after late completion', async () => {
  const f = fixture();
  let resolve!: (value: Awaited<ReturnType<typeof f.create>>) => void;
  f.create.mockReturnValueOnce(new Promise(value => {resolve = value;}));
  let current = true;
  const result = completeAppleSignIn({...f, client: () => f.client, isCurrent: () => current});
  await Promise.resolve(); await Promise.resolve();
  current = false;
  f.client.signIn = {create: vi.fn(async () => ({id: 'signin_new', status: 'complete', createdSessionId: 'sess_new', firstFactorVerification: {status: 'verified', error: null}}))};
  resolve({id: 'signin_old', status: 'complete', createdSessionId: 'sess_old', firstFactorVerification: {status: 'verified', error: null}});
  expect(await result).toBeNull();
  expect(f.setActive).not.toHaveBeenCalled(); expect(f.client.resetSignIn).not.toHaveBeenCalled(); expect(f.client.resetSignUp).not.toHaveBeenCalled();
});
