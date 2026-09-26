import {createHash} from 'node:crypto';
import {lstat,readFile,readdir,realpath} from 'node:fs/promises';
import {basename,join,resolve} from 'node:path';

export const CAPTURE_HELPERS = ['ScribeDesktopAudioHelper','ScribeProviderPresentationHelper'];
const failure = () => new Error('Desktop recording installation is unavailable');
export async function verifyDesktopCapturePackage(directory, manifest) {
  const required = CAPTURE_HELPERS.flatMap(name => [`${name}.app/Contents/MacOS/${name}`,`${name}.app/Contents/Info.plist`]);
  const allowed = new Set([...required,...CAPTURE_HELPERS.map(name => `${name}.app/Contents/_CodeSignature/CodeResources`)]);
  if (!manifest || Object.keys(manifest).sort().join(',') !== 'files,version' || manifest.version !== 1 ||
      !manifest.files || typeof manifest.files !== 'object' || Array.isArray(manifest.files) ||
      !required.every(name => Object.hasOwn(manifest.files,name)) ||
      Object.keys(manifest.files).some(name => !allowed.has(name))) throw failure();
  // Apple adds a sealed-resource file when signing each helper bundle. Its exact
  // bytes belong in the ASAR-protected manifest just like the executable.
  const expected = Object.keys(manifest.files).sort();
  const observed=[];
  let visited=0;
  async function inspect(folder) {
    const relative=folder.slice(directory.length+1);
    if(++visited>32||!expected.some(name=>name.startsWith(relative+'/'))||
      await realpath(folder)!==folder||!(await lstat(folder)).isDirectory())throw failure();
    for(const name of await readdir(folder)){
      const path=join(folder,name),stat=await lstat(path);
      if(stat.isSymbolicLink())throw failure();
      if(stat.isDirectory())await inspect(path);
      else if(stat.isFile())observed.push(path.slice(directory.length+1));else throw failure();
    }
  }
  for(const name of CAPTURE_HELPERS)await inspect(join(directory,name+'.app'));
  if(observed.sort().join(',')!==expected.join(','))throw failure();
  for(const name of expected){
    const path=join(directory,name),stat=await lstat(path),hash=manifest.files[name];
    if(stat.size>64*1024*1024||typeof hash!=='string'||!/^[a-f0-9]{64}$/.test(hash)||
      createHash('sha256').update(await readFile(path)).digest('hex')!==hash)throw failure();
  }
  return Object.fromEntries(CAPTURE_HELPERS.map((name,i)=>[i?'presentation':'audio',{
    helperPath:join(directory,`${name}.app/Contents/MacOS/${name}`),
    helperSha256:manifest.files[`${name}.app/Contents/MacOS/${name}`],
  }]));
}

export async function preparePackagedDesktopCapture(root) {
  root=resolve(root);
  const path=join(root,'native-capture/manifest.json'),stat=await lstat(path);
  if(!stat.isFile()||stat.isSymbolicLink()||stat.size>16384)throw failure();
  const directory=join(basename(root)==='app.asar'?root+'.unpacked':root,'native-capture');
  return verifyDesktopCapturePackage(directory,JSON.parse(await readFile(path,'utf8')));
}
