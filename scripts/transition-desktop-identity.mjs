/** Offline operator tool. Quit CosmaBot first and keep it closed until completion. */
import {execFile} from 'node:child_process';
import {constants} from 'node:fs';
import {lstat, mkdir, open, readFile, realpath, rename, rmdir, unlink} from 'node:fs/promises';
import {createHash, randomUUID} from 'node:crypto';
import {homedir} from 'node:os';
import {dirname, isAbsolute, join, resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {promisify} from 'node:util';
import {validateOperationalNativeIdentity} from '../clients/desktop/native-identity-config.mjs';

const run = promisify(execFile);
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const refuse = () => { throw new Error('Desktop identity transition refused; saved workspace was preserved'); };
const keys = ['contract', 'transitionId', 'sourceIdentity', 'targetIdentity', 'sourceMarkerSha256', 'expiresAt'];
const identityHash = value => hash(JSON.stringify(value, Object.keys(value).sort()));

function checkedPlan(plan, now) {
  if (!plan || Object.keys(plan).length !== keys.length || keys.some(key => !Object.hasOwn(plan, key)) ||
      plan.contract !== 'cosmas-desktop-identity-transition-v1' ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(plan.transitionId) ||
      !/^[0-9a-f]{64}$/.test(plan.sourceMarkerSha256) || typeof plan.expiresAt !== 'string' ||
      !/(Z|\+00:00)$/.test(plan.expiresAt) || !(Date.parse(plan.expiresAt) > now) ||
      Date.parse(plan.expiresAt) > now + 24 * 60 * 60 * 1000) refuse();
  const source = validateOperationalNativeIdentity(plan.sourceIdentity, 'desktop', plan.sourceIdentity?.apiOrigin);
  const target = validateOperationalNativeIdentity(plan.targetIdentity, 'desktop', source.apiOrigin);
  if (source.profile !== 'operational-beta-v1' || target.profile !== 'operational-staging-v1' ||
      source.frontendOrigin === target.frontendOrigin) refuse();
  const marker = identity => ({contract: 'cosmas-os-desktop-installation-v1',
    bundleIdentifier: 'com.cosmasos.beta.desktop', storageGeneration: 1, electronVersion: '43.4.1',
    rendererPartition: 'persist:cosmasos-operational-beta', authHelperBundleIdentifier: 'com.cosmasos.beta.desktop.auth',
    apiOrigin: source.apiOrigin, dataMode: 'synthetic', identityBinding: identityHash(identity)});
  // A later approved rollback can have a new deadline; JSON key order is irrelevant.
  const immutable = {contract: plan.contract, transitionId: plan.transitionId, sourceIdentity: identityHash(source),
    targetIdentity: identityHash(target), sourceMarkerSha256: plan.sourceMarkerSha256};
  return {before: marker(source), after: marker(target), digest: hash(JSON.stringify(immutable))};
}

async function secureDirectory(path) {
  const stat = await lstat(path);
  if (!isAbsolute(path) || resolve(path) !== path || await realpath(path) !== path ||
      !stat.isDirectory() || stat.isSymbolicLink() || stat.uid !== process.getuid() || stat.mode & 0o077) refuse();
}

async function readPrivate(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const stat = await file.stat();
    if (!stat.isFile() || stat.nlink !== 1 || stat.uid !== process.getuid() || stat.mode & 0o077 || stat.size > 16384) refuse();
    const buffer = Buffer.alloc(16385);
    const {bytesRead} = await file.read(buffer, 0, buffer.length, 0);
    if (bytesRead > 16384) refuse();
    return buffer.subarray(0, bytesRead);
  } finally { await file.close(); }
}

async function syncDirectory(path) {
  const file = await open(path, constants.O_RDONLY | constants.O_DIRECTORY | constants.O_NOFOLLOW);
  try { await file.sync(); } finally { await file.close(); }
}

async function replace(path, bytes) {
  const temporary = path + '.' + randomUUID() + '.tmp';
  const file = await open(temporary, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600);
  try {
    await file.writeFile(bytes); await file.sync(); await file.close();
    await rename(temporary, path); await syncDirectory(dirname(path));
  } finally {
    await file.close();
    await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; });
  }
}

export function isDesktopProfileProcess(command, profile) {
  // Scribe also uses the audio/presentation helper names. Its independent app
  // must not block this transition; CosmaBot's packaged helpers match its path.
  return command.includes(profile) ||
    /\/(?:CosmaBot|CosmasOS)[^/]*\.app\//i.test(command) ||
    /\/CosmasDesktopAuth(?:\s|$)/.test(command);
}

export async function assertMacQuiescent(profile) {
  if (process.platform !== 'darwin') refuse();
  // Inspect executable names, not argument strings that may contain this manifest path.
  const {stdout} = await run('/bin/ps', ['-axo', 'comm='], {maxBuffer: 4 * 1024 * 1024});
  if (stdout.split('\n').some(command => isDesktopProfileProcess(command, profile))) refuse();
  // Fail on open state files or any inspection error except lsof's no-match status.
  try {
    await run('/usr/sbin/lsof', ['-F', 'p', '+D', profile], {maxBuffer: 1024 * 1024});
  } catch (error) {
    if (error.code === 1 && error.stdout === '' && error.stderr === '') return;
    throw error;
  }
  refuse();
}

export async function transitionDesktopIdentity({profile, plan, action, quiescent = assertMacQuiescent, now = Date.now()}) {
  if (!['plan', 'apply', 'rollback'].includes(action)) refuse();
  const expected = checkedPlan(plan, now);
  await secureDirectory(dirname(profile)); await secureDirectory(profile);
  const lock = join(profile, '.cosmas-identity-maintenance');
  if (action !== 'plan') { await mkdir(lock, {mode: 0o700}); await syncDirectory(profile); }
  try { return await transitionWhileStopped(profile, plan, action, expected, quiescent); }
  finally {
    if (action !== 'plan') { await rmdir(lock); await syncDirectory(profile); }
  }
}

async function transitionWhileStopped(profile, plan, action, expected, quiescent) {
  await quiescent(profile);
  const filename = join(profile, 'cosmas-installation.json');
  const receiptPath = join(profile, 'identity-transition-' + plan.transitionId + '.json');
  const current = await readPrivate(filename);
  const actual = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(current));
  const matches = value => actual && Object.keys(actual).length === Object.keys(value).length &&
    Object.entries(value).every(([key, content]) => actual[key] === content);
  const isBefore = matches(expected.before) && hash(current) === plan.sourceMarkerSha256;
  const isAfter = matches(expected.after);
  if (!isBefore && !isAfter) refuse();
  let receipt;
  try { receipt = JSON.parse(await readPrivate(receiptPath)); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  const after = Buffer.from(JSON.stringify(expected.after) + '\n');
  if (receipt !== undefined) {
    if (!receipt || Object.keys(receipt).length !== 4 || receipt.contract !== 'cosmas-desktop-identity-recovery-v1' ||
        receipt.requestSha256 !== expected.digest || typeof receipt.originalMarker !== 'string' ||
        hash(Buffer.from(receipt.originalMarker, 'base64')) !== plan.sourceMarkerSha256 ||
        receipt.targetMarkerSha256 !== hash(after)) refuse();
  } else if (!isBefore || action === 'rollback') refuse();
  if (isAfter && !current.equals(after)) refuse();
  if (action === 'plan') return {status: isAfter ? 'already_applied' : 'ready', requestSha256: expected.digest};
  if (action === 'apply' && isAfter || action === 'rollback' && isBefore) {
    return {status: action === 'apply' ? 'already_applied' : 'already_rolled_back', requestSha256: expected.digest};
  }
  // The immutable original marker is durable before its atomic replacement.
  if (receipt === undefined) {
    receipt = {contract: 'cosmas-desktop-identity-recovery-v1', requestSha256: expected.digest,
      originalMarker: current.toString('base64'), targetMarkerSha256: hash(after)};
    await replace(receiptPath, Buffer.from(JSON.stringify(receipt) + '\n'));
  }
  await quiescent(profile);
  checkedPlan(plan, Date.now());
  if (!(await readPrivate(filename)).equals(current)) refuse();
  await replace(filename, action === 'apply' ? after : Buffer.from(receipt.originalMarker, 'base64'));
  return {status: action === 'apply' ? 'applied' : 'rolled_back', requestSha256: expected.digest};
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const [action, manifest, confirmation, ...extra] = process.argv.slice(2);
    if (extra.length || confirmation !== '--confirm-offline-staging-maintenance') refuse();
    const raw = await readFile(manifest);
    if (raw.length > 16384) refuse();
    const plan = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(raw));
    const profile = join(homedir(), 'Library/Application Support/CosmasOS Beta/com.cosmasos.beta.desktop');
    console.log(JSON.stringify(await transitionDesktopIdentity({profile, plan, action})));
  } catch {
    console.error('Desktop identity transition refused; retain the profile and recovery receipt for inspection');
    process.exitCode = 1;
  }
}
