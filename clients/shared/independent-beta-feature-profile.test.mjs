import test from 'node:test';
import assert from 'node:assert/strict';
import {INDEPENDENT_BETA_FEATURE_PROFILE,INDEPENDENT_BETA_FEATURE_FLAGS,STANDALONE_FEATURE_PROFILE,
  REVIEWED_CORE_CAPTURE_ORIGIN,resolveBetaFeatureProfile,validateBetaFeatureManifest,validateNativeBetaProfile} from './beta-feature-profile.mjs';
import {workspaceIdentityInputs} from '../../scripts/prepare-workspace-identity.mjs';

const apiOrigin='https://api.example.invalid';
const common={VITE_WORKSPACE_FEATURE_PROFILE:INDEPENDENT_BETA_FEATURE_PROFILE,
  VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_API_ORIGIN:apiOrigin,
  VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',VITE_CLERK_PUBLISHABLE_KEY:'pk_test_invented_fixture',
  VITE_WORKSPACE_ORGANIZATION_ID:'org_invented_beta',VITE_COSMANEURA_WEB_ORIGIN:REVIEWED_CORE_CAPTURE_ORIGIN,
  // Staging independent-beta: CosmaBot API origin only (S2S ciphertext proxy).
  VITE_CAPTURE_UPLOAD_ORIGINS:apiOrigin,VITE_WORKSPACE_CAPTURE_MODE:'browser_microphone'};
const input=client=>({...common,VITE_WORKSPACE_HOSTED_CLIENT:client,
  VITE_API_BASE:client==='desktop'?'app://cosmas/api':common.VITE_WORKSPACE_HOSTED_API_ORIGIN,
  VITE_WORKSPACE_WEB_ORIGIN:client==='web'?common.VITE_WORKSPACE_WEB_ORIGIN:'',
  VITE_WORKSPACE_CAPTURE_MODE:client==='apple'?'ios_native':'browser_microphone'});

test('main independent beta exposes Chief, Google and Core capture while keeping other platform services dark',()=>{
  for(const client of ['web','desktop','apple']){
    const {env,manifest}=resolveBetaFeatureProfile(input(client));
    assert.deepEqual(manifest.enabledFlags,[...INDEPENDENT_BETA_FEATURE_FLAGS]);
    assert.equal(env.VITE_MESSAGES_ENABLED,'true');
    assert.equal(env.VITE_WORKSPACE_CAPTURE_ENABLED,'true');
    assert.equal(env.VITE_WORKSPACE_CAPTURE_NOTES_ENABLED,'true');
    assert.equal(manifest.platformAccess,'disabled');
    assert.equal(manifest.captureMode,client==='apple'?'ios_native':'browser_microphone');
    assert.equal(manifest.coreWebOrigin,REVIEWED_CORE_CAPTURE_ORIGIN);
    assert.deepEqual(manifest.captureUploadOrigins,[apiOrigin]);
    assert.equal(env.VITE_CAPTURE_UPLOAD_ORIGINS,apiOrigin);
    for(const flag of ['VITE_CORE_CONNECTION_ENABLED','VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED',
      'VITE_WORKSPACE_SCHEDULING_ENABLED','VITE_EHR_READ_ENABLED','VITE_WORKSPACE_CAPTURE_CORRECTIONS_ENABLED',
      'VITE_WORKSPACE_CAPTURE_RECOVERY_ENABLED','VITE_WORKSPACE_PREP_ENABLED'])assert.equal(env[flag],'false');
    assert.equal(validateBetaFeatureManifest(manifest),manifest);
    if(client==='desktop')assert.equal(validateNativeBetaProfile(manifest,{client,apiOrigin,
      coreWebOrigin:REVIEWED_CORE_CAPTURE_ORIGIN,captureUploadOrigins:[apiOrigin],
      microphoneCapture:true,renewableNativeCapture:true,nativeRendererRecovery:true}),manifest);
    if(client==='apple')assert.equal(validateNativeBetaProfile(manifest,{client,apiOrigin,
      coreWebOrigin:REVIEWED_CORE_CAPTURE_ORIGIN,captureUploadOrigins:[apiOrigin],
      renewableNativeCapture:true,nativeRendererRecovery:true,simulatorCustody:true}),manifest);
  }
});

test('independent beta refuses broadening, wrong Core origin, blob upload origins and misleading feature manifests',()=>{
  for(const change of [{VITE_CORE_CONNECTION_ENABLED:'true'},{VITE_WORKSPACE_MICROSOFT_CONNECTION_ENABLED:'true'},
    {VITE_WORKSPACE_SCHEDULING_ENABLED:'true'},{VITE_EHR_READ_ENABLED:'true'},{VITE_WORKSPACE_DATA_MODE:'authorized_beta'},
    {VITE_WORKSPACE_ORGANIZATION_ID:undefined},{VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED:'false'},
    {VITE_WORKSPACE_CAPTURE_ENABLED:'false'},{VITE_COSMANEURA_WEB_ORIGIN:'https://app.cosmaneura.com'},
    {VITE_COSMANEURA_WEB_ORIGIN:'https://core.example.invalid'},{VITE_WORKSPACE_CAPTURE_MODE:'disabled'},
    // Empty upload origins are forced to the CosmaBot API origin; non-API values conflict.
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://api.assemblyai.com'},
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://cosmaneurastaginguploads.blob.core.windows.net'},
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid'}])
    assert.throws(()=>resolveBetaFeatureProfile({...input('web'),...change}));
  const m=resolveBetaFeatureProfile(input('web')).manifest;
  assert.throws(()=>validateBetaFeatureManifest({...m,enabledFlags:m.enabledFlags.filter(s=>s!=='VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED')}));
  assert.throws(()=>validateBetaFeatureManifest({...m,enabledFlags:[...m.enabledFlags,'VITE_EHR_READ_ENABLED']}));
  assert.throws(()=>validateBetaFeatureManifest({...m,profile:STANDALONE_FEATURE_PROFILE}));
});

test('public identity preparation carries independent Core capture into all three actual builds',()=>{
  const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.com',
    publishableKey:'pk_live_'+Buffer.from('clerk.example.com$').toString('base64'),frontendOrigin:'https://clerk.example.com',
    organizationId:'org_invented_beta',audience:'cosmas-os-beta-api'};
  const files=workspaceIdentityInputs(identity,{webOrigin:'https://workspace.example.com',
    coreWebOrigin:REVIEWED_CORE_CAPTURE_ORIGIN,captureUploadOrigins:[identity.apiOrigin],
    dataMode:'synthetic',featureProfile:INDEPENDENT_BETA_FEATURE_PROFILE});
  for(const client of ['web','desktop','apple']){
    const env=files[client+'-build-env.json'];assert.equal(env.VITE_WORKSPACE_FEATURE_PROFILE,INDEPENDENT_BETA_FEATURE_PROFILE);
    assert.equal(env.VITE_MESSAGES_ENABLED,'true');assert.equal(env.VITE_WORKSPACE_GOOGLE_CALENDAR_ENABLED,'true');
    assert.equal(env.VITE_WORKSPACE_CAPTURE_ENABLED,'true');
    assert.equal(env.VITE_COSMANEURA_WEB_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
    assert.equal(env.VITE_CAPTURE_UPLOAD_ORIGINS,identity.apiOrigin);
    assert.equal(env.VITE_WORKSPACE_CAPTURE_MODE,client==='apple'?'ios_native':'browser_microphone');
  }
  assert.equal(files['web-build-arguments.json'].VITE_WORKSPACE_FEATURE_PROFILE,INDEPENDENT_BETA_FEATURE_PROFILE);
  assert.equal(files['web-build-arguments.json'].VITE_COSMANEURA_WEB_ORIGIN,REVIEWED_CORE_CAPTURE_ORIGIN);
  assert.equal(files['identity-bindings.json'].native_bundles.apple,'com.cosmasos.beta.ios');
  assert.equal(files['identity-bindings.json'].platform_access,'disabled');
  assert.equal(files['identity-bindings.json'].core_web_origin,REVIEWED_CORE_CAPTURE_ORIGIN);
});
