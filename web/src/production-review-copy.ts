import {PRODUCTION_API_ORIGIN} from '../../clients/shared/operational-native-identity.mjs';

type Env = Record<string, string | boolean | undefined>;

/**
 * App Store / production-review builds pin VITE_WORKSPACE_HOSTED_API_ORIGIN to
 * PRODUCTION_API_ORIGIN (api.beta.cosmas.ai) via the operational-production-v1
 * identity. Staging and live beta use other origins. Unknown/omitted → not production.
 */
export function isProductionReviewProfile(env: Env = import.meta.env): boolean {
  return env.VITE_WORKSPACE_HOSTED_API_ORIGIN === PRODUCTION_API_ORIGIN;
}

export function nativeSignInUnavailableDetail(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'This installation could not start sign-in. Reopen the app or contact your practice administrator.'
    : 'Use the approved test build to sign in to your workspace.';
}

/** Trailing disclaimer after the EHR instructional sentence; empty on production. */
export function inventedRecordsDisclaimer(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env) ? '' : ' Only invented records are supported in this setup.';
}

export function athenaInventedExampleSuffix(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env) ? '' : ' · Local example — invented Athena clinical records';
}

export function tebraInventedExampleSuffix(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env) ? '' : ' · Local example — invented Tebra clinical records';
}

export function comingSoonLabel(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env) ? 'Not available' : 'Coming soon';
}

export function paymentsComingSoonReason(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'Live payment collection is not available in this release.'
    : 'Live payment collection is not available in this beta.';
}

export function schedulingGuideAccess(env: Env = import.meta.env): string {
  const booking = isProductionReviewProfile(env)
    ? 'Live booking is not available in this release.'
    : 'Live booking is not available in this beta.';
  return `Uses the Google account approved for your Scheduling practice to check availability and review proposals. This is separate from Gmail. ${booking}`;
}

export function unavailableInBetaLabel(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env) ? 'Unavailable' : 'Unavailable in this beta';
}

export function remainsUnavailableClause(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? ' remains unavailable. Turning on chat does not connect this operational lane.'
    : ' remains unavailable in this beta. Turning on chat does not connect this operational lane.';
}

export function teamSetupPrerequisitesChangedMessage(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'Team prerequisites changed. Your settings are retained; refresh the setup and run the settings check again before saving.'
    : 'Team prerequisites changed. Your settings are retained; refresh the setup and run the invented rehearsal again before saving.';
}

export function teamSetupReviewRequiredMessage(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'Review this exact team configuration and run the settings check again before saving. Your draft is retained.'
    : 'Review this exact team configuration and run the invented rehearsal again before saving. Your draft is retained.';
}

export function teamSaveRequiresCheckMessage(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'Check team settings and review the current draft before saving these capability changes.'
    : 'Run the invented rehearsal and review the current draft before saving these capability changes.';
}

export function elationSandboxSetupCopy(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'This uses the practice’s configured Elation sandbox. Loading appointments contacts that sandbox. Your practice administrator manages its credentials.'
    : 'This uses the practice’s configured Elation sandbox for invented test records. Loading appointments contacts that sandbox. Your practice administrator manages its credentials.';
}

export function vendorDeliveryDisabledMessage(env: Env = import.meta.env): string {
  return isProductionReviewProfile(env)
    ? 'Vendor delivery is disabled for this environment.'
    : 'Vendor delivery is disabled for this beta environment.';
}
