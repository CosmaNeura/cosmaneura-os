import {describe, expect, it} from 'vitest';
import {EnrollmentError} from './enrollment-contract';
import {nativeSignInRecovery, nativeSignInRecoveryMessage} from './native-signin-contract';

describe('native sign-in contract recovery', () => {
  it('maps contract HTTP/code pairs to app actions', () => {
    expect(nativeSignInRecovery(new EnrollmentError(401, 'enrollment_session_inactive'))).toBe('clearSessionAndSignIn');
    expect(nativeSignInRecovery(new EnrollmentError(403, 'enrollment_billing_required'))).toBe('resumeEnrollment');
    expect(nativeSignInRecovery(new EnrollmentError(408, 'enrollment_native_profile_interrupted'))).toBe('retryWithNewNonce');
    expect(nativeSignInRecovery(new EnrollmentError(409, 'enrollment_revision_conflict'))).toBe('rereadStatus');
    expect(nativeSignInRecovery(new EnrollmentError(422, 'enrollment_invalid_native_identity'))).toBe('fixRequest');
    expect(nativeSignInRecovery(new EnrollmentError(503, 'enrollment_native_workspace_unqualified'))).toBe('unavailable');
    expect(nativeSignInRecovery(new Error('other'))).toBe('unavailable');
  });

  it('keeps recovery copy free of secrets and clinical detail', () => {
    const text = nativeSignInRecoveryMessage(new EnrollmentError(403, 'enrollment_agreement_required'));
    expect(text.toLowerCase()).not.toMatch(/token|secret|patient|mrn|stripe|clerk\.cosmas/);
    expect(text).toMatch(/setup|workspace/i);
  });
});
