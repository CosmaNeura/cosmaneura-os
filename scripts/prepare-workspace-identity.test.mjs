import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm,symlink} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {workspaceIdentityInputs,prepareWorkspaceIdentity,identityDigest} from './prepare-workspace-identity.mjs';

const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
  publishableKey:'pk_live_'+Buffer.from('identity.example.invalid$').toString('base64'),
  frontendOrigin:'https://identity.example.invalid',organizationId:'org_w75_invented',audience:'cosmas-beta-api'};
const options={webOrigin:'https://workspace.example.invalid',coreWebOrigin:'https://core.example.invalid',captureUploadOrigins:['https://uploads.example.invalid']};

test('shared development identity produces all clients only with explicit synthetic data',()=>{
  const staging={...identity,profile:'operational-staging-v1',audience:'',frontendOrigin:'https://invented.clerk.accounts.dev',
    publishableKey:'pk_test_'+Buffer.from('invented.clerk.accounts.dev$').toString('base64')};
  const files=workspaceIdentityInputs(staging,{...options,dataMode:'synthetic'});
  assert.equal(files['identity-bindings.json'].profile,staging.profile);
  for(const client of ['web','desktop','apple']) {
    assert.equal(files[client+'-build-env.json'].VITE_CLERK_PUBLISHABLE_KEY,staging.publishableKey);
    assert.equal(files[client+'-build-env.json'].VITE_WORKSPACE_DATA_MODE,'synthetic');
  }
  assert.equal(files['apple-identity.json'].profile,staging.profile);
  assert.equal('os.identity.tfvars.json' in files,false);
  assert.deepEqual(files['os.runtime-identity.json'],{
    CLERK_SESSION_POLICY:'shared_staging',
    CLERK_ORGANIZATION_ID:staging.organizationId,CLERK_ISSUER:staging.frontendOrigin,
    CLERK_JWKS_URL:staging.frontendOrigin+'/.well-known/jwks.json',CLERK_AUDIENCE:staging.audience,
  });
  assert.throws(()=>workspaceIdentityInputs(staging,options));
  assert.throws(()=>workspaceIdentityInputs(staging,{...options,dataMode:'authorized_beta'}));
});

test('one existing identity creates consistent full web/desktop/iPhone inputs without activation',()=>{
  const files=workspaceIdentityInputs(identity,options);
  assert.equal(Object.keys(files).length,8);
  assert.deepEqual(files['desktop-identity.json'],identity);
  assert.deepEqual(files['apple-identity.json'],{...identity,client:'apple'});
  const os=files['os.identity.tfvars.json'];
  assert.equal('os.runtime-identity.json' in files,false);
  assert.equal(os.clerk_org_id,identity.organizationId);
  assert.equal(os.clerk_jwks_url,identity.frontendOrigin+'/.well-known/jwks.json');
  assert.equal(os.clerk_audience,identity.audience);
  for(const client of ['web','desktop','apple']){
    const env=files[client+'-build-env.json'];
    assert.equal(env.VITE_WORKSPACE_DATA_MODE,'authorized_beta');
    assert.equal(env.VITE_WORKSPACE_HOSTED_API_ORIGIN,identity.apiOrigin);
    assert.equal(env.VITE_CLERK_PUBLISHABLE_KEY,identity.publishableKey);
    assert.equal(env.VITE_WORKSPACE_FEATURE_PROFILE,'operational-beta-v1');
    assert.equal(env.VITE_ATHENA_CONNECTION_ENABLED,'true');
  }
  assert.equal(files['apple-build-env.json'].VITE_WORKSPACE_CAPTURE_MODE,'ios_native');
  assert.equal(files['desktop-build-env.json'].VITE_API_BASE,'app://cosmas/api');
  assert.equal(files['web-build-arguments.json'].VITE_WORKSPACE_WEB_ORIGIN,options.webOrigin);
  for(const key of ['workspace_native_release','deploy_workloads','workspace_hosted_enabled','workspace_apple_enabled','workspace_desktop_enabled'])assert.equal(key in os,false);
  assert.equal(files['identity-bindings.json'].activation_authorized,false);
});

test('public identity mismatch and invalid companion/upload origins are rejected',()=>{
  for(const changed of [{client:'apple'},{publishableKey:'pk_test_x'},{frontendOrigin:'https://other.example.invalid'},
    {apiOrigin:'http://localhost:8000'},{audience:'contains spaces'},{secret:'not accepted'}])
    assert.throws(()=>workspaceIdentityInputs({...identity,...changed},options));
  for(const changed of [{webOrigin:'http://localhost:3000'},{coreWebOrigin:'https://core.example.invalid/path'},
    {captureUploadOrigins:[]},{captureUploadOrigins:['https://uploads.example.invalid','https://uploads.example.invalid']}])
    assert.throws(()=>workspaceIdentityInputs(identity,{...options,...changed}));
});
test('first-owner native staging keeps the real auth identity and leaves full hosted web defaults intact',()=>{
  const files=workspaceIdentityInputs(identity,{...options,dataMode:'synthetic',nativeFeatureProfile:'first-owner-staging-v1'});
  assert.deepEqual(files['desktop-identity.json'],identity);
  for(const client of ['desktop','apple']){
    const env=files[client+'-build-env.json'];
    assert.equal(env.VITE_WORKSPACE_FEATURE_PROFILE,'first-owner-staging-v1');
    assert.equal(env.VITE_WORKSPACE_CAPTURE_MODE,'disabled');
    assert.equal(env.VITE_COSMANEURA_WEB_ORIGIN,'');
    assert.equal(env.VITE_CAPTURE_UPLOAD_ORIGINS,'');
    assert.equal(env.VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED,'false');
  }
  assert.equal(files['web-build-env.json'].VITE_WORKSPACE_FEATURE_PROFILE,'operational-beta-v1');
  assert.equal(files['web-build-env.json'].VITE_WORKSPACE_CAPTURE_ENABLED,'true');
  assert.throws(()=>workspaceIdentityInputs(identity,{...options,nativeFeatureProfile:'first-owner-staging-v1'}));
  assert.throws(()=>workspaceIdentityInputs(identity,{...options,dataMode:'synthetic',nativeFeatureProfile:'unknown'}));
});

test('explicit synthetic staging retains the real-format identity and every account boundary',()=>{
  const files=workspaceIdentityInputs(identity,{...options,dataMode:'synthetic'});
  for(const client of ['web','desktop','apple']){
    assert.equal(files[client+'-build-env.json'].VITE_WORKSPACE_DATA_MODE,'synthetic');
    assert.equal(files[client+'-build-env.json'].VITE_CLERK_PUBLISHABLE_KEY,identity.publishableKey);
    assert.equal(files[client+'-build-env.json'].VITE_WORKSPACE_AUTHENTICATED_ENABLED,'true');
  }
  assert.deepEqual(files['desktop-identity.json'],identity);
  assert.equal(files['identity-bindings.json'].data_mode,'synthetic');
  assert.equal(files['identity-bindings.json'].activation_authorized,false);
  for(const dataMode of [null,'',false,'synth_os','production'])
    assert.throws(()=>workspaceIdentityInputs(identity,{...options,dataMode}));
  for(const changed of [{publishableKey:'pk_test_fixture'},{organizationId:''},{apiOrigin:'http://localhost:8000'}])
    assert.throws(()=>workspaceIdentityInputs({...identity,...changed},{...options,dataMode:'synthetic'}));
});

test('identity digest is key-order independent and changes with review-relevant identity',()=>{
  assert.equal(identityDigest(identity),identityDigest(Object.fromEntries(Object.entries(identity).reverse())));
  assert.notEqual(identityDigest(identity),identityDigest({...identity,audience:'other-api'}));
  assert.match(identityDigest({...identity,audience:'urn:cosmas:<a>&b'}),/^[0-9a-f]{64}$/);
});

test('file preparation refuses duplicate keys and existing output without replacement',async t=>{
  const root=await mkdtemp(join(tmpdir(),'cosmas-w75-identity-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const path=join(root,'identity.json'),output=join(root,'prepared');
  await writeFile(path,JSON.stringify(identity));
  await prepareWorkspaceIdentity({identityPath:path,...options,output});
  assert.deepEqual(JSON.parse(await readFile(join(output,'desktop-identity.json'),'utf8')),identity);
  await assert.rejects(()=>prepareWorkspaceIdentity({identityPath:path,...options,output}));
  await writeFile(path,JSON.stringify(identity).replace('"version":1','"version":1,"version":1'));
  await assert.rejects(()=>prepareWorkspaceIdentity({identityPath:path,...options,output:join(root,'duplicate')}));
  const linked=join(root,'linked');await symlink(path,linked);
  await assert.rejects(()=>prepareWorkspaceIdentity({identityPath:linked,...options,output:join(root,'linked-output')}));
});
