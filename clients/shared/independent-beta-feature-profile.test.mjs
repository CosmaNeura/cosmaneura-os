import test from 'node:test';
import assert from 'node:assert/strict';
import {INDEPENDENT_BETA_FEATURE_PROFILE,INDEPENDENT_BETA_FEATURE_FLAGS,STANDALONE_FEATURE_PROFILE,
  resolveBetaFeatureProfile,validateBetaFeatureManifest,validateNativeBetaProfile} from './beta-feature-profile.mjs';
import {workspaceIdentityInputs} from '../../scripts/prepare-workspace-identity.mjs';
const common={VITE_WORKSPACE_FEATURE_PROFILE:INDEPENDENT_BETA_FEATURE_PROFILE,
  VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',
  VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',VITE_CLERK_PUBLISHABLE_KEY:'pk_test_invented_fixture',
  VITE_WORKSPACE_ORGANIZATION_ID:'org_invented_beta',VITE_COSMANEURA_WEB_ORIGIN:'',VITE_CAPTURE_UPLOAD_ORIGINS:'',
  VITE_WORKSPACE_CAPTURE_MODE:'disabled'};
const input=client=>({...common,VITE_WORKSPACE_HOSTED_CLIENT:client,
  VITE_API_BASE:client==='desktop'?'app://cosmas/api':common.VITE_WORKSPACE_HOSTED_API_ORIGIN,
  VITE_WORKSPACE_WEB_ORIGIN:client==='web'?common.VITE_WORKSPACE_WEB_ORIGIN:''});
test('main independent beta exposes Chief and Google while preserving platform isolation across clients',()=>{
  for(const client of ['web','desktop','apple']){
    const {env,manifest}=resolveBetaFeatureProfile(input(client));
    assert.deepEqual(manifest.enabledFlags,[...INDEPENDENT_BETA_FEATURE_FLAGS]);
    assert.equal(env.VITE_MESSAGES_ENABLED,'true');
    assert.equal(manifest.platformAccess,'disabled');assert.equal(manifest.captureMode,'disabled');
    assert.equal(manifest.coreWebOrigin,'');assert.deepEqual(manifest.captureUploadOrigins,[]);
    for(const flag of ['VITE_CORE_CONNECTION_ENABLED','VITE_WORKSPACE_CAPTURE_ENABLED',
      'VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED','VITE_WORKSPACE_SCHEDULING_ENABLED','VITE_EHR_READ_ENABLED'])assert.equal(env[flag],'false');
    assert.equal(validateBetaFeatureManifest(manifest),manifest);
    if(client!=='web')assert.equal(validateNativeBetaProfile(manifest,{client,apiOrigin:common.VITE_WORKSPACE_HOSTED_API_ORIGIN,
      coreWebOrigin:'',captureUploadOrigins:[],microphoneCapture:false}),manifest);
  }
});
test('independent beta refuses broadening and misleading or partial feature manifests',()=>{
  for(const change of [{VITE_CORE_CONNECTION_ENABLED:'true'},{VITE_WORKSPACE_CAPTURE_ENABLED:'true'},
    {VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED:'true'},{VITE_WORKSPACE_SCHEDULING_ENABLED:'true'},
    {VITE_EHR_READ_ENABLED:'true'},{VITE_WORKSPACE_DATA_MODE:'authorized_beta'},
    {VITE_WORKSPACE_ORGANIZATION_ID:undefined},{VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED:'false'}])
    assert.throws(()=>resolveBetaFeatureProfile({...input('web'),...change}));
  const m=resolveBetaFeatureProfile(input('web')).manifest;
  assert.throws(()=>validateBetaFeatureManifest({...m,enabledFlags:m.enabledFlags.filter(s=>s!=='VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED')}));
  assert.throws(()=>validateBetaFeatureManifest({...m,enabledFlags:[...m.enabledFlags,'VITE_EHR_READ_ENABLED']}));
  assert.throws(()=>validateBetaFeatureManifest({...m,profile:STANDALONE_FEATURE_PROFILE}));
});
test('public identity preparation carries the main independent profile into all three actual builds',()=>{
  const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.com',
    publishableKey:'pk_live_'+Buffer.from('clerk.example.com$').toString('base64'),frontendOrigin:'https://clerk.example.com',
    organizationId:'org_invented_beta',audience:'cosmas-os-beta-api'};
  const files=workspaceIdentityInputs(identity,{webOrigin:'https://workspace.example.com',coreWebOrigin:'',captureUploadOrigins:[],
    dataMode:'synthetic',featureProfile:INDEPENDENT_BETA_FEATURE_PROFILE});
  for(const client of ['web','desktop','apple']){
    const env=files[client+'-build-env.json'];assert.equal(env.VITE_WORKSPACE_FEATURE_PROFILE,INDEPENDENT_BETA_FEATURE_PROFILE);
    assert.equal(env.VITE_MESSAGES_ENABLED,'true');assert.equal(env.VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED,'true');
    assert.equal(env.VITE_WORKSPACE_CAPTURE_ENABLED,'false');
  }
  assert.equal(files['web-build-arguments.json'].VITE_WORKSPACE_FEATURE_PROFILE,INDEPENDENT_BETA_FEATURE_PROFILE);
  assert.equal(files['identity-bindings.json'].native_bundles.apple,'com.cosmasos.beta.ios');
  assert.equal(files['identity-bindings.json'].platform_access,'disabled');
});
