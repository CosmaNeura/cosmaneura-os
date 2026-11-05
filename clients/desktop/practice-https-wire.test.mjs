import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import test from 'node:test';
import {createHttpsPracticeAccountWire} from './practice-https-wire.mjs';

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

function mockRequest(handler) {
  return (url, options, callback) => {
    const req = new EventEmitter();
    req.write = () => {};
    req.end = () => {
      const res = new EventEmitter();
      res.statusCode = 200;
      queueMicrotask(() => {
        handler({url, options, res});
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

test('production Infos wire pins enrollment-api and Origin for /native/config', async () => {
  const seen = [];
  const wire = createHttpsPracticeAccountWire({
    infos: productionInfos(),
    requestImplementation: mockRequest(({url, options}) => {
      seen.push({href: url.href, method: options.method, headers: options.headers});
    }),
  });
  assert.equal(wire.production, true);
  assert.equal(wire.accountOrigin, 'https://enrollment-api.cosmas.ai');
  const reply = await wire.enrollmentRequest('config');
  assert.equal(reply.status, 200);
  assert.equal(reply.body.native_account.native_origin, 'app://cosmas');
  assert.equal(seen.length, 1);
  assert.equal(seen[0].href, 'https://enrollment-api.cosmas.ai/enrollment/v1/native/config');
  assert.equal(seen[0].method, 'GET');
  assert.equal(seen[0].headers.Origin, 'app://cosmas');
  assert.equal(seen[0].headers.Authorization, undefined);
});

test('bearer-required ops fail closed without signed helper token source', async () => {
  const wire = createHttpsPracticeAccountWire({
    infos: productionInfos(),
    requestImplementation: mockRequest(() => {}),
  });
  await assert.rejects(
    wire.enrollmentRequest('status'),
    /signed account-realm bearer token/,
  );
});

test('disabled Infos refuses wire construction', () => {
  assert.throws(
    () => createHttpsPracticeAccountWire({infos: {...productionInfos(), enabled: false}}),
    /disabled/,
  );
});
