import assert from 'node:assert/strict';
import test from 'node:test';
import {permittedApiPath, proxyWorkspaceRequest} from './api-proxy.mjs';

const id = '00000000-0000-4000-8000-000000000001';
test('only listed same-origin workspace routes can reach the loopback API', () => {
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}`, 'GET'), `/workspaces/${id}`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/conversation`, 'POST'), `/workspaces/${id}/conversation`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/handoffs/${id}/retry`, 'POST'), `/workspaces/${id}/handoffs/${id}/retry`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/handoffs/${id}/execute`, 'POST'), null);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/notes`, 'POST'), `/workspaces/${id}/notes`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/notes/${id}/review`, 'POST'), `/workspaces/${id}/notes/${id}/review`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/notes/${id}/sign`, 'POST'), null);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/follow-ups`, 'POST'), `/workspaces/${id}/follow-ups`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/follow-ups/${id}/decide`, 'POST'), `/workspaces/${id}/follow-ups/${id}/decide`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/follow-ups/${id}/complete`, 'POST'), `/workspaces/${id}/follow-ups/${id}/complete`);
  assert.equal(permittedApiPath(`app://cosmas/api/workspaces/${id}/follow-ups/${id}/send`, 'POST'), null);
  for (const url of ['https://cosmas/api/workspaces', 'app://other/api/workspaces',
    'app://user@cosmas/api/workspaces', 'app://cosmas:8018/api/workspaces',
    'app://cosmas/api/workspaces?url=https://outside.invalid', 'app://cosmas/api/admin/identities/bind',
    'app://cosmas/api/retention/purge', 'app://cosmas/api/../../private',
    'app://cosmas/api/workspaces/%2f..%2fadmin']) {
    assert.equal(permittedApiPath(url, 'POST'), null, url);
  }
  assert.equal(permittedApiPath('app://cosmas/api/workspaces', 'DELETE'), null);
});

test('proxy forwards only synthetic identity and JSON; no cookies or bearer credentials', async () => {
  let captured;
  const request = new Request('app://cosmas/api/provider-team', {method: 'POST',
    headers: {'X-Box-Id': id, 'X-Actor-Principal-Id': id, Authorization: 'invented-secret', Cookie: 'invented-cookie'},
    body: '{"configuration":"invented"}'});
  const response = await proxyWorkspaceRequest(request, async (url, options) => {
    captured = {url, options};
    return Response.json({saved: true}, {headers: {'Set-Cookie': 'invented-upstream-cookie'}});
  });
  assert.equal(captured.url, 'http://127.0.0.1:8018/provider-team');
  assert.equal(captured.options.headers.get('x-box-id'), id);
  assert.equal(captured.options.headers.get('authorization'), null);
  assert.equal(captured.options.headers.get('cookie'), null);
  assert.equal(captured.options.redirect, 'error');
  assert.equal(response.headers.get('set-cookie'), null);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await response.json(), {saved: true});
});

test('oversized input and malformed identity do not invoke an upstream service', async () => {
  let count = 0;
  const upstream = async () => { count++; return Response.json({}); };
  const large = await proxyWorkspaceRequest(new Request('app://cosmas/api/provider-team',
    {method: 'POST', body: 'x'.repeat(128_001)}), upstream);
  assert.equal(large.status, 503);
  const malformed = await proxyWorkspaceRequest(new Request('app://cosmas/api/provider-team',
    {headers: {'X-Box-Id': 'not-an-id'}}), upstream);
  assert.equal(malformed.status, 400);
  assert.equal(count, 0);
});

test('upstream errors, redirects and non-JSON responses never disclose private details', async () => {
  for (const upstream of [async () => { throw new Error('private-details'); },
    async () => new Response('private-details', {status: 302, headers: {Location: 'https://outside.invalid'}}),
    async () => new Response('private-details', {headers: {'content-type': 'text/html'}})]) {
    const response = await proxyWorkspaceRequest(new Request('app://cosmas/api/workspaces'), upstream);
    assert.ok([502, 503].includes(response.status));
    assert.ok(!(await response.text()).includes('private-details'));
  }
});
