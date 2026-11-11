/** Retained desktop API; the public identity contract is browser-safe and shared. */
export {OPERATIONAL_NATIVE_PROFILE, STAGING_NATIVE_PROFILE, PRODUCTION_NATIVE_PROFILE,
  validateOperationalNativeDataMode, validateOperationalNativeIdentity, operationalNativeBundle,
  operationalNativeAuthSettings}
  from '../shared/operational-native-identity.mjs';
