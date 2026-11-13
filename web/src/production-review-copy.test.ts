import {describe, expect, it, vi} from 'vitest';
import {PRODUCTION_API_ORIGIN} from '../../clients/shared/operational-native-identity.mjs';
import {
  athenaInventedExampleSuffix,
  comingSoonLabel,
  inventedRecordsDisclaimer,
  isProductionReviewProfile,
  nativeSignInUnavailableDetail,
  paymentsComingSoonReason,
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

describe('isProductionReviewProfile', () => {
  it('is true only for the pinned production-review API origin', () => {
    expect(isProductionReviewProfile(production)).toBe(true);
    expect(isProductionReviewProfile(staging)).toBe(false);
    expect(isProductionReviewProfile(betaPractice)).toBe(false);
    expect(isProductionReviewProfile(omitted)).toBe(false);
    expect(isProductionReviewProfile({VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.beta.cosmas.ai.evil.invalid'})).toBe(false);
  });
  it('fails if the production origin pin is inverted or loosened to a prefix match', () => {
    // Mutation: treat any origin containing "beta.cosmas.ai" as production.
    const loose = (env: Record<string, string | boolean | undefined>) =>
      String(env.VITE_WORKSPACE_HOSTED_API_ORIGIN ?? '').includes('beta.cosmas.ai');
    expect(loose({VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.beta.cosmas.ai.evil.invalid'})).toBe(true);
    expect(isProductionReviewProfile({VITE_WORKSPACE_HOSTED_API_ORIGIN: 'https://api.beta.cosmas.ai.evil.invalid'})).toBe(false);
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
      expect(vendorDeliveryDisabledMessage(env)).toBe('Vendor delivery is disabled for this beta environment.');
    }
  });

  it('gives production reviewers non-test-stage wording without claiming missing features', () => {
    expect(nativeSignInUnavailableDetail(production)).toBe(
      'This installation could not start sign-in. Reopen the app or contact your practice administrator.',
    );
    expect(nativeSignInUnavailableDetail(production)).not.toMatch(/test build|synthetic|invented|rehearsal|Coming soon/i);
    expect(inventedRecordsDisclaimer(production)).toBe('');
    expect(athenaInventedExampleSuffix(production)).toBe('');
    expect(tebraInventedExampleSuffix(production)).toBe('');
    expect(comingSoonLabel(production)).toBe('Not available');
    expect(paymentsComingSoonReason(production)).toBe('Live payment collection is not available in this release.');
    expect(schedulingGuideAccess(production)).toContain('Live booking is not available in this release.');
    expect(schedulingGuideAccess(production)).not.toContain('this beta');
    expect(unavailableInBetaLabel(production)).toBe('Unavailable');
    expect(remainsUnavailableClause(production)).toBe(
      ' remains unavailable. Turning on chat does not connect this operational lane.',
    );
    expect(teamSetupPrerequisitesChangedMessage(production)).toContain('settings check');
    expect(teamSetupPrerequisitesChangedMessage(production)).not.toContain('rehearsal');
    expect(teamSetupReviewRequiredMessage(production)).not.toContain('rehearsal');
    expect(teamSaveRequiresCheckMessage(production)).toBe(
      'Check team settings and review the current draft before saving these capability changes.',
    );
    expect(elationSandboxSetupCopy(production)).not.toContain('invented');
    expect(elationSandboxSetupCopy(production)).toContain('Elation sandbox');
    expect(vendorDeliveryDisabledMessage(production)).toBe('Vendor delivery is disabled for this environment.');
  });

  it('fails if production copy is swapped back to staging text (mutation)', () => {
    // Mutation: drop the production branch so reviewers still see test-build wording.
    const broken = (_env: Env) => 'Use the approved test build to sign in to your workspace.';
    expect(broken(production)).toBe(nativeSignInUnavailableDetail(staging));
    expect(nativeSignInUnavailableDetail(production)).not.toBe(nativeSignInUnavailableDetail(staging));
  });
});

describe('ehrTransportLabel production vs staging', () => {
  it('keeps invented transport labels off production and on staging', async () => {
    const {ehrTransportLabel} = await import('./ehr-read-api');
    vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN', 'https://api.staging.cosmas.ai');
    expect(ehrTransportLabel({provider: 'tebra'})).toBe('Local example — invented Tebra records');
    expect(ehrTransportLabel({transport: 'vendor_sandbox'})).toBe('Elation sandbox — invented test data');
    vi.stubEnv('VITE_WORKSPACE_HOSTED_API_ORIGIN', PRODUCTION_API_ORIGIN);
    // ehrTransportLabel reads import.meta.env at call time via isProductionReviewProfile()
    // After stubEnv, vitest updates import.meta.env for subsequent calls.
    expect(ehrTransportLabel({provider: 'tebra'})).toBe('Tebra clinical records');
    expect(ehrTransportLabel({transport: 'vendor_sandbox'})).toBe('Elation sandbox');
    vi.unstubAllEnvs();
  });
});

type Env = Record<string, string | boolean | undefined>;
