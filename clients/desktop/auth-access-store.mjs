import {constants} from 'node:fs';
import {lstat, mkdir, open, realpath, rename, unlink} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {join, resolve} from 'node:path';

const STATES = new Set(['needs_login', 'logout_pending', 'allowed']);
const unavailable = () => new Error('Native access storage unavailable');

/** One non-secret access decision. No account identifiers or credentials. */
export function createAuthAccessStore(stateDirectory) {
  const root = resolve(stateDirectory);
  const directory = join(root, 'workspace-auth');
  const filename = join(directory, 'access.json');
  let queue = Promise.resolve();
  const serialize = action => {
    const result = queue.then(action);
    queue = result.catch(() => {});
    return result;
  };
  async function secureDirectory() {
    const rootStat = await lstat(root);
    if (!rootStat.isDirectory() || await realpath(root) !== root || rootStat.uid !== process.getuid()) throw unavailable();
    await mkdir(directory, {mode: 0o700}).catch(error => { if (error.code !== 'EEXIST') throw error; });
    const stat = await lstat(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid() || (stat.mode & 0o077)) throw unavailable();
  }
  async function syncDirectory() {
    const handle = await open(directory, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
    try { await handle.sync(); } finally { await handle.close(); }
  }
  async function inspectFile() {
    const stat = await lstat(filename);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.nlink !== 1 || stat.uid !== process.getuid() ||
        stat.mode & 0o077 || stat.size > 128) throw unavailable();
  }
  const encoded = access => JSON.stringify({version: 1, access}) + '\n';
  async function read() {
    await secureDirectory();
    try { await inspectFile(); }
    catch (error) {
      if (error.code !== 'ENOENT') throw error;
      // A new app must explicitly sign in even if a native SDK session exists.
      const handle = await open(filename, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
      try { await handle.writeFile(encoded('needs_login')); await handle.sync(); } finally { await handle.close(); }
      await syncDirectory();
    }
    const handle = await open(filename, constants.O_RDONLY | constants.O_NOFOLLOW);
    try {
      const stat = await handle.stat();
      if (!stat.isFile() || stat.size > 128 || stat.nlink !== 1 || stat.uid !== process.getuid() ||
          stat.mode & 0o077) throw unavailable();
      const bytes = Buffer.alloc(129);
      const {bytesRead} = await handle.read(bytes, 0, bytes.length, 0);
      if (bytesRead > 128) throw unavailable();
      const value = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, bytesRead)));
      if (!value || Object.keys(value).length !== 2 || value.version !== 1 || !STATES.has(value.access)) throw unavailable();
      return value.access;
    } finally { await handle.close(); }
  }
  async function write(access) {
    if (!STATES.has(access)) throw unavailable();
    await secureDirectory(); await inspectFile();
    const temporary = join(directory, '.access-' + randomUUID() + '.tmp');
    try {
      const handle = await open(temporary, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
      try { await handle.writeFile(encoded(access)); await handle.sync(); } finally { await handle.close(); }
      await rename(temporary, filename); await syncDirectory();
    } finally { await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
  }
  return Object.freeze({
    read: () => serialize(read).catch(() => { throw unavailable(); }),
    write: access => serialize(() => write(access)).catch(() => { throw unavailable(); }),
  });
}
