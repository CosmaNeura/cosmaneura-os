import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {
  assertSyntheticOnly,
  prepareSyntheticIphoneWebBundle,
  syntheticIphoneRendererIdentity,
  syntheticIphoneRendererInputs,
} from './prepare-synthetic-iphone-web-bundle.mjs';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';
import {resolveHostedWorkspace} from '../clients/shared/hosted-workspace-config.mjs';
import {
  OPERATIONAL_NATIVE_PROFILE,
  STAGING_NATIVE_PROFILE,
  validateOperationalNativeIdentity,
} from '../clients/shared/operational-native-identity.mjs';

test('synthetic iPhone inputs use pk_test dummy and *.synthetic.example only', () => {
  const files = syntheticIphoneRendererInputs();
  const identity = files['apple-identity.json'];
  const env = files['apple-build-env.json'];
  assert.equal(identity.profile, 'operational-staging-v1');
  assert.equal(identity.client, 'apple');
  assert.match(identity.publishableKey, /^pk_test_/);
  assert.ok(identity.frontendOrigin.endsWith('.synthetic.example'));
  assert.ok(identity.apiOrigin.endsWith('.synthetic.example'));
  assert.equal(env.VITE_WORKSPACE_DATA_MODE, 'synthetic');
  assert.equal(env.VITE_WORKSPACE_CAPTURE_MODE, 'disabled');
  assertSyntheticOnly(identity);
  assertSyntheticOnly(env);
  for (const forbidden of ['pk_live_', 'sk_live_', 'sk_test_', 'cosmas.ai', 'cosmaneura.com']) {
    assert.equal(JSON.stringify(files).includes(forbidden), false, forbidden);
  }
});

test('assertSyntheticOnly refuses live keys and non-example origins', () => {
  const identity = syntheticIphoneRendererIdentity();
  assert.throws(
    () => assertSyntheticOnly({...identity, publishableKey: 'pk_live_abc'}),
    /non-synthetic material: pk_live_/,
  );
  assert.throws(
    () => assertSyntheticOnly({...identity, apiOrigin: 'https://api.cosmas.ai'}),
    /non-synthetic material: cosmas\.ai/,
  );
});

test('staging accepts *.synthetic.example and production rejects it', () => {
  const frontendOrigin = 'https://clerk.synthetic.example';
  const apiOrigin = 'https://api.synthetic.example';
  const hostname = 'clerk.synthetic.example';
  const pkTest = 'pk_test_' + Buffer.from(hostname + '$').toString('base64');
  const pkLive = 'pk_live_' + Buffer.from(hostname + '$').toString('base64');
  const staging = validateOperationalNativeIdentity({
    version: 1,
    profile: STAGING_NATIVE_PROFILE,
    client: 'apple',
    apiOrigin,
    publishableKey: pkTest,
    frontendOrigin,
    organizationId: 'org_synthetic_iphone_sim',
    audience: '',
  }, 'apple', apiOrigin);
  assert.equal(staging.profile, STAGING_NATIVE_PROFILE);
  assert.throws(
    () => validateOperationalNativeIdentity({
      version: 1,
      profile: OPERATIONAL_NATIVE_PROFILE,
      client: 'apple',
      apiOrigin,
      publishableKey: pkLive,
      frontendOrigin,
      organizationId: 'org_synthetic_iphone_sim',
      audience: 'cosmas-os-beta-api',
    }, 'apple', apiOrigin),
    /incomplete or inconsistent/,
  );
});

test('prepareSyntheticIphoneWebBundle writes inputs and invokes the renderer builder', async t => {
  const root = await mkdtemp(join(tmpdir(), 'cosmas-synth-web-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const output = join(root, 'bundle');
  let calls = 0;
  const prepared = await prepareSyntheticIphoneWebBundle({output}, {
    build: async config => {
      calls += 1;
      const env = JSON.parse(await readFile(join(output, 'inputs', 'apple-build-env.json'), 'utf8'));
      assert.equal(process.env.VITE_CLERK_PUBLISHABLE_KEY?.startsWith('pk_test_'), true);
      assert.equal(process.env.VITE_WORKSPACE_HOSTED_API_ORIGIN?.endsWith('.synthetic.example'), true);
      const {mkdir, writeFile} = await import('node:fs/promises');
      await mkdir(config.build.outDir, {recursive: true});
      await writeFile(join(config.build.outDir, 'index.html'), '<html></html>');
      await writeFile(
        join(config.build.outDir, 'cosmas-beta-features.json'),
        JSON.stringify(resolveBetaFeatureProfile(env).manifest),
      );
      await writeFile(
        join(config.build.outDir, 'cosmas-workspace-build.json'),
        JSON.stringify({version: 1, ...resolveHostedWorkspace(env)}),
      );
    },
  });
  assert.equal(calls, 1);
  assert.ok(prepared.dist.endsWith('dist'));
  const receipt = JSON.parse(await readFile(join(output, 'synthetic-web-bundle.json'), 'utf8'));
  assert.equal(receipt.publishable_key_prefix, 'pk_test_');
  assert.equal(receipt.secrets, false);
  assert.ok(receipt.origins.api.endsWith('.synthetic.example'));
});
