import assert from 'node:assert/strict';
import test from 'node:test';
import {
  isProductionNativePracticeInfos,
  productionPracticeHelperRequiredMessage,
  validateNativePracticeInfos,
} from './practice-infos-config.mjs';

function stagingPractice() {
  const host = 'invented-practice.clerk.accounts.dev';
  return {
    enabled: true,
    accountOrigin: 'https://enrollment-api.staging.cosmas.ai',
    realm: {
      publishableKey: 'pk_test_' + Buffer.from(`${host}$`).toString('base64'),
      frontendOrigin: `https://${host}`,
      audience: '',
      profile: 'operational-staging-v1',
      keychainNamespace: 'a'.repeat(64),
    },
    apiOrigins: [],
    registeredPracticeOrigins: 'synthetic-practice-uuid-staging-v1',
  };
}

function productionPractice() {
  const host = 'clerk.cosmas.ai';
  return {
    enabled: true,
    accountOrigin: 'https://enrollment-api.cosmas.ai',
    realm: {
      publishableKey: 'pk_live_' + Buffer.from(`${host}$`).toString('base64'),
      frontendOrigin: `https://${host}`,
      audience: 'cosmabot-practice-api',
      profile: 'operational-beta-v1',
      keychainNamespace: 'c'.repeat(64),
    },
    apiOrigins: [],
    registeredPracticeOrigins: 'practice-uuid-production-v1',
  };
}

test('staging and production Infos are accepted', () => {
  assert.deepEqual(validateNativePracticeInfos(stagingPractice()), stagingPractice());
  assert.deepEqual(validateNativePracticeInfos(productionPractice()), productionPractice());
  assert.equal(isProductionNativePracticeInfos(productionPractice()), true);
  assert.equal(isProductionNativePracticeInfos(stagingPractice()), false);
});

test('staging rejects production mix', () => {
  for (const change of [
    value => { value.realm.profile = 'operational-beta-v1'; },
    value => { value.realm.audience = 'cosmas-os-beta'; },
    value => { value.registeredPracticeOrigins = 'practice-uuid-production-v1'; },
    value => { value.registeredPracticeOrigins = '*'; },
    value => { value.accountOrigin = 'https://enrollment-api.staging.cosmas.ai/path'; },
    value => { value.accountOrigin = 'https://enrollment-api.cosmas.ai'; },
    value => { value.accountOrigin = 'https://enrollment.example.invalid'; },
  ]) {
    const value = stagingPractice();
    change(value);
    assert.throws(() => validateNativePracticeInfos(value));
  }
});

test('production rejects staging mix and empty audience', () => {
  for (const change of [
    value => { value.accountOrigin = 'https://enrollment.example.invalid'; },
    value => { value.registeredPracticeOrigins = 'synthetic-practice-uuid-staging-v1'; },
    value => { value.realm.audience = ''; },
    value => { value.realm.profile = 'operational-staging-v1'; },
    value => { value.realm.frontendOrigin = 'https://other.clerk.accounts.dev'; },
  ]) {
    const value = productionPractice();
    change(value);
    assert.throws(() => validateNativePracticeInfos(value));
  }
});

test('helper message stays explicit for production Mac blocking', () => {
  assert.match(productionPracticeHelperRequiredMessage(), /signed CosmasNativePracticeConnection helper/);
  assert.match(productionPracticeHelperRequiredMessage(), /clerk\.cosmas\.ai/);
});
