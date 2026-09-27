import {constants} from 'node:fs';
import {createHash} from 'node:crypto';
import {lstat, mkdir, open, readdir, realpath} from 'node:fs/promises';
import {isAbsolute, join, resolve} from 'node:path';
import {exactHostedApiOrigin} from './hosted-auth-http.mjs';
import {validateOperationalNativeIdentity, validateOperationalNativeDataMode} from './native-identity-config.mjs';

const unavailable = () => new Error('Saved workspace is incompatible or unavailable; local data was preserved');
const markerName = 'cosmas-installation.json';

/** Development installation identity. Never migrate, reset, or choose a fallback profile. */
export async function prepareDesktopState(config, appData, electronVersion) {
  const hosted = config.mode === 'hosted-beta-authenticated';
  const operational = hosted && (config.dataMode === 'authorized_beta' || Object.hasOwn(config, 'nativeIdentity'));
  if (hosted && (!['synthetic','authorized_beta'].includes(config.dataMode) || !exactHostedApiOrigin(config.apiOrigin) || !config.installation)) throw unavailable();
  let identityBinding;
  if (operational) {
    const publicIdentity = validateOperationalNativeIdentity(config.nativeIdentity, 'desktop', config.apiOrigin);
    validateOperationalNativeDataMode(config.dataMode, publicIdentity);
    identityBinding = createHash('sha256').update(JSON.stringify(publicIdentity, Object.keys(publicIdentity).sort())).digest('hex');
    if (config.installationRoot !== undefined) throw unavailable();
  } else if (config.nativeIdentity !== undefined) throw unavailable();
  if (config.installation === undefined) {
    if (typeof config.stateDirectory !== 'string' || !isAbsolute(config.stateDirectory)) throw unavailable();
    return config.stateDirectory; // Preserve the existing isolated W6/W9/W13 compositions.
  }
  const identity = config.installation;
  if (!identity || typeof identity !== 'object' || (!hosted && config.mode !== 'local-synthetic-authenticated') || config.stateDirectory !== undefined ||
      identity.version !== 1 || (operational ? identity.profile !== 'beta' : !/^w[1-9][0-9]*[a-z]?$/.test(identity.profile)) ||
      identity.bundleIdentifier !== (operational ? 'com.cosmasos.beta.desktop' : `com.cosmasos.synthetic.desktop.${identity.profile}`) ||
      identity.storageGeneration !== 1 || identity.electronVersion !== '43.4.1' ||
      electronVersion !== identity.electronVersion ||
      identity.rendererPartition !== (operational ? 'persist:cosmasos-operational-beta' : 'persist:cosmasos-authenticated-local') ||
      (operational ? identity.authHelperBundleIdentifier !== 'com.cosmasos.beta.desktop.auth' :
       !/^com\.cosmasos\.synthetic\.desktop\.auth\.w[1-9][0-9]*[a-z]?$/.test(identity.authHelperBundleIdentifier))) {
    throw unavailable();
  }
  const base = config.installationRoot ?? join(appData, operational ? 'CosmasOS Beta' : hosted ? 'CosmasOS Hosted Beta' : 'CosmasOS Synthetic');
  if (typeof base !== 'string' || !isAbsolute(base) || resolve(base) !== base) throw unavailable();
  const directory = join(base, identity.bundleIdentifier);
  async function secureDirectory(path) {
    await mkdir(path, {recursive: true, mode: 0o700});
    const stat = await lstat(path);
    if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid() ||
        stat.mode & 0o077 || await realpath(path) !== path) throw unavailable();
  }
  try {
    await secureDirectory(base);
    await secureDirectory(directory);
    const filename = join(directory, markerName);
    const expected = {
      contract: 'cosmas-os-desktop-installation-v1',
      bundleIdentifier: identity.bundleIdentifier,
      storageGeneration: identity.storageGeneration,
      electronVersion: identity.electronVersion,
      rendererPartition: identity.rendererPartition,
      authHelperBundleIdentifier: identity.authHelperBundleIdentifier,
      ...(hosted ? {apiOrigin: config.apiOrigin, dataMode: config.dataMode} : {}),
      ...(operational ? {identityBinding} : {}),
    };
    try { await lstat(filename); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      // A missing marker in a populated profile is a recovery issue, not a new install.
      if ((await readdir(directory)).length !== 0) throw unavailable();
      const handle = await open(filename, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
      try { await handle.writeFile(JSON.stringify(expected) + '\n'); await handle.sync(); }
      finally { await handle.close(); }
      const parent = await open(directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
      try { await parent.sync(); } finally { await parent.close(); }
    }
    const handle = await open(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const stat = await handle.stat();
      if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() || stat.mode & 0o077 || stat.size > 2048) throw unavailable();
      const bytes = Buffer.alloc(2049);
      const {bytesRead} = await handle.read(bytes, 0, bytes.length, 0);
      if (bytesRead > 2048) throw unavailable();
      const actual = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, bytesRead)));
      if (!actual || Object.keys(actual).length !== Object.keys(expected).length ||
          Object.entries(expected).some(([key, value]) => actual[key] !== value)) throw unavailable();
    } finally { await handle.close(); }
    return directory;
  } catch { throw unavailable(); }
}
