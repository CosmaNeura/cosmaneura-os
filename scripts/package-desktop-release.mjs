/**
 * ASAR integrity and fuse packaging adapted from Scribe fe22a435b6201c2d8013348927ea6a349e0b48c6.
 * See clients/desktop/release/scribe-packaging-reuse.json for exact source hashes.
 * Builds a fresh unsigned candidate; never signs, notarizes, installs or launches.
 */
import {createHash} from 'node:crypto';
import {execFile} from 'node:child_process';
import {cp, lstat, mkdir, readFile, readdir, readlink, realpath, rm, writeFile} from 'node:fs/promises';
import {basename, dirname, extname, isAbsolute, join, relative, resolve, sep} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {promisify} from 'node:util';
import {validateOperationalNativeIdentity, validateOperationalNativeDataMode, operationalNativeAuthSettings} from '../clients/desktop/native-identity-config.mjs';
import {validateBetaFeatureManifest} from '../clients/shared/beta-feature-profile.mjs';
import {verifyNativeHelper} from '../clients/desktop/spawn-auth-helper.mjs';
import {verifyDesktopCapturePackage,CAPTURE_HELPERS} from '../clients/desktop/native-capture-package.mjs';

const exec = promisify(execFile);
const source = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const fail = () => { throw new Error('Desktop release packaging input or integrity check failed; existing inputs were preserved'); };
const digest = bytes => createHash('sha256').update(bytes).digest('hex');
const inside = (root, path) => { const r = relative(root, path); return r === '' || !r.startsWith('..' + sep) && r !== '..' && !isAbsolute(r); };
const unpackedPrefixes = ['native-auth/CosmasDesktopAuth.app/',...CAPTURE_HELPERS.map(name=>`native-capture/${name}.app/`)];
const isUnpacked = name => unpackedPrefixes.some(prefix=>name.startsWith(prefix));

async function absent(path) {
  try { await lstat(path); } catch (e) { if (e.code === 'ENOENT') return; throw e; }
  fail();
}

/** Scribe's tree inventory with byte count and executable mode added for exact copies. */
export async function inventory(root) {
  if (await realpath(root) !== root || !(await lstat(root)).isDirectory()) fail();
  const result = Object.create(null);
  async function visit(folder) {
    for (const name of (await readdir(folder)).sort()) {
      const path = join(folder, name), key = relative(root, path), stat = await lstat(path);
      if (stat.isSymbolicLink()) {
        const target = await readlink(path);
        if (isAbsolute(target) || !inside(root, resolve(dirname(path), target)) || !inside(root, await realpath(path))) fail();
        result[key] = {link:target, mode:stat.mode};
      } else if (stat.isDirectory()) await visit(path);
      else if (stat.isFile()) result[key] = {sha256:digest(await readFile(path)), bytes:stat.size, mode:stat.mode};
      else fail();
    }
  }
  await visit(root);
  return result;
}
const stable = value => Array.isArray(value) ? value.map(stable) : value && typeof value==='object'
  ? Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>[key,stable(item)])) : value;
const canonical = object => JSON.stringify(stable(object));
const equal = (a,b) => { if (canonical(a) !== canonical(b)) fail(); };

/** Refuse stale renderer routing before copying or sealing a release. Do not execute candidate code. */
export async function verifyStaticAssetInventory(app, files) {
  const code=await readFile(join(app,'static-assets.mjs'),'utf8');
  const declarations=[...code.matchAll(/^const RENDERER_ASSETS = Object\.freeze\((\{[\s\S]*?^\})\);$/gm)];
  if (declarations.length!==1) fail();
  let assets;
  try { assets=JSON.parse(declarations[0][1]); } catch { fail(); }
  const names=Object.keys(files).filter(name=>name.startsWith('public/'));
  if (!names.includes('public/index.html') || names.some(name=>files[name].link)) fail();
  equal(Object.keys(assets).sort(),['/',...names.map(name=>name.slice('public'.length))].sort());
  const requiredTypes={'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript',
    '.css':'text/css','.json':'application/json','.wasm':'application/wasm'};
  for (const route of Object.keys(assets)) {
    const entry=assets[route], file=route==='/'?'public/index.html':`public${route}`;
    if (!entry || typeof entry!=='object' || Array.isArray(entry)) fail();
    equal(Object.keys(entry).sort(),['contentType','file']);
    if (entry.file!==file || typeof entry.contentType!=='string' ||
        !/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/i.test(entry.contentType) ||
        requiredTypes[extname(file)] && entry.contentType!==requiredTypes[extname(file)]) fail();
  }
  return {files:names.length,routes:Object.keys(assets).length,assetMapSHA256:digest(canonical(assets))};
}

export async function loadBuildTools(directory) {
  const lock = JSON.parse(await readFile(join(source,'clients/desktop/release/build-tools-lock.json'),'utf8'));
  const actual=await inventory(join(directory,'node_modules'));
  equal(Object.keys(actual).map(name=>'node_modules/'+name).sort(),Object.keys(lock.files).sort());
  for (const [name,item] of Object.entries(lock.files)) {
    const path=join(directory,name), stat=await lstat(path);
    if (await realpath(path)!==path || !stat.isFile() || stat.size!==item.bytes || digest(await readFile(path))!==item.sha256) fail();
  }
  return {asar:await import(pathToFileURL(join(directory,'node_modules/@electron/asar/lib/asar.js')).href),
    fuses:await import(pathToFileURL(join(directory,'node_modules/@electron/fuses/dist/index.js')).href),
    lockSHA256:digest(await readFile(join(source,'clients/desktop/release/build-tools-lock.json')))};
}

async function plist(path) {
  return JSON.parse((await exec('/usr/bin/plutil',['-convert','json','-o','-',path],{timeout:10000,maxBuffer:1048576})).stdout);
}

/** Electron's official template ships a default app; verify it before replacing it. */
export async function validateTemplateIntegrity(asar, application, info) {
  const path=join(application,'Contents/Resources/default_app.asar');
  if (info.ElectronAsarIntegrity===undefined) { await absent(path);return false; }
  const integrity=info.ElectronAsarIntegrity;
  if (!integrity || Object.keys(integrity).length!==1 || !integrity['Resources/default_app.asar']) fail();
  const stat=await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) fail();
  const raw=asar.getRawHeader(path);
  if (typeof raw.headerString!=='string') fail();
  equal(integrity,{'Resources/default_app.asar':{algorithm:'SHA256',hash:digest(Buffer.from(raw.headerString))}});
  return true;
}

/** Check every packed byte/block and only the explicitly permitted unpacked native bundle. */
export async function verifyArchive(asar, archive, expected) {
  asar.uncache(archive);
  const raw=asar.getRawHeader(archive);
  if (typeof raw.headerString!=='string' || !raw.header?.files) fail();
  const entries=Object.create(null);
  function visit(files,prefix='') {
    for (const [name,entry] of Object.entries(files)) {
      if (!name || name.includes('/') || name.includes('\\') || name==='.' || name==='..' || !entry || typeof entry!=='object') fail();
      const path=prefix+name;
      if (entry.files!==undefined) visit(entry.files,path+'/');
      else {
        if (entry.link!==undefined || Object.hasOwn(entries,path)) fail();
        entries[path]=entry;
      }
    }
  }
  visit(raw.header.files);
  equal(Object.keys(entries).sort(),Object.keys(expected).sort());
  for (const [name,entry] of Object.entries(entries)) {
    const wanted=expected[name];
    if (wanted.link || entry.size!==wanted.bytes || (entry.unpacked===true)!==isUnpacked(name) ||
        !entry.unpacked && (entry.executable===true)!==!!(wanted.mode & 0o100)) fail();
    const bytes=asar.extractFile(archive,name);
    if (bytes.length!==wanted.bytes || digest(bytes)!==wanted.sha256) fail();
    if (!entry.unpacked) {
      const i=entry.integrity;
      if (i?.algorithm!=='SHA256' || i.hash!==wanted.sha256 || !Number.isSafeInteger(i.blockSize) || i.blockSize<=0 || !Array.isArray(i.blocks)) fail();
      const blocks=[];
      for (let start=0;start<bytes.length;start+=i.blockSize) blocks.push(digest(bytes.subarray(start,start+i.blockSize)));
      if (!blocks.length) blocks.push(digest(Buffer.alloc(0)));
      equal(blocks,i.blocks);
    }
  }
  const unpacked=await inventory(archive+'.unpacked');
  const allowed=Object.fromEntries(Object.entries(expected).filter(([name])=>isUnpacked(name)));
  equal(unpacked,allowed);
  const manifestEntry=entries['native-auth/manifest.json'];
  if (!manifestEntry || manifestEntry.unpacked) fail();
  const manifest=JSON.parse(asar.extractFile(archive,'native-auth/manifest.json').toString());
  await verifyNativeHelper(join(archive+'.unpacked','native-auth'),manifest);
  if(entries['native-capture/manifest.json']){
    if(entries['native-capture/manifest.json'].unpacked)fail();
    await verifyDesktopCapturePackage(join(archive+'.unpacked','native-capture'),JSON.parse(asar.extractFile(archive,'native-capture/manifest.json').toString()));
  }
  return {sha256:digest(await readFile(archive)),headerSHA256:digest(Buffer.from(raw.headerString)),
    packedFiles:Object.values(entries).filter(e=>!e.unpacked).length,unpackedFiles:Object.keys(unpacked).length};
}

/** Retain Scribe's capability restrictions and use the supplied Electron snapshot. */
export function fuseConfiguration(fuses) {
  const o=fuses.FuseV1Options;
  return {version:fuses.FuseVersion.V1,resetAdHocDarwinSignature:false,strictlyRequireAllFuses:true,
    [o.RunAsNode]:false,[o.EnableCookieEncryption]:true,[o.EnableNodeOptionsEnvironmentVariable]:false,
    [o.EnableNodeCliInspectArguments]:false,[o.EnableEmbeddedAsarIntegrityValidation]:true,
    // Stock Electron 43.4.1 ships the shared V8 snapshot, not a browser-only variant.
    [o.OnlyLoadAppFromAsar]:true,[o.LoadBrowserProcessSpecificV8Snapshot]:false,
    [o.GrantFileProtocolExtraPrivileges]:false,[o.WasmTrapHandlers]:true};
}

export async function verifyFuses(fuses, application) {
  const wire=await fuses.getCurrentFuseWire(application), expected=fuseConfiguration(fuses);
  if (wire.version!==expected.version) fail();
  const keys=Object.keys(expected).filter(key=>/^\d+$/.test(key));
  if (Object.keys(wire).length!==keys.length+1) fail();
  for (const key of keys) if (wire[key] !== (expected[key]?49:48)) fail();
  return wire;
}

/** The operational identity selects custody; the retained mode selects data scope. */
export function validateOperationalReleaseProfile(config, manifest, info) {
  const identity=validateOperationalNativeIdentity(config.nativeIdentity,'desktop',config.apiOrigin);
  validateOperationalNativeDataMode(config.dataMode,identity);
  const profile=validateBetaFeatureManifest(manifest);
  if (config.mode!=='hosted-beta-authenticated' || !['synthetic','authorized_beta'].includes(config.dataMode) || profile.client!=='desktop' ||
      profile.dataMode!==config.dataMode || profile.apiOrigin!==config.apiOrigin || config.appVersion!==info.CFBundleShortVersionString ||
      config.buildNumber!==info.CFBundleVersion || config.installation?.bundleIdentifier!==info.CFBundleIdentifier) fail();
  if (profile.captureMode==='disabled' && (config.nativeCaptureEnabled!==false || config.microphoneCaptureEnabled===true ||
      config.captureUploadOrigins?.length || ['cosmaneuraWebOrigin','googleConnectionClientId','googleConnectionCallbackUri',
        'microsoftConnectionTenantId','microsoftConnectionClientId','microsoftConnectionCallbackUri',
        'schedulingGoogleClientId','schedulingGoogleCallbackUri'].some(key=>config[key]))) fail();
  return identity;
}

export function validateSourceProvenance(provenance) {
  if (!provenance || typeof provenance!=='object' || Array.isArray(provenance) ||
      Object.keys(provenance).sort().join(',')!=='commit,dirty,tree,version' || provenance.version!==1 ||
      provenance.dirty!==false || typeof provenance.commit!=='string' || typeof provenance.tree!=='string' ||
      !/^[a-f0-9]{40}$/.test(provenance.commit) || !/^[a-f0-9]{40}$/.test(provenance.tree)) fail();
  return provenance;
}

export async function packageRelease({application,inputManifest,toolsDirectory,output}) {
  for (const path of [application,inputManifest,toolsDirectory,output]) if (!isAbsolute(path) || resolve(path)!==path) fail();
  if (!application.endsWith('.app') || !output.endsWith('.app') || inside(application,output) || inside(output,application) ||
      inside(source,output) || inside(toolsDirectory,output) || inside(output,toolsDirectory) ||
      await realpath(dirname(output))!==dirname(output)) fail();
  await absent(output);await absent(output+'.receipt.json');await absent(output+'.incomplete.json');
  const original=await inventory(application), expected=JSON.parse(await readFile(inputManifest,'utf8'));
  equal(original,expected);
  const info=await plist(join(application,'Contents/Info.plist'));
  if (info.CFBundleIdentifier!=='com.cosmasos.beta.desktop' || info.CosmasElectronVersion!=='43.4.1' ||
      typeof info.CFBundleExecutable!=='string' || basename(info.CFBundleExecutable)!==info.CFBundleExecutable) fail();
  const app=join(application,'Contents/Resources/app'), appFiles=await inventory(app);
  if (Object.values(appFiles).some(item=>item.link)) fail();
  const staticAssets=await verifyStaticAssetInventory(app,appFiles);
  const config=JSON.parse(await readFile(join(app,'synthetic-build.json'),'utf8'));
  const provenance=validateSourceProvenance(config.sourceProvenance);
  const identity=validateOperationalReleaseProfile(config,
    JSON.parse(await readFile(join(app,'public/cosmas-beta-features.json'),'utf8')),info);
  const pkg=JSON.parse(await readFile(join(app,'package.json'),'utf8'));
  if (pkg.main!=='main.mjs' || pkg.type!=='module' || pkg.version!==config.appVersion) fail();
  const helperInfo=await plist(join(app,'native-auth/CosmasDesktopAuth.app/Contents/Info.plist'));
  equal(helperInfo.CosmasNativeAuth,operationalNativeAuthSettings(identity));
  equal(helperInfo.CosmasNativeIdentity,identity);
  await verifyNativeHelper(join(app,'native-auth'),JSON.parse(await readFile(join(app,'native-auth/manifest.json'),'utf8')));
  if(config.nativeCaptureEnabled===true){
    equal(helperInfo.CosmasConfiguredCapture,{enabled:true,apiOrigin:config.apiOrigin});
    await verifyDesktopCapturePackage(join(app,'native-capture'),JSON.parse(await readFile(join(app,'native-capture/manifest.json'),'utf8')));
    if(!appFiles['workspace-native-capture.mjs']||!appFiles['native-capture-package.mjs'])fail();
  } else if(config.nativeCaptureEnabled===false) {
    equal(helperInfo.CosmasConfiguredCapture,{enabled:false});
  }
  const tools=await loadBuildTools(toolsDirectory);
  const templateArchive=await validateTemplateIntegrity(tools.asar,application,info);
  const intent={version:1,sourceManifestSHA256:digest(await readFile(inputManifest)),input:application,output,completed:false};
  await writeFile(output+'.incomplete.json',JSON.stringify(intent,null,2)+'\n',{flag:'wx',mode:0o600});
  await cp(application,output,{recursive:true,dereference:false,errorOnExist:true,force:false,verbatimSymlinks:true});
  equal(await inventory(output),original);
  const resources=join(output,'Contents/Resources'), archive=join(resources,'app.asar');
  await absent(archive);await absent(archive+'.unpacked');
  await tools.asar.createPackageWithOptions(join(resources,'app'),archive,{smartUnpack:false,
    unpackDir:'{native-auth/CosmasDesktopAuth.app,native-capture/ScribeDesktopAudioHelper.app,native-capture/ScribeProviderPresentationHelper.app}'});
  const verified=await verifyArchive(tools.asar,archive,appFiles);
  await exec('/usr/bin/plutil',[templateArchive?'-replace':'-insert','ElectronAsarIntegrity','-json',JSON.stringify({'Resources/app.asar':{algorithm:'SHA256',hash:verified.headerSHA256}}),join(output,'Contents/Info.plist')],{timeout:10000});
  // Delete only the redundant copy created by this invocation after byte verification.
  await rm(join(resources,'app'),{recursive:true});
  if (templateArchive) await rm(join(resources,'default_app.asar'));
  const binary=await realpath(tools.fuses.pathToFuseFile(output));
  if (!inside(output,binary)) fail();
  await tools.fuses.flipFuses(output,fuseConfiguration(tools.fuses));
  const wire=await verifyFuses(tools.fuses,output);
  const finalInfo=await plist(join(output,'Contents/Info.plist'));
  equal(finalInfo.ElectronAsarIntegrity,{'Resources/app.asar':{algorithm:'SHA256',hash:verified.headerSHA256}});
  equal(await verifyArchive(tools.asar,archive,appFiles),verified);
  equal(await inventory(application),original);
  const final=await inventory(output), changedFramework=relative(output,binary);
  for (const [name,item] of Object.entries(original)) {
    if (name.startsWith('Contents/Resources/app/') || name==='Contents/Info.plist' || name===changedFramework ||
        templateArchive && name==='Contents/Resources/default_app.asar') continue;
    equal(final[name],item);
  }
  const receipt={...intent,completed:true,archive:verified,staticAssets,fuses:wire,changedFramework,replacedElectronDefaultArchive:templateArchive,
    buildToolsLockSHA256:tools.lockSHA256,bundleIdentifier:info.CFBundleIdentifier,appVersion:config.appVersion,buildNumber:config.buildNumber,sourceProvenance:provenance,
    files:final,sourcePreserved:true,signed:false,notarized:false,installedOrLaunched:false,distributionAllowed:false};
  await writeFile(output+'.receipt.json',JSON.stringify(receipt,null,2)+'\n',{flag:'wx',mode:0o600});
  await rm(output+'.incomplete.json');
  return receipt;
}

if (process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  try {
    const args=process.argv.slice(2), names=['--application','--input-manifest','--tools','--output'];
    if (args.length!==8 || names.some((name,index)=>args[index*2]!==name)) fail();
    const result=await packageRelease({application:args[1],inputManifest:args[3],toolsDirectory:args[5],output:args[7]});
    process.stdout.write(JSON.stringify({completed:true,archive:result.archive,signed:false,distributionAllowed:false})+'\n');
  } catch (e) { process.stderr.write(e.message+'\n');process.exitCode=1; }
}
