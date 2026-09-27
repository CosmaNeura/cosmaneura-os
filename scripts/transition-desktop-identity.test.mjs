import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash, randomUUID} from 'node:crypto';
import {chmod, link, mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {prepareDesktopState} from '../clients/desktop/installation-state.mjs';
import {isDesktopProfileProcess, transitionDesktopIdentity} from './transition-desktop-identity.mjs';

test('separate Scribe helpers do not block CosmaBot; its own helpers and profile users do', () => {
  const profile = '/Users/invented/Library/Application Support/CosmasOS Beta/com.cosmasos.beta.desktop';
  for (const helper of ['ScribeDesktopAudioHelper', 'ScribeProviderPresentationHelper']) {
    const suffix = `/Contents/Resources/app/native/${helper}.app/Contents/MacOS/${helper}`;
    assert.equal(isDesktopProfileProcess('/Applications/Cosmaneura Scribe Beta.app' + suffix, profile), false);
    assert.equal(isDesktopProfileProcess('/Applications/CosmaBot-Desktop-0.1.48.app' + suffix, profile), true);
    assert.equal(isDesktopProfileProcess('/Applications/CosmasOS Beta.app' + suffix, profile), true);
  }
  assert.equal(isDesktopProfileProcess('/prepared/CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth', profile), true);
  assert.equal(isDesktopProfileProcess(profile + '/helper', profile), true);
  assert.equal(isDesktopProfileProcess('/Applications/Other.app/Contents/MacOS/Other', profile), false);
});

async function fixture(t) {
  const root = await mkdtemp(join(await realpath(tmpdir()), 'cosmas-identity-transition-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const identity = (host, shared = false) => ({version: 1, profile: shared ? 'operational-staging-v1' : 'operational-beta-v1',
    client: 'desktop', apiOrigin: 'https://api.example.invalid',
    publishableKey: (shared ? 'pk_test_' : 'pk_live_') + Buffer.from(host + '$').toString('base64'),
    frontendOrigin: 'https://' + host, organizationId: shared ? 'org_shared' : 'org_original', audience: shared ? '' : 'cosmas-api'});
  const sourceIdentity = identity('identity.example.invalid'), targetIdentity = identity('invented.clerk.accounts.dev', true);
  const config = {mode: 'hosted-beta-authenticated', dataMode: 'synthetic', apiOrigin: sourceIdentity.apiOrigin, nativeIdentity: sourceIdentity,
    installation: {version: 1, profile: 'beta', bundleIdentifier: 'com.cosmasos.beta.desktop', storageGeneration: 1,
      electronVersion: '43.4.1', rendererPartition: 'persist:cosmasos-operational-beta', authHelperBundleIdentifier: 'com.cosmasos.beta.desktop.auth'}};
  const profile = await prepareDesktopState(config, root, '43.4.1');
  const filename = join(profile, 'cosmas-installation.json'), original = await readFile(filename);
  await writeFile(join(profile, 'invented-encrypted-draft'), Buffer.from([12, 209, 0, 41, 9]), {mode: 0o600});
  const plan = {contract: 'cosmas-desktop-identity-transition-v1', transitionId: randomUUID(), sourceIdentity, targetIdentity,
    sourceMarkerSha256: createHash('sha256').update(original).digest('hex'), expiresAt: new Date(Date.now() + 3600000).toISOString()};
  const change = (action, options = {}) => transitionDesktopIdentity({profile, plan, action, quiescent: async () => {}, ...options});
  return {root, profile, filename, original, plan, config, change};
}

test('shared identity opens the same populated profile; rollback restores its exact original marker', async t => {
  const f = await fixture(t);
  const draft = await readFile(join(f.profile, 'invented-encrypted-draft'));
  const inventory = await readdir(f.profile);
  assert.equal((await f.change('plan')).status, 'ready');
  assert.deepEqual(await readdir(f.profile), inventory);
  assert.equal((await f.change('apply')).status, 'applied');
  assert.equal((await f.change('apply')).status, 'already_applied');
  assert.equal(await prepareDesktopState({...f.config, nativeIdentity: f.plan.targetIdentity}, f.root, '43.4.1'), f.profile);
  await assert.rejects(prepareDesktopState(f.config, f.root, '43.4.1'));
  assert.deepEqual(await readFile(join(f.profile, 'invented-encrypted-draft')), draft);
  const renewed = {...f.plan, expiresAt: new Date(Date.now() + 7200000).toISOString()};
  assert.equal((await f.change('rollback', {plan: renewed})).status, 'rolled_back');
  assert.equal((await f.change('rollback', {plan: renewed})).status, 'already_rolled_back');
  assert.deepEqual(await readFile(f.filename), f.original);
  assert.equal(await prepareDesktopState(f.config, f.root, '43.4.1'), f.profile);
  assert.deepEqual(await readFile(join(f.profile, 'invented-encrypted-draft')), draft);
});

test('busy application, changed marker and expired or broader plans cannot change saved state', async t => {
  const f = await fixture(t);
  await assert.rejects(f.change('apply', {quiescent: async () => { throw new Error('invented busy application'); }}));
  for (const changed of [{expiresAt: '2020-01-01T00:00:00Z'}, {expiresAt: '2099-01-01T00:00:00Z'},
    {sourceMarkerSha256: 'a'.repeat(64)}, {extra: true}, {targetIdentity: {...f.plan.targetIdentity, apiOrigin: 'https://other.example.invalid'}}]) {
    await assert.rejects(f.change('apply', {plan: {...f.plan, ...changed}}));
  }
  assert.deepEqual(await readFile(f.filename), f.original);
  assert.deepEqual(await readdir(f.profile), ['cosmas-installation.json', 'invented-encrypted-draft']);
});

test('interruption after durable recovery receipt leaves the original marker and permits exact retry', async t => {
  const f = await fixture(t);
  let checks = 0;
  await assert.rejects(f.change('apply', {quiescent: async () => { if (++checks === 2) throw new Error('invented interruption'); }}));
  assert.deepEqual(await readFile(f.filename), f.original);
  assert.equal((await f.change('apply')).status, 'applied');
  assert.equal((await f.change('rollback')).status, 'rolled_back');
  assert.deepEqual(await readFile(f.filename), f.original);
});

test('concurrent or crashed maintenance lock and mismatched recovery receipt require inspection', async t => {
  const f = await fixture(t), lock = join(f.profile, '.cosmas-identity-maintenance');
  await mkdir(lock, {mode: 0o700});
  await assert.rejects(f.change('apply'));
  assert.deepEqual(await readFile(f.filename), f.original);
  await rm(lock, {recursive: true});
  for (const invalid of ['{}', 'null', 'false']) {
    await writeFile(join(f.profile, 'identity-transition-' + f.plan.transitionId + '.json'), invalid, {mode: 0o600});
    await assert.rejects(f.change('apply'));
  }
  assert.deepEqual(await readFile(f.filename), f.original);
});

test('linked marker and nonprivate profile cannot be used to rewrite other files', async t => {
  const f = await fixture(t), external = join(f.root, 'external-marker');
  await writeFile(external, f.original, {mode: 0o600}); await rm(f.filename);
  await symlink(external, f.filename); await assert.rejects(f.change('apply'));
  await rm(f.filename); await link(external, f.filename); await assert.rejects(f.change('apply'));
  assert.deepEqual(await readFile(external), f.original);
  await rm(f.filename); await writeFile(f.filename, f.original, {mode: 0o600});
  await chmod(f.profile, 0o755); await assert.rejects(f.change('apply'));
  assert.deepEqual(await readFile(f.filename), f.original);
});
