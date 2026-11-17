import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {resolveBuild} from '../build-config.mjs';
import {handleMessage, boxCall} from '../src/worker-core.mjs';
const profile = JSON.parse(readFileSync(new URL('../local-profile.json', import.meta.url)));
const sender = {id: profile.extensionId, url: `${profile.extensionOrigin}/panel.html`};
const clerk = () => ({proofOrganization: 'org_invented', organization: {id: 'org_invented'},
  session: {status: 'active', getToken: async () => 'invented-token'}});

test('manifest identity, bundled scripts, permissions and profile agree', () => {
  const manifest = JSON.parse(readFileSync(new URL('../manifest.json', import.meta.url)));
  const digest = createHash('sha256').update(Buffer.from(manifest.key, 'base64')).digest().subarray(0, 16);
  const id = [...digest].flatMap(b => [String.fromCharCode(97 + (b >> 4)), String.fromCharCode(97 + (b & 15))]).join('');
  assert.equal(id, profile.extensionId);
  assert.equal(manifest.manifest_version, 3);
  assert.deepEqual(manifest.permissions, ['sidePanel', 'storage', 'clipboardWrite']);
  assert.deepEqual(manifest.host_permissions, ['http://127.0.0.1:8765/*', 'http://127.0.0.1:8766/*']);
  assert.deepEqual(manifest.content_scripts[0].matches, ['http://127.0.0.1:8765/schedule.html']);
  assert.match(manifest.content_security_policy.extension_pages, /script-src 'self'; object-src 'none'/);
  assert.equal(manifest.externally_connectable, undefined);
});

test('only the fixed panel can invoke the authenticated worker', async () => {
  let calls = 0;
  const deps = {getClerk: async () => { calls++; return clerk(); },
    fetcher: async () => ({ok: true, json: async () => ({signed_in: true})})};
  assert.equal((await handleMessage({type: 'connect'}, sender, deps)).state, 'connected');
  for (const wrong of [{...sender, id: 'a'.repeat(32)}, {...sender, url: 'chrome-extension://' + 'a'.repeat(32) + '/panel.html'},
    {...sender, url: profile.extensionOrigin + '/content.js'}, {...sender, tab: {id: 1}},
    {...sender, url: profile.fixtureOrigin + '/schedule.html'}, undefined]) {
    assert.equal((await handleMessage({type: 'connect'}, wrong, deps)).state, 'request_refused');
  }
  assert.equal(calls, 1);
});

test('no session, inactive session, missing token and wrong org fail closed before fetch', async () => {
  let requests = 0;
  for (const auth of [null, {}, {...clerk(), session: null}, {...clerk(), session: {status: 'pending'}},
    {...clerk(), organization: {id: 'org_other'}}, {...clerk(), session: {status: 'active', getToken: async () => null}}]) {
    const result = await boxCall(async () => auth, async () => {requests++;}, '/workspace/extension-session');
    assert.equal(result.state, 'sign_in_required');
  }
  assert.equal(requests, 0);
});

test('local call uses bearer only, refuses redirects, returns no bearer and retries after failure', async () => {
  let attempts = 0;
  const fetcher = async (url, options) => {
    assert.equal(url, profile.apiOrigin + '/workspace/extension-session');
    assert.equal(options.headers.Authorization, 'Bearer invented-token');
    assert.equal(options.redirect, 'error');
    assert.equal(options.credentials, 'omit');
    attempts++;
    return attempts === 1 ? {ok: false, status: 401} : {ok: true, json: async () => ({signed_in: true})};
  };
  assert.deepEqual(await boxCall(async () => clerk(), fetcher, '/workspace/extension-session'), {state: 'sign_in_required'});
  assert.deepEqual(await boxCall(async () => clerk(), fetcher, '/workspace/extension-session'), {state: 'connected', result: {signed_in: true}});
  assert.equal((await boxCall(async () => clerk(), fetcher, 'https://other.invalid')).state, 'request_refused');
});

test('missing selector response never posts an empty list', async () => {
  const result = await handleMessage({type: 'read-fixture'}, sender, {
    readFixture: async () => ({state: 'screen_not_recognised'}),
    getClerk: () => assert.fail('must not fetch token'), fetcher: () => assert.fail('must not post')});
  assert.deepEqual(result, {state: 'screen_not_recognised'});
});

test('worker error responses scrub payloads, passwords and tokens', async () => {
  const secret = 'invented-identifier-secret';
  const result = await handleMessage({type: 'sign-in', identifier: secret, password: secret}, sender,
    {getClerk: async () => {throw new Error(secret);}});
  assert.deepEqual(result, {state: 'sign_in_unavailable'});
  assert.ok(!JSON.stringify(result).includes(secret));
});

test('build accepts matched development configuration only and errors never echo it', () => {
  const issuer = 'https://invented-extension.clerk.accounts.dev';
  const key = ['pk', 'test', Buffer.from('invented-extension.clerk.accounts.dev$').toString('base64')].join('_');
  const env = {COSMABOT_EXTENSION_CLERK_PUBLISHABLE_KEY: key, COSMABOT_EXTENSION_CLERK_ISSUER: issuer,
    COSMABOT_EXTENSION_CLERK_ORGANIZATION_ID: 'org_invented'};
  assert.equal(resolveBuild(env).issuer, issuer);
  for (const bad of [{}, {...env, COSMABOT_EXTENSION_CLERK_ISSUER: 'https://other.clerk.accounts.dev'},
    {...env, COSMABOT_EXTENSION_CLERK_PUBLISHABLE_KEY: key.replace('test', 'live')}])
    assert.throws(() => resolveBuild(bad), {message: 'CosmaBot development Clerk configuration required'});
  assert.deepEqual(resolveBuild({}, true), {publishableKey: null, organization: null, issuer: null});
});

test('password-complete sign-in activates configured org and calls the Box; extra steps remain blocked', async () => {
  let activated = false;
  const auth = clerk();
  auth.client = {signIn: {create: async ({identifier, password}) => {
    assert.equal(identifier, 'invented-user');
    assert.equal(password, 'invented-password');
    return {status: 'complete', createdSessionId: 'invented-session'};
  }}};
  auth.setActive = async ({session, organization}) => {
    assert.equal(session, 'invented-session');
    assert.equal(organization, auth.proofOrganization);
    activated = true;
  };
  const deps = {getClerk: async () => auth, fetcher: async () => {
    assert.ok(activated);
    return {ok: true, json: async () => ({signed_in: true})};
  }};
  const message = {type: 'sign-in', identifier: 'invented-user', password: 'invented-password'};
  assert.equal((await handleMessage(message, sender, deps)).state, 'connected');
  auth.client.signIn.create = async () => ({status: 'needs_second_factor'});
  assert.equal((await handleMessage(message, sender, deps)).state, 'sign_in_step_required');
  auth.signOut = async () => {auth.session = null;};
  assert.equal((await handleMessage({type: 'sign-out'}, sender, deps)).state, 'sign_in_required');
  assert.equal((await handleMessage({type: 'connect'}, sender, deps)).state, 'sign_in_required');
});
