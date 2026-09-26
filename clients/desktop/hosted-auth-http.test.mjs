import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
import test from 'node:test';
import {createHostedWorkspaceTransport} from './hosted-auth-http.mjs';
import {proxyAuthenticatedWorkspaceRequest} from './workspace-auth-proxy.mjs';

const origin = 'https://api.example.invalid';
test('hosted requests pin TLS identity and discard upstream cookies and redirects', async () => {
  const seen = []; let status = 200;
  const transport = createHostedWorkspaceTransport(origin, (address, callback) => {
    seen.push(address);
    const request = new EventEmitter();
    request.write = () => {};
    request.end = () => {
      const response = new PassThrough(); response.statusCode = status;
      response.headers = {'content-type':'application/json','cache-control':'no-store','set-cookie':'private=ignored'};
      callback(response); response.end('{"ok":true}');
    };
    return request;
  });
  const response = await transport(origin + '/workspaces', {method:'GET',headers:{Authorization:'Bearer invented'}});
  assert.deepEqual(await response.json(),{ok:true}); assert.equal(response.headers.get('set-cookie'),null);
  assert.equal(seen[0].host,'api.example.invalid'); assert.equal(seen[0].servername,'api.example.invalid');
  assert.equal(seen[0].port,443); assert.equal(seen[0].rejectUnauthorized,true); assert.equal(seen[0].minVersion,'TLSv1.2');
  assert.equal(seen[0].agent,false);
  for(const url of ['https://other.example.invalid/workspaces',origin+'/workspaces?token=secret',origin+'/workspaces#x'])
    await assert.rejects(transport(url,{method:'GET',headers:{}}));
  assert.equal(seen.length,1);
  status=302; await assert.rejects(transport(origin+'/workspaces',{method:'GET',headers:{}}));
  assert.equal(seen.length,2);
});

test('the desktop bridge keeps credentials native and its closed route list on HTTPS', async () => {
  const revision='00000000-0000-4000-8000-000000000001';
  const ready={phase:'ready',revision,identity:{userId:'user_one',sessionId:'sess_one',organizationId:'org_one'}};
  let tokens=0,requests=0;
  const auth={getState:async()=>ready,snapshot:()=>ready,getToken:async()=>{tokens++;return 'invented.native.token';},subscribe:()=>()=>{}};
  const request=path=>new Request('app://cosmas/api'+path,{headers:{'X-Cosmas-Desktop-Session':revision,'Content-Type':'application/json'}});
  const fetcher=async(url,options)=>{
    requests++;assert.equal(url,origin+'/workspaces');assert.equal(options.headers.Authorization,'Bearer invented.native.token');
    return new Response('[]',{headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  };
  assert.equal((await proxyAuthenticatedWorkspaceRequest(request('/workspaces'),auth,fetcher,origin)).status,200);
  assert.equal((await proxyAuthenticatedWorkspaceRequest(request('/synth/seed'),auth,fetcher,origin)).status,404);
  assert.equal((await proxyAuthenticatedWorkspaceRequest(request('/workspaces'),auth,fetcher,'http://remote.invalid')).status,503);
  assert.equal(tokens,1);assert.equal(requests,1);
});
