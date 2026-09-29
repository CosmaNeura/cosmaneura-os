import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {mkdtemp,mkdir,readFile,realpath,rm,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {inventory,loadBuildTools,verifyArchive,fuseConfiguration,validateTemplateIntegrity,validateOperationalReleaseProfile,verifyStaticAssetInventory} from './package-desktop-release.mjs';
import {resolveBetaFeatureProfile} from '../clients/shared/beta-feature-profile.mjs';
import {CAPTURE_HELPERS,verifyDesktopCapturePackage} from '../clients/desktop/native-capture-package.mjs';
const tools=await loadBuildTools(process.env.COSMAS_RELEASE_TOOLS);

async function rendererFixture(t) {
  const app=await realpath(await mkdtemp(join(tmpdir(),'cosmas-renderer-routing-')));
  t.after(()=>rm(app,{recursive:true,force:true}));
  await mkdir(join(app,'public/assets'),{recursive:true});
  await writeFile(join(app,'public/index.html'),'<script type="module" src="./assets/index-old.js"></script>');
  await writeFile(join(app,'public/assets/index-old.js'),'export const ready=true;');
  const assets={'/':{file:'public/index.html',contentType:'text/html'},
    '/index.html':{file:'public/index.html',contentType:'text/html'},
    '/assets/index-old.js':{file:'public/assets/index-old.js',contentType:'text/javascript'}};
  const writeMap=map=>writeFile(join(app,'static-assets.mjs'),
    'throw new Error("Candidate code must not execute during inventory checks");\n'+
    `const RENDERER_ASSETS = Object.freeze(${JSON.stringify(map,null,2)});\n`);
  await writeMap(assets);
  return {app,assets,writeMap};
}

test('renderer replacement refuses stale routes and accepts the regenerated map without executing it',async t=>{
  const {app,assets,writeMap}=await rendererFixture(t);
  assert.equal((await verifyStaticAssetInventory(app,await inventory(app))).routes,3);
  await rm(join(app,'public/assets/index-old.js'));
  await writeFile(join(app,'public/assets/index-new.js'),'export const ready="updated";');
  await writeFile(join(app,'public/index.html'),'<script type="module" src="./assets/index-new.js"></script>');
  await assert.rejects(verifyStaticAssetInventory(app,await inventory(app)));
  delete assets['/assets/index-old.js'];
  assets['/assets/index-new.js']={file:'public/assets/index-new.js',contentType:'text/javascript'};
  await writeMap(assets);
  const checked=await verifyStaticAssetInventory(app,await inventory(app));
  assert.equal(checked.files,2);assert.equal(checked.routes,3);
  assert.match(checked.assetMapSHA256,/^[a-f0-9]{64}$/);
});

test('renderer routing rejects missing entry points, wrong destinations and non-module MIME types',async t=>{
  const {app,assets,writeMap}=await rendererFixture(t),files=await inventory(app);
  for (const alter of [map=>delete map['/'],map=>map['/'].file='main.mjs',
    map=>map['/assets/index-old.js'].contentType='text/plain',map=>map['/unknown']=map['/']]) {
    const invalid=structuredClone(assets);alter(invalid);await writeMap(invalid);
    await assert.rejects(verifyStaticAssetInventory(app,files));
  }
  await writeMap(assets);
  await rm(join(app,'public/index.html'));
  await assert.rejects(verifyStaticAssetInventory(app,await inventory(app)));
});

test('first-owner release preserves operational identity and refuses native capture or connector activation',()=>{
  const identity={version:1,profile:'operational-beta-v1',client:'desktop',apiOrigin:'https://api.example.invalid',
    frontendOrigin:'https://identity.example.invalid',publishableKey:'pk_live_'+Buffer.from('identity.example.invalid$').toString('base64'),
    organizationId:'org_fixture',audience:'cosmas-beta-api'};
  const profile=resolveBetaFeatureProfile({VITE_WORKSPACE_FEATURE_PROFILE:'first-owner-staging-v1',
    VITE_WORKSPACE_HOSTED_CLIENT:'desktop',VITE_WORKSPACE_DATA_MODE:'synthetic',VITE_WORKSPACE_HOSTED_API_ORIGIN:identity.apiOrigin,
    VITE_API_BASE:'app://cosmas/api',VITE_WORKSPACE_WEB_ORIGIN:'',VITE_COSMANEURA_WEB_ORIGIN:'',
    VITE_CAPTURE_UPLOAD_ORIGINS:'',VITE_WORKSPACE_CAPTURE_MODE:'disabled'}).manifest;
  const info={CFBundleIdentifier:'com.cosmasos.beta.desktop',CFBundleShortVersionString:'0.1.43',CFBundleVersion:'1003'};
  const config={nativeIdentity:identity,mode:'hosted-beta-authenticated',dataMode:'synthetic',apiOrigin:identity.apiOrigin,
    appVersion:info.CFBundleShortVersionString,buildNumber:info.CFBundleVersion,
    installation:{bundleIdentifier:info.CFBundleIdentifier},nativeCaptureEnabled:false};
  assert.deepEqual(validateOperationalReleaseProfile(config,profile,info),identity);
  for(const change of [{nativeCaptureEnabled:true},{nativeCaptureEnabled:undefined},{microphoneCaptureEnabled:true},
    {cosmaneuraWebOrigin:'https://core.example.invalid'},{googleConnectionClientId:'invented.apps.googleusercontent.com'},
    {captureUploadOrigins:['https://uploads.example.invalid']}])
    assert.throws(()=>validateOperationalReleaseProfile({...config,...change},profile,info));
});

for(const signed of [false,true]) test(`desktop recording helpers preserve ${signed?'signed':'unsigned'} manifests outside ASAR`,async t=>{
  const root=await realpath(await mkdtemp(join(tmpdir(),'cosmas-capture-asar-'))),source=join(root,'input');
  t.after(()=>rm(root,{recursive:true,force:true}));
  const files={};
  for(const name of CAPTURE_HELPERS)for(const [path,value] of [[`Contents/MacOS/${name}`,'invented binary'],['Contents/Info.plist','invented config'],
    ...(signed?[['Contents/_CodeSignature/CodeResources','invented sealed resources']]:[])]){
    const relative=`${name}.app/${path}`;
    await mkdir(join(source,'native-capture',relative,'..'),{recursive:true});
    await writeFile(join(source,'native-capture',relative),value,{mode:0o755});
    files[relative]=createHash('sha256').update(value).digest('hex');
  }
  const manifest={version:1,files};await writeFile(join(source,'native-capture/manifest.json'),JSON.stringify(manifest));
  const authFiles={};
  for(const [path,value] of [['Contents/MacOS/CosmasDesktopAuth','invented auth'],['Contents/Info.plist','invented auth config']]){
    const relative=`CosmasDesktopAuth.app/${path}`;
    await mkdir(join(source,'native-auth',relative,'..'),{recursive:true});
    await writeFile(join(source,'native-auth',relative),value,{mode:0o755});
    authFiles[relative]=createHash('sha256').update(value).digest('hex');
  }
  await writeFile(join(source,'native-auth/manifest.json'),JSON.stringify({version:1,
    executable:'CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth',files:authFiles}));
  await writeFile(join(source,'workspace-native-capture.mjs'),'export const invented=true;');
  const expected=await inventory(source),archive=join(root,'app.asar');
  await tools.asar.createPackageWithOptions(source,archive,{smartUnpack:false,
    unpackDir:'{native-auth/CosmasDesktopAuth.app,native-capture/ScribeDesktopAudioHelper.app,native-capture/ScribeProviderPresentationHelper.app}'});
  const checked=await verifyArchive(tools.asar,archive,expected);assert.equal(checked.unpackedFiles,signed?8:6);assert.equal(checked.packedFiles,3);
  const native=join(archive+'.unpacked','native-capture');
  await verifyDesktopCapturePackage(native,manifest);
  if(signed){
    const relative=`${CAPTURE_HELPERS[0]}.app/Contents/_CodeSignature/CodeResources`,path=join(native,relative);
    await writeFile(path,'changed sealed resources');
    await assert.rejects(verifyArchive(tools.asar,archive,expected));
    await assert.rejects(verifyDesktopCapturePackage(native,manifest));
    await writeFile(path,'invented sealed resources');
    await assert.rejects(verifyDesktopCapturePackage(native,{version:1,files:{...files,[`${CAPTURE_HELPERS[0]}.app/Contents/_CodeSignature/unexpected`]:files[relative]}}));
    const missing={...files};delete missing[`${CAPTURE_HELPERS[0]}.app/Contents/MacOS/${CAPTURE_HELPERS[0]}`];
    await assert.rejects(verifyDesktopCapturePackage(native,{version:1,files:missing}));
  }
});

test('real ASAR preserves executable custody and catches changed packed and unpacked bytes',async()=>{
  const root=await realpath(await mkdtemp(join(tmpdir(),'cosmas-real-asar-'))), source=join(root,'input');
  const native={'CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth':'invented executable',
    'CosmasDesktopAuth.app/Contents/Info.plist':'invented config'};
  for (const [name,bytes] of Object.entries(native)) {
    await mkdir(join(source,'native-auth',name,'..'),{recursive:true});await writeFile(join(source,'native-auth',name),bytes,{mode:0o755});
  }
  const manifest={version:1,executable:'CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth',
    files:Object.fromEntries(Object.entries(native).map(([k,v])=>[k,createHash('sha256').update(v).digest('hex')]))};
  await writeFile(join(source,'native-auth/manifest.json'),JSON.stringify(manifest));
  await writeFile(join(source,'main.mjs'),'console.log("UNIQUE_INVENTED_PACKED_CONTENT");');
  const expected=await inventory(source), archive=join(root,'app.asar');
  await tools.asar.createPackageWithOptions(source,archive,{smartUnpack:false,unpackDir:'native-auth/CosmasDesktopAuth.app'});
  const result=await verifyArchive(tools.asar,archive,expected);
  assert.equal(result.packedFiles,2);assert.equal(result.unpackedFiles,2);
  const bytes=await readFile(archive), index=bytes.indexOf('UNIQUE_INVENTED_PACKED_CONTENT');assert.ok(index>0);
  bytes[index]^=1;await writeFile(archive,bytes);
  await assert.rejects(verifyArchive(tools.asar,archive,expected));
  bytes[index]^=1;await writeFile(archive,bytes);
  await writeFile(join(archive+'.unpacked','native-auth',manifest.executable),'changed executable');
  await assert.rejects(verifyArchive(tools.asar,archive,expected));
});
test('fuse adaptation keeps capability restrictions and selects the supplied V8 snapshot',()=>{
  const f=fuseConfiguration(tools.fuses),o=tools.fuses.FuseV1Options;
  assert.equal(f.resetAdHocDarwinSignature,false);assert.equal(f.strictlyRequireAllFuses,true);
  assert.equal(f[o.RunAsNode],false);assert.equal(f[o.EnableNodeOptionsEnvironmentVariable],false);
  assert.equal(f[o.EnableNodeCliInspectArguments],false);assert.equal(f[o.OnlyLoadAppFromAsar],true);
  assert.equal(f[o.EnableEmbeddedAsarIntegrityValidation],true);
  assert.equal(f[o.LoadBrowserProcessSpecificV8Snapshot],false);
});

test('official default-app metadata must match its actual header before replacement',async()=>{
  const root=await realpath(await mkdtemp(join(tmpdir(),'cosmas-template-asar-'))),input=join(root,'source'),app=join(root,'Template.app');
  await mkdir(input);await writeFile(join(input,'main.js'),'invented template');
  const archive=join(app,'Contents/Resources/default_app.asar');
  await tools.asar.createPackageWithOptions(input,archive,{});
  const hash=createHash('sha256').update(tools.asar.getRawHeader(archive).headerString).digest('hex');
  const info={ElectronAsarIntegrity:{'Resources/default_app.asar':{algorithm:'SHA256',hash}}};
  assert.equal(await validateTemplateIntegrity(tools.asar,app,info),true);
  await assert.rejects(validateTemplateIntegrity(tools.asar,app,{ElectronAsarIntegrity:{'Resources/default_app.asar':{algorithm:'SHA256',hash:'0'.repeat(64)}}}));
  await assert.rejects(validateTemplateIntegrity(tools.asar,app,{}));
});
