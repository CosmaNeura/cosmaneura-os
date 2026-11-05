import {describe, expect, it, vi, afterEach} from 'vitest';
import {desktopPracticeConnectionPort,nativePracticeConnectionAvailable} from '../../clients/capture/src/native/practice-connection-plugin';

function port() {
  return {
    version: 1 as const,
    capabilities: vi.fn(async () => ({contract_version: 'cosmabot.native-practice-connection.v1', available: false, enrollment_available: false})),
    accountStatus: vi.fn(), beginAccountSignIn: vi.fn(), accountToken: vi.fn(), enrollmentRequest: vi.fn(),
    openCheckout: vi.fn(), openEnrollmentDestination: vi.fn(), activatePracticeOrganization: vi.fn(),
    activateRegisteredPractice: vi.fn(), returnToBeta: vi.fn(), signOut: vi.fn(), addListener: vi.fn(),
  };
}

describe('desktop practice connection port', () => {
  afterEach(() => {
    delete (window as {cosmasDesktopPractice?: unknown}).cosmasDesktopPractice;
    vi.restoreAllMocks();
  });

  it('accepts only the exact versioned host surface', () => {
    expect(desktopPracticeConnectionPort(undefined)).toBeNull();
    expect(desktopPracticeConnectionPort({version: 1})).toBeNull();
    const valid = port();
    expect(desktopPracticeConnectionPort(valid)).toBe(valid);
    window.cosmasDesktopPractice = valid;
    expect(nativePracticeConnectionAvailable()).toBe(true);
  });

  it('rejects a credential-bearing or partial port', () => {
    expect(desktopPracticeConnectionPort({...port(), getToken: () => 'forged'})).toBeNull();
    expect(desktopPracticeConnectionPort({...port(), version: 2})).toBeNull();
    const {signOut: _omit, ...partial} = port();
    expect(desktopPracticeConnectionPort(partial)).toBeNull();
  });
});
