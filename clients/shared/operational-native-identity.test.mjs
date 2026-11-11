import assert from 'node:assert/strict';
import test from 'node:test';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import * as shared from './operational-native-identity.mjs';
import * as desktop from '../desktop/native-identity-config.mjs';
import {exactHostedOrigin} from './hosted-workspace-config.mjs';
import {exactHostedApiOrigin} from '../desktop/hosted-auth-http.mjs';

test('desktop retains exactly the shared operational identity contract',()=>{
  assert.deepEqual(Object.keys(desktop).sort(),Object.keys(shared).sort());
  for(const name of Object.keys(shared))assert.equal(desktop[name],shared[name],name);
  for(const value of [undefined,null,'','https://api.example.invalid','https://a.staging.cosmas.ai',
    'https://api.example.invalid:443','https://api.example.invalid/','https://api.example.invalid/path',
    'https://user@api.example.invalid','https://api.example.invalid?','https://api.example.invalid#',
    'https://127.0.0.1','https://host.localhost','https://UPPER.example.invalid',
    'http://api.example.invalid','https://api.*.example.invalid']) {
    assert.equal(exactHostedOrigin(value),exactHostedApiOrigin(value),String(value));
  }
});

test('registered profile and shared identity bundle for an actual browser without Node modules',async()=>{
  const require=createRequire(new URL('../../web/package.json',import.meta.url));
  const viteRequire=createRequire(require.resolve('vite'));
  const {build}=viteRequire('esbuild');
  const result=await build({entryPoints:[fileURLToPath(new URL('./native-practice-profile.mjs',import.meta.url))],
    bundle:true,platform:'browser',format:'esm',write:false,metafile:true,logLevel:'silent'});
  assert.equal(result.outputFiles.length,1);
  assert.ok(result.outputFiles[0].contents.length>0);
  assert.ok(Object.keys(result.metafile.inputs).some(path=>path.endsWith('operational-native-identity.mjs')));
  assert.ok(Object.keys(result.metafile.inputs).every(path=>!path.includes('clients/desktop/')));
  assert.ok(Object.values(result.metafile.inputs).every(input=>input.imports.every(item=>!item.path.startsWith('node:'))));
});

function pkForHost(hostname, prefix) {
  return prefix + Buffer.from(hostname + '$').toString('base64');
}

test('*.synthetic.example is accepted for staging and rejected for production', () => {
  const frontendOrigin = 'https://clerk.synthetic.example';
  const apiOrigin = 'https://api.synthetic.example';
  const hostname = 'clerk.synthetic.example';
  const staging = shared.validateOperationalNativeIdentity({
    version: 1,
    profile: shared.STAGING_NATIVE_PROFILE,
    client: 'apple',
    apiOrigin,
    publishableKey: pkForHost(hostname, 'pk_test_'),
    frontendOrigin,
    organizationId: 'org_synthetic_iphone_sim',
    audience: '',
  }, 'apple', apiOrigin);
  assert.equal(staging.frontendOrigin, frontendOrigin);
  assert.throws(
    () => shared.validateOperationalNativeIdentity({
      version: 1,
      profile: shared.OPERATIONAL_NATIVE_PROFILE,
      client: 'apple',
      apiOrigin,
      publishableKey: pkForHost(hostname, 'pk_live_'),
      frontendOrigin,
      organizationId: 'org_synthetic_iphone_sim',
      audience: 'cosmas-os-beta-api',
    }, 'apple', apiOrigin),
    /incomplete or inconsistent/,
  );
});
