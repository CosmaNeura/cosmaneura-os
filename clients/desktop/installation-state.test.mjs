import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, readFile, writeFile, chmod, symlink, rm, readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {basename, dirname, join} from 'node:path';
import {prepareDesktopState} from './installation-state.mjs';
import {createAuthAccessStore} from './auth-access-store.mjs';

const identity = Object.freeze({version: 1, profile: 'w19', bundleIdentifier: 'com.cosmasos.synthetic.desktop.w19',
  storageGeneration: 1, electronVersion: '43.4.1', rendererPartition: 'persist:cosmasos-authenticated-local',
  authHelperBundleIdentifier: 'com.cosmasos.synthetic.desktop.auth.w16'});
async function fixture(t) {
  // macOS /tmp is a symlink; the runtime deliberately requires canonical storage paths.
  const {realpath} = await import('node:fs/promises');
  const root = await mkdtemp(join(await realpath(tmpdir()), 'cosmas-installation-test-'));
  t.after(() => rm(root, {recursive: true, force: true}));
  const config = {mode: 'local-synthetic-authenticated', installationRoot: join(root, 'profiles'), installation: {...identity}};
  return {root, config, prepare: (value = config, runtime = '43.4.1') => prepareDesktopState(value, '/unused', runtime)};
}

test('upgrade and compatible rollback retain ciphertext, access decision and the original marker', async t => {
  const {prepare, config} = await fixture(t);
  const path = await prepare();
  const marker = await readFile(join(path, 'cosmas-installation.json'));
  const ciphertext = Buffer.from([8, 212, 0, 25, 155, 71, 32]);
  await writeFile(join(path, 'invented-encrypted-queue'), ciphertext, {mode: 0o600});
  const access = createAuthAccessStore(path);
  assert.equal(await access.read(), 'needs_login');
  await access.write('logout_pending');
  for (const [appVersion, buildNumber] of [['0.2.0', '2'], ['0.1.0', '1']]) {
    assert.equal(await prepare({...config, appVersion, buildNumber}), path);
    assert.deepEqual(await readFile(join(path, 'cosmas-installation.json')), marker);
    assert.deepEqual(await readFile(join(path, 'invented-encrypted-queue')), ciphertext);
    assert.equal(await createAuthAccessStore(path).read(), 'logout_pending');
  }
});

test('hosted installation binds saved data to its service without rewriting a local or different hosted profile', async t => {
  const {prepare,config}=await fixture(t);
  const hosted={...config,mode:'hosted-beta-authenticated',dataMode:'synthetic',apiOrigin:'https://api.example.invalid'};
  const directory=await prepare(hosted);
  const marker=await readFile(join(directory,'cosmas-installation.json'));
  await assert.rejects(prepare({...hosted,apiOrigin:'https://other.example.invalid'}));
  await assert.rejects(prepare(config));
  assert.deepEqual(await readFile(join(directory,'cosmas-installation.json')),marker);
  assert.equal(await prepare(hosted),directory);
});

for (const [field, value] of Object.entries({storageGeneration: 2, electronVersion: '44.0.0',
  rendererPartition: 'persist:other', authHelperBundleIdentifier: 'com.cosmasos.synthetic.desktop.auth.w19'})) {
  test(`incompatible persisted ${field} blocks without rewriting any file`, async t => {
    const {prepare} = await fixture(t);
    const path = await prepare();
    const filename = join(path, 'cosmas-installation.json');
    const changed = {...JSON.parse(await readFile(filename, 'utf8')), [field]: value};
    const encoded = JSON.stringify(changed);
    await writeFile(filename, encoded);
    await assert.rejects(prepare(), /local data was preserved/);
    assert.equal(await readFile(filename, 'utf8'), encoded);
    assert.deepEqual(await readdir(path), ['cosmas-installation.json']);
  });
}

test('different profile cannot acquire a previous profile or native helper identity', async t => {
  const {prepare, config} = await fixture(t);
  const prior = await prepare();
  await assert.rejects(prepare({...config, installation: {...identity, profile: 'w13'}}), /preserved/);
  await assert.rejects(prepare({...config, installation: {...identity, authHelperBundleIdentifier: 'com.production.auth'}}), /preserved/);
  const next = await prepare({...config, installation: {...identity, profile: 'w19a', bundleIdentifier: 'com.cosmasos.synthetic.desktop.w19a'}});
  assert.notEqual(prior, next);
});

test('a missing marker in a populated profile never silently initializes it', async t => {
  const {prepare} = await fixture(t);
  const path = await prepare();
  await rm(join(path, 'cosmas-installation.json'));
  await writeFile(join(path, 'invented-recording'), 'retained');
  await assert.rejects(prepare(), /preserved/);
  assert.deepEqual(await readdir(path), ['invented-recording']);
});

test('malformed or overly broad profile metadata cannot launch or be reset', async t => {
  const {prepare} = await fixture(t);
  const path = await prepare(), filename = join(path, 'cosmas-installation.json');
  for (const text of ['', '{', 'null', 'x'.repeat(2049)]) {
    await writeFile(filename, text);
    await assert.rejects(prepare(), /preserved/);
    assert.equal(await readFile(filename, 'utf8'), text);
  }
  await chmod(path, 0o755);
  await assert.rejects(prepare(), /preserved/);
});

test('symlinked storage and marker files are refused without opening their data', async t => {
  const {prepare, config, root} = await fixture(t);
  const target = join(root, 'target'); await mkdir(target);
  await symlink(target, config.installationRoot);
  await assert.rejects(prepare(), /preserved/);
  assert.deepEqual(await readdir(target), []);
  await rm(config.installationRoot);
  const path = await prepare(), marker = join(path, 'cosmas-installation.json');
  const saved = await readFile(marker); await rm(marker);
  const external = join(target, 'marker'); await writeFile(external, saved);
  await symlink(external, marker);
  await assert.rejects(prepare(), /preserved/);
  assert.deepEqual(await readFile(external), saved);
});

test('wrong running Electron or conflicting legacy state path fails closed', async t => {
  const {prepare, config} = await fixture(t);
  await assert.rejects(prepare(config, '44.0.0'), /preserved/);
  await assert.rejects(prepare({...config, stateDirectory: '/old'}), /preserved/);
});

test('existing isolated compositions retain their original state paths without new files', async t => {
  const {root, prepare} = await fixture(t);
  assert.equal(await prepare({stateDirectory: join(root, 'old')}), join(root, 'old'));
  assert.deepEqual(await readdir(root), []);
});

async function operationalFixture(t) {
  const {root} = await fixture(t);
  const apiOrigin = 'https://api.example.invalid';
  const nativeIdentity = {
    version: 1, profile: 'operational-beta-v1', client: 'desktop', apiOrigin,
    frontendOrigin: 'https://identity.example.invalid',
    publishableKey: 'pk_live_' + Buffer.from('identity.example.invalid$').toString('base64'),
    organizationId: 'org_invented_practice', audience: 'invented-cosmabot-api',
  };
  const installation = {version: 1, profile: 'beta', bundleIdentifier: 'com.cosmasos.beta.desktop',
    storageGeneration: 1, electronVersion: '43.4.1', rendererPartition: 'persist:cosmasos-operational-beta',
    authHelperBundleIdentifier: 'com.cosmasos.beta.desktop.auth'};
  const config = {mode: 'hosted-beta-authenticated', apiOrigin, dataMode: 'synthetic', nativeIdentity,
    installation: {...installation, storageScope: 'identity-v1'}};
  const legacy = {...config, installation, nativeIdentity: {...nativeIdentity,
    profile: 'operational-staging-v1', audience: '', organizationId: 'org_invented_old_lab',
    frontendOrigin: 'https://invented-old.clerk.accounts.dev',
    publishableKey: 'pk_test_' + Buffer.from('invented-old.clerk.accounts.dev$').toString('base64')}};
  return {root, config, legacy, prepare: value => prepareDesktopState(value, root, '43.4.1')};
}

test('identity-scoped beta cold start preserves the complete old installation and supports both rollback paths', async t => {
  const {config, legacy, prepare} = await operationalFixture(t);
  const oldPath = await prepare(legacy);
  const oldMarker = await readFile(join(oldPath, 'cosmas-installation.json'));
  const oldCiphertext = Buffer.from([19, 210, 0, 155]);
  await writeFile(join(oldPath, 'old-encrypted-drafts'), oldCiphertext, {mode: 0o600});
  assert.equal(await createAuthAccessStore(oldPath).read(), 'needs_login');
  await createAuthAccessStore(oldPath).write('logout_pending');
  const directory = await prepare(config);
  assert.equal(dirname(directory), dirname(oldPath));
  assert.match(basename(directory), /^com\.cosmasos\.beta\.desktop\.identity-[a-f0-9]{64}$/);
  assert.deepEqual(await readdir(directory), ['cosmas-installation.json']);
  assert.equal(await createAuthAccessStore(directory).read(), 'needs_login');
  const marker = await readFile(join(directory, 'cosmas-installation.json'));
  assert.equal(JSON.parse(marker).storageScope, 'identity-v1');
  const ciphertext = Buffer.from([209, 6, 0, 18]);
  await writeFile(join(directory, 'new-encrypted-drafts'), ciphertext, {mode: 0o600});
  await createAuthAccessStore(directory).write('logout_pending');
  for (const buildNumber of ['1104', '1103']) {
    assert.equal(await prepare({...config, buildNumber}), directory);
    assert.deepEqual(await readFile(join(directory, 'cosmas-installation.json')), marker);
    assert.deepEqual(await readFile(join(directory, 'new-encrypted-drafts')), ciphertext);
    assert.equal(await createAuthAccessStore(directory).read(), 'logout_pending');
  }
  assert.equal(await prepare(legacy), oldPath);
  assert.deepEqual(await readFile(join(oldPath, 'cosmas-installation.json')), oldMarker);
  assert.deepEqual(await readFile(join(oldPath, 'old-encrypted-drafts')), oldCiphertext);
  assert.equal(await createAuthAccessStore(oldPath).read(), 'logout_pending');
});

test('each exact native identity has separate state and an omitted scope cannot adopt old account data', async t => {
  const {config, legacy, prepare} = await operationalFixture(t);
  const oldPath = await prepare(legacy), path = await prepare(config);
  await writeFile(join(path, 'retained-ciphertext'), 'invented encrypted bytes', {mode: 0o600});
  const changes = [
    {organizationId: 'org_invented_other'},
    {frontendOrigin: 'https://other.example.invalid', publishableKey: 'pk_live_' + Buffer.from('other.example.invalid$').toString('base64')},
    {audience: 'invented-other-api'},
    {apiOrigin: 'https://other-api.example.invalid'},
  ];
  const directories = new Set([oldPath, path]);
  for (const change of changes) {
    const identity = {...config.nativeIdentity, ...change};
    const next = await prepare({...config, apiOrigin: identity.apiOrigin, nativeIdentity: identity});
    assert.equal(directories.has(next), false);
    assert.deepEqual(await readdir(next), ['cosmas-installation.json']);
    directories.add(next);
  }
  await assert.rejects(prepare({...config, installation: legacy.installation}), /preserved/);
  assert.equal(await readFile(join(path, 'retained-ciphertext'), 'utf8'), 'invented encrypted bytes');
  assert.equal(await prepare(legacy), oldPath);
});

test('unsupported or nonoperational storage scopes fail before creating state', async t => {
  const {root, config, prepare} = await operationalFixture(t);
  for (const storageScope of ['', null, false, 'identity-v2', undefined]) {
    await assert.rejects(prepare({...config, installation: {...config.installation, storageScope}}), /preserved/);
  }
  await assert.rejects(prepare({mode: 'local-synthetic-authenticated', installationRoot: join(root, 'synthetic'),
    installation: {...identity, storageScope: 'identity-v1'}}), /preserved/);
  assert.deepEqual(await readdir(root), []);
});

test('identity-scoped roots retain missing-marker recovery and symlink protections', async t => {
  const {root, config, prepare} = await operationalFixture(t);
  const directory = await prepare(config);
  const marker = join(directory, 'cosmas-installation.json');
  await rm(marker);
  await writeFile(join(directory, 'retained-ciphertext'), 'do not reset', {mode: 0o600});
  await assert.rejects(prepare(config), /preserved/);
  assert.deepEqual(await readdir(directory), ['retained-ciphertext']);
  await rm(directory, {recursive: true});
  const target = join(root, 'untouched-target');
  await mkdir(target, {mode: 0o700});
  await symlink(target, directory);
  await assert.rejects(prepare(config), /preserved/);
  assert.deepEqual(await readdir(target), []);
});
