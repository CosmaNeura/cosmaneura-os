import assert from 'node:assert/strict';
import test from 'node:test';
import {createDesktopPracticeSession} from './practice-session.mjs';
import {createFakePracticeAccountWire} from './practice-fake-wire.mjs';

test('disabled practice host stays dark and rejects sign-in', async () => {
  const practice = await createDesktopPracticeSession({enabled: false});
  assert.deepEqual(await practice.capabilities(), {
    contract_version: 'cosmabot.native-practice-connection.v1',
    available: false, enrollment_available: false,
  });
  await assert.rejects(practice.beginAccountSignIn(), /unavailable/);
  practice.close();
});

test('enabled fake host opens Connect practice through Open Chief', async () => {
  const admitted = [];
  const practice = await createDesktopPracticeSession({
    enabled: true,
    wire: createFakePracticeAccountWire(),
    admitWorkspace: async snapshot => { admitted.push(snapshot); },
  });
  const capabilities = await practice.capabilities();
  assert.equal(capabilities.available, true);
  assert.equal(capabilities.enrollment_available, true);

  const config = await practice.enrollmentRequest({
    expectedRevision: practice.snapshot().revision, operation: 'config',
  });
  assert.equal(config.status, 200);
  assert.equal(config.body.native_account.native_origin, 'app://cosmas');
  assert.equal(config.body.data_mode, 'synthetic');

  const signedIn = await practice.beginAccountSignIn();
  assert.equal(signedIn.phase, 'accountReady');
  assert.equal(signedIn.identity.userId, 'user_invented_desktop');

  const status = await practice.enrollmentRequest({
    expectedRevision: signedIn.revision, operation: 'status',
  });
  assert.equal(status.body.stage, 'ready');
  assert.match(status.body.workspace.url, /\/chief$/);

  const token = await practice.accountToken({expectedRevision: signedIn.revision});
  assert.match(token.token, /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);

  const org = await practice.activatePracticeOrganization({expectedRevision: signedIn.revision});
  assert.equal(org.revision, signedIn.revision);

  const snapshot = await practice.activateRegisteredPractice({expectedRevision: signedIn.revision});
  assert.equal(snapshot.contract_version, 'cosmabot.native-active-workspace.v1');
  assert.equal(snapshot.profile.client, 'desktop');
  assert.equal(snapshot.profile.native_origin, 'app://cosmas');
  assert.equal(snapshot.profile.session.subject, 'user_invented_desktop');
  assert.equal(admitted.length, 1);
  assert.equal(admitted[0], snapshot);

  await practice.returnToBeta({expectedRevision: signedIn.revision});
  assert.equal(practice.snapshot().phase, 'signedOut');
  practice.close();
});

test('revision fencing rejects stale activate and enrollment calls', async () => {
  const practice = await createDesktopPracticeSession({enabled: true});
  const ready = await practice.beginAccountSignIn();
  await assert.rejects(
    practice.activateRegisteredPractice({expectedRevision: '00000000-0000-4000-8000-000000000099'}),
    /unavailable/,
  );
  await assert.rejects(
    practice.enrollmentRequest({expectedRevision: ready.revision, operation: 'not-an-op'}),
    /unavailable/,
  );
  practice.close();
});
