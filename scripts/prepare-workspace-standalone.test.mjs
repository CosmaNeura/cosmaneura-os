import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,readFile,rm,stat} from 'node:fs/promises';
import {spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {workspaceIdentityInputs} from './prepare-workspace-identity.mjs';
import {STANDALONE_FEATURE_PROFILE,validateBetaFeatureManifest} from '../clients/shared/beta-feature-profile.mjs';

const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
  publishableKey:'pk_live_'+Buffer.from('identity.example.invalid$').toString('base64'),
  frontendOrigin:'https://identity.example.invalid',organizationId:'org_invented_standalone',audience:'cosmabot-standalone-api'};
const options={webOrigin:'https://workspace.example.invalid',coreWebOrigin:'',captureUploadOrigins:[],dataMode:'synthetic',featureProfile:STANDALONE_FEATURE_PROFILE};
const script=fileURLToPath(new URL('./prepare-workspace-identity.mjs',import.meta.url));

test('standalone preparation emits every client and hosted build argument under the same closed profile',()=>{
  const files=workspaceIdentityInputs(identity,options),proof=files['standalone-profile.json'];
  for(const client of ['web','desktop','apple']){
    const env=files[client+'-build-env.json'];
    assert.equal(env.VITE_WORKSPACE_FEATURE_PROFILE,STANDALONE_FEATURE_PROFILE);
    assert.equal(env.VITE_WORKSPACE_CAPTURE_MODE,'disabled');assert.equal(env.VITE_COSMANEURA_WEB_ORIGIN,'');
    assert.equal(env.VITE_CAPTURE_UPLOAD_ORIGINS,'');assert.equal(env.VITE_CORE_CONNECTION_ENABLED,'false');
    assert.equal(env.VITE_WORKSPACE_AUTHENTICATED_ENABLED,'true');
    assert.equal(env.VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED,'false');assert.equal(env.VITE_MESSAGES_ENABLED,'true');
    assert.equal(env.VITE_CONNECTION_ONBOARDING_ENABLED,'true');
    assert.equal(validateBetaFeatureManifest(proof.clients[client]),proof.clients[client]);
  }
  assert.equal(files['web-build-arguments.json'].VITE_WORKSPACE_FEATURE_PROFILE,STANDALONE_FEATURE_PROFILE);
  assert.equal(files['web-build-arguments.json'].VITE_WORKSPACE_CAPTURE_MODE,'disabled');
  assert.equal(files['web-build-arguments.json'].VITE_MESSAGES_ENABLED,'true');
  assert.equal(files['identity-bindings.json'].native_feature_profile,STANDALONE_FEATURE_PROFILE);
  assert.equal(files['identity-bindings.json'].core_web_origin,'');
  assert.equal(proof.identity_sha256,files['identity-bindings.json'].identity_sha256);
  assert.equal(proof.dedicated_resource_ownership_verified,false);assert.equal(proof.activation_authorized,false);
  assert.deepEqual(files['desktop-identity.json'],identity);
});

test('standalone public preparation does not hide conflicting inputs or promote data/identity',()=>{
  for(const change of [{coreWebOrigin:'https://app.cosmaneura.com'},
    {coreWebOrigin:'https://staging-app.cosmaneura.com'},{captureUploadOrigins:['https://uploads.example.invalid']},
    {dataMode:'authorized_beta'},{dataMode:undefined},{nativeFeatureProfile:'first-owner-staging-v1'},
    {featureProfile:'unknown'},{webOrigin:'https://app.cosmaneura.com'}])
    assert.throws(()=>workspaceIdentityInputs(identity,{...options,...change}));
  assert.throws(()=>workspaceIdentityInputs({...identity,apiOrigin:'https://staging-app.cosmaneura.com'},options));
  assert.throws(()=>workspaceIdentityInputs({...identity,organizationId:''},options));
  assert.throws(()=>workspaceIdentityInputs({...identity,publishableKey:'pk_live_wrong'},options));
});

test('standalone CLI accepts no Core/upload arguments and refuses ambiguous selection before writing',async t=>{
  const root=await mkdtemp(join(tmpdir(),'cosmabot-standalone-public-'));t.after(()=>rm(root,{recursive:true,force:true}));
  const path=join(root,'identity.json');await writeFile(path,JSON.stringify(identity));
  const args=['--identity',path,'--web-origin',options.webOrigin,'--data-mode','synthetic','--feature-profile',STANDALONE_FEATURE_PROFILE];
  const output=join(root,'good');
  const result=spawnSync(process.execPath,[script,...args,'--output',output],{encoding:'utf8'});
  assert.equal(result.status,0,result.stderr);
  assert.equal(JSON.parse(result.stdout).feature_profile,STANDALONE_FEATURE_PROFILE);
  assert.equal(JSON.parse(await readFile(join(output,'web-build-env.json'),'utf8')).VITE_WORKSPACE_FEATURE_PROFILE,STANDALONE_FEATURE_PROFILE);
  const retained=await readFile(join(output,'standalone-profile.json'),'utf8');
  assert.notEqual(spawnSync(process.execPath,[script,...args,'--output',output],{encoding:'utf8'}).status,0);
  assert.equal(await readFile(join(output,'standalone-profile.json'),'utf8'),retained);
  let index=0;
  for(const extra of [['--core-web-origin','https://app.cosmaneura.com'],
    ['--capture-upload-origin','https://uploads.example.invalid'],['--native-feature-profile','operational-beta-v1'],
    ['--feature-profile',STANDALONE_FEATURE_PROFILE],['--unknown','value']]){
    const rejected=join(root,'reject-'+index++);
    const invalid=spawnSync(process.execPath,[script,...args,...extra,'--output',rejected],{encoding:'utf8'});
    assert.notEqual(invalid.status,0);await assert.rejects(()=>stat(rejected),{code:'ENOENT'});
  }
  const omitted=join(root,'missing-mode');
  const missing=args.filter((_,index)=>index!==4&&index!==5);
  assert.notEqual(spawnSync(process.execPath,[script,...missing,'--output',omitted],{encoding:'utf8'}).status,0);
  await assert.rejects(()=>stat(omitted),{code:'ENOENT'});
});
