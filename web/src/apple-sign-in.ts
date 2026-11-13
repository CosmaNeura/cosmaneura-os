import type {AppleCredential} from '../../clients/capture/src/native/apple-sign-in-plugin';

export const APPLE_INVITATION_MESSAGE = "We couldn't find an invitation for that Apple ID. Sign in with the email address your invitation was sent to, or use Google.";
export const APPLE_ERROR_MESSAGE = "Apple sign-in didn't finish. Try again or use another sign-in option.";
type Attempt = {
  id?: string;
  status: string | null;
  createdSessionId: string | null;
  firstFactorVerification: {status: string | null; error: {code: string} | null};
};
export type AppleBrowserClient = {
  signIn: {id?: string; create(options: {strategy: 'oauth_token_apple'; token: string}): Promise<Attempt>};
  resetSignIn(): void;
  resetSignUp(): void;
};
const noInviteCodes = new Set(['sign_up_mode_restricted', 'sign_up_restricted_waitlist', 'form_identifier_not_found']);
function noInvite(error: unknown): boolean {
  const errors = (error as {errors?: {code?: string}[]})?.errors;
  return Array.isArray(errors) && errors.some(value => noInviteCodes.has(value.code ?? ''));
}

/// Authenticate the existing browser client; never transfer to or create sign-up.
export async function completeAppleSignIn({credential, client, setActive, isCurrent}: {
  credential: () => Promise<AppleCredential>;
  client: () => AppleBrowserClient;
  setActive: (options: {session: string}) => Promise<void>;
  isCurrent: () => boolean;
}): Promise<string | null> {
  let attemptClient: AppleBrowserClient | null = null;
  let resource: AppleBrowserClient['signIn'] | null = null;
  let attemptID: string | null = null;
  try {
    let response = await credential();
    if (!isCurrent() || response.status === 'dismissed' || response.status === 'canceled') return null;
    if (response.status !== 'credential' || !response.token) return APPLE_ERROR_MESSAGE;
    // Read the live resource at call time so a retry never reuses a reset attempt.
    attemptClient = client();
    resource = attemptClient.signIn;
    const resultPromise = resource.create({strategy: 'oauth_token_apple', token: response.token});
    response = {status: 'dismissed'}; // Do not retain the Apple token beyond submission.
    const result = await resultPromise;
    attemptID = result.id ?? null;
    if (!isCurrent()) return null;
    if (result.firstFactorVerification.status === 'transferable' ||
        noInviteCodes.has(result.firstFactorVerification.error?.code ?? '')) return APPLE_INVITATION_MESSAGE;
    if (result.status !== 'complete' || !result.createdSessionId || result.firstFactorVerification.error) return APPLE_ERROR_MESSAGE;
    await setActive({session: result.createdSessionId});
    return null;
  } catch (error) { return noInvite(error) ? APPLE_INVITATION_MESSAGE : APPLE_ERROR_MESSAGE; }
  finally {
    // Browser resources only. No native Clerk client/attempt/Keychain was created.
    if (attemptClient && (isCurrent() || attemptClient.signIn === resource ||
        (attemptID && attemptClient.signIn.id === attemptID))) {
      attemptClient.resetSignIn();
      attemptClient.resetSignUp();
    }
  }
}
