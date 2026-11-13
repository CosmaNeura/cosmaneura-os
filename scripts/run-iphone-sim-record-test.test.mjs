import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, writeFile, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const RUNNER = join(ROOT, 'scripts/run-iphone-sim-record-test.sh');

const IPHONE_18_PRO_MAX = 'com.apple.CoreSimulator.SimDeviceType.iPhone-18-Pro-Max';
const IPHONE_DUO = 'com.apple.CoreSimulator.SimDeviceType.iPhone-Duo';

const runtimesFour = {
  runtimes: [
    {
      name: 'iOS 26.5',
      version: '26.5',
      platform: 'iOS',
      identifier: 'com.apple.CoreSimulator.SimRuntime.iOS-26-5',
      isAvailable: true,
      supportedDeviceTypes: [
        {name: 'iPhone 18 Pro Max', identifier: IPHONE_18_PRO_MAX},
        {name: 'iPhone 16', identifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'},
      ],
    },
    {
      name: 'iOS 27.0',
      version: '27.0',
      platform: 'iOS',
      identifier: 'com.apple.CoreSimulator.SimRuntime.iOS-27-0',
      isAvailable: true,
      supportedDeviceTypes: [
        {name: 'iPhone 18 Pro Max', identifier: IPHONE_18_PRO_MAX},
        {name: 'iPhone 16', identifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'},
      ],
    },
    {
      name: 'iOS 27.2',
      version: '27.2',
      platform: 'iOS',
      identifier: 'com.apple.CoreSimulator.SimRuntime.iOS-27-2',
      isAvailable: true,
      supportedDeviceTypes: [
        {name: 'iPhone 18 Pro Max', identifier: IPHONE_18_PRO_MAX},
        {name: 'iPhone 16', identifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'},
      ],
    },
    {
      name: 'iOS 27.2 iPhone Duo',
      version: '27.2',
      platform: 'iOS',
      identifier: 'com.apple.CoreSimulator.SimRuntime.iOS-27-2-iPhone19-4',
      isAvailable: true,
      supportedDeviceTypes: [{name: 'iPhone Duo', identifier: IPHONE_DUO}],
    },
  ],
};

const deviceTypes = {
  devicetypes: [
    {name: 'iPhone 18 Pro Max', identifier: IPHONE_18_PRO_MAX},
    {name: 'iPhone 16', identifier: 'com.apple.CoreSimulator.SimDeviceType.iPhone-16'},
    {name: 'iPhone Duo', identifier: IPHONE_DUO},
  ],
};

function runRunner(args) {
  return spawnSync('bash', [RUNNER, ...args], {encoding: 'utf8'});
}

test('select-runtime-and-iphone skips Duo-only runtime and picks newest iPhone', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'cosmas-runner-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const runtimesPath = join(dir, 'runtimes.json');
  const devicesPath = join(dir, 'devicetypes.json');
  await writeFile(runtimesPath, JSON.stringify(runtimesFour));
  await writeFile(devicesPath, JSON.stringify(deviceTypes));
  const result = runRunner(['--select-runtime-and-iphone', runtimesPath, devicesPath]);
  assert.equal(result.status, 0, result.stderr);
  const [runtimeId, deviceId] = result.stdout.trim().split('\t');
  assert.equal(runtimeId, 'com.apple.CoreSimulator.SimRuntime.iOS-27-2');
  assert.equal(deviceId, IPHONE_18_PRO_MAX);
  assert.equal(result.stdout.includes('iPhone19-4'), false);
});

test('select-runtime-for-device keeps fixture behaviour for iPhone19-4 skip', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'cosmas-runner-'));
  t.after(() => rm(dir, {recursive: true, force: true}));
  const runtimesPath = join(dir, 'runtimes.json');
  await writeFile(runtimesPath, JSON.stringify(runtimesFour));
  const result = runRunner(['--select-runtime-for-device', IPHONE_18_PRO_MAX, runtimesPath]);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout.trim(), 'com.apple.CoreSimulator.SimRuntime.iOS-27-2');
});

test('runner documents full SHA or PR number for remote refs', async () => {
  const {readFile} = await import('node:fs/promises');
  const text = await readFile(RUNNER, 'utf8');
  assert.match(text, /full 40-character SHA or a PR number/);
  assert.match(text, /Abbreviated SHAs are resolved only when already present/);
  // Abbreviated path resolves locally then fetches the full object name.
  assert.match(text, /git fetch --depth=1 origin "\$full"/);
  assert.match(text, /Pass a full 40-character SHA or a PR number/);
});
