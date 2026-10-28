import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp, mkdir, readFile, realpath, rm, symlink, writeFile, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {buildNativeRenderer, nativeRendererArguments} from './build-native-renderer.mjs';
import {workspaceIdentityInputs} from './prepare-workspace-identity.mjs';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';
import {resolveHostedWorkspace} from '../clients/shared/hosted-workspace-config.mjs';

const identity = {version: 1, profile: 'operational-beta-v1', client: 'desktop',
  apiOrigin: 'https://api.example.invalid',
  publishableKey: 'pk_live_' + Buffer.from('identity.example.invalid$').toString('base64'),
  frontendOrigin: 'https://identity.example.invalid', organizationId: 'org_renderer_invented', audience: 'cosmas-beta-api'};
const options = {webOrigin: 'https://workspace.example.invalid', coreWebOrigin: 'https://core.example.invalid',
  captureUploadOrigins: ['https://uploads.example.invalid']};

async function fixture(t, client = 'desktop', dataMode = 'authorized_beta', nativeFeatureProfile = 'operational-beta-v1') {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'cosmas-native-renderer-')));
  t.after(() => rm(root, {recursive: true, force: true}));
  const inputs = join(root, 'clients'), output = join(root, 'renderer');
  await mkdir(inputs);
  const files = structuredClone(workspaceIdentityInputs(identity, {...options, dataMode, nativeFeatureProfile}));
  for (const [name, value] of Object.entries(files)) await writeFile(join(inputs, name), JSON.stringify(value));
  return {root, inputs, output, client, files};
}

for (const client of ['desktop','apple']) test(`${client} explicitly builds the first-owner synthetic profile with operational auth`,async t=>{
  const f=await fixture(t,client,'synthetic','first-owner-staging-v1');
  const env=f.files[client+'-build-env.json'];
  const result=await buildNativeRenderer(f,{build:config=>emit(config,env)});
  assert.equal(result.profile.profile,'first-owner-staging-v1');
  assert.equal(result.profile.captureMode,'disabled');
  assert.equal(result.profile.dataMode,'synthetic');
  assert.deepEqual(result.profile.enabledFlags,['VITE_AI_ACTIVITY_ENABLED','VITE_WORKSPACE_ROUTINES_ENABLED']);
});

async function emit(config, env, change = {}) {
  await mkdir(config.build.outDir);
  await writeFile(join(config.build.outDir, 'index.html'), '<html></html>');
  await writeFile(join(config.build.outDir, 'cosmas-beta-features.json'),
    JSON.stringify(change.profile ?? resolveBetaFeatureProfile(env).manifest));
  await writeFile(join(config.build.outDir, 'cosmas-workspace-build.json'),
    JSON.stringify(change.transport ?? {version: 1, ...resolveHostedWorkspace(env)}));
}

for(const client of ['desktop','apple'])test(`${client} retains exact optional pilot flags through renderer compilation`,async t=>{
  const f=await fixture(t,client,'synthetic'),name=client+'-build-env.json';
  const optIns={VITE_MESSAGES_ENABLED:'true',VITE_EHR_READ_ENABLED:'true',VITE_CALENDAR_IMPORT_ENABLED:'false',VITE_MICROSOFT_MESSAGE_ENABLED:'true'};
  const env={...f.files[name],...optIns};
  await writeFile(join(f.inputs,name),JSON.stringify(env));
  let calls=0;
  const result=await buildNativeRenderer(f,{build:async config=>{
    calls++;
    for(const [key,value] of Object.entries(optIns))assert.equal(process.env[key],value);
    await emit(config,env);
  }});
  assert.equal(calls,1);
  assert.deepEqual(result.profile.enabledFlags,resolveBetaFeatureProfile(env).manifest.enabledFlags);
  assert.equal(result.profile.enabledFlags.includes('VITE_CALENDAR_IMPORT_ENABLED'),false);
  assert.equal(result.inputsSha256[name],createHash('sha256').update(await readFile(join(f.inputs,name))).digest('hex'));
  assert.equal(Object.keys(process.env).some(key=>key.startsWith('VITE_')),false);
});

test('CLI requires explicit inputs, native client and output without duplicate arguments', () => {
  assert.deepEqual(nativeRendererArguments(['--inputs', '/retained/clients', '--client', 'apple', '--output', '/new/build']),
    {inputs: '/retained/clients', client: 'apple', output: '/new/build'});
  for (const args of [[], ['--inputs', '/retained/clients'], ['--client'],
    ['--client', 'desktop', '--client', 'apple'], ['--source', '/other/source'], ['--output', '--client']]) {
    assert.throws(() => nativeRendererArguments(args));
  }
});

for (const client of ['desktop', 'apple']) for (const dataMode of ['authorized_beta', 'synthetic']) {
  test(`${client} consumes retained ${dataMode} inputs and verifies both emitted manifests`, async t => {
    const f = await fixture(t, client, dataMode), env = f.files[client + '-build-env.json'];
    const beforeNodeEnv = process.env.NODE_ENV;
    let calls = 0;
    const result = await buildNativeRenderer(f, {build: async config => {
      calls++;
      assert.equal(config.envDir, false, 'Project and parent dotenv files must not be loaded');
      assert.equal(config.configLoader, 'runner', 'Configuration loading must not write into reused node_modules');
      assert.equal(config.cacheDir, join(f.output, '.vite-cache'));
      assert.equal(config.mode, 'production');
      assert.equal(config.build.emptyOutDir, false);
      assert.equal(process.env.NODE_ENV, 'production');
      for (const [name, value] of Object.entries(env)) assert.equal(process.env[name], value);
      await emit(config, env);
    }});
    assert.equal(calls, 1);
    assert.equal(result.dist, join(f.output, 'dist'));
    assert.equal(result.client, client);
    assert.equal(result.profile.dataMode, dataMode);
    assert.deepEqual(result.profile, resolveBetaFeatureProfile(env).manifest);
    for (const name of [client + '-identity.json', client + '-build-env.json']) {
      assert.equal(result.inputsSha256[name], createHash('sha256').update(await readFile(join(f.inputs, name))).digest('hex'));
    }
    const receipt = JSON.parse(await readFile(join(f.output, 'native-renderer-build.json'), 'utf8'));
    assert.equal(receipt.nativeCompiled, false);
    assert.equal(receipt.packaged, false);
    assert.equal(receipt.launched, false);
    await assert.rejects(access(join(f.output, '.incomplete')), {code: 'ENOENT'});
    assert.equal(process.env.NODE_ENV, beforeNodeEnv);
    assert.equal(Object.keys(process.env).some(key => key.startsWith('VITE_')), false);
  });
}

test('inconsistent identity, stale or incomplete profile, and unsolicited environment fields fail before output', async t => {
  const changes = [
    files => { files['desktop-identity.json'].publishableKey = 'pk_test_invented'; },
    files => { files['desktop-build-env.json'].VITE_WORKSPACE_HOSTED_API_ORIGIN = 'https://different.example.invalid'; },
    files => { files['desktop-build-env.json'].VITE_CLERK_PUBLISHABLE_KEY = 'pk_live_other'; },
    files => { files['desktop-build-env.json'].VITE_WORKSPACE_HOSTED_CLIENT = 'apple'; },
    files => { files['desktop-build-env.json'].VITE_WORKSPACE_DATA_MODE = 'unknown'; },
    files => { delete files['desktop-build-env.json'].VITE_WORKSPACE_DATA_MODE; },
    files => { files['desktop-build-env.json'].VITE_WORKSPACE_PREP_ENABLED = 'false'; },
    files => { delete files['desktop-build-env.json'].VITE_WORKSPACE_PREP_ENABLED; },
    files => { files['desktop-build-env.json'].VITE_UNREVIEWED_VALUE = 'not retained'; },
  ];
  for (const [index, change] of changes.entries()) {
    await t.test(String(index), async t => {
      const f = await fixture(t);
      change(f.files);
      for (const name of ['desktop-identity.json', 'desktop-build-env.json']) {
        await writeFile(join(f.inputs, name), JSON.stringify(f.files[name]));
      }
      await assert.rejects(buildNativeRenderer(f, {build: () => assert.fail('Invalid inputs must not compile')}));
      await assert.rejects(access(f.output), {code: 'ENOENT'});
    });
  }
});

test('ambient VITE configuration is refused without modifying it or creating output', async t => {
  const f = await fixture(t);
  process.env.VITE_API_BASE = 'https://ambient.example.invalid';
  try {
    await assert.rejects(buildNativeRenderer(f), /ambient VITE/);
    assert.equal(process.env.VITE_API_BASE, 'https://ambient.example.invalid');
    await assert.rejects(access(f.output), {code: 'ENOENT'});
  } finally { delete process.env.VITE_API_BASE; }
});

test('duplicate, linked and incomplete retained inputs are refused', async t => {
  for (const kind of ['duplicate', 'linked', 'incomplete']) {
    await t.test(kind, async t => {
      const f = await fixture(t), path = join(f.inputs, 'desktop-identity.json');
      if (kind === 'duplicate') {
        await writeFile(path, JSON.stringify(identity).replace('"version":1', '"version":1,"version":1'));
      } else if (kind === 'linked') {
        const target = join(f.root, 'identity.json');
        await writeFile(target, JSON.stringify(identity));
        await rm(path);
        await symlink(target, path);
      } else await writeFile(join(f.inputs, '.incomplete'), 'not finished');
      await assert.rejects(buildNativeRenderer(f));
      await assert.rejects(access(f.output), {code: 'ENOENT'});
    });
  }
});

test('output cannot replace existing data or overlap source/inputs through a symlink', async t => {
  const f = await fixture(t);
  await mkdir(f.output);
  const sentinel = join(f.output, 'keep.txt');
  await writeFile(sentinel, 'keep');
  await assert.rejects(buildNativeRenderer(f));
  assert.equal(await readFile(sentinel, 'utf8'), 'keep');
  await assert.rejects(buildNativeRenderer({...f, output: join(f.inputs, 'build')}), /separate/);
  await assert.rejects(buildNativeRenderer({...f, output: f.root}), /separate/);
  const link = join(f.root, 'source-link');
  await symlink(fileURLToPath(new URL('../', import.meta.url)), link);
  await assert.rejects(buildNativeRenderer({...f, output: join(link, 'native-renderer-output')}), /separate/);
  await assert.rejects(buildNativeRenderer({...f, client: 'web'}), /desktop or apple/);
});

test('mismatched emitted manifests or changed retained inputs cannot produce success evidence', async t => {
  for (const kind of ['profile', 'transport', 'input']) {
    await t.test(kind, async t => {
      const f = await fixture(t), env = f.files['desktop-build-env.json'];
      await assert.rejects(buildNativeRenderer(f, {build: async config => {
        await emit(config, env, kind === 'profile' ? {profile: {...resolveBetaFeatureProfile(env).manifest, client: 'apple'}} :
          kind === 'transport' ? {transport: {version: 1, ...resolveHostedWorkspace(env), apiOrigin: 'https://different.example.invalid'}} : {});
        if (kind === 'input') await writeFile(join(f.inputs, 'desktop-identity.json'), JSON.stringify({...identity, audience: 'changed'}));
      }}), kind === 'input' ? /inputs changed/ : /manifests differ/);
      await access(join(f.output, '.incomplete'));
      await assert.rejects(access(join(f.output, 'native-renderer-build.json')), {code: 'ENOENT'});
      assert.equal(Object.keys(process.env).some(key => key.startsWith('VITE_')), false);
    });
  }
});

test('compiler failure keeps incomplete output and restores the caller environment', async t => {
  const f = await fixture(t), beforeNodeEnv = process.env.NODE_ENV;
  await assert.rejects(buildNativeRenderer(f, {build: async () => { throw new Error('Invented compilation failure'); }}),
    /Invented compilation failure/);
  await access(join(f.output, '.incomplete'));
  await assert.rejects(access(join(f.output, 'native-renderer-build.json')), {code: 'ENOENT'});
  assert.equal(process.env.NODE_ENV, beforeNodeEnv);
  assert.equal(Object.keys(process.env).some(key => key.startsWith('VITE_')), false);
});
