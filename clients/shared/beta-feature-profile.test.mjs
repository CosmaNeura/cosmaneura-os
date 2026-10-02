import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {createRequire} from 'node:module';
import {BETA_FEATURE_FLAGS,NATIVE_STAGING_FEATURE_PROFILE,resolveBetaFeatureProfile,validateNativeBetaProfile} from './beta-feature-profile.mjs';
const root=fileURLToPath(new URL('../../',import.meta.url));
const base={VITE_WORKSPACE_FEATURE_PROFILE:'operational-beta-v1',VITE_WORKSPACE_HOSTED_CLIENT:'web',
  VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',
  VITE_API_BASE:'https://api.example.invalid',VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',
  VITE_COSMANEURA_WEB_ORIGIN:'https://core.example.invalid',VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid',
  VITE_WORKSPACE_CAPTURE_MODE:'browser_microphone',VITE_CLERK_PUBLISHABLE_KEY:'pk_test_local_fixture'};
function native(client){return {...base,VITE_WORKSPACE_HOSTED_CLIENT:client,VITE_WORKSPACE_WEB_ORIGIN:'',
  VITE_API_BASE:client==='desktop'?'app://cosmas/api':base.VITE_API_BASE,
  VITE_WORKSPACE_CAPTURE_MODE:client==='apple'?'ios_native':'browser_microphone'};}
function expected(client){return {client,apiOrigin:base.VITE_WORKSPACE_HOSTED_API_ORIGIN,
  coreWebOrigin:base.VITE_COSMANEURA_WEB_ORIGIN,captureUploadOrigins:[base.VITE_CAPTURE_UPLOAD_ORIGINS],
  microphoneCapture:client==='desktop',renewableNativeCapture:true,nativeRendererRecovery:true,simulatorCustody:true};}
test('profile covers every actual workflow gate, including the formerly omitted Scribe and appointment paths',()=>{
  const env=resolveBetaFeatureProfile(base).env;
  const gates=new Set();
  for(const folder of ['web/src','clients/capture/src'])for(const entry of readdirSync(join(root,folder),{recursive:true,withFileTypes:true})){
    if(!entry.isFile()||!/[.](ts|tsx)$/.test(entry.name)||entry.name.includes('.test.'))continue;
    const contents=readFileSync(join(entry.parentPath,entry.name),'utf8');
    for(const match of contents.matchAll(/import[.]meta[.]env[.](VITE_\w+_ENABLED)/g))gates.add(match[1]);
  }
  for(const key of gates)assert.ok(key in env,`Unclassified build gate: ${key}`);
  for(const key of BETA_FEATURE_FLAGS)assert.ok(gates.has(key),`Unused profile flag: ${key}`);
  for(const key of ['VITE_WORKSPACE_CAPTURE_ENABLED','VITE_WORKSPACE_APPOINTMENTS_ENABLED','VITE_INBOX_ENABLED','VITE_COSMANEURA_RECORD_ENABLED'])assert.equal(env[key],'true');
});
test('rejects prior partial recipes, misspelled flags and individual feature exclusions',()=>{
  for(const change of [{VITE_WORKSPACE_FEATURE_PROFILE:undefined},{VITE_WORKSPACE_AI_ACTIVITY_ENABLED:'true'},
    {VITE_WORKSPACE_CAPTURE_ENABLED:'false'},{VITE_CAPTURE_IOS_NATIVE_PCM_ENABLED:'true'},
    {VITE_DESKTOP_SYNTHETIC_ENABLED:'true'},{VITE_WORKSPACE_APPOINTMENTS_ENABLED:'TRUE'}]){
    assert.throws(()=>resolveBetaFeatureProfile({...base,...change}));
  }
});
test('explicit native first-owner staging enables only available work and refuses connector or live-data promotion',()=>{
  for(const client of ['desktop','apple']) {
    const input={...native(client),VITE_WORKSPACE_FEATURE_PROFILE:NATIVE_STAGING_FEATURE_PROFILE,
      VITE_COSMANEURA_WEB_ORIGIN:'',VITE_CAPTURE_UPLOAD_ORIGINS:'',VITE_WORKSPACE_CAPTURE_MODE:'disabled'};
    const {env,manifest}=resolveBetaFeatureProfile(input);
    assert.deepEqual(manifest.enabledFlags,['VITE_AI_ACTIVITY_ENABLED','VITE_WORKSPACE_ROUTINES_ENABLED']);
    for(const key of BETA_FEATURE_FLAGS)assert.equal(env[key],manifest.enabledFlags.includes(key)?'true':'false');
    assert.equal(env.VITE_WORKSPACE_AUTHENTICATED_ENABLED,'true');
    assert.equal(env.VITE_CAPTURE_IOS_NATIVE_PCM_ENABLED,'false');
    assert.equal(env.VITE_CAPTURE_E2E_MICROPHONE_ENABLED,'false');
    assert.equal(validateNativeBetaProfile(manifest,{client,apiOrigin:input.VITE_WORKSPACE_HOSTED_API_ORIGIN,
      coreWebOrigin:'',captureUploadOrigins:[],microphoneCapture:false,deviceCustody:true,simulatorCustody:false}),manifest);
    for(const change of [{VITE_WORKSPACE_HOSTED_CLIENT:'web'},{VITE_WORKSPACE_DATA_MODE:'authorized_beta'},
      {VITE_WORKSPACE_CAPTURE_ENABLED:'true'},{VITE_WORKSPACE_GOOGLE_CONNECTION_ENABLED:'true'},
      {VITE_COSMANEURA_WEB_ORIGIN:'https://core.example.invalid'},
      {VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid'},{VITE_WORKSPACE_CAPTURE_MODE:'synthetic'}])
      assert.throws(()=>resolveBetaFeatureProfile({...input,...change}));
  }
});
test('requires usable exact origins and explicit source mode, without a synthetic fallback for real data',()=>{
  for(const change of [{VITE_COSMANEURA_WEB_ORIGIN:''},{VITE_CAPTURE_UPLOAD_ORIGINS:''},
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid/path'},
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://*.example.invalid'},
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid,https://uploads.example.invalid'},
    {VITE_WORKSPACE_CAPTURE_MODE:undefined},{VITE_WORKSPACE_CAPTURE_MODE:'ios_native'},
    {VITE_WORKSPACE_CAPTURE_MODE:'synthetic',VITE_WORKSPACE_DATA_MODE:'authorized_beta',VITE_CLERK_PUBLISHABLE_KEY:'pk_live_fixture'},
    {VITE_CLERK_PUBLISHABLE_KEY:''}])assert.throws(()=>resolveBetaFeatureProfile({...base,...change}));
});
test('both native composers validate all profile features and matching origins and source support',()=>{
  for(const client of ['desktop','apple']){
    const manifest=resolveBetaFeatureProfile(native(client)).manifest;const options=expected(client);
    assert.equal(validateNativeBetaProfile(manifest,options),manifest);
    for(const change of [{coreWebOrigin:'https://other.example.invalid'},
      {captureUploadOrigins:['https://other.example.invalid']},{apiOrigin:'https://other.example.invalid'}]){
      assert.throws(()=>validateNativeBetaProfile(manifest,{...options,...change}));
    }
    for(const change of [{enabledFlags:manifest.enabledFlags.slice(1)},{athenaAccess:'write'},{extra:true}]){
      assert.throws(()=>validateNativeBetaProfile({...manifest,...change},options));
    }
    assert.throws(()=>validateNativeBetaProfile(manifest,{...options,...(client==='desktop'?{microphoneCapture:false}:{nativeRendererRecovery:false})}));
  }
});

test('synthetic Apple data can use operational device custody without admitting a Simulator identity',()=>{
  const manifest=resolveBetaFeatureProfile(native('apple')).manifest;
  const device={...expected('apple'),deviceCustody:true,simulatorCustody:false};
  assert.equal(validateNativeBetaProfile(manifest,device),manifest);
  assert.throws(()=>validateNativeBetaProfile(manifest,{...device,simulatorCustody:true}));
  assert.throws(()=>validateNativeBetaProfile(manifest,{...device,deviceCustody:false}));
  const authorized=resolveBetaFeatureProfile({...native('apple'),VITE_WORKSPACE_DATA_MODE:'authorized_beta'}).manifest;
  assert.equal(validateNativeBetaProfile(authorized,device),authorized);
  assert.throws(()=>validateNativeBetaProfile(authorized,expected('apple')));
});
test('ordinary Vite config emits the expanded profile in both direct flags and whole import.meta.env',async()=>{
  const require=createRequire(join(root,'web/package.json'));const {build}=await import(require.resolve('vite'));
  const saved=Object.fromEntries(Object.entries(process.env).filter(([key])=>key.startsWith('VITE_')));
  for(const key of Object.keys(saved))delete process.env[key];Object.assign(process.env,base);
  try{
    const output=await build({root:join(root,'web'),mode:'production',logLevel:'silent',
      plugins:[{name:'profile-proof',resolveId:id=>id==='virtual:profile-proof'?id:null,
        load:id=>id==='virtual:profile-proof'?'export default import.meta.env; export const capture = import.meta.env.VITE_WORKSPACE_CAPTURE_ENABLED;':null}],
      build:{write:false,minify:false,rollupOptions:{preserveEntrySignatures:'strict',input:'virtual:profile-proof',output:{format:'es'}}}});
    const chunks=output.output;
    const entry=chunks.find(item=>item.type==='chunk'&&item.isEntry);
    const module=await import('data:text/javascript;base64,'+Buffer.from(entry.code).toString('base64'));
    assert.equal(module.capture,'true');
    for(const key of BETA_FEATURE_FLAGS)assert.equal(module.default[key],'true',key);
    assert.equal(module.default.VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED,'false');
    const manifest=JSON.parse(chunks.find(item=>item.fileName==='cosmas-beta-features.json').source);
    assert.deepEqual(manifest,resolveBetaFeatureProfile(base).manifest);
    process.env.VITE_WORKSPACE_CAPTURE_ENABLED='false';
    await assert.rejects(()=>build({root:join(root,'web'),logLevel:'silent',build:{write:false}}),/conflicts/);
    delete process.env.VITE_WORKSPACE_CAPTURE_ENABLED;
    process.env.VITE_WORKSPACE_SCHEDULING_PATIENT_SETUP_ENABLED='true';
    await assert.rejects(()=>build({root:join(root,'web'),logLevel:'silent',build:{write:false}}),/conflicts/);
  }finally{for(const key of Object.keys(process.env))if(key.startsWith('VITE_'))delete process.env[key];Object.assign(process.env,saved);}
});
