import test from 'node:test';
import assert from 'node:assert/strict';
import {workspaceIdentityInputs} from './prepare-workspace-identity.mjs';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';
import {validateOperationalReleaseProfile} from './package-desktop-release.mjs';

const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
  frontendOrigin:'https://identity.example.invalid',publishableKey:'pk_live_'+btoa('identity.example.invalid$'),
  organizationId:'org_invented_profile_test',audience:'cosmas-beta-api'};
const options={webOrigin:'https://workspace.example.invalid',coreWebOrigin:'https://core.example.invalid',
  captureUploadOrigins:['https://uploads.example.invalid']};
const info={CFBundleIdentifier:'com.cosmasos.beta.desktop',CFBundleShortVersionString:'0.1.0',CFBundleVersion:'1'};

for(const dataMode of ['synthetic','authorized_beta']) {
  test(`release validation retains operational identity for ${dataMode} and rejects inconsistent manifests`,()=>{
    const files=workspaceIdentityInputs(identity,{...options,dataMode});
    const manifest=resolveBetaFeatureProfile(files['desktop-build-env.json']).manifest;
    const config={mode:'hosted-beta-authenticated',dataMode,apiOrigin:identity.apiOrigin,nativeIdentity:identity,
      appVersion:'0.1.0',buildNumber:'1',installation:{bundleIdentifier:info.CFBundleIdentifier}};
    assert.deepEqual(validateOperationalReleaseProfile(config,manifest,info),identity);
    for(const changed of [
      {...config,dataMode:dataMode==='synthetic'?'authorized_beta':'synthetic'},
      {...config,dataMode:undefined}, {...config,nativeIdentity:undefined},
      {...config,nativeIdentity:{...identity,publishableKey:'pk_test_invented'}},
      {...config,apiOrigin:'https://other.example.invalid'},
      {...config,nativeIdentity:{...identity,frontendOrigin:'https://other.example.invalid'}},
      {...config,buildNumber:'2'},
    ]) assert.throws(()=>validateOperationalReleaseProfile(changed,manifest,info));
    assert.throws(()=>validateOperationalReleaseProfile(config,{...manifest,dataMode:'unknown'},info));
  });
}
