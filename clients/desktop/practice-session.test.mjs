import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import test from 'node:test';
import {createDesktopPracticeSession} from './practice-session.mjs';
import {createFakePracticeAccountWire} from './practice-fake-wire.mjs';
function productionInfos() {
  const host = 'clerk.cosmas.ai';
  return {
    enabled: true,
    accountOrigin: 'https://enrollment-api.cosmas.ai',
    realm: {
      publishableKey: 'pk_live_' + Buffer.from(`${host}$`).toString('base64'),
      frontendOrigin: `https://${host}`,
      audience: 'cosmabot-practice-api',
      profile: 'operational-beta-v1',
      keychainNamespace: 'c'.repeat(64),
    },
    apiOrigins: [],
    registeredPracticeOrigins: 'practice-uuid-production-v1',
  };
}

function mockConfigRequest() {
  return (url, options, callback) => {
    const req = new EventEmitter();
    req.write = () => {};
    req.end = () => {
      const res = new EventEmitter();
      res.statusCode = 200;
      queueMicrotask(() => {
        callback(res);
        res.emit('data', Buffer.from(JSON.stringify({
          contract_version: 'enrollment.v1', enabled: true, data_mode: 'production',
          native_account: {
            issuer: 'https://clerk.cosmas.ai', audience: 'cosmabot-practice-api',
            session_policy: 'practice-uuid-production-v1', native_origin: 'app://cosmas',
          },
        }), 'utf8'));
        res.emit('end');
      });
    };
    req.destroy = () => {};
    return req;
  };
}

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

test('openCheckout aliases destination open and signOut clears account', async () => {
  const practice = await createDesktopPracticeSession({enabled: true});
  const ready = await practice.beginAccountSignIn();
  assert.deepEqual(
    await practice.openCheckout({
      expectedRevision: ready.revision, checkoutSessionId: 'cs_invented',
    }),
    {status: 'opened'},
  );
  assert.deepEqual(
    await practice.openEnrollmentDestination({
      expectedRevision: ready.revision, destination: 'portal',
    }),
    {status: 'opened'},
  );
  const signedOut = await practice.signOut({expectedRevision: ready.revision});
  assert.equal(signedOut.phase, 'signedOut');
  assert.equal(signedOut.identity, null);
  practice.close();
});

test('fake wire returns closed shapes for practices and unknown ops', async () => {
  const wire = createFakePracticeAccountWire();
  const practices = await wire.enrollmentRequest('practices');
  assert.equal(practices.status, 200);
  assert.equal(practices.body.active_practice_id, wire.PRACTICE_ID);
  const missing = await wire.enrollmentRequest('unknown');
  assert.equal(missing.status, 404);
  assert.throws(
    () => createFakePracticeAccountWire({nativeOrigin: 'https://evil.example'}),
    /Origin app:\/\/cosmas/,
  );
});

test('subscribe receives account events and close fences further calls', async () => {
  const practice = await createDesktopPracticeSession({enabled: true});
  const events = [];
  const stop = practice.subscribe(state => { events.push(state.phase); });
  await practice.beginAccountSignIn();
  stop();
  await practice.signOut({expectedRevision: practice.snapshot().revision});
  assert.deepEqual(events, ['signingIn', 'accountReady']);
  practice.close();
  await assert.rejects(practice.capabilities(), /unavailable/);
  await assert.rejects(practice.beginAccountSignIn(), /unavailable/);
});

test('host method surface matches detector-required CosmasDesktopPractice keys', async () => {
  const practice = await createDesktopPracticeSession({enabled: true});
  const required = [
    'capabilities', 'accountStatus', 'beginAccountSignIn', 'accountToken', 'enrollmentRequest',
    'openCheckout', 'openEnrollmentDestination', 'activatePracticeOrganization',
    'activateRegisteredPractice', 'returnToBeta', 'signOut',
  ];
  for (const name of required) assert.equal(typeof practice[name], 'function');
  assert.equal(typeof practice.getToken, 'undefined');
  practice.close();
});

test('production Infos refuses fake wire and blocks Open Chief without signed helper', async () => {
  await assert.rejects(
    createDesktopPracticeSession({
      enabled: true, infos: productionInfos(), wire: createFakePracticeAccountWire(),
    }),
    /cannot use a fake\/local/,
  );

  const {createHttpsPracticeAccountWire} = await import('./practice-https-wire.mjs');
  const practice = await createDesktopPracticeSession({
    enabled: true,
    infos: productionInfos(),
    wire: createHttpsPracticeAccountWire({
      infos: productionInfos(),
      requestImplementation: mockConfigRequest(),
    }),
  });
  assert.deepEqual(await practice.capabilities(), {
    contract_version: 'cosmabot.native-practice-connection.v1',
    available: true, enrollment_available: true,
  });
  const config = await practice.enrollmentRequest({
    expectedRevision: practice.snapshot().revision, operation: 'config',
  });
  assert.equal(config.status, 200);
  assert.equal(config.body.native_account.issuer, 'https://clerk.cosmas.ai');
  await assert.rejects(practice.beginAccountSignIn(), /signed CosmasNativePracticeConnection helper/);
  await assert.rejects(
    practice.activateRegisteredPractice({expectedRevision: practice.snapshot().revision}),
    /signed CosmasNativePracticeConnection helper/,
  );
  practice.close();
});
