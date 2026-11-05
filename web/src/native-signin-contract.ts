import {EnrollmentError,validateEnrollmentConfig,type EnrollmentConfig} from './enrollment-contract';

/**
 * App-side recovery for docs/NATIVE_SIGNIN_ACCOUNT_CONTRACT.md error table.
 * Discovery/status remain server-authoritative; this only maps codes to UI actions.
 */
export type NativeSignInRecovery =
  | 'clearSessionAndSignIn'
  | 'resumeEnrollment'
  | 'retryWithNewNonce'
  | 'rereadStatus'
  | 'fixRequest'
  | 'unavailable';

export type NativeAccountOrigin = 'capacitor://localhost' | 'app://cosmas';
export type NativeAccountConfig = Readonly<{
  issuer: string; audience: string; session_policy: string; native_origin: NativeAccountOrigin;
}>;

const closed = (value: unknown, keys: string[]): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value) &&
  Object.keys(value).sort().join(',') === [...keys].sort().join(',') &&
  Reflect.ownKeys(value).length === keys.length &&
  Object.values(Object.getOwnPropertyDescriptors(value)).every(property => 'value' in property && property.enumerable);

/** Contract GET /native/config native_account block (issuer, audience, session policy, Origin). */
export function readNativeAccountConfig(value: unknown): NativeAccountConfig {
  if (!closed(value, ['issuer', 'audience', 'session_policy', 'native_origin']) ||
      typeof value.issuer !== 'string' || !/^https:\/\/[a-z0-9.-]+$/.test(value.issuer) ||
      typeof value.audience !== 'string' || value.audience.length > 255 ||
      (value.audience !== '' && !/^[\x21-\x7e]+$/.test(value.audience)) ||
      typeof value.session_policy !== 'string' || !value.session_policy || value.session_policy.length > 64 ||
      !/^[\x21-\x7e]+$/.test(value.session_policy) ||
      (value.native_origin !== 'capacitor://localhost' && value.native_origin !== 'app://cosmas')) {
    throw new EnrollmentError(502, 'invalid_enrollment_response');
  }
  return Object.freeze({
    issuer: value.issuer, audience: value.audience, session_policy: value.session_policy,
    native_origin: value.native_origin,
  });
}

/**
 * Native /config includes native_account; browser /config does not.
 * Strip host-only fields and require Origin to match this app (apple vs desktop).
 */
export function validateNativeEnrollmentConfig(value: unknown, expectedOrigin: NativeAccountOrigin): EnrollmentConfig {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new EnrollmentError(502, 'invalid_enrollment_response');
  }
  const record = value as Record<string, unknown>;
  const account = readNativeAccountConfig(record.native_account);
  if (account.native_origin !== expectedOrigin) {
    throw new EnrollmentError(422, 'enrollment_invalid_native_identity');
  }
  const {native_account: _account, workspace_confirmation_configured: _confirm, ...rest} = record;
  return validateEnrollmentConfig(rest);
}

const CLEAR = new Set([
  'enrollment_invalid_identity', 'enrollment_session_inactive', 'enrollment_native_identity_invalid',
  'enrollment_authentication_required',
]);
const RESUME = new Set([
  'enrollment_practice_required', 'enrollment_agreement_required', 'enrollment_billing_required',
  'enrollment_runtime_scope_denied', 'enrollment_practice_access_denied', 'enrollment_verified_email_required',
  'enrollment_workspace_preparation_pending', 'enrollment_access_denied',
]);
const RETRY_NONCE = new Set(['enrollment_native_profile_interrupted']);
const REREAD = new Set(['enrollment_revision_conflict', 'enrollment_practice_selection_changed']);
const FIX = new Set([
  'enrollment_invalid_native_identity', 'enrollment_invalid_native_profile', 'enrollment_invalid_request',
]);

export function nativeSignInRecovery(error: unknown): NativeSignInRecovery {
  if (!(error instanceof EnrollmentError)) return 'unavailable';
  if (error.status === 401 || CLEAR.has(error.code)) return 'clearSessionAndSignIn';
  if (error.status === 403 || RESUME.has(error.code)) return 'resumeEnrollment';
  if (error.status === 408 || RETRY_NONCE.has(error.code)) return 'retryWithNewNonce';
  if (error.status === 409 || REREAD.has(error.code)) return 'rereadStatus';
  if (error.status === 422 || error.status === 413 || FIX.has(error.code)) return 'fixRequest';
  return 'unavailable';
}

/** Short human copy for CosmaBot account/practice screens. No secrets or PHI. */
export function nativeSignInRecoveryMessage(error: unknown): string {
  switch (nativeSignInRecovery(error)) {
    case 'clearSessionAndSignIn':
      return 'Your sign-in expired. Sign in again to continue.';
    case 'resumeEnrollment':
      return 'Your practice still needs setup before Chief can open. Continue setup, or return to your existing workspace.';
    case 'retryWithNewNonce':
      return 'Opening your practice was interrupted. Try Open Chief again.';
    case 'rereadStatus':
      return 'Your current practice changed. Check your practices before opening Chief.';
    case 'fixRequest':
      return 'This build could not complete that practice request. Return to your existing workspace and try again later.';
    default:
      return 'Your practices could not be checked. Try again, or return to your existing workspace.';
  }
}
