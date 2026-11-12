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

test('production profile accepts only clerk.beta.cosmas.ai and staging rejects production hosts',()=>{
  const liveKey=host=>'pk_live_'+Buffer.from(host+'$').toString('base64');
  for (const client of ['apple','desktop']) {
    const production={
      version:1,profile:shared.PRODUCTION_NATIVE_PROFILE,client,
      apiOrigin:'https://api.beta.cosmas.ai',
      frontendOrigin:'https://clerk.beta.cosmas.ai',
      publishableKey:liveKey('clerk.beta.cosmas.ai'),
      organizationId:'org_invented_beta',audience:'cosmas-os-beta-api',
    };
    assert.deepEqual(shared.validateOperationalNativeIdentity(production,client,production.apiOrigin),production);
    assert.equal(shared.operationalNativeAuthSettings(production).frontendOrigin,'https://clerk.beta.cosmas.ai');
    assert.equal(shared.validateOperationalNativeDataMode('authorized_beta',production),'authorized_beta');
    for (const changed of [
      {frontendOrigin:'https://clerk.cosmas.ai',publishableKey:liveKey('clerk.cosmas.ai')},
      {frontendOrigin:'https://clerk.staging.cosmas.ai',publishableKey:liveKey('clerk.staging.cosmas.ai')},
      {frontendOrigin:'https://invented.clerk.accounts.dev',publishableKey:'pk_test_'+Buffer.from('invented.clerk.accounts.dev$').toString('base64')},
      {frontendOrigin:'https://preview.clerk.beta.cosmas.ai',publishableKey:liveKey('preview.clerk.beta.cosmas.ai')},
      {frontendOrigin:'https://clerk.example.invalid',publishableKey:liveKey('clerk.example.invalid')},
      {audience:''},{profile:'unknown-profile-v1'},
    ]) assert.throws(()=>shared.validateOperationalNativeIdentity({...production,...changed},client,production.apiOrigin));

    // I1: production-review accepts only api.beta.cosmas.ai; invented/wrong API origins fail.
    for (const wrongApi of [
      'https://api.example.invalid',
      'https://api.cosmas.ai',
      'https://api.staging.cosmas.ai',
      'https://enrollment-api.cosmas.ai',
    ]) {
      const bad={...production,apiOrigin:wrongApi};
      assert.throws(()=>shared.validateOperationalNativeIdentity(bad,client,wrongApi));
      assert.throws(()=>shared.validateOperationalNativeIdentity(production,client,wrongApi));
    }

    const staging={
      version:1,profile:shared.STAGING_NATIVE_PROFILE,client,
      apiOrigin:'https://api.staging.cosmas.ai',
      frontendOrigin:'https://clerk.staging.cosmas.ai',
      publishableKey:liveKey('clerk.staging.cosmas.ai'),
      organizationId:'org_invented_beta',audience:'cosmas-os-beta-api',
    };
    assert.deepEqual(shared.validateOperationalNativeIdentity(staging,client,staging.apiOrigin),staging);
    for (const changed of [
      {frontendOrigin:'https://clerk.beta.cosmas.ai',publishableKey:liveKey('clerk.beta.cosmas.ai')},
      {frontendOrigin:'https://clerk.cosmas.ai',publishableKey:liveKey('clerk.cosmas.ai')},
    ]) assert.throws(()=>shared.validateOperationalNativeIdentity({...staging,...changed},client,staging.apiOrigin));

    const beta={
      version:1,profile:shared.OPERATIONAL_NATIVE_PROFILE,client,
      apiOrigin:'https://api.example.invalid',
      frontendOrigin:'https://clerk.cosmas.ai',
      publishableKey:liveKey('clerk.cosmas.ai'),
      organizationId:'org_invented_beta',audience:'cosmas-os-beta-api',
    };
    assert.deepEqual(shared.validateOperationalNativeIdentity(beta,client,beta.apiOrigin),beta);
    for (const changed of [
      {frontendOrigin:'https://clerk.beta.cosmas.ai',publishableKey:liveKey('clerk.beta.cosmas.ai')},
      {frontendOrigin:'https://clerk.staging.cosmas.ai',publishableKey:liveKey('clerk.staging.cosmas.ai')},
      {frontendOrigin:'https://clerk.example.invalid',publishableKey:liveKey('clerk.example.invalid')},
      {frontendOrigin:'https://clerk.cosmaneura.com',publishableKey:liveKey('clerk.cosmaneura.com')},
    ]) assert.throws(()=>shared.validateOperationalNativeIdentity({...beta,...changed},client,beta.apiOrigin));
  }
});
