import assert from 'node:assert/strict';
import test from 'node:test';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

const directory = process.env.COSMAS_DESKTOP_COMPOSED;
if (!directory) throw new Error('Set COSMAS_DESKTOP_COMPOSED to the isolated composed app directory.');
const source = filename => import(pathToFileURL(resolve(directory, filename)).href);
const security = await source('scribe-security.mjs');
const assets = await source('static-assets.mjs');
const diagnostics = await source('scribe-diagnostics.mjs');

test('reused window stays sandboxed without Node, devtools, webviews or insecure content', () => {
  const options = security.createSecureBrowserWindowOptions('/invented/preload.cjs');
  assert.equal(options.webPreferences.sandbox, true);
  assert.equal(options.webPreferences.contextIsolation, true);
  assert.equal(options.webPreferences.nodeIntegration, false);
  assert.equal(options.webPreferences.webSecurity, true);
  assert.equal(options.webPreferences.devTools, false);
  assert.equal(options.webPreferences.webviewTag, false);
  assert.equal(options.webPreferences.allowRunningInsecureContent, false);
  assert.match(security.RENDERER_CONTENT_SECURITY_POLICY, /connect-src 'self'/);
});

test('reused boundary denies external navigation, new windows, permissions and downloads', () => {
  const handlers = new Map();
  const port = {session: {webRequest: {onHeadersReceived: handler => handlers.set('headers', handler)},
    setPermissionRequestHandler: handler => handlers.set('permission', handler),
    setPermissionCheckHandler: handler => handlers.set('check', handler),
    on: (name, handler) => handlers.set(name, handler)},
    on: (name, handler) => handlers.set(name, handler),
    setWindowOpenHandler: handler => handlers.set('window', handler)};
  security.installElectronRendererSecurity(port, 'app://cosmas/index.html');
  assert.deepEqual(handlers.get('window')(), {action: 'deny'});
  assert.equal(handlers.get('check')(), false);
  let allowed;
  handlers.get('permission')(null, 'media', value => { allowed = value; }, {});
  assert.equal(allowed, false);
  for (const [name, destination] of [['will-navigate', 'https://outside.invalid'],
    ['will-redirect', 'app://other/index.html'], ['will-attach-webview'], ['will-download']]) {
    let blocked = false;
    handlers.get(name)({preventDefault: () => { blocked = true; }}, destination);
    assert.equal(blocked, true, name);
  }
});

test('only manifested static assets resolve; traversal, credentials and query URLs fail', () => {
  assert.equal(assets.resolveStaticAsset('app://cosmas/index.html', directory).path,
    resolve(directory, 'public/index.html'));
  for (const url of ['file:///private/data', 'https://cosmas/index.html', 'app://user@cosmas/index.html',
    'app://cosmas/index.html?query=private', 'app://cosmas/../main.mjs', 'app://cosmas/%2e%2e/main.mjs',
    'app://cosmas/public/index.html', 'app://cosmas/api/workspaces']) {
    assert.equal(assets.resolveStaticAsset(url, directory), null, url);
  }
});

test('reused diagnostic policy rejects inspect and network logging', () => {
  assert.throws(() => diagnostics.enforceNoPhiDiagnosticPolicy({hasSwitch: () => false}, ['--inspect'], []));
  assert.throws(() => diagnostics.enforceNoPhiDiagnosticPolicy({hasSwitch: name => name === 'log-net-log'}, [], []));
  diagnostics.enforceNoPhiDiagnosticPolicy({hasSwitch: () => false}, [], []);
});
