import assert from 'node:assert/strict';
import test from 'node:test';
import {installMicrophonePermissions} from './microphone-permissions.mjs';

function fixture(enabled,admitted=true) {
  let phase='ready', check, request, destroyed=false, url='app://cosmas/index.html';
  const renderer={getURL:()=>url,isDestroyed:()=>destroyed,mainFrame:{url},session:{
    setPermissionCheckHandler:value=>{check=value;},setPermissionRequestHandler:value=>{request=value;}}};
  installMicrophonePermissions(renderer,{snapshot:()=>({phase})},enabled,()=>admitted);
  const details={isMainFrame:true,requestingUrl:url,securityOrigin:'app://cosmas',mediaType:'audio',mediaTypes:['audio']};
  return {renderer,details,setPhase:value=>{phase=value;},destroy:()=>{destroyed=true;},navigate:()=>{url='app://cosmas/other.html';},
    check:(contents=renderer,permission='media',origin='app://cosmas',input=details)=>check(contents,permission,origin,input),
    request:(contents=renderer,permission='media',input=details)=>{
      let result;request(contents,permission,value=>{result=value;},input);return result;
    }};
}
test('microphone remains denied by default, even in the signed-in window',()=>{
  for(const enabled of [undefined,false]){const f=fixture(enabled);assert.equal(f.check(),false);assert.equal(f.request(),false);}
  assert.throws(()=>fixture('true'));
});
test('an enabled current main frame may request only audio',()=>{
  const f=fixture(true);assert.equal(f.check(),true);assert.equal(f.request(),true);
  assert.equal(f.check(f.renderer,'media','app://cosmas/'),true);
  assert.equal(f.check(f.renderer,'media','app://cosmas/',{...f.details,embeddingOrigin:'app://cosmas/'}),true);
  for(const mediaType of ['video','unknown',undefined])assert.equal(f.check(f.renderer,'media','app://cosmas',{...f.details,mediaType}),false);
  for(const mediaTypes of [[],['video'],['audio','video'],['audio','audio'],undefined])assert.equal(f.request(f.renderer,'media',{...f.details,mediaTypes}),false);
});
test('an enabled signed-in frame without main-process capture admission cannot acquire audio',()=>{
  const f=fixture(true,false);assert.equal(f.check(),false);assert.equal(f.request(),false);
  let check;const renderer={...f.renderer,session:{setPermissionCheckHandler:handler=>{check=handler;},setPermissionRequestHandler:()=>{}}};
  installMicrophonePermissions(renderer,{snapshot:()=>({phase:'ready'})},true);
  assert.equal(check(renderer,'media','app://cosmas',f.details),false);
});
test('other windows, frames, origins and capabilities remain denied',()=>{
  const f=fixture(true);
  for(const contents of [null,{}, {...f.renderer}]){assert.equal(f.check(contents),false);assert.equal(f.request(contents),false);}
  for(const permission of ['display-capture','geolocation','openExternal','camera','speaker-selection','clipboard-read','fileSystem']){
    assert.equal(f.check(f.renderer,permission),false);assert.equal(f.request(f.renderer,permission),false);
  }
  for(const origin of ['https://cosmas','app://cosmas.evil','app://cosmas?x','app://cosmas/other','null'])assert.equal(f.check(f.renderer,'media',origin),false);
  for(const change of [{isMainFrame:false},{requestingUrl:'app://cosmas/index.html?x'},{securityOrigin:'https://outside.invalid'},{embeddingOrigin:'https://outside.invalid'}]){
    assert.equal(f.check(f.renderer,'media','app://cosmas',{...f.details,...change}),false);
    assert.equal(f.request(f.renderer,'media',{...f.details,...change}),false);
  }
});
test('sign-out, unavailable identity, navigation and destroyed windows revoke access immediately',()=>{
  const f=fixture(true);
  for(const phase of ['signedOut','signingIn','loading','unavailable']){f.setPhase(phase);assert.equal(f.check(),false);assert.equal(f.request(),false);}
  f.setPhase('ready');assert.equal(f.request(),true);f.navigate();assert.equal(f.request(),false);
  const other=fixture(true);other.destroy();assert.equal(other.check(),false);assert.equal(other.request(),false);
});
