import assert from 'node:assert/strict';
import test from 'node:test';
import {createHash} from 'node:crypto';
import {mkdtemp, mkdir, realpath, writeFile, symlink} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {nativeHelperPaths, verifyNativeHelper, preparePackagedAuthHelper} from './spawn-auth-helper.mjs';

async function fixture() {
  const root=await realpath(await mkdtemp(join(tmpdir(),'cosmas-helper-package-')));
  const directory=join(root,'native-auth'), executable='CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth';
  const files={[executable]:'invented executable bytes','CosmasDesktopAuth.app/Contents/Info.plist':'invented public config'};
  const manifest={version:1,executable,files:{}};
  for (const [name,bytes] of Object.entries(files)) {
    await mkdir(join(directory,name,'..'),{recursive:true});await writeFile(join(directory,name),bytes);
    manifest.files[name]=createHash('sha256').update(bytes).digest('hex');
  }
  await writeFile(join(directory,'manifest.json'),JSON.stringify(manifest));
  return {root,directory,manifest};
}

test('existing loose helpers retain their exact verified spawn capability without launching it',async()=>{
  const f=await fixture();assert.equal(await verifyNativeHelper(f.directory,f.manifest),join(f.directory,f.manifest.executable));
  assert.equal(typeof await preparePackagedAuthHelper(f.root,f.root),'function');
});
test('archive manifest remains protected while the executable path is explicitly unpacked',()=>{
  assert.deepEqual(nativeHelperPaths('/tmp/Cosmas.app/Contents/Resources/app.asar/'),{
    manifestPath:'/tmp/Cosmas.app/Contents/Resources/app.asar/native-auth/manifest.json',
    directory:'/tmp/Cosmas.app/Contents/Resources/app.asar.unpacked/native-auth'});
  assert.throws(()=>nativeHelperPaths('/tmp/app.asar'));
});
test('changed, unlisted and linked native files cannot acquire a spawn capability',async()=>{
  const changed=await fixture();await writeFile(join(changed.directory,changed.manifest.executable),'different');
  await assert.rejects(verifyNativeHelper(changed.directory,changed.manifest));
  const extra=await fixture();await writeFile(join(extra.directory,'CosmasDesktopAuth.app/unlisted.dylib'),'extra');
  await assert.rejects(verifyNativeHelper(extra.directory,extra.manifest));
  const linked=await fixture();await symlink(linked.manifest.executable,join(linked.directory,'CosmasDesktopAuth.app/link'));
  await assert.rejects(verifyNativeHelper(linked.directory,linked.manifest));
  await assert.rejects(verifyNativeHelper(extra.directory,{...extra.manifest,executable:'../../other'}));
});
