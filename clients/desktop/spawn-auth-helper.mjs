import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFile, realpath, lstat, readdir} from 'node:fs/promises';
import {basename, dirname, join, resolve} from 'node:path';
import {createAuthHelperClient} from './auth-helper-client.mjs';

/** The manifest stays inside integrity-protected ASAR; only the native .app is unpacked. */
export function nativeHelperPaths(root) {
  const normalized = resolve(root);
  const archived = basename(normalized) === 'app.asar';
  if (archived && basename(dirname(normalized)) !== 'Resources') throw new Error('Native session unavailable');
  return {manifestPath: join(normalized, 'native-auth/manifest.json'),
    directory: join(archived ? normalized + '.unpacked' : normalized, 'native-auth')};
}

/** Verify the complete native bundle before exposing a spawn capability. */
export async function verifyNativeHelper(directory, manifest) {
  if (!manifest || Object.keys(manifest).sort().join(',') !== 'executable,files,version' ||
      manifest.version !== 1 || manifest.executable !== 'CosmasDesktopAuth.app/Contents/MacOS/CosmasDesktopAuth' ||
      !manifest.files || typeof manifest.files !== 'object' || Array.isArray(manifest.files) ||
      Object.keys(manifest.files).length > 64) throw new Error('Native session unavailable');
  const seen = new Set();
  let visited = 0;
  async function inspect(folder) {
    if (++visited > 128 || !Object.keys(manifest.files).some(name => name.startsWith(folder.slice(directory.length + 1) + '/'))) throw new Error('Native session unavailable');
    if (await realpath(folder) !== folder || !(await lstat(folder)).isDirectory()) throw new Error('Native session unavailable');
    for (const name of await readdir(folder)) {
      const path = join(folder, name), stat = await lstat(path);
      if (stat.isSymbolicLink()) throw new Error('Native session unavailable');
      if (stat.isDirectory()) await inspect(path);
      else if (stat.isFile()) {
        const relative = path.slice(directory.length + 1);
        if (seen.size >= 64 || !Object.hasOwn(manifest.files, relative)) throw new Error('Native session unavailable');
        seen.add(relative);
      } else throw new Error('Native session unavailable');
    }
  }
  await inspect(join(directory, 'CosmasDesktopAuth.app'));
  if (seen.size !== Object.keys(manifest.files).length) throw new Error('Native session unavailable');
  for (const [relative, expected] of Object.entries(manifest.files)) {
    if (!relative.startsWith('CosmasDesktopAuth.app/') || relative.includes('\\') ||
        relative.split('/').some(part => !part || part === '.' || part === '..') ||
        typeof expected !== 'string' || !/^[a-f0-9]{64}$/.test(expected)) throw new Error('Native session unavailable');
    const path = join(directory, relative), stat = await lstat(path);
    if (await realpath(path) !== path || !stat.isFile() || stat.size > 64 * 1024 * 1024) throw new Error('Native session unavailable');
    if (createHash('sha256').update(await readFile(path)).digest('hex') !== expected) throw new Error('Native session unavailable');
  }
  if (!Object.hasOwn(manifest.files, manifest.executable) ||
      !Object.hasOwn(manifest.files, 'CosmasDesktopAuth.app/Contents/Info.plist')) throw new Error('Native session unavailable');
  return join(directory, manifest.executable);
}

/** Resolve and verify one packaged executable; no renderer-selected path or arguments. */
export async function preparePackagedAuthHelper(root, temporaryDirectory) {
  if (process.platform !== 'darwin') throw new Error('Native session unavailable');
  const {directory, manifestPath} = nativeHelperPaths(root);
  const stat = await lstat(manifestPath);
  if (!stat.isFile() || stat.size > 16384 || stat.isSymbolicLink()) throw new Error('Native session unavailable');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8'));
  const executable = await verifyNativeHelper(directory, manifest);
  return () => createAuthHelperClient(spawn(executable, [], {shell: false, stdio: ['pipe', 'pipe', 'pipe'],
    env: {PATH: '/usr/bin:/bin', LANG: 'en_US.UTF-8', TMPDIR: temporaryDirectory}}));
}
