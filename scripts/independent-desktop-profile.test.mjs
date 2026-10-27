import assert from 'node:assert/strict';
import test from 'node:test';
import {validateOperationalReleaseProfile} from './package-desktop-release.mjs';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';

const identity = {version: 1, profile: 'operational-beta-v1', client: 'desktop',
  apiOrigin: 'https://api.example.invalid', frontendOrigin: 'https://identity.example.invalid',
  publishableKey: 'pk_live_' + Buffer.from('identity.example.invalid$').toString('base64'),
  organizationId: 'org_invented_practice', audience: 'invented-cosmabot-api'};
const info = {CFBundleIdentifier: 'com.cosmasos.beta.desktop', CFBundleShortVersionString: '0.1.143', CFBundleVersion: '1103'};
function fixture(profile = 'independent-beta-v1') {
  const manifest = resolveBetaFeatureProfile({VITE_WORKSPACE_FEATURE_PROFILE: profile,
    VITE_WORKSPACE_HOSTED_CLIENT: 'desktop', VITE_WORKSPACE_DATA_MODE: 'synthetic',
    VITE_WORKSPACE_HOSTED_API_ORIGIN: identity.apiOrigin, VITE_API_BASE: 'app://cosmas/api',
    VITE_WORKSPACE_WEB_ORIGIN: '', VITE_COSMANEURA_WEB_ORIGIN: '',
    VITE_CAPTURE_UPLOAD_ORIGINS: '', VITE_WORKSPACE_CAPTURE_MODE: 'disabled',
    VITE_CLERK_PUBLISHABLE_KEY: identity.publishableKey}).manifest;
  const config = {nativeIdentity: identity, mode: 'hosted-beta-authenticated', dataMode: 'synthetic',
    apiOrigin: identity.apiOrigin, appVersion: info.CFBundleShortVersionString, buildNumber: info.CFBundleVersion,
    nativeCaptureEnabled: false, installation: {bundleIdentifier: info.CFBundleIdentifier,
      ...(profile === 'independent-beta-v1' ? {storageScope: 'identity-v1'} : {})}};
  return {manifest, config};
}

test('independent desktop release requires the new private identity namespace and accepts the approved Google pair', () => {
  const {manifest, config} = fixture();
  assert.deepEqual(validateOperationalReleaseProfile(config, manifest, info), identity);
  assert.deepEqual(validateOperationalReleaseProfile({...config,
    googleConnectionClientId: 'invented.apps.googleusercontent.com',
    googleConnectionCallbackUri: identity.apiOrigin + '/connections/google/callback'}, manifest, info), identity);
  for (const storageScope of [undefined, null, '', 'identity-v2']) {
    assert.throws(() => validateOperationalReleaseProfile({...config,
      installation: {...config.installation, storageScope}}, manifest, info));
  }
  for (const change of [
    {googleConnectionClientId: 'invented.apps.googleusercontent.com'},
    {googleConnectionCallbackUri: identity.apiOrigin + '/connections/google/callback'},
    {googleConnectionClientId: 'invented.apps.googleusercontent.com', googleConnectionCallbackUri: 'https://other.example.invalid/connections/google/callback'},
    {googleConnectionClientId: 'invalid', googleConnectionCallbackUri: identity.apiOrigin + '/connections/google/callback'},
  ]) assert.throws(() => validateOperationalReleaseProfile({...config, ...change}, manifest, info));
});

test('independent desktop release rejects unqualified capabilities and changing an old profile storage contract', () => {
  const {manifest, config} = fixture();
  for (const changed of [{nativeCaptureEnabled: true}, {microphoneCaptureEnabled: true},
    {captureUploadOrigins: ['https://uploads.example.invalid']}, {cosmaneuraWebOrigin: 'https://core.example.invalid'},
    ...['microsoftConnectionTenantId', 'microsoftConnectionClientId', 'microsoftConnectionCallbackUri',
      'schedulingGoogleClientId', 'schedulingGoogleCallbackUri'].map(key => ({[key]: 'invented-setting'}))]) {
    assert.throws(() => validateOperationalReleaseProfile({...config, ...changed}, manifest, info));
  }
  for (const profile of ['standalone-practice-v1', 'first-owner-staging-v1']) {
    const prior = fixture(profile);
    assert.deepEqual(validateOperationalReleaseProfile(prior.config, prior.manifest, info), identity);
    assert.throws(() => validateOperationalReleaseProfile({...prior.config,
      installation: {...prior.config.installation, storageScope: 'identity-v1'}}, prior.manifest, info));
  }
});
