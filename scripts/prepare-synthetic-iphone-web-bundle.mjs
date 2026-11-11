#!/usr/bin/env node
/**
 * Synthetic-only Apple renderer inputs + web bundle for the unsigned iPhone
 * Simulator build (com.cosmasos.synthetic).
 *
 * Emits apple-identity.json / apple-build-env.json with *.synthetic.example
 * origins and a pk_test_ dummy that only encodes that invented host. No real
 * Clerk keys, secrets, or production hosts. Then compiles the Apple renderer
 * via build-native-renderer.mjs.
 *
 * One command (from repository root, Node 24):
 *
 *   node scripts/prepare-synthetic-iphone-web-bundle.mjs \
 *     --output /absolute/path/to/fresh-synthetic-apple-renderer
 *
 * Pass `<output>/dist` as the App/public web assets for the simulator compose.
 */
import {createHash} from 'node:crypto';
import {mkdir, writeFile, realpath} from 'node:fs/promises';
import {basename, dirname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {buildNativeRenderer} from './build-native-renderer.mjs';
import {validateOperationalNativeIdentity, validateOperationalNativeDataMode}
  from '../clients/shared/operational-native-identity.mjs';
import {resolveBetaFeatureProfile, NATIVE_STAGING_FEATURE_PROFILE}
  from '../clients/shared/beta-feature-profile.mjs';

const SYNTHETIC_API = 'https://api.synthetic.example';
const SYNTHETIC_FRONTEND = 'https://clerk.synthetic.example';
const SYNTHETIC_WEB = 'https://app.synthetic.example';
const FORBIDDEN_HOST_SNIPPETS = [
  'cosmas.ai', 'cosmaneura.com', 'clerk.com', 'pk_live_', 'sk_live_', 'sk_test_',
];

function pkTestForHost(hostname) {
  return 'pk_test_' + Buffer.from(hostname + '$').toString('base64');
}

/** Pure synthetic Apple identity for build-native-renderer.mjs. */
export function syntheticIphoneRendererIdentity() {
  const hostname = new URL(SYNTHETIC_FRONTEND).hostname;
  const identity = validateOperationalNativeIdentity({
    version: 1,
    profile: 'operational-staging-v1',
    client: 'apple',
    apiOrigin: SYNTHETIC_API,
    publishableKey: pkTestForHost(hostname),
    frontendOrigin: SYNTHETIC_FRONTEND,
    organizationId: 'org_synthetic_iphone_sim',
    audience: '',
  }, 'apple', SYNTHETIC_API);
  validateOperationalNativeDataMode('synthetic', identity);
  assertSyntheticOnly(identity);
  return identity;
}

export function assertSyntheticOnly(value) {
  const text = JSON.stringify(value);
  for (const snippet of FORBIDDEN_HOST_SNIPPETS) {
    if (text.includes(snippet)) {
      throw new Error(`Synthetic iPhone renderer refused non-synthetic material: ${snippet}`);
    }
  }
  if (!text.includes('.synthetic.example')) {
    throw new Error('Synthetic iPhone renderer requires *.synthetic.example origins');
  }
  if (!String(value.publishableKey || value.VITE_CLERK_PUBLISHABLE_KEY || '').startsWith('pk_test_')) {
    throw new Error('Synthetic iPhone renderer requires a pk_test_ dummy publishable key');
  }
  for (const key of ['apiOrigin', 'frontendOrigin', 'VITE_WORKSPACE_HOSTED_API_ORIGIN', 'VITE_API_BASE']) {
    if (!Object.hasOwn(value, key) || value[key] == null || value[key] === '') continue;
    const host = new URL(value[key]).hostname;
    if (!host.endsWith('.synthetic.example')) {
      throw new Error(`Origin must end with .synthetic.example: ${value[key]}`);
    }
  }
}

export function syntheticIphoneRendererInputs() {
  const identity = syntheticIphoneRendererIdentity();
  // first-owner-staging keeps Core/capture dark; Simulator mic XCUITest uses a
  // native launch-arg hook against the real Capacitor plugin path instead.
  const profile = resolveBetaFeatureProfile({
    VITE_WORKSPACE_FEATURE_PROFILE: NATIVE_STAGING_FEATURE_PROFILE,
    VITE_WORKSPACE_HOSTED_CLIENT: 'apple',
    VITE_WORKSPACE_DATA_MODE: 'synthetic',
    VITE_WORKSPACE_HOSTED_API_ORIGIN: identity.apiOrigin,
    VITE_API_BASE: identity.apiOrigin,
    VITE_WORKSPACE_WEB_ORIGIN: '',
    VITE_CLERK_PUBLISHABLE_KEY: identity.publishableKey,
    VITE_COSMANEURA_WEB_ORIGIN: '',
    VITE_CAPTURE_UPLOAD_ORIGINS: '',
    VITE_WORKSPACE_CAPTURE_MODE: 'disabled',
  });
  assertSyntheticOnly(identity);
  assertSyntheticOnly(profile.env);
  return {
    'apple-identity.json': {...identity},
    'apple-build-env.json': {...profile.env},
  };
}

function parseArgs(argv) {
  if (argv.length !== 2 || argv[0] !== '--output' || !argv[1] || argv[1].startsWith('--')) {
    throw new Error('Usage: node scripts/prepare-synthetic-iphone-web-bundle.mjs --output /absolute/fresh-dir');
  }
  return {output: argv[1]};
}

export async function prepareSyntheticIphoneWebBundle({output}, {build} = {}) {
  const outputPath = join(await realpath(dirname(resolve(output))), basename(resolve(output)));
  const inputsRoot = join(outputPath, 'inputs');
  const rendererRoot = join(outputPath, 'renderer');
  await mkdir(outputPath, {recursive: false, mode: 0o700});
  await mkdir(inputsRoot, {mode: 0o700});
  const inputs = syntheticIphoneRendererInputs();
  for (const [name, value] of Object.entries(inputs)) {
    await writeFile(join(inputsRoot, name), JSON.stringify(value, null, 2) + '\n', {flag: 'wx'});
  }
  const result = await buildNativeRenderer(
    {inputs: inputsRoot, client: 'apple', output: rendererRoot},
    {build},
  );
  const receipt = {
    purpose: 'synthetic-iphone-simulator-web-bundle',
    signed: false,
    secrets: false,
    publishable_key_prefix: 'pk_test_',
    origins: {
      api: SYNTHETIC_API,
      frontend: SYNTHETIC_FRONTEND,
      web: SYNTHETIC_WEB,
    },
    inputs_sha256: Object.fromEntries(
      await Promise.all(Object.keys(inputs).map(async name => {
        const {readFile} = await import('node:fs/promises');
        const raw = await readFile(join(inputsRoot, name));
        return [name, createHash('sha256').update(raw).digest('hex')];
      })),
    ),
    dist: result.dist,
  };
  await writeFile(join(outputPath, 'synthetic-web-bundle.json'), JSON.stringify(receipt, null, 2) + '\n');
  return {outputPath, inputsRoot, dist: result.dist, receipt};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = parseArgs(process.argv.slice(2));
    const prepared = await prepareSyntheticIphoneWebBundle(args);
    console.log(`Prepared synthetic iPhone web bundle: ${prepared.dist}`);
    console.log('Inputs are pk_test_ + *.synthetic.example only; no secrets.');
  } catch (error) {
    console.error(String(error?.message || error));
    process.exit(1);
  }
}
