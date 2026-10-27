import test from 'node:test';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {BETA_FEATURE_FLAGS,STANDALONE_FEATURE_FLAGS,STANDALONE_FEATURE_PROFILE,
  resolveBetaFeatureProfile,validateBetaFeatureManifest,validateNativeBetaProfile} from './beta-feature-profile.mjs';

const root=fileURLToPath(new URL('../../',import.meta.url));
const standalone={VITE_WORKSPACE_FEATURE_PROFILE:STANDALONE_FEATURE_PROFILE,
  VITE_WORKSPACE_HOSTED_CLIENT:'web',VITE_WORKSPACE_DATA_MODE:'synthetic',
  VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://api.example.invalid',VITE_API_BASE:'https://api.example.invalid',
  VITE_WORKSPACE_WEB_ORIGIN:'https://workspace.example.invalid',VITE_CLERK_PUBLISHABLE_KEY:'pk_test_invented_fixture',
  VITE_COSMANEURA_WEB_ORIGIN:'',VITE_CAPTURE_UPLOAD_ORIGINS:'',VITE_WORKSPACE_CAPTURE_MODE:'disabled'};
const platformFlags=['VITE_CORE_CONNECTION_ENABLED','VITE_CORE_APPOINTMENT_SETUP_ENABLED',
  'VITE_COSMANEURA_RECORD_ENABLED','VITE_ATHENA_CONNECTION_ENABLED','VITE_ATHENA_VISIT_LINK_ENABLED',
  'VITE_WORKSPACE_CAPTURE_ENABLED','VITE_WORKSPACE_CAPTURE_NOTES_ENABLED',
  'VITE_WORKSPACE_CAPTURE_CORRECTIONS_ENABLED','VITE_WORKSPACE_CAPTURE_RECOVERY_ENABLED',
  'VITE_WORKSPACE_CAPTURE_SOURCE_ENABLED','VITE_WORKSPACE_CAPTURE_LONG_VISITS_ENABLED',
  'VITE_WORKSPACE_PREP_ENABLED','VITE_WORKSPACE_PREP_WORK_ENABLED',
  'VITE_CAPTURE_E2E_MICROPHONE_ENABLED','VITE_CAPTURE_IOS_NATIVE_PCM_ENABLED'];
function input(client){return {...standalone,VITE_WORKSPACE_HOSTED_CLIENT:client,
  VITE_WORKSPACE_WEB_ORIGIN:client==='web'?standalone.VITE_WORKSPACE_WEB_ORIGIN:'',
  VITE_API_BASE:client==='desktop'?'app://cosmas/api':standalone.VITE_API_BASE};}

test('standalone keeps own authenticated work and independent connections while explicitly closing every platform feature',()=>{
  for(const client of ['web','desktop','apple']){
    const {env,manifest}=resolveBetaFeatureProfile(input(client));
    for(const key of platformFlags){assert.equal(env[key],'false',key);assert.ok(manifest.disabledFlags.includes(key),key);}
    for(const key of STANDALONE_FEATURE_FLAGS)assert.equal(env[key],'true',key);
    for(const key of BETA_FEATURE_FLAGS)assert.equal(env[key],STANDALONE_FEATURE_FLAGS.includes(key)?'true':'false',key);
    for(const key of ['VITE_WORKSPACE_ENABLED','VITE_WORKSPACE_AUTHENTICATED_ENABLED','VITE_WORKSPACE_HOSTED_ENABLED'])assert.equal(env[key],'true');
    assert.equal(env.VITE_WORKSPACE_NATIVE_AUTH_ENABLED,client==='apple'?'true':'false');
    assert.equal(env.VITE_WORKSPACE_DESKTOP_AUTH_ENABLED,client==='desktop'?'true':'false');
    assert.equal(manifest.platformAccess,'disabled');assert.equal(manifest.athenaAccess,'disabled');
    assert.equal(manifest.coreWebOrigin,'');assert.deepEqual(manifest.captureUploadOrigins,[]);
    assert.equal(validateBetaFeatureManifest(manifest),manifest);
    if(client!=='web'){
      const expected={client,apiOrigin:standalone.VITE_API_BASE,coreWebOrigin:'',captureUploadOrigins:[],microphoneCapture:false,
        renewableNativeCapture:true,nativeRendererRecovery:true};
      // Shared native auth/recovery code is permitted, but runtime capture is off.
      assert.equal(validateNativeBetaProfile(manifest,expected),manifest);
      assert.throws(()=>validateNativeBetaProfile(manifest,{...expected,microphoneCapture:true}));
      assert.throws(()=>validateNativeBetaProfile(manifest,{...expected,coreWebOrigin:'https://core.example.invalid'}));
      assert.throws(()=>validateNativeBetaProfile(manifest,{...expected,captureUploadOrigins:['https://uploads.example.invalid']}));
    }
  }
});

test('standalone rejects stale Core, capture, local-auth bypass and broader data configuration',()=>{
  for(const key of platformFlags)assert.throws(()=>resolveBetaFeatureProfile({...standalone,[key]:'true'}),undefined,key);
  for(const change of [{VITE_COSMANEURA_WEB_ORIGIN:'https://app.cosmaneura.com'},
    {VITE_COSMANEURA_WEB_ORIGIN:'https://staging-app.cosmaneura.com'},
    {VITE_CAPTURE_UPLOAD_ORIGINS:'https://uploads.example.invalid'},
    {VITE_WORKSPACE_CAPTURE_MODE:'synthetic'},{VITE_WORKSPACE_CAPTURE_MODE:'browser_microphone'},
    {VITE_WORKSPACE_DATA_MODE:'authorized_beta'},{VITE_WORKSPACE_DATA_MODE:undefined},
    {VITE_WORKSPACE_AUTHENTICATED_ENABLED:'false'},{VITE_DESKTOP_SYNTHETIC_ENABLED:'true'},
    {VITE_WORKSPACE_APPLE_LOCAL_TRANSPORT_ENABLED:'true'},{VITE_CLERK_PUBLISHABLE_KEY:''},
    {VITE_SCRIBE_UNREVIEWED_ENABLED:'true'},{VITE_MESSAGES_ENABLED:'false'}])
    assert.throws(()=>resolveBetaFeatureProfile({...standalone,...change}));
  for(const host of ['app.cosmaneura.com','staging-app.cosmaneura.com','chat.cosmaneura.com','staging-chat.cosmaneura.com']){
    assert.throws(()=>resolveBetaFeatureProfile({...standalone,VITE_WORKSPACE_WEB_ORIGIN:'https://'+host}));
    assert.throws(()=>resolveBetaFeatureProfile({...standalone,VITE_WORKSPACE_HOSTED_API_ORIGIN:'https://'+host,VITE_API_BASE:'https://'+host}));
  }
});

test('standalone evidence rejects missing, reordered or inflated feature claims',()=>{
  const manifest=resolveBetaFeatureProfile(standalone).manifest;
  for(const change of [{disabledFlags:manifest.disabledFlags.slice(1)},
    {disabledFlags:[...manifest.disabledFlags].reverse()},{enabledFlags:[...manifest.enabledFlags,'VITE_CORE_CONNECTION_ENABLED']},
    {authentication:'email_only'},{platformAccess:'enabled'},{athenaAccess:'read_only'},
    {coreWebOrigin:'https://core.example.invalid'},{captureUploadOrigins:['https://uploads.example.invalid']},
    {profile:'operational-beta-v1'},{extra:true}])assert.throws(()=>validateBetaFeatureManifest({...manifest,...change}));
});

test('ordinary Vite build emits the standalone feature values and cannot accept ambient capture promotion',async()=>{
  const require=createRequire(join(root,'web/package.json'));const {build}=await import(require.resolve('vite'));
  const saved=Object.fromEntries(Object.entries(process.env).filter(([key])=>key.startsWith('VITE_')));
  for(const key of Object.keys(saved))delete process.env[key];Object.assign(process.env,standalone);
  try{
    const result=await build({root:join(root,'web'),configLoader:'runner',envDir:false,mode:'production',logLevel:'silent',
      plugins:[{name:'standalone-proof',resolveId:id=>id==='virtual:standalone-proof'?id:null,
        load:id=>id==='virtual:standalone-proof'?'export default import.meta.env; export const capture = import.meta.env.VITE_WORKSPACE_CAPTURE_ENABLED;':null}],
      build:{write:false,minify:false,rollupOptions:{preserveEntrySignatures:'strict',input:'virtual:standalone-proof',output:{format:'es'}}}});
    const entry=result.output.find(item=>item.type==='chunk'&&item.isEntry);
    const compiled=await import('data:text/javascript;base64,'+Buffer.from(entry.code).toString('base64'));
    for(const key of platformFlags)assert.equal(compiled.default[key],'false',key);
    for(const key of STANDALONE_FEATURE_FLAGS)assert.equal(compiled.default[key],'true',key);
    assert.equal(compiled.capture,'false');
    const manifest=JSON.parse(result.output.find(item=>item.fileName==='cosmas-beta-features.json').source);
    assert.deepEqual(manifest,resolveBetaFeatureProfile(standalone).manifest);
    process.env.VITE_WORKSPACE_CAPTURE_ENABLED='true';
    await assert.rejects(()=>build({root:join(root,'web'),configLoader:'runner',envDir:false,logLevel:'silent',build:{write:false}}),/conflicts/);
  }finally{for(const key of Object.keys(process.env))if(key.startsWith('VITE_'))delete process.env[key];Object.assign(process.env,saved);}
});
