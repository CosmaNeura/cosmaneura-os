import test from 'node:test';
import assert from 'node:assert/strict';
import {workspaceIdentityInputs} from './prepare-workspace-identity.mjs';
import {validateOperationalReleaseProfile} from './package-desktop-release.mjs';

test('standalone release permits independent account configuration while refusing native capture or Core navigation',()=>{
  const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
    frontendOrigin:'https://identity.example.invalid',publishableKey:'pk_live_'+Buffer.from('identity.example.invalid$').toString('base64'),
    organizationId:'org_invented_standalone',audience:'cosmabot-standalone-api'};
  const files=workspaceIdentityInputs(identity,{webOrigin:'https://workspace.example.invalid',coreWebOrigin:'',captureUploadOrigins:[],
    dataMode:'synthetic',featureProfile:'standalone-practice-v1'});
  const manifest=files['standalone-profile.json'].clients.desktop;
  const info={CFBundleIdentifier:'com.cosmasos.beta.desktop',CFBundleShortVersionString:'0.1.51',CFBundleVersion:'1051'};
  const config={nativeIdentity:identity,mode:'hosted-beta-authenticated',dataMode:'synthetic',apiOrigin:identity.apiOrigin,
    appVersion:info.CFBundleShortVersionString,buildNumber:info.CFBundleVersion,
    installation:{bundleIdentifier:info.CFBundleIdentifier},nativeCaptureEnabled:false,microphoneCaptureEnabled:false,
    cosmaneuraWebOrigin:'',captureUploadOrigins:[],googleConnectionClientId:'invented.apps.googleusercontent.com',
    googleConnectionCallbackUri:identity.apiOrigin+'/connections/google/callback'};
  assert.deepEqual(validateOperationalReleaseProfile(config,manifest,info),identity);
  for(const changed of [{nativeCaptureEnabled:true},{nativeCaptureEnabled:undefined},{microphoneCaptureEnabled:true},
    {cosmaneuraWebOrigin:'https://app.cosmaneura.com'},{captureUploadOrigins:['https://uploads.example.invalid']}])
    assert.throws(()=>validateOperationalReleaseProfile({...config,...changed},manifest,info));
});
