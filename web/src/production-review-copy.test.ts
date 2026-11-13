import {describe, expect, it, afterEach, vi} from 'vitest';
import {PRODUCTION_API_ORIGIN} from '../../clients/shared/operational-native-identity.mjs';
import {
  athenaInventedExampleSuffix,
  comingSoonLabel,
  ehrAccessNotEnabledMessage,
  ehrTransportLabelCopy,
  elationSandboxEnableButtonLabel,
  inventedRecordsDisclaimer,
  isProductionReviewProfile,
  nativeSignInUnavailableDetail,
  paymentsComingSoonReason,
  practiceRecordsSavedDraftRecoveryAction,
  practiceRecordsSavedDraftRecoveryCopy,
  practiceRecordsUnavailableCopy,
  remainsUnavailableClause,
  schedulingGuideAccess,
  teamSaveRequiresCheckMessage,
  teamSetupPrerequisitesChangedMessage,
  teamSetupReviewRequiredMessage,
  tebraInventedExampleSuffix,
  unavailableInBetaLabel,
  elationSandboxSetupCopy,
  vendorDeliveryDisabledMessage,
} from './production-review-copy';

const production = {VITE_WORKSPACE_HOSTED_API_ORIGIN: PRODUCTION_API_ORIGIN};
const staging = {VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.staging.cosmas.ai'};
const betaPractice = {
  VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.00000000-0000-4000-8000-000000000001.workspace.cosmas.ai',
};
const omitted = {};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('isProductionReviewProfile', () => {
  it('is true only for the exact hosted production-review API origin', () => {
    expect(isProductionReviewProfile(production)).toBe(true);
    expect(isProductionReviewProfile(staging)).toBe(false);
    expect(isProductionReviewProfile(betaPractice)).toBe(false);
    expect(isProductionReviewProfile(omitted)).toBe(false);
    expect(isProductionReviewProfile({VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.beta.cosmas.ai.evil.invalid'})).toBe(false);
    expect(isProductionReviewProfile({VITE_WORKSPACE_HOSTED_API_ORIGIN: 'not-a-url'})).toBe(false);
  });

  it('refuses lookalike origins (port, http, trailing dot, userinfo host, beta.staging)', () => {
    for (const raw of [
      'https://api.beta.cosmas.ai:443',
      'https://api.beta.cosmas.ai:8443',
      'http://api.beta.cosmas.ai',
      'https://api.beta.cosmas.ai.',
      'https://api.beta.cosmas.ai@other-host.invalid',
      'https://api.beta.staging.cosmas.ai',
      `${PRODUCTION_API_ORIGIN}/`,
      `${PRODUCTION_API_ORIGIN}/path`,
    ]) {
      expect(isProductionReviewProfile({VITE_WORKSPACE_HOSTED_API_ORIGIN: raw}), raw).toBe(false);
    }
  });
});

describe('production-review copy helpers', () => {
  it('keeps staging and beta on today\'s exact test-stage wording', () => {
    for (const env of [staging, betaPractice, omitted]) {
      expect(nativeSignInUnavailableDetail(env)).toBe('Use the approved test build to sign in to your workspace.');
      expect(inventedRecordsDisclaimer(env)).toBe(' Only invented records are supported in this setup.');
      expect(athenaInventedExampleSuffix(env)).toBe(' · Local example — invented Athena clinical records');
      expect(tebraInventedExampleSuffix(env)).toBe(' · Local example — invented Tebra clinical records');
      expect(comingSoonLabel(env)).toBe('Coming soon');
      expect(paymentsComingSoonReason(env)).toBe('Live payment collection is not available in this beta.');
      expect(schedulingGuideAccess(env)).toContain('Live booking is not available in this beta.');
      expect(unavailableInBetaLabel(env)).toBe('Unavailable in this beta');
      expect(remainsUnavailableClause(env)).toBe(' remains unavailable in this beta. Turning on chat does not connect this operational lane.');
      expect(teamSetupPrerequisitesChangedMessage(env)).toContain('invented rehearsal');
      expect(teamSetupReviewRequiredMessage(env)).toContain('invented rehearsal');
      expect(teamSaveRequiresCheckMessage(env)).toBe(
        'Run the invented rehearsal and review the current draft before saving these capability changes.',
      );
      expect(elationSandboxSetupCopy(env)).toContain('invented test records');
      expect(elationSandboxEnableButtonLabel(env)).toBe('Use this practice’s Elation sandbox');
      expect(ehrAccessNotEnabledMessage('problems', env)).toBe(
        'Problem-list access is not enabled in this setup. Appointment review remains available.',
      );
      expect(vendorDeliveryDisabledMessage(env)).toBe('Vendor delivery is disabled for this beta environment.');
      expect(ehrTransportLabelCopy({provider: 'tebra'}, env)).toBe('Local example — invented Tebra records');
      expect(ehrTransportLabelCopy({transport: 'vendor_sandbox'}, env)).toBe('Elation sandbox — invented test data');
      expect(ehrTransportLabelCopy({transport: 'mock'}, env)).toBe('Local example');
      expect(practiceRecordsUnavailableCopy(env)).toBe('');
    }
  });

  it('gives production reviewers honest non-test-stage wording without empty screens', () => {
    expect(nativeSignInUnavailableDetail(production)).toBe(
      'This installation could not start sign-in. Reopen the app or contact your practice administrator.',
    );
    expect(nativeSignInUnavailableDetail(production)).not.toMatch(/test build|synthetic|invented|rehearsal|Coming soon/i);
    expect(practiceRecordsUnavailableCopy(production)).toBe('Practice records are not available in this release.');
    expect(practiceRecordsSavedDraftRecoveryCopy(production)).toBe('Reopen a saved private draft for this visit.');
    expect(practiceRecordsSavedDraftRecoveryCopy(production)).not.toContain('does not read practice records');
    expect(practiceRecordsSavedDraftRecoveryAction(production)).toBe('Review saved private draft');
    expect(inventedRecordsDisclaimer(production)).toMatch(/Sample records|not from a live/i);
    expect(athenaInventedExampleSuffix(production)).toContain('Sample records, not from your Athena account');
    expect(tebraInventedExampleSuffix(production)).toBe(' · Sample records, not from your Tebra account');
    expect(ehrTransportLabelCopy({provider: 'tebra'}, production)).toBe('Sample records, not from your Tebra account');
    expect(ehrTransportLabelCopy({provider: 'tebra'}, production)).not.toBe('Tebra clinical records');
    expect(comingSoonLabel(production)).toBe('Not available');
    expect(paymentsComingSoonReason(production)).toBe('Live payment collection is not available in this release.');
    expect(schedulingGuideAccess(production)).toContain('Live booking is not available in this release.');
    expect(unavailableInBetaLabel(production)).toBe('Unavailable');
    expect(teamSaveRequiresCheckMessage(production)).not.toContain('rehearsal');
    expect(elationSandboxSetupCopy(production)).not.toContain('invented');
    expect(elationSandboxEnableButtonLabel(production)).toBe('Enable this practice’s Elation sandbox');
    expect(ehrAccessNotEnabledMessage('labs', production)).toBe(
      'Laboratory-report access is not enabled. Other available records remain accessible.',
    );
    expect(vendorDeliveryDisabledMessage(production)).toBe('Vendor delivery is disabled for this environment.');
  });
});

describe('ehrTransportLabel staging path', () => {
  it('keeps invented transport labels on staging (panel still mounts off production)', async () => {
    const {ehrTransportLabel} = await import('./ehr-read-api');
    vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN', 'https://api.staging.cosmas.ai');
    expect(ehrTransportLabel({provider: 'tebra'})).toBe('Local example — invented Tebra records');
    expect(ehrTransportLabel({transport: 'vendor_sandbox'})).toBe('Elation sandbox — invented test data');
    expect(ehrTransportLabel({transport: 'mock'})).toBe('Local example');
  });
});
