import assert from 'node:assert/strict';
import {createServer,request as httpRequest} from 'node:http';
import {once,EventEmitter} from 'node:events';
import {PassThrough} from 'node:stream';
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
      assert.equal(observed[0].headers['content-length'],String(Buffer.byteLength(options.body)));
      assert.equal(observed[0].headers['transfer-encoding'],undefined);
    });
    await t.test('UTF-8 JSON, sliced PDF bytes and GET retain exact actual socket framing',async()=>{
      const body='{"display_name":"Jos\u00e9 \ud83e\ude7a"}';
      await (await local(origin+'/practice-access/setup/complete',{...options,body})).text();
      const unicode=observed.at(-1);
      assert.equal(unicode.headers['content-length'],String(Buffer.byteLength(body)));
      assert.equal(unicode.headers['transfer-encoding'],undefined);assert.equal(unicode.body,body);
      const bytes=Buffer.from('prefix%PDF-1.7\nreviewedsuffix'),pdf=bytes.subarray(6,bytes.length-6);
      await (await local(origin+'/workspaces/00000000-0000-4000-8000-000000000001/vendor-artifacts/00000000-0000-4000-8000-000000000002/content',{
        method:'PUT',headers:{'Content-Type':'application/pdf','X-Cosmas-Vendor-Contract':'1'},body:pdf})).text();
      const binary=observed.at(-1);
      assert.equal(binary.headers['content-length'],String(pdf.byteLength));
      assert.equal(binary.headers['transfer-encoding'],undefined);assert.equal(binary.body,pdf.toString());
      await (await local(origin+'/workspaces',{...options,method:'GET',body:undefined})).text();
      assert.equal(observed.at(-1).body,'');assert.equal(observed.at(-1).headers['transfer-encoding'],undefined);
    });
    await t.test('redirects fail without following the external location',async () => {
      mode='redirect'; await assert.rejects(local(origin+'/workspaces',options));
      assert.equal(observed.length,5);
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

test('frames UTF-8, empty JSON and binary bytes exactly without caller framing or mutation',async()=>{
  const inputs=['{"name":"Jos\u00e9 \ud83e\ude7a"}','',new Uint8Array([0,128,255])];
  for(const body of inputs){
    let address,sent;
    const headers={'Content-Type':'application/json'};
    const expected=Buffer.from(body);
    const pending=transport(origin+'/workspaces',{method:'POST',headers,body},(value,reply)=>{
      address=value;const request=new EventEmitter();
      request.write=value=>{sent=Buffer.from(value);if(body instanceof Uint8Array)body.fill(0);};
      request.end=()=>{const response=new PassThrough();response.statusCode=200;response.headers={'content-type':'application/json','cache-control':'no-store'};reply(response);response.end('{}');};
      return request;
    });
    await pending;
    assert.equal(address.headers['Content-Length'],String(expected.byteLength));
    assert.deepEqual(sent??Buffer.alloc(0),expected);
    assert.deepEqual(headers,{'Content-Type':'application/json'});
  }
  for(const bad of [{headers:{'Transfer-Encoding':'chunked'}},{headers:{'content-length':'1'}},{body:{private:'unsupported'}},{method:'GET',body:'{}'}])
    await assert.rejects(transport(origin+'/workspaces',{...options,...bad},()=>assert.fail('no socket on invalid framing')));
});
