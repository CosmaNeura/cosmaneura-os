// @vitest-environment node
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {renderBetaNginx} from './render-beta-nginx.mjs';
import {resolveBetaFeatureProfile} from '../../clients/shared/beta-feature-profile.mjs';
// Keep these filesystem assertions runnable by both repository test runners.
const {test}=await import(process.env.VITEST?'vitest':'node:test');
const template=readFileSync(new URL('../nginx.conf',import.meta.url),'utf8');
const env={VITE_WORKSPACE_FEATURE_PROFILE:'operational-beta-v1',VITE_WORKSPACE_HOSTED_CLIENT:'web',
  VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',
  VITE_API_BASE:'https://api.example.invalid',VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',
  VITE_COSMANEURA_WEB_ORIGIN:'https://core.example.invalid',VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid',
  VITE_WORKSPACE_CAPTURE_MODE:'browser_microphone',VITE_CLERK_PUBLISHABLE_KEY:'pk_test_fixture'};
const manifest=resolveBetaFeatureProfile(env).manifest;
test('the actual web template allows only self microphone for the selected browser source',()=>{
  assert.equal(renderBetaNginx(template,manifest),template.replace('microphone=()','microphone=(self)'));
});
test('synthetic builds preserve the original microphone denial',()=>{
  assert.equal(renderBetaNginx(template,resolveBetaFeatureProfile({...env,VITE_WORKSPACE_CAPTURE_MODE:'synthetic'}).manifest),template);
});
test('missing features, foreign clients and conflicting headers cannot generate a permissive policy',()=>{
  for(const item of [null,{...manifest,enabledFlags:[]},{...manifest,athenaAccess:'write'},
    {...manifest,client:'apple'},{...manifest,unexpected:'field'}])assert.throws(()=>renderBetaNginx(template,item));
  for(const text of [template.replace('microphone=()','microphone=*'),template+'\nadd_header Permissions-Policy "microphone=*";']){
    assert.throws(()=>renderBetaNginx(text,manifest));
  }
});
