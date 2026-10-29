import assert from 'node:assert/strict';
import test from 'node:test';
import {once} from 'node:events';
import {createServer, request as httpRequest} from 'node:http';
import {connectorApiRoute, CONNECTOR_HEADERS} from './connector-api-routes.mjs';
import {permittedAuthenticatedApiPath, proxyAuthenticatedWorkspaceRequest as proxy} from './workspace-auth-proxy.mjs';
import {fetchLocalAuthenticatedWorkspace as local} from './local-auth-http.mjs';

const id = '00000000-0000-4000-8000-000000000071';
const header = 'X-Cosmas-Conversations';
const cursor = 'c1' + 'a'.repeat(160);
const watermark = 'r1' + 'a'.repeat(16) + 'r' + 'b'.repeat(96);
const collection = '/workspaces/conversations';
const marker = `/workspaces/${id}/conversations/chief/read`;
const paths = [[collection, 'GET', 0], [collection + '/pages/' + cursor, 'GET', 0],
  ...['chief', 'scribe', 'visit_prep', 'follow_up', id].map(bot => [`/workspaces/${id}/conversations/${bot}/read`, 'POST', 4096])];
const tick = () => new Promise(resolve => setImmediate(resolve));
const sized = length => '{}' + ' '.repeat(length - 2);
const response = (body='{}', status=200, extra={}) => new Response(body, {status,
  headers:{'Content-Type':'application/json', 'Cache-Control':'no-store', ...extra}});
function auth() {
  let state = {phase:'ready', revision:id, identity:{userId:'invented', sessionId:'invented', organizationId:'invented'}};
  let tokens = 0;
  const listeners = new Set();
  return {getState:async()=>state, snapshot:()=>state, getToken:async()=>{tokens++;return 'invented.current.session';},
    subscribe:callback=>{listeners.add(callback);return()=>listeners.delete(callback);}, count:()=>tokens,
    revoke(){state={phase:'signedOut',revision:id,identity:null};for(const callback of listeners)callback(state);}};
}
function request(path=collection, method='GET', body='{}') {
  return new Request('app://cosmas/api' + path, {method,
    headers:{'Content-Type':'application/json', 'X-Cosmas-Desktop-Session':id, 'X-Cosmas-Draft-Recovery':'2', [header]:'1'},
    ...(method==='POST'?{body,duplex:'half'}:{})});
}

test('conversation pages and human markers admit only exact negotiated paths and byte budgets', () => {
  assert.equal(CONNECTOR_HEADERS.filter(value=>value===header).length, 1);
  for(const [path,method,input] of paths) {
    assert.deepEqual(connectorApiRoute(path,method), {header,input,output:65536,seconds:15,strictResponse:true,errorOutput:2048});
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,method),path);
    for(const wrong of ['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS','get']) if(wrong!==method) {
      assert.equal(connectorApiRoute(path,wrong),null);
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,wrong),null);
    }
    for(const tail of ['?','?all-bots=true','?owner='+id,'/','/resolve','/send','/execute']) {
      assert.equal(connectorApiRoute(path+tail,method),null);
      assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path+tail,method),null);
    }
    for(const url of ['app://other/api'+path,'https://outside.invalid'+path,'app://cosmas/api'+path+'#fragment',
      'app://cosmas/api/unused/../'+path.slice(1), 'app://cosmas/api'+path.replace('conversations','%63onversations')])
      assert.equal(permittedAuthenticatedApiPath(url,method),null);
  }
  for(const path of [collection+'/pages/'+cursor.slice(1), collection+'/pages/'+cursor+'0',
    collection+'/pages/'+cursor.toUpperCase(), collection+'/pages', marker.replace('chief','research'),
    marker.replace('chief','custom'), marker.replace('chief','CHIEF'), marker.replace('chief',id.replace('-4000-','-0000-')),
    marker.replace(id,'not-a-uuid'), marker.replace('/read','/unread')]) {
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'GET'),null);
    assert.equal(permittedAuthenticatedApiPath('app://cosmas/api'+path,'POST'),null);
  }
});

test('conversation contracts and renderer authority are checked before credentials or dispatch', async () => {
  for(const [path,method] of paths) {
    for(const value of [null,'','2','1, 1']) {
      const session=auth(), req=request(path,method);
      if(value===null) req.headers.delete(header); else req.headers.set(header,value);
      assert.equal((await proxy(req,session,()=>assert.fail('no dispatch'))).status,426);
      assert.equal(session.count(),0);
    }
    for(const other of CONNECTOR_HEADERS.filter(value=>value!==header)) {
      const session=auth(), req=request(path,method);req.headers.set(other,'1');
      assert.equal((await proxy(req,session,()=>assert.fail('no mixed contract'))).status,426);
      assert.equal(session.count(),0);
    }
  }
  for(const name of ['Authorization','X-Box-Id','X-Actor-Principal-Id','Cookie','Content-Encoding']) {
    const session=auth(), req=request();req.headers.set(name,'invented');
    assert.equal((await proxy(req,session,()=>assert.fail('no renderer authority'))).status,401);
    assert.equal(session.count(),0);
  }
});

test('opening a chat and marking observed activity forward the exact distinct commands', async () => {
  for(const command of [{}, {watermark}, {manual_unread:true,expected_version:1},
    {watermark,manual_unread:false,expected_version:2}]) {
    const body=JSON.stringify(command), session=auth();let calls=0;
    const result=await proxy(request(marker,'POST',body),session,async(url,options)=>{
      calls++;
      assert.equal(url,'http://127.0.0.1:8046'+marker);
      assert.equal(new TextDecoder().decode(options.body),body);
      assert.equal(options.headers[header],'1');
      assert.equal(options.headers['Authorization'],'Bearer invented.current.session');
      assert.equal(options.headers['X-Cosmas-Draft-Recovery'],'2');
      assert.equal(options.headers['X-Cosmas-Desktop-Session'],undefined);
      assert.equal(options.redirect,'error');assert.equal(options.credentials,'omit');assert.equal(options.cache,'no-store');
      return response(JSON.stringify({contract_version:1,marker_version:1,manual_unread:false,seen_watermark:null}));
    });
    assert.equal(result.status,200);assert.equal(result.headers.get('Cache-Control'),'no-store');
    assert.equal(result.headers.get('Authorization'),null);
    assert.equal(calls,1);assert.equal(session.count(),1);
  }
});

test('conversation requests are bodyless reads or at most 4096 bytes of JSON before credential access', async () => {
  assert.equal((await proxy(request(marker,'POST',sized(4096)),auth(),async()=>response())).status,200);
  for(const body of [sized(4097),'{',new Uint8Array([0xff])]) {
    const session=auth();
    assert.equal((await proxy(request(marker,'POST',body),session,()=>assert.fail('no oversized or malformed request'))).status,503);
    assert.equal(session.count(),0);
  }
  const base=request(), session=auth();
  const body=new ReadableStream({start(controller){controller.enqueue(new TextEncoder().encode('{}'));controller.close();}});
  assert.equal((await proxy({url:base.url,method:'GET',headers:base.headers,signal:base.signal,body},session,
    ()=>assert.fail('no GET body'))).status,503);
  assert.equal(session.count(),0);
  const wrongType=request(marker,'POST');wrongType.headers.set('Content-Type','text/plain');
  assert.equal((await proxy(wrongType,auth(),()=>assert.fail('JSON only'))).status,400);
});

test('conversation responses retain strict no-store, encoding, size and authority failure limits', async () => {
  for(const [path,method] of paths.slice(0,3)) {
    assert.equal((await proxy(request(path,method),auth(),async()=>response(sized(65536)))).status,200);
    assert.equal((await proxy(request(path,method),auth(),async()=>response(sized(65537)))).status,503);
    assert.equal((await proxy(request(path,method),auth(),async()=>response(sized(2048),409))).status,409);
    assert.equal((await proxy(request(path,method),auth(),async()=>response(sized(2049),409))).status,503);
    for(const extra of [{'Cache-Control':'private'}, {'Content-Type':'text/html'}, {'Content-Encoding':'gzip'},
      {'Content-Length':'3'}, {'Content-Length':'02'}, {'Content-Length':'65537'}])
      assert.equal((await proxy(request(path,method),auth(),async()=>response('{}',200,extra))).status,502);
    for(const status of [401,403,404])
      assert.equal((await proxy(request(path,method),auth(),async()=>response(sized(2049),status))).status,status);
  }
});

test('sign-out while inbox response is pending stops disclosure without retry', async () => {
  const session=auth();let calls=0,cancelled=0;
  const pending=proxy(request(),session,async()=>{calls++;return response(new ReadableStream({
    pull(){return new Promise(()=>{});},cancel(){cancelled++;}}));});
  await tick();session.revoke();
  assert.equal((await pending).status,401);assert.equal(calls,1);assert.equal(cancelled,1);
});

test('the 15-second inbox deadline fences late credentials before dispatch', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const session=auth();let release,calls=0;
  session.getToken=()=>new Promise(resolve=>{release=resolve;});
  const pending=proxy(request(),session,async()=>{calls++;return response();});
  await tick();t.mock.timers.tick(15000);assert.equal((await pending).status,504);
  release('invented.current.session');await tick();assert.equal(calls,0);
});

test('conversation pages and markers use owned loopback sockets with exact body framing', async () => {
  const seen=[];
  const server=createServer(async(req,res)=>{
    const chunks=[];for await(const chunk of req) chunks.push(chunk);
    seen.push({method:req.method,path:req.url,headers:req.headers,body:Buffer.concat(chunks)});
    res.writeHead(200,{'Content-Type':'application/json','Cache-Control':'no-store','Content-Length':'2'});res.end('{}');
  });
  server.listen(0,'127.0.0.1');await once(server,'listening');const port=server.address().port;
  const transport=(url,options)=>local(url,options,(address,callback)=>{
    assert.equal(address.host,'127.0.0.1');assert.equal(address.port,8046);
    return httpRequest({...address,port},callback);
  });
  try {
    const body=JSON.stringify({watermark,manual_unread:false,expected_version:2});
    for(const [path,method] of paths.slice(0,3)) {
      const result=await proxy(request(path,method,body),auth(),transport);
      assert.equal(result.status,200);
      const actual=seen.at(-1);
      assert.equal(actual.path,path);assert.equal(actual.method,method);
      assert.equal(actual.headers[header.toLowerCase()],'1');
      assert.equal(actual.headers.authorization,'Bearer invented.current.session');
      assert.equal(actual.headers['x-cosmas-desktop-session'],undefined);
      assert.equal(actual.headers['transfer-encoding'],undefined);
      assert.equal(actual.body.toString(),method==='POST'?body:'');
      if(method==='POST')assert.equal(actual.headers['content-length'],String(Buffer.byteLength(body)));
    }
    assert.equal(seen.length,3);
  } finally {server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
