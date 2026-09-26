import assert from 'node:assert/strict';
import test from 'node:test';
import {chmod, lstat, mkdir, mkdtemp, readFile, symlink, writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createAuthAccessStore} from './auth-access-store.mjs';

const directory = () => mkdtemp('/private/tmp/cosmas-w8u-store-test-');
test('persists a non-secret access decision atomically across instances with private permissions', async () => {
  const root = await directory(); const store = createAuthAccessStore(root);
  assert.equal(await store.read(), 'needs_login');
  await store.write('allowed'); await store.write('logout_pending');
  assert.equal(await createAuthAccessStore(root).read(), 'logout_pending');
  const path = join(root, 'workspace-auth/access.json');
  assert.equal((await lstat(path)).mode & 0o777, 0o600);
  assert.equal((await lstat(join(root, 'workspace-auth'))).mode & 0o777, 0o700);
  assert.deepEqual(JSON.parse(await readFile(path, 'utf8')), {version: 1, access: 'logout_pending'});
});

test('rejects corrupt, oversized and publicly readable state without resetting it', async () => {
  for (const content of ['invalid', '{"version":1,"access":"allowed","token":"forged"}', 'x'.repeat(129)]) {
    const root = await directory(); const store = createAuthAccessStore(root); await store.read();
    const path = join(root, 'workspace-auth/access.json'); await writeFile(path, content);
    await assert.rejects(store.read(), /^Error: Native access storage unavailable$/);
    assert.equal(await readFile(path, 'utf8'), content);
  }
  const root = await directory(); const store = createAuthAccessStore(root); await store.read();
  await chmod(join(root, 'workspace-auth/access.json'), 0o644);
  await assert.rejects(store.read(), /Native access storage unavailable/);
});

test('rejects directory and file symlinks rather than reading another location', async () => {
  const root = await directory(), outside = await directory();
  await symlink(outside, join(root, 'workspace-auth'));
  await assert.rejects(createAuthAccessStore(root).read(), /Native access storage unavailable/);
  const second = await directory(); await mkdir(join(second, 'workspace-auth'), {mode: 0o700});
  const target = join(outside, 'access.json'); await writeFile(target, 'untouched');
  await symlink(target, join(second, 'workspace-auth/access.json'));
  await assert.rejects(createAuthAccessStore(second).read(), /Native access storage unavailable/);
  assert.equal(await readFile(target, 'utf8'), 'untouched');
});
