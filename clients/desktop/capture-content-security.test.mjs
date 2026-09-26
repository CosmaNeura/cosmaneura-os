import assert from 'node:assert/strict';
import test from 'node:test';
import {captureContentSecurityPolicy, privateDocumentContentSecurityPolicy, installCaptureContentSecurityPolicy} from './capture-content-security.mjs';

const base = "default-src 'none'; connect-src 'self'; script-src 'self'; media-src 'none'; object-src 'none'";
test('private PDF frames allow only local blobs and preserve all other retained restrictions', () => {
  const capture = captureContentSecurityPolicy(base, ['https://storage.invalid']);
  assert.equal(privateDocumentContentSecurityPolicy(capture), capture + '; frame-src blob:');
  assert.equal(privateDocumentContentSecurityPolicy(base + "; frame-src 'none'"), base + '; frame-src blob:');
  for (const invalid of [null, base.replace("object-src 'none'", 'object-src *'),
    base.replace("default-src 'none'", "default-src 'self'"),
    base + '; frame-src https:', base + '; frame-src blob:',
    base + "; frame-src 'none'; frame-src 'none'", base + "; object-src 'none'"]) {
    assert.throws(() => privateDocumentContentSecurityPolicy(invalid));
  }
});
test('upload access is absent by default and changes only connect-src for exact origins', () => {
  assert.equal(captureContentSecurityPolicy(base), base);
  assert.equal(captureContentSecurityPolicy(base, []), base);
  assert.equal(captureContentSecurityPolicy(base, ['https://storage.invalid', 'https://storage.invalid']),
    base.replace("connect-src 'self'", "connect-src 'self' https://storage.invalid"));
});
test('unbounded origins, schemes, credentials, paths and directive injection fail closed', () => {
  for (const origins of [null, {}, 'https://storage.invalid', Array(5).fill('https://storage.invalid'),
    ...['*', 'https:', 'http://storage.invalid', 'https://*.invalid', 'https://user@storage.invalid',
      'https://storage.invalid/', 'https://storage.invalid/path', 'https://storage.invalid?sig=x',
      'https://storage.invalid#x', 'https://storage.invalid:443', 'https://storage.invalid; script-src *',
      'https://storage.invalid\nhttps://other.invalid', 'https://localhost', 'https://a..invalid',
      'https://-a.invalid', 'https://storage.invalid.', 'https://127.1', 'https://0x7f000001'].map(value => [value])]) {
    assert.throws(() => captureContentSecurityPolicy(base, origins), JSON.stringify(origins));
  }
  assert.throws(() => captureContentSecurityPolicy("default-src 'none'", []));
  assert.throws(() => captureContentSecurityPolicy("connect-src *", []));
  assert.throws(() => captureContentSecurityPolicy("connect-src 'self'; connect-src 'self'", []));
});
test('the installed header preserves other restrictions and removes differently cased duplicate CSP', () => {
  let handler;
  const policy = captureContentSecurityPolicy(base, ['https://storage.invalid']);
  installCaptureContentSecurityPolicy({onHeadersReceived: value => { handler = value; }}, policy);
  let result;
  handler({responseHeaders: {'content-security-policy': ['connect-src *'], 'Cache-Control': ['no-store']}}, value => { result = value; });
  assert.deepEqual(result, {responseHeaders: {'Cache-Control': ['no-store'], 'Content-Security-Policy': [policy]}});
});
