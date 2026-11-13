/** Retained desktop API; the public identity contract is browser-safe and shared. */
export {OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE, PRODUCTION_NATIVE_PROFILE,
  PRODUCTION_INSTALLATION_PROFILE, BETA_INSTALLATION_PROFILE, STAGING_INSTALLATION_PROFILE,
  PRODUCTION_API_ORIGIN, dedicatedClerkHostsByProfile, isAccountsDevClerkHost,
  requireProductionInstallationProfile, loadOperationalNativeIdentity,
  validateOperationalNativeDataMode, validateOperationalNativeIdentity,
  operationalNativeBundle, operationalNativeAuthSettings}
  from '../shared/operational-native-identity.mjs';
