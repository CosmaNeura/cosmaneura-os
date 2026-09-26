import assert from 'node:assert/strict';
import {createServer,request as httpRequest} from 'node:http';
import {once} from 'node:events';
import test from 'node:test';
import {fetchLocalAuthenticatedWorkspace as transport} from './local-auth-http.mjs';

const origin = 'http://127.0.0.1:8046';
const options = {method:'POST',headers:{'Content-Type':'application/json',
  Authorization:'Bearer invented.local.token', Origin:'app://cosmas'},body:'{"kind":"invented"}'};

test('fixed direct transport rejects other destinations, query data and methods before connection', async () => {
  for (const url of ['https://127.0.0.1:8046/workspaces','http://localhost:8046/workspaces',
    'http://127.0.0.1:8018/workspaces','http://127.0.0.1:8046/workspaces?token=invented',
    'http://invented@127.0.0.1:8046/workspaces',origin+'/workspaces#fragment']) {
    await assert.rejects(transport(url,options),/Local workspace unavailable/);
  }
  await assert.rejects(transport(origin+'/workspaces',{...options,method:'DELETE'}));
});

test('actual loopback transport bounds its response surface and survives failed upstream responses', async t => {
  let mode = 'json'; const observed = [];
  const server = createServer(async (request,response) => {
    const chunks=[];for await (const chunk of request) chunks.push(chunk);
    observed.push({url:request.url,method:request.method,headers:request.headers,body:Buffer.concat(chunks).toString()});
    if (mode === 'redirect') {response.writeHead(302,{Location:'https://outside.example.invalid/'});response.end();return;}
    if (mode === 'empty') {response.writeHead(204);response.end();return;}
    if (mode === 'hang') return;
    response.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Set-Cookie':'invented=ignored'});
    response.end('{"ok":true}');
  });
  server.listen(0,'127.0.0.1'); await once(server,'listening');
  const port=server.address().port;
  // Keep existing local services untouched while proving the fixed product target.
  const local=(url,options)=>transport(url,options,(address,callback)=>{
    assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);
    return httpRequest({...address,port},callback);
  });
  try {
    await t.test('signed JSON uses the direct fixed socket and does not expose cookie headers',async () => {
      const response = await local(origin+'/workspaces',options);
      assert.deepEqual(await response.json(),{ok:true});
      assert.equal(response.headers.get('set-cookie'),null);
      assert.equal(response.headers.get('cache-control'),'no-store');
      assert.equal(observed[0].headers.authorization,options.headers.Authorization);
      assert.equal(observed[0].headers.cookie,undefined);
      assert.equal(observed[0].headers.origin,'app://cosmas');
      assert.equal(observed[0].body,options.body);
    });
    await t.test('redirects fail without following the external location',async () => {
      mode='redirect'; await assert.rejects(local(origin+'/workspaces',options));
      assert.equal(observed.length,2);
    });
    await t.test('unexpected bodyless status rejects instead of crashing the main process',async () => {
      mode='empty'; await assert.rejects(local(origin+'/workspaces',options));
      mode='json'; assert.equal((await local(origin+'/workspaces',options)).status,200);
    });
    await t.test('cancellation closes an outstanding direct request',async () => {
      mode='hang';const controller=new AbortController();
      const pending=local(origin+'/workspaces',{...options,signal:controller.signal});
      const rejected=assert.rejects(pending,/Local workspace unavailable/);
      controller.abort();await rejected;
    });
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
